#!/usr/bin/env python3

import argparse
import json
import math
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUT_JSON = ROOT / "Figure_4.json"
OUTPUT_DOT = ROOT / "Figure_4_network.dot"
OUTPUT_SVG = ROOT / "Figure_4_network.svg"
CANVAS_WIDTH = 2200
CANVAS_HEIGHT = 1300
TOP_PAD = 42
BOTTOM_PAD = 44
LEFT_PAD = 36
RIGHT_PAD = 36
IMPORTANT_EDGE_THRESHOLD = 0.20
IMPORTANT_GENE_THRESHOLD = 0.30
HUB_RING_THRESHOLD = 0.60
COMPONENT_BOXES = [
    (0.45, 0.53, 1.02),
    (0.63, 0.37, 0.72),
    (0.64, 0.71, 0.75),
]


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def node_size(weight: float) -> float:
    # Weight spans ~0.01-1.0; sqrt scaling keeps high-weight hubs visible
    # without shrinking the mid-range too aggressively.
    return 0.45 + 1.55 * math.sqrt(max(weight, 0.0))


def edge_penwidth(weight: float) -> float:
    return 0.6 + 2.8 * math.sqrt(max(weight, 0.0))


def edge_color(weight: float) -> str:
    # Darker gray for stronger edges.
    shade = int(round(210 - 130 * clamp(math.sqrt(weight), 0.0, 1.0)))
    return f"#{shade:02x}{shade:02x}{shade:02x}"


def node_fill(is_significant: bool, weight: float) -> str:
    if is_significant:
        base = (215, 48, 39)
        fade = int(round(25 * (1.0 - clamp(math.sqrt(weight), 0.0, 1.0))))
        r = clamp(base[0] + fade, 0, 255)
        g = clamp(base[1] + fade, 0, 255)
        b = clamp(base[2] + fade, 0, 255)
        return f"#{int(r):02x}{int(g):02x}{int(b):02x}"
    base = (116, 141, 174)
    fade = int(round(45 * (1.0 - clamp(math.sqrt(weight), 0.0, 1.0))))
    r = clamp(base[0] + fade, 0, 255)
    g = clamp(base[1] + fade, 0, 255)
    b = clamp(base[2] + fade, 0, 255)
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def label_size(weight: float) -> int:
    return int(round(10 + 8 * math.sqrt(max(weight, 0.0))))


def escape_label(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def connected_components(node_ids, edges):
    adjacency = {node_id: set() for node_id in node_ids}
    for edge in edges:
        src = edge["Actual_From"]
        dst = edge["Actual_To"]
        adjacency[src].add(dst)
        adjacency[dst].add(src)

    seen = set()
    components = []
    for node_id in node_ids:
        if node_id in seen:
            continue
        stack = [node_id]
        seen.add(node_id)
        component = []
        while stack:
            current = stack.pop()
            component.append(current)
            for nxt in adjacency[current]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        components.append(sorted(component))
    return sorted(components, key=len, reverse=True)


def force_layout(component_ids, component_edges, weight_by_id, initial_positions=None, anchor_map=None):
    rng = random.Random(7 + len(component_ids))
    n = max(len(component_ids), 1)
    area = 1.0
    k = math.sqrt(area / n)
    positions = {}
    for node_id in component_ids:
        if initial_positions and node_id in initial_positions:
            x, y = initial_positions[node_id]
            positions[node_id] = [x, y]
        else:
            positions[node_id] = [rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5)]
    degrees = {node_id: 0 for node_id in component_ids}
    for edge in component_edges:
        degrees[edge["Actual_From"]] += 1
        degrees[edge["Actual_To"]] += 1

    iterations = 520 if n > 60 else 380
    temperature = 0.17
    gravity = 0.02

    for _ in range(iterations):
        disp = {node_id: [0.0, 0.0] for node_id in component_ids}
        for i, src in enumerate(component_ids):
            for dst in component_ids[i + 1 :]:
                dx = positions[src][0] - positions[dst][0]
                dy = positions[src][1] - positions[dst][1]
                dist = math.hypot(dx, dy) + 1e-6
                force = 1.45 * (k * k) / dist
                ux = dx / dist
                uy = dy / dist
                disp[src][0] += ux * force
                disp[src][1] += uy * force
                disp[dst][0] -= ux * force
                disp[dst][1] -= uy * force

        for edge in component_edges:
            src = edge["Actual_From"]
            dst = edge["Actual_To"]
            dx = positions[src][0] - positions[dst][0]
            dy = positions[src][1] - positions[dst][1]
            dist = math.hypot(dx, dy) + 1e-6
            edge_weight = max(float(edge["Weight"]), 0.02)
            force = (dist * dist) / k * (0.30 + 1.45 * math.sqrt(edge_weight))
            ux = dx / dist
            uy = dy / dist
            disp[src][0] -= ux * force
            disp[src][1] -= uy * force
            disp[dst][0] += ux * force
            disp[dst][1] += uy * force

        for node_id in component_ids:
            x, y = positions[node_id]
            center_force = gravity * (1.0 + 0.15 * degrees[node_id])
            disp[node_id][0] -= x * center_force
            disp[node_id][1] -= y * center_force
            if anchor_map and node_id in anchor_map:
                ax, ay = anchor_map[node_id]
                disp[node_id][0] += (ax - x) * 0.018
                disp[node_id][1] += (ay - y) * 0.018

            dx, dy = disp[node_id]
            dist = math.hypot(dx, dy) + 1e-6
            step = min(temperature, dist)
            weight_boost = 0.75 + 0.35 * math.sqrt(max(weight_by_id[node_id], 0.0))
            positions[node_id][0] += dx / dist * step * weight_boost
            positions[node_id][1] += dy / dist * step * weight_boost

        temperature *= 0.985

    xs = [positions[node_id][0] for node_id in component_ids]
    ys = [positions[node_id][1] for node_id in component_ids]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    for node_id in component_ids:
        positions[node_id][0] = (positions[node_id][0] - min_x) / span_x
        positions[node_id][1] = (positions[node_id][1] - min_y) / span_y
    return positions


def node_radius(weight: float, important_gene_threshold: float) -> float:
    radius = 6 + 13 * math.sqrt(weight)
    if weight >= important_gene_threshold:
        radius += 5
    return radius


def node_font_size(weight: float, important_gene_threshold: float) -> float:
    font_size = 6 + 6.2 * math.sqrt(weight)
    if weight >= important_gene_threshold:
        font_size += 1.5
    return font_size


def relax_positions(node_ids, positions, weight_by_id, important_gene_threshold, box, iterations=220):
    x0, y0, x1, y1 = box
    for _ in range(iterations):
        moved = False
        for i, src in enumerate(node_ids):
            sx, sy = positions[src]
            sr = node_radius(weight_by_id[src], important_gene_threshold)
            sfont = node_font_size(weight_by_id[src], important_gene_threshold)
            slabel_w = max(sr * 1.8, len(str(src)) * sfont * 0.34)
            slabel_h = max(sr * 1.2, sfont * 1.1)
            for dst in node_ids[i + 1 :]:
                dx, dy = positions[dst]
                dr = node_radius(weight_by_id[dst], important_gene_threshold)
                dfont = node_font_size(weight_by_id[dst], important_gene_threshold)
                dlabel_w = max(dr * 1.8, len(str(dst)) * dfont * 0.34)
                dlabel_h = max(dr * 1.2, dfont * 1.1)

                vx = dx - sx
                vy = dy - sy
                dist = math.hypot(vx, vy) + 1e-6

                min_node_gap = sr + dr + 8
                label_gap_x = (slabel_w + dlabel_w) / 2 + 12
                label_gap_y = (slabel_h + dlabel_h) / 2 + 8

                overlap_node = min_node_gap - dist
                overlap_label_x = label_gap_x - abs(vx)
                overlap_label_y = label_gap_y - abs(vy)

                if overlap_node > 0 or (overlap_label_x > 0 and overlap_label_y > 0):
                    if abs(vx) < 1e-3 and abs(vy) < 1e-3:
                        ux, uy = 1.0, 0.0
                    else:
                        ux, uy = vx / dist, vy / dist

                    push = max(overlap_node, min(overlap_label_x, overlap_label_y), 0) * 0.12
                    push = min(push, 6.0)
                    positions[src] = (
                        max(x0, min(x1, sx - ux * push)),
                        max(y0, min(y1, sy - uy * push)),
                    )
                    positions[dst] = (
                        max(x0, min(x1, dx + ux * push)),
                        max(y0, min(y1, dy + uy * push)),
                    )
                    sx, sy = positions[src]
                    moved = True
        if not moved:
            break


def load_figure4_graph():
    data = json.loads(INPUT_JSON.read_text())
    pvalue_ids = {node["gene_node_idx"] for node in data["pvalue_nodes"]}
    nodes = sorted(data["nodes"], key=lambda x: (-x["Weight"], x["gene_node_name"]))
    edges = sorted(
        data["edges"],
        key=lambda x: (-x["Weight"], x["Actual_From"], x["Actual_To"]),
    )
    return data, pvalue_ids, nodes, edges


def compute_seed_gene_positions(nodes, edges):
    content_width = CANVAS_WIDTH - LEFT_PAD - RIGHT_PAD
    content_height = CANVAS_HEIGHT - TOP_PAD - BOTTOM_PAD
    weight_by_id = {node["gene_node_idx"]: float(node["Weight"]) for node in nodes}
    components = connected_components([node["gene_node_idx"] for node in nodes], edges)
    anchor_centers = [
        (-0.36, -0.02),
        (-0.05, 0.28),
        (0.40, -0.08),
        (0.22, 0.32),
    ]
    initial_positions = {}
    anchor_map = {}
    for comp_index, component_ids in enumerate(components):
        ax, ay = anchor_centers[min(comp_index, len(anchor_centers) - 1)]
        rng = random.Random(100 + comp_index)
        for node_id in component_ids:
            jitter = 0.12 if comp_index == 0 else 0.08
            initial_positions[node_id] = (
                ax + rng.uniform(-jitter, jitter),
                ay + rng.uniform(-jitter, jitter),
            )
            anchor_map[node_id] = (ax, ay)

    all_node_ids = [node["gene_node_idx"] for node in nodes]
    global_positions = force_layout(
        all_node_ids,
        edges,
        weight_by_id,
        initial_positions=initial_positions,
        anchor_map=anchor_map,
    )
    positions = {}
    box = (
        LEFT_PAD + 0.03 * content_width,
        TOP_PAD + 0.08 * content_height,
        LEFT_PAD + 0.97 * content_width,
        TOP_PAD + 0.94 * content_height,
    )
    for node_id in all_node_ids:
        x = box[0] + global_positions[node_id][0] * (box[2] - box[0])
        y = box[1] + global_positions[node_id][1] * (box[3] - box[1])
        positions[node_id] = (x, y)
    for component_ids in components:
        relax_positions(component_ids, positions, weight_by_id, IMPORTANT_GENE_THRESHOLD, box, iterations=260)
    return positions


def gene_collision_radius(node):
    weight = float(node["Weight"])
    return 0.052 + 0.028 * math.sqrt(weight) + 0.0048 * len(node["gene_node_name"])


def force_layout_genes(component_nodes, component_edges, initial_positions):
    names = [node["gene_node_name"] for node in component_nodes]
    node_by_name = {node["gene_node_name"]: node for node in component_nodes}
    pos = {name: list(initial_positions[name]) for name in names}
    radii = {name: gene_collision_radius(node_by_name[name]) for name in names}
    degrees = {name: 0 for name in names}
    for edge in component_edges:
        a = edge["from_name"]
        b = edge["to_name"]
        degrees[a] += 1
        degrees[b] += 1

    temperature = 0.096
    for _ in range(620):
        disp = {name: [0.0, 0.0] for name in names}
        for i, a in enumerate(names):
            ax, ay = pos[a]
            for b in names[i + 1 :]:
                bx, by = pos[b]
                dx = ax - bx
                dy = ay - by
                dist = math.hypot(dx, dy) + 1e-6
                desired = radii[a] + radii[b] + 0.052
                repel = 0.013 * desired * desired / (dist * dist)
                if dist < desired:
                    repel += (desired - dist) * 0.60
                ux, uy = dx / dist, dy / dist
                disp[a][0] += ux * repel
                disp[a][1] += uy * repel
                disp[b][0] -= ux * repel
                disp[b][1] -= uy * repel

        for edge in component_edges:
            a = edge["from_name"]
            b = edge["to_name"]
            ax, ay = pos[a]
            bx, by = pos[b]
            dx = bx - ax
            dy = by - ay
            dist = math.hypot(dx, dy) + 1e-6
            weight = float(edge["Weight"])
            desired = 0.32 + 0.17 * (1.0 - math.sqrt(weight))
            spring = 0.12 + 0.05 * weight
            force = (dist - desired) * spring
            ux, uy = dx / dist, dy / dist
            disp[a][0] += ux * force
            disp[a][1] += uy * force
            disp[b][0] -= ux * force
            disp[b][1] -= uy * force

        for name in names:
            x, y = pos[name]
            disp[name][0] -= x * 0.0085 * (1.0 + degrees[name] * 0.04)
            disp[name][1] -= y * 0.0085 * (1.0 + degrees[name] * 0.04)
            dx, dy = disp[name]
            mag = math.hypot(dx, dy) + 1e-6
            step = min(temperature, mag)
            pos[name][0] += dx / mag * step
            pos[name][1] += dy / mag * step

        temperature *= 0.988

    xs = [pos[name][0] for name in names]
    ys = [pos[name][1] for name in names]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    for name in names:
        pos[name][0] = (pos[name][0] - min_x) / span_x - 0.5
        pos[name][1] = (pos[name][1] - min_y) / span_y - 0.5
    return pos


def prepare_gene_components(nodes, edges, base_positions):
    node_by_id = {node["gene_node_idx"]: node for node in nodes}
    components = connected_components([node["gene_node_idx"] for node in nodes], edges)

    gene_edges = []
    for edge in edges:
        gene_edges.append(
            {
                **edge,
                "from_name": node_by_id[edge["Actual_From"]]["gene_node_name"],
                "to_name": node_by_id[edge["Actual_To"]]["gene_node_name"],
            }
        )

    prepared = []
    for comp_idx, comp_node_ids in enumerate(components):
        comp_nodes = [node_by_id[node_id] for node_id in comp_node_ids]
        comp_names = {node["gene_node_name"] for node in comp_nodes}
        comp_edges = [edge for edge in gene_edges if edge["from_name"] in comp_names and edge["to_name"] in comp_names]
        xs = [base_positions[node_id][0] for node_id in comp_node_ids]
        ys = [base_positions[node_id][1] for node_id in comp_node_ids]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        initial_positions = {}
        for node_id in comp_node_ids:
            node = node_by_id[node_id]
            initial_positions[node["gene_node_name"]] = (
                (base_positions[node_id][0] - min_x) / span_x - 0.5,
                (base_positions[node_id][1] - min_y) / span_y - 0.5,
            )
        gene_pos = force_layout_genes(comp_nodes, comp_edges, initial_positions)
        prepared.append(
            {
                "index": comp_idx,
                "genes": comp_nodes,
                "gene_edges": comp_edges,
                "gene_positions": gene_pos,
            }
        )
    return prepared


def transform_gene_component(component, placement):
    center_x = CANVAS_WIDTH * placement[0]
    center_y = CANVAS_HEIGHT * placement[1]
    size_scale = placement[2]
    items = []
    for gene in component["genes"]:
        name = gene["gene_node_name"]
        x, y = component["gene_positions"][name]
        r = gene_collision_radius(gene)
        items.append((x - r, y - r, x + r, y + r))

    min_x = min(item[0] for item in items)
    min_y = min(item[1] for item in items)
    max_x = max(item[2] for item in items)
    max_y = max(item[3] for item in items)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    target_w = 760.0 * size_scale
    target_h = 760.0 * size_scale
    scale = min(target_w / span_x, target_h / span_y)
    offset_x = center_x - (min_x + span_x / 2) * scale
    offset_y = center_y - (min_y + span_y / 2) * scale

    gene_positions_px = {}
    for gene in component["genes"]:
        name = gene["gene_node_name"]
        x, y = component["gene_positions"][name]
        gene_positions_px[name] = (offset_x + x * scale, offset_y + y * scale)

    component["gene_positions_px"] = gene_positions_px
    component["scale"] = scale
    return component


def global_relax_layout_genes(components):
    item_pos = {}
    item_radius = {}
    item_home = {}
    edge_specs = []

    for component in components:
        comp_genes = component["genes"]
        centroid_x = sum(component["gene_positions_px"][gene["gene_node_name"]][0] for gene in comp_genes) / len(comp_genes)
        centroid_y = sum(component["gene_positions_px"][gene["gene_node_name"]][1] for gene in comp_genes) / len(comp_genes)
        component["home_center_px"] = (centroid_x, centroid_y)

        for gene in comp_genes:
            name = gene["gene_node_name"]
            item_id = f"gene::{name}"
            x, y = component["gene_positions_px"][name]
            radius_px = node_radius(float(gene["Weight"]), IMPORTANT_GENE_THRESHOLD) + 6.5
            item_pos[item_id] = [x, y]
            item_home[item_id] = [x, y]
            item_radius[item_id] = radius_px

    for component in components:
        for edge in component["gene_edges"]:
            a = f"gene::{edge['from_name']}"
            b = f"gene::{edge['to_name']}"
            weight = float(edge["Weight"])
            edge_specs.append(
                {
                    "a": a,
                    "b": b,
                    "desired": 88.0 + 44.0 * (1.0 - math.sqrt(weight)),
                    "strength": 0.020 + 0.016 * weight,
                }
            )

    center_x = CANVAS_WIDTH * 0.53
    center_y = CANVAS_HEIGHT * 0.54
    temp = 7.8
    item_ids = list(item_pos)
    for _ in range(320):
        disp = {item_id: [0.0, 0.0] for item_id in item_ids}

        for i, a in enumerate(item_ids):
            ax, ay = item_pos[a]
            for b in item_ids[i + 1 :]:
                bx, by = item_pos[b]
                dx = ax - bx
                dy = ay - by
                dist = math.hypot(dx, dy) + 1e-6
                desired = item_radius[a] + item_radius[b] + 18.0
                repel = 5800.0 / (dist * dist)
                if dist < desired:
                    repel += (desired - dist) * 0.88
                ux, uy = dx / dist, dy / dist
                disp[a][0] += ux * repel
                disp[a][1] += uy * repel
                disp[b][0] -= ux * repel
                disp[b][1] -= uy * repel

        for spec in edge_specs:
            a = spec["a"]
            b = spec["b"]
            ax, ay = item_pos[a]
            bx, by = item_pos[b]
            dx = bx - ax
            dy = by - ay
            dist = math.hypot(dx, dy) + 1e-6
            force = (dist - spec["desired"]) * spec["strength"]
            ux, uy = dx / dist, dy / dist
            disp[a][0] += ux * force
            disp[a][1] += uy * force
            disp[b][0] -= ux * force
            disp[b][1] -= uy * force

        for item_id in item_ids:
            x, y = item_pos[item_id]
            home_x, home_y = item_home[item_id]
            disp[item_id][0] += (home_x - x) * 0.012
            disp[item_id][1] += (home_y - y) * 0.012
            disp[item_id][0] += (center_x - x) * 0.00115
            disp[item_id][1] += (center_y - y) * 0.00115

        for item_id in item_ids:
            dx, dy = disp[item_id]
            mag = math.hypot(dx, dy)
            if mag < 1e-6:
                continue
            step = min(temp, mag)
            item_pos[item_id][0] += dx / mag * step
            item_pos[item_id][1] += dy / mag * step

        temp *= 0.989

    min_x = min(pos[0] - item_radius[item_id] for item_id, pos in item_pos.items())
    max_x = max(pos[0] + item_radius[item_id] for item_id, pos in item_pos.items())
    min_y = min(pos[1] - item_radius[item_id] for item_id, pos in item_pos.items())
    max_y = max(pos[1] + item_radius[item_id] for item_id, pos in item_pos.items())
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)
    fit_w = CANVAS_WIDTH - 260.0
    fit_h = CANVAS_HEIGHT - 190.0
    scale = min(fit_w / span_x, fit_h / span_y)
    offset_x = (CANVAS_WIDTH - span_x * scale) / 2 - min_x * scale + 34.0
    offset_y = (CANVAS_HEIGHT - span_y * scale) / 2 - min_y * scale + 10.0

    for component in components:
        for gene in component["genes"]:
            name = gene["gene_node_name"]
            item_id = f"gene::{name}"
            x, y = item_pos[item_id]
            component["gene_positions_px"][name] = (x * scale + offset_x, y * scale + offset_y)

    return components


def compute_gene_positions_aligned(nodes, edges):
    base_positions = compute_seed_gene_positions(nodes, edges)
    components = prepare_gene_components(nodes, edges, base_positions)
    transformed = []
    for idx, component in enumerate(components):
        placement = COMPONENT_BOXES[min(idx, len(COMPONENT_BOXES) - 1)]
        transformed.append(transform_gene_component(component, placement))
    transformed = global_relax_layout_genes(transformed)
    positions = {}
    for component in transformed:
        for gene in component["genes"]:
            node_id = gene["gene_node_idx"]
            name = gene["gene_node_name"]
            positions[node_id] = component["gene_positions_px"][name]
    return positions


def compute_gene_positions(nodes, edges):
    # Keep exported base behavior stable for business-layer scripts that import this function.
    return compute_seed_gene_positions(nodes, edges)


def build_svg(nodes, edges, pvalue_ids, positions=None):
    width = CANVAS_WIDTH
    height = CANVAS_HEIGHT
    positions = positions or compute_gene_positions(nodes, edges)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="10" y="40" font-family="Helvetica,Arial,sans-serif" font-size="30" font-weight="700" fill="#111111">a</text>',
        '<g id="legend">',
        '<circle cx="110" cy="42" r="7" fill="#b8e0ee" stroke="none"/>',
        '<text x="124" y="47" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Genes</text>',
        '<circle cx="110" cy="63" r="7" fill="#f5a3a3" stroke="none"/>',
        '<text x="124" y="68" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Important Genes with P value &lt; 0.1</text>',
        '<circle cx="110" cy="84" r="7" fill="none" stroke="#ff8f1f" stroke-width="2.5"/>',
        '<text x="124" y="89" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Top-weight hub genes</text>',
        '<path d="M 108,108 Q 122,98 136,108" stroke="#a8a8a8" stroke-width="1.8" fill="none"/>',
        '<text x="146" y="113" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Gene-Gene</text>',
        '<path d="M 108,129 Q 122,119 136,129" stroke="#111111" stroke-width="3.6" stroke-linecap="round" fill="none"/>',
        '<text x="146" y="134" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Important Gene-Gene</text>',
        '</g>',
        '<g id="edges" stroke-linecap="round" fill="none">',
    ]

    node_name_by_id = {node["gene_node_idx"]: node["gene_node_name"] for node in nodes}
    for edge_index, edge in enumerate(sorted(edges, key=lambda item: item["Weight"])):
        x1, y1 = positions[edge["Actual_From"]]
        x2, y2 = positions[edge["Actual_To"]]
        edge_weight = float(edge["Weight"])
        is_important = edge_weight >= IMPORTANT_EDGE_THRESHOLD
        color = "#111111" if is_important else "#b1b1b1"
        width_px = 3.4 if is_important else 1.35
        opacity = 0.95 if is_important else 0.88
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy) + 1e-6
        px, py = -dy / dist, dx / dist
        from_name = node_name_by_id[edge["Actual_From"]]
        sign = 1 if (edge_index + len(from_name)) % 2 == 0 else -1
        bend = sign * (8.0 + 10.0 * (1.0 - math.sqrt(edge_weight)))
        cx = (x1 + x2) / 2 + px * bend
        cy = (y1 + y2) / 2 + py * bend
        parts.append(
            f'<path d="M {x1:.2f},{y1:.2f} Q {cx:.2f},{cy:.2f} {x2:.2f},{y2:.2f}" '
            f'stroke="{color}" stroke-width="{width_px:.2f}" stroke-opacity="{opacity:.2f}"/>'
        )
    parts.append("</g>")

    parts.append('<g id="nodes">')
    for node in sorted(nodes, key=lambda item: item["Weight"]):
        node_id = node["gene_node_idx"]
        x, y = positions[node_id]
        weight = float(node["Weight"])
        is_sig = node_id in pvalue_ids
        radius = node_radius(weight, IMPORTANT_GENE_THRESHOLD)
        fill = "#f5a3a3" if is_sig else "#b8e0ee"
        stroke = "none"
        font_size = node_font_size(weight, IMPORTANT_GENE_THRESHOLD)
        font_color = "#4a4a4a"
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="1.1"/>'
        )
        if weight >= HUB_RING_THRESHOLD:
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius + 3.5:.2f}" fill="none" stroke="#ff8f1f" stroke-width="2.5"/>'
            )
        parts.append(
            f'<text x="{x:.2f}" y="{y + font_size * 0.33:.2f}" text-anchor="middle" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="{font_size:.1f}" font-weight="600" '
            f'fill="{font_color}">{node["gene_node_name"]}</text>'
        )
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Base gene-network layout utilities and optional gene-only rendering."
    )
    parser.add_argument(
        "--emit-gene-only",
        action="store_true",
        help="Write gene-only outputs (Figure_4_network.dot and Figure_4_network.svg).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Default behavior is utility-only: no gene-only files are emitted unless requested.
    if not args.emit_gene_only:
        return

    _, pvalue_ids, nodes, edges = load_figure4_graph()
    positions = compute_gene_positions_aligned(nodes, edges)

    lines = [
        "graph Figure4 {",
        '  layout="sfdp";',
        '  overlap="prism";',
        '  outputorder="edgesfirst";',
        '  splines="true";',
        '  bgcolor="white";',
        '  pad="0.2";',
        '  nodesep="0.2";',
        '  ranksep="0.4";',
        '  K="1.2";',
        '  start="7";',
        '  fontname="Helvetica";',
        '  labelloc="t";',
        '  label="Figure 4 reconstructed core signaling network\\nNode size scales with GiG weight; red nodes mark p < 0.05 in either comparison";',
        '  fontsize="20";',
        '  node [shape="circle", style="filled", fontname="Helvetica", color="#364152", penwidth="0.8"];',
        '  edge [color="#b0b8c4", fontname="Helvetica"];',
    ]

    for node in nodes:
        node_id = node["gene_node_idx"]
        weight = float(node["Weight"])
        sig = node_id in pvalue_ids
        fill = node_fill(sig, weight)
        width = node_size(weight)
        fontsize = label_size(weight)
        fontcolor = "white" if weight >= 0.35 or sig else "#1f2937"
        tooltip = (
            f'{node["gene_node_name"]} | weight={weight:.4f} | '
            f't2ds p={node["t2ds_no_t2ds_pvalue"]:.4g} | '
            f'pret2ds p={node["pret2ds_no_t2ds_pvalue"]:.4g}'
        )
        lines.append(
            "  "
            + f'"{node_id}" ['
            + f'label="{escape_label(node["gene_node_name"])}", '
            + f'width="{width:.3f}", height="{width:.3f}", fixedsize="false", '
            + f'fillcolor="{fill}", fontsize="{fontsize}", fontcolor="{fontcolor}", '
            + f'tooltip="{escape_label(tooltip)}"'
            + "];"
        )

    for edge in edges:
        weight = float(edge["Weight"])
        lines.append(
            "  "
            + f'"{edge["Actual_From"]}" -- "{edge["Actual_To"]}" ['
            + f'penwidth="{edge_penwidth(weight):.3f}", '
            + f'color="{edge_color(weight)}", '
            + f'tooltip="weight={weight:.4f}"'
            + "];"
        )

    lines.append("}")
    OUTPUT_DOT.write_text("\n".join(lines) + "\n")
    OUTPUT_SVG.write_text(build_svg(nodes, edges, pvalue_ids, positions=positions))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import csv
import math
import re
from collections import defaultdict

from render_gene_network_base import (
    ROOT,
    CANVAS_WIDTH,
    CANVAS_HEIGHT,
    HUB_RING_THRESHOLD,
    IMPORTANT_EDGE_THRESHOLD,
    IMPORTANT_GENE_THRESHOLD,
    connected_components,
    compute_gene_positions,
    load_figure4_graph,
    node_font_size,
    node_radius,
)


LEDGER_CSV = ROOT / "T2D_preT2D_drug_evidence_20260508/final_outputs/T2D_preT2D_Drug_Evidence_Ledger.csv"
OUTPUT_SVG = ROOT / "Figure_4_network_with_drugs.svg"
OUTPUT_EDGE_CSV = ROOT / "Figure_4_drug_edges.csv"
OUTPUT_CITATION_CSV = ROOT / "Figure_4_drug_citation_legend.csv"


STATUS_PRIORITY = {
    "approved": 3,
    "investigational": 2,
    "preclinical": 1,
    "unknown": 0,
}

STATUS_STYLE = {
    "approved": {"fill": "#a8ddb5", "stroke": "#2f855a", "edge": "#2f855a", "dash": ""},
    "investigational": {"fill": "#f6d58b", "stroke": "#c88719", "edge": "#c88719", "dash": "7 5"},
    "preclinical": {"fill": "#e8c4b1", "stroke": "#9a5b36", "edge": "#9a5b36", "dash": "4 4"},
    "unknown": {"fill": "#d8dadd", "stroke": "#6b7280", "edge": "#6b7280", "dash": "2 5"},
}

COMPONENT_BOXES = [
    (0.45, 0.53, 1.02),
    (0.63, 0.37, 0.72),
    (0.64, 0.71, 0.75),
]


def clamp(value, low, high):
    return max(low, min(high, value))


def parse_citation(raw_text):
    pmid_match = re.search(r"PMID:\s*([0-9]+)", raw_text, flags=re.I)
    if pmid_match:
        return f"PMID:{pmid_match.group(1)}"
    doi_match = re.search(r"DOI:\s*([^;\s]+)", raw_text, flags=re.I)
    if doi_match:
        return f"DOI:{doi_match.group(1)}"
    return raw_text.split(";")[0].strip()


def load_drug_overlay(gene_names):
    grouped = {}
    rows = list(csv.DictReader(LEDGER_CSV.open(newline="")))
    for row in rows:
        target = row["Target"].strip()
        drug = row["Candidate Drug"].strip()
        if target not in gene_names or drug == "No validated drug":
            continue
        status = row["Development Status"].strip().lower() or "unknown"
        entry = grouped.setdefault(
            drug,
            {
                "name": drug,
                "status": status,
                "targets": [],
                "citations": [],
            },
        )
        if STATUS_PRIORITY.get(status, -1) > STATUS_PRIORITY.get(entry["status"], -1):
            entry["status"] = status
        citation = parse_citation(row["Evidence Citation (PMID/DOI/Author-Year)"])
        if citation not in entry["citations"]:
            entry["citations"].append(citation)
        entry["targets"].append(
            {
                "target": target,
                "drug_class": row["Drug Class"].strip(),
                "citation": citation,
                "status": status,
            }
        )
    return sorted(grouped.values(), key=lambda item: (item["status"], item["name"]))


def gene_collision_radius(node):
    weight = float(node["Weight"])
    return 0.052 + 0.028 * math.sqrt(weight) + 0.0048 * len(node["gene_node_name"])


def drug_collision_radius(drug):
    return 0.095 + 0.0036 * len(drug["name"]) + 0.012 * max(0, len(drug["targets"]) - 1)


def drug_box_dimensions_px(drug):
    width_px = max(84.0, 18.0 + len(drug["name"]) * 7.4)
    height_px = 24.0
    return width_px, height_px


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


def prepare_components(nodes, edges, drugs, base_positions):
    node_by_id = {node["gene_node_idx"]: node for node in nodes}
    id_by_name = {node["gene_node_name"]: node["gene_node_idx"] for node in nodes}
    components = connected_components([node["gene_node_idx"] for node in nodes], edges)
    comp_index_by_id = {}
    for idx, comp in enumerate(components):
        for node_id in comp:
            comp_index_by_id[node_id] = idx

    gene_edges = []
    for edge in edges:
        gene_edges.append(
            {
                **edge,
                "from_name": node_by_id[edge["Actual_From"]]["gene_node_name"],
                "to_name": node_by_id[edge["Actual_To"]]["gene_node_name"],
            }
        )

    drugs_by_component = defaultdict(list)
    for drug in drugs:
        links_by_component = defaultdict(list)
        for link in drug["targets"]:
            comp_idx = comp_index_by_id[id_by_name[link["target"]]]
            links_by_component[comp_idx].append(link)
        for comp_idx, links in links_by_component.items():
            citations = []
            for link in links:
                if link["citation"] not in citations:
                    citations.append(link["citation"])
            drugs_by_component[comp_idx].append(
                {
                    "name": drug["name"],
                    "status": drug["status"],
                    "targets": links,
                    "citations": citations,
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
                "drugs": drugs_by_component.get(comp_idx, []),
            }
        )
    return prepared


def side_for_anchor(anchor_x, anchor_y, center_x, center_y):
    dx = anchor_x - center_x
    dy = anchor_y - center_y
    if abs(dx) > abs(dy):
        return "right" if dx >= 0 else "left"
    return "bottom" if dy >= 0 else "top"


def place_drugs_for_component(component):
    gene_pos = component["gene_positions"]
    gene_names = [node["gene_node_name"] for node in component["genes"]]
    xs = [gene_pos[name][0] for name in gene_names]
    ys = [gene_pos[name][1] for name in gene_names]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    side_groups = defaultdict(list)
    for drug in component["drugs"]:
        targets = [gene_pos[target["target"]] for target in drug["targets"]]
        anchor_x = sum(x for x, _ in targets) / len(targets)
        anchor_y = sum(y for _, y in targets) / len(targets)
        side = side_for_anchor(anchor_x, anchor_y, center_x, center_y)
        side_groups[side].append(
            {
                **drug,
                "anchor_x": anchor_x,
                "anchor_y": anchor_y,
                "width_local": 0.20 + 0.0115 * len(drug["name"]),
                "height_local": 0.055,
                "citations_summary": " / ".join(drug["citations"][:2]) + (" +" if len(drug["citations"]) > 2 else ""),
            }
        )

    positioned = []
    for side, items in side_groups.items():
        if side in ("top", "bottom"):
            items = sorted(items, key=lambda item: item["anchor_x"])
            row_cap = 3 if len(items) >= 5 else 4
            rows = [items[i : i + row_cap] for i in range(0, len(items), row_cap)]
            base_y = min_y - 0.20 if side == "top" else max_y + 0.20
            for row_idx, row in enumerate(rows):
                cursor = 0.0
                slots = []
                for item in row:
                    slots.append(cursor + item["width_local"] / 2)
                    cursor += item["width_local"] + 0.050
                total = cursor - 0.050 if row else 0.0
                slots = [slot - total / 2 for slot in slots]
                row_y = base_y - row_idx * 0.105 if side == "top" else base_y + row_idx * 0.105
                center_x_row = sum(item["anchor_x"] for item in row) / len(row)
                for item, slot in zip(row, slots):
                    item["x_local"] = center_x_row + slot
                    item["y_local"] = row_y
                    item["side"] = side
                    positioned.append(item)
        else:
            items = sorted(items, key=lambda item: item["anchor_y"])
            row_cap = 3 if len(items) >= 5 else 4
            cols = [items[i : i + row_cap] for i in range(0, len(items), row_cap)]
            base_x = min_x - 0.22 if side == "left" else max_x + 0.22
            for col_idx, col in enumerate(cols):
                cursor = 0.0
                slots = []
                for item in col:
                    slots.append(cursor + item["height_local"] / 2)
                    cursor += item["height_local"] + 0.068
                total = cursor - 0.068 if col else 0.0
                slots = [slot - total / 2 for slot in slots]
                col_x = base_x - col_idx * 0.24 if side == "left" else base_x + col_idx * 0.24
                center_y_col = sum(item["anchor_y"] for item in col) / len(col)
                for item, slot in zip(col, slots):
                    item["x_local"] = col_x
                    item["y_local"] = center_y_col + slot
                    item["side"] = side
                    positioned.append(item)

    component["drug_positions"] = positioned
    return component


def transform_component(component, placement):
    center_x = CANVAS_WIDTH * placement[0]
    center_y = CANVAS_HEIGHT * placement[1]
    size_scale = placement[2]
    items = []
    for gene in component["genes"]:
        name = gene["gene_node_name"]
        x, y = component["gene_positions"][name]
        r = gene_collision_radius(gene)
        items.append((x - r, y - r, x + r, y + r))
    for drug in component["drug_positions"]:
        w = drug["width_local"] / 2
        h = drug["height_local"] / 2
        items.append((drug["x_local"] - w, drug["y_local"] - h, drug["x_local"] + w, drug["y_local"] + h))

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

    drug_positions_px = []
    for drug in component["drug_positions"]:
        px = offset_x + drug["x_local"] * scale
        py = offset_y + drug["y_local"] * scale
        drug_positions_px.append({**drug, "x": px, "y": py})

    component["gene_positions_px"] = gene_positions_px
    component["drug_positions_px"] = drug_positions_px
    component["scale"] = scale
    return component


def global_relax_layout(components):
    item_pos = {}
    item_radius = {}
    item_kind = {}
    item_component = {}
    item_home = {}
    drug_meta = {}
    edge_specs = []

    for component in components:
        comp_idx = component["index"]
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
            item_kind[item_id] = "gene"
            item_component[item_id] = comp_idx

        for drug in component["drug_positions_px"]:
            item_id = f"drug::{comp_idx}::{drug['name']}"
            width_px, height_px = drug_box_dimensions_px(drug)
            radius_px = max(width_px / 2, 34.0)
            item_pos[item_id] = [drug["x"], drug["y"]]
            item_home[item_id] = [drug["x"], drug["y"]]
            item_radius[item_id] = radius_px
            item_kind[item_id] = "drug"
            item_component[item_id] = comp_idx
            drug_meta[item_id] = {"width_px": width_px, "height_px": height_px, "side": drug["side"]}

    for component in components:
        for edge in component["gene_edges"]:
            a = f"gene::{edge['from_name']}"
            b = f"gene::{edge['to_name']}"
            weight = float(edge["Weight"])
            edge_specs.append(
                {
                    "kind": "gene",
                    "a": a,
                    "b": b,
                    "desired": 88.0 + 44.0 * (1.0 - math.sqrt(weight)),
                    "strength": 0.020 + 0.016 * weight,
                }
            )
        for drug in component["drug_positions_px"]:
            drug_id = f"drug::{component['index']}::{drug['name']}"
            for link in drug["targets"]:
                gene_id = f"gene::{link['target']}"
                edge_specs.append(
                    {
                        "kind": "drug",
                        "a": gene_id,
                        "b": drug_id,
                        "desired": 118.0 + 14.0 * max(0, len(drug["targets"]) - 1),
                        "strength": 0.030,
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
                if item_kind[a] == "drug" or item_kind[b] == "drug":
                    desired += 28.0
                if item_kind[a] == "drug" and item_kind[b] == "drug":
                    desired += 10.0
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

            if item_kind[item_id] == "drug":
                comp_home_x, comp_home_y = components[item_component[item_id]]["home_center_px"]
                dx = x - comp_home_x
                dy = y - comp_home_y
                dist = math.hypot(dx, dy) + 1e-6
                desired = 155.0
                side = drug_meta[item_id]["side"]
                side_unit = {
                    "top": (0.0, -1.0),
                    "bottom": (0.0, 1.0),
                    "left": (-1.0, 0.0),
                    "right": (1.0, 0.0),
                }[side]
                disp[item_id][0] += side_unit[0] * 0.95
                disp[item_id][1] += side_unit[1] * 0.95
                disp[item_id][0] += (dx / dist) * (desired - dist) * 0.015
                disp[item_id][1] += (dy / dist) * (desired - dist) * 0.015

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
        for drug in component["drug_positions_px"]:
            item_id = f"drug::{component['index']}::{drug['name']}"
            x, y = item_pos[item_id]
            drug["x"] = x * scale + offset_x
            drug["y"] = y * scale + offset_y

    return components


def build_augmented_layout(nodes, edges, drugs):
    base_positions = compute_gene_positions(nodes, edges)
    components = prepare_components(nodes, edges, drugs, base_positions)
    components = [place_drugs_for_component(component) for component in components]
    transformed = []
    for idx, component in enumerate(components):
        placement = COMPONENT_BOXES[min(idx, len(COMPONENT_BOXES) - 1)]
        transformed.append(transform_component(component, placement))
    return global_relax_layout(transformed)


def render_legend(parts):
    parts.extend(
        [
            '<g id="legend">',
            '<circle cx="110" cy="42" r="7" fill="#b8e0ee" stroke="none"/>',
            '<text x="124" y="47" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Genes</text>',
            '<circle cx="110" cy="63" r="7" fill="#f5a3a3" stroke="none"/>',
            '<text x="124" y="68" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Important Genes with P value &lt; 0.1</text>',
            '<circle cx="110" cy="84" r="7" fill="none" stroke="#ff8f1f" stroke-width="2.5"/>',
            '<text x="124" y="89" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Top-weight hub genes</text>',
            '<rect x="108" y="100" width="20" height="12" rx="6" fill="#a8ddb5" stroke="#2f855a" stroke-width="1.5"/>',
            '<text x="138" y="110" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Approved drug</text>',
            '<rect x="108" y="118" width="20" height="12" rx="6" fill="#f6d58b" stroke="#c88719" stroke-width="1.5"/>',
            '<text x="138" y="128" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Investigational drug</text>',
            '<path d="M 108,146 Q 122,136 136,146" stroke="#a8a8a8" stroke-width="1.8" fill="none"/>',
            '<text x="146" y="151" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Gene-Gene</text>',
            '<path d="M 108,167 Q 122,157 136,167" stroke="#111111" stroke-width="3.6" stroke-linecap="round" fill="none"/>',
            '<text x="146" y="172" font-family="Helvetica,Arial,sans-serif" font-size="12.5" fill="#4a4a4a">Important Gene-Gene</text>',
            '<path d="M 108,188 Q 122,178 136,188" stroke="#c88719" stroke-width="2.0" stroke-dasharray="7 5" fill="none"/>',
            '<text x="144" y="193" font-family="Helvetica,Arial,sans-serif" font-size="9.5" fill="#6b6b6b">PMID:12345678</text>',
            '</g>',
        ]
    )


def render_svg(nodes, components, pvalue_ids):
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS_WIDTH}" height="{CANVAS_HEIGHT}" viewBox="0 0 {CANVAS_WIDTH} {CANVAS_HEIGHT}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<text x="10" y="40" font-family="Helvetica,Arial,sans-serif" font-size="30" font-weight="700" fill="#111111">a</text>',
    ]
    render_legend(parts)

    edge_rows = []
    citation_rows = []

    parts.append('<g id="gene_edges" stroke-linecap="round" fill="none">')
    for component in components:
        for edge_index, edge in enumerate(sorted(component["gene_edges"], key=lambda item: item["Weight"])):
            x1, y1 = component["gene_positions_px"][edge["from_name"]]
            x2, y2 = component["gene_positions_px"][edge["to_name"]]
            edge_weight = float(edge["Weight"])
            is_important = edge_weight >= IMPORTANT_EDGE_THRESHOLD
            color = "#111111" if is_important else "#b1b1b1"
            width_px = 3.4 if is_important else 1.35
            opacity = 0.95 if is_important else 0.88
            dx = x2 - x1
            dy = y2 - y1
            dist = math.hypot(dx, dy) + 1e-6
            px, py = -dy / dist, dx / dist
            sign = 1 if (edge_index + len(edge["from_name"])) % 2 == 0 else -1
            bend = sign * (8.0 + 10.0 * (1.0 - math.sqrt(edge_weight)))
            cx = (x1 + x2) / 2 + px * bend
            cy = (y1 + y2) / 2 + py * bend
            parts.append(
                f'<path d="M {x1:.2f},{y1:.2f} Q {cx:.2f},{cy:.2f} {x2:.2f},{y2:.2f}" '
                f'stroke="{color}" stroke-width="{width_px:.2f}" stroke-opacity="{opacity:.2f}"/>'
            )
    parts.append("</g>")

    parts.append('<g id="drug_edges" stroke-linecap="round" fill="none">')
    for component in components:
        for drug in component["drug_positions_px"]:
            style = STATUS_STYLE.get(drug["status"], STATUS_STYLE["unknown"])
            targets_sorted = sorted(
                drug["targets"],
                key=lambda item: component["gene_positions_px"][item["target"]][0] + component["gene_positions_px"][item["target"]][1],
            )
            for link_index, link in enumerate(targets_sorted):
                tx, ty = component["gene_positions_px"][link["target"]]
                dx = drug["x"] - tx
                dy = drug["y"] - ty
                dist = math.hypot(dx, dy) + 1e-6
                ux, uy = dx / dist, dy / dist
                px, py = -uy, ux
                side_unit = {
                    "top": (0.0, -1.0),
                    "bottom": (0.0, 1.0),
                    "left": (-1.0, 0.0),
                    "right": (1.0, 0.0),
                }[drug["side"]]
                offset = (link_index - (len(targets_sorted) - 1) / 2) * 18.0
                mx, my = (tx + drug["x"]) / 2, (ty + drug["y"]) / 2
                outward_bend = 26.0
                cx = mx + px * offset + side_unit[0] * outward_bend
                cy = my + py * offset + side_unit[1] * outward_bend
                parts.append(
                    f'<path d="M {tx:.2f},{ty:.2f} Q {cx:.2f},{cy:.2f} {drug["x"]:.2f},{drug["y"]:.2f}" '
                    f'stroke="{style["edge"]}" stroke-width="2.0" '
                    + (f'stroke-dasharray="{style["dash"]}" ' if style["dash"] else "")
                    + 'stroke-opacity="0.92" fill="none"/>'
                )
                badge_t = 0.61
                bx = (1 - badge_t) * (1 - badge_t) * tx + 2 * (1 - badge_t) * badge_t * cx + badge_t * badge_t * drug["x"]
                by = (1 - badge_t) * (1 - badge_t) * ty + 2 * (1 - badge_t) * badge_t * cy + badge_t * badge_t * drug["y"]
                bx += side_unit[0] * 10.0 + px * offset * 0.18
                by += side_unit[1] * 10.0 + py * offset * 0.18
                label = link["citation"]
                label_w = max(64.0, 12.0 + len(label) * 5.8)
                label_h = 15.0
                parts.append(
                    f'<rect x="{bx - label_w / 2:.2f}" y="{by - label_h / 2:.2f}" width="{label_w:.2f}" height="{label_h:.2f}" '
                    'rx="7" fill="white" fill-opacity="0.88" stroke="none"/>'
                )
                parts.append(
                    f'<text x="{bx:.2f}" y="{by + 3.1:.2f}" text-anchor="middle" '
                    'font-family="Helvetica,Arial,sans-serif" font-size="8.4" font-weight="500" fill="#6b6b6b">'
                    + label
                    + '</text>'
                )
                citation_rows.append(
                    {
                        "Citation Text": label,
                        "Target": link["target"],
                        "Drug": drug["name"],
                        "Development Status": drug["status"],
                        "Drug Class": link["drug_class"],
                        "Evidence Citation": link["citation"],
                    }
                )
                edge_rows.append(
                    {
                        "Target": link["target"],
                        "Drug": drug["name"],
                        "Development Status": drug["status"],
                        "Citation Text": label,
                        "Evidence Citation": link["citation"],
                    }
                )
    parts.append("</g>")

    parts.append('<g id="gene_nodes">')
    for component in components:
        for node in sorted(component["genes"], key=lambda item: item["Weight"]):
            x, y = component["gene_positions_px"][node["gene_node_name"]]
            weight = float(node["Weight"])
            radius_px = node_radius(weight, IMPORTANT_GENE_THRESHOLD)
            fill = "#f5a3a3" if node["gene_node_idx"] in pvalue_ids else "#b8e0ee"
            font_size = node_font_size(weight, IMPORTANT_GENE_THRESHOLD)
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius_px:.2f}" fill="{fill}" stroke="none"/>'
            )
            if weight >= HUB_RING_THRESHOLD:
                parts.append(
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius_px + 3.5:.2f}" fill="none" stroke="#ff8f1f" stroke-width="2.5"/>'
                )
            parts.append(
                f'<text x="{x:.2f}" y="{y + font_size * 0.33:.2f}" text-anchor="middle" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="{font_size:.1f}" font-weight="600" fill="#4a4a4a">{node["gene_node_name"]}</text>'
            )
    parts.append("</g>")

    parts.append('<g id="drug_nodes">')
    for component in components:
        for drug in component["drug_positions_px"]:
            style = STATUS_STYLE.get(drug["status"], STATUS_STYLE["unknown"])
            width_px, height_px = drug_box_dimensions_px(drug)
            x0 = drug["x"] - width_px / 2
            y0 = drug["y"] - height_px / 2
            parts.append(
                f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{width_px:.2f}" height="{height_px:.2f}" '
                f'rx="11" fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1.6"/>'
            )
            parts.append(
                f'<text x="{drug["x"]:.2f}" y="{drug["y"] + 4.1:.2f}" text-anchor="middle" '
                'font-family="Helvetica,Arial,sans-serif" font-size="11.0" font-weight="700" fill="#2b2b2b">'
                + drug["name"]
                + '</text>'
            )
    parts.append("</g>")

    parts.append("</svg>")
    return "\n".join(parts) + "\n", edge_rows, citation_rows


def write_csv(path, rows, fieldnames):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    _, pvalue_ids, nodes, edges = load_figure4_graph()
    drugs = load_drug_overlay({node["gene_node_name"] for node in nodes})
    components = build_augmented_layout(nodes, edges, drugs)
    svg_text, edge_rows, citation_rows = render_svg(nodes, components, pvalue_ids)
    OUTPUT_SVG.write_text(svg_text)
    write_csv(
        OUTPUT_EDGE_CSV,
        edge_rows,
        ["Target", "Drug", "Development Status", "Citation Text", "Evidence Citation"],
    )
    write_csv(
        OUTPUT_CITATION_CSV,
        citation_rows,
        ["Citation Text", "Target", "Drug", "Development Status", "Drug Class", "Evidence Citation"],
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Automatic renderer for mixed gene+drug network JSON.

Expected input schema:
- nodes[*]:
  - required: id
  - optional: type (gene|drug), weight, status
- edges[*]:
  - required: source, target
  - optional: type (gene-gene|target-drug), evidence, weight

Design goals:
- Preserve the same automatic layout strategy as render_gene_network_auto.py
- Deterministic by seed
- Multi-attempt layout with quality scoring and best-attempt selection
- Validation plus machine-readable metrics
"""

import argparse
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


REQUIRED_NODE_FIELDS = ("id",)
REQUIRED_EDGE_FIELDS = ("source", "target")


@dataclass
class Node:
    node_id: int
    name: str
    kind: str
    weight: float
    status: Optional[str]


@dataclass
class Edge:
    src: int
    dst: int
    weight: float
    kind: str
    evidence: Optional[str]


@dataclass
class LayoutResult:
    positions: Dict[int, Tuple[float, float]]
    radii: Dict[int, float]
    font_sizes: Dict[int, float]
    metrics: Dict[str, float]
    score: float
    seed: int
    layout_seconds: float = 0.0


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    q = clamp(q, 0.0, 1.0)
    xs = sorted(values)
    idx = q * (len(xs) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return xs[lo]
    frac = idx - lo
    return xs[lo] * (1.0 - frac) + xs[hi] * frac


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fully automatic mixed gene+drug graph renderer for JSON with "
            "nodes(id/type/weight/status) and edges(source/target/type/evidence/weight)."
        )
    )
    parser.add_argument("input_json", type=Path, help="Input JSON file path.")
    parser.add_argument("--output-svg", type=Path, default=None, help="Output SVG path.")
    parser.add_argument("--output-metrics", type=Path, default=None, help="Output metrics JSON path.")
    parser.add_argument("--width", type=int, default=2400, help="Canvas width.")
    parser.add_argument("--height", type=int, default=1400, help="Canvas height.")
    parser.add_argument("--seed", type=int, default=42, help="Base random seed.")
    parser.add_argument("--attempts", type=int, default=5, help="Number of independent layout attempts.")
    parser.add_argument(
        "--max-edge-cross-checks",
        type=int,
        default=40000,
        help="Maximum edge-pair checks for crossing estimate.",
    )
    return parser.parse_args()


def normalize_node_kind(kind_raw: Optional[str]) -> str:
    k = (kind_raw or "").strip().lower()
    if k in {"gene", "drug"}:
        return k
    return "gene"


def normalize_edge_kind(kind_raw: Optional[str]) -> str:
    k = (kind_raw or "").strip().lower()
    if k in {"gene-gene", "target-drug"}:
        return k
    return "gene-gene"


def validate_and_load_graph(path: Path) -> Tuple[List[Node], List[Edge], Dict[str, float]]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("Input JSON must be an object.")

    if "nodes" not in payload or "edges" not in payload:
        raise ValueError("Input JSON must contain top-level 'nodes' and 'edges'.")
    if not isinstance(payload["nodes"], list) or not isinstance(payload["edges"], list):
        raise ValueError("'nodes' and 'edges' must be arrays.")

    nodes: List[Node] = []
    name_to_id: Dict[str, int] = {}
    invalid_node_weight = 0
    empty_names = 0
    unknown_node_types = 0

    for idx, row in enumerate(payload["nodes"]):
        if not isinstance(row, dict):
            raise ValueError(f"Node at index {idx} is not an object.")
        for field in REQUIRED_NODE_FIELDS:
            if field not in row:
                raise ValueError(f"Node at index {idx} missing field '{field}'.")

        name = str(row["id"]).strip()
        if not name:
            empty_names += 1
            name = f"node_{idx}"

        if name in name_to_id:
            raise ValueError(f"Duplicate node id/name detected: {name}")

        kind_raw = row.get("type")
        kind = normalize_node_kind(kind_raw)
        if (kind_raw is not None) and (str(kind_raw).strip().lower() not in {"gene", "drug"}):
            unknown_node_types += 1

        if "weight" in row and row["weight"] is not None:
            try:
                weight = float(row["weight"])
            except Exception as exc:
                raise ValueError(f"Node '{name}' has non-numeric weight: {row['weight']} ({exc})") from exc
        else:
            weight = 1.0

        if not math.isfinite(weight) or weight < 0:
            invalid_node_weight += 1
            weight = 0.0

        status_raw = row.get("status")
        status = str(status_raw).strip() if status_raw is not None and str(status_raw).strip() else None

        node_id = len(nodes)
        name_to_id[name] = node_id
        nodes.append(Node(node_id=node_id, name=name, kind=kind, weight=weight, status=status))

    edges: List[Edge] = []
    dropped_edges = 0
    self_loops = 0
    invalid_edge_weight = 0
    unknown_edge_types = 0

    dedup: Dict[Tuple[int, int, str], Tuple[float, Optional[str]]] = {}
    for idx, row in enumerate(payload["edges"]):
        if not isinstance(row, dict):
            raise ValueError(f"Edge at index {idx} is not an object.")
        for field in REQUIRED_EDGE_FIELDS:
            if field not in row:
                raise ValueError(f"Edge at index {idx} missing field '{field}'.")

        src_name = str(row["source"]).strip()
        dst_name = str(row["target"]).strip()
        if src_name not in name_to_id or dst_name not in name_to_id:
            dropped_edges += 1
            continue

        src = name_to_id[src_name]
        dst = name_to_id[dst_name]
        if src == dst:
            self_loops += 1
            continue

        kind_raw = row.get("type")
        kind = normalize_edge_kind(kind_raw)
        if (kind_raw is not None) and (str(kind_raw).strip().lower() not in {"gene-gene", "target-drug"}):
            unknown_edge_types += 1

        if "weight" in row and row["weight"] is not None:
            try:
                weight = float(row["weight"])
            except Exception:
                invalid_edge_weight += 1
                weight = 0.0
        else:
            weight = 1.0

        if not math.isfinite(weight) or weight < 0:
            invalid_edge_weight += 1
            weight = 0.0

        evidence_raw = row.get("evidence")
        evidence = str(evidence_raw).strip() if evidence_raw is not None and str(evidence_raw).strip() else None

        a, b = (src, dst) if src < dst else (dst, src)
        key = (a, b, kind)
        current = dedup.get(key)
        if current is None or weight > current[0]:
            dedup[key] = (weight, evidence)

    for (a, b, kind), (w, evidence) in dedup.items():
        edges.append(Edge(src=a, dst=b, weight=w, kind=kind, evidence=evidence))

    if not nodes:
        raise ValueError("No valid nodes found.")
    if not edges:
        raise ValueError("No valid edges found after validation/dedup.")

    n_gene = sum(1 for n in nodes if n.kind == "gene")
    n_drug = sum(1 for n in nodes if n.kind == "drug")
    e_gene_gene = sum(1 for e in edges if e.kind == "gene-gene")
    e_target_drug = sum(1 for e in edges if e.kind == "target-drug")

    quality = {
        "node_count": float(len(nodes)),
        "edge_count": float(len(edges)),
        "gene_nodes": float(n_gene),
        "drug_nodes": float(n_drug),
        "gene_gene_edges": float(e_gene_gene),
        "target_drug_edges": float(e_target_drug),
        "dropped_edges_missing_nodes": float(dropped_edges),
        "dropped_self_loops": float(self_loops),
        "normalized_bad_node_weights": float(invalid_node_weight),
        "normalized_bad_edge_weights": float(invalid_edge_weight),
        "empty_node_names_fixed": float(empty_names),
        "unknown_node_types_defaulted": float(unknown_node_types),
        "unknown_edge_types_defaulted": float(unknown_edge_types),
    }
    return nodes, edges, quality


def connected_components(nodes: Sequence[Node], edges: Sequence[Edge]) -> List[List[int]]:
    adjacency = {n.node_id: set() for n in nodes}
    for e in edges:
        adjacency[e.src].add(e.dst)
        adjacency[e.dst].add(e.src)

    seen = set()
    comps = []
    for n in adjacency:
        if n in seen:
            continue
        stack = [n]
        seen.add(n)
        comp = []
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in adjacency[cur]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        comps.append(sorted(comp))
    return sorted(comps, key=len, reverse=True)


def force_layout_component(
    comp_ids: Sequence[int],
    edges_by_comp: Sequence[Edge],
    weight_by_id: Dict[int, float],
    seed: int,
) -> Dict[int, Tuple[float, float]]:
    rng = random.Random(seed)
    ids = list(comp_ids)
    n = len(ids)
    if n == 1:
        return {ids[0]: (0.0, 0.0)}

    positions = {i: [rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5)] for i in ids}
    degree = {i: 0 for i in ids}
    for e in edges_by_comp:
        degree[e.src] += 1
        degree[e.dst] += 1

    area = 1.0
    k = math.sqrt(area / max(1, n))
    temp = 0.18
    iterations = 420 if n > 90 else 320 if n > 40 else 240

    for _ in range(iterations):
        disp = {i: [0.0, 0.0] for i in ids}

        for ix, a in enumerate(ids):
            ax, ay = positions[a]
            for b in ids[ix + 1 :]:
                bx, by = positions[b]
                dx = ax - bx
                dy = ay - by
                d = math.hypot(dx, dy) + 1e-6
                rep = (k * k) / d
                ux, uy = dx / d, dy / d
                disp[a][0] += ux * rep
                disp[a][1] += uy * rep
                disp[b][0] -= ux * rep
                disp[b][1] -= uy * rep

        for e in edges_by_comp:
            a, b = e.src, e.dst
            ax, ay = positions[a]
            bx, by = positions[b]
            dx, dy = bx - ax, by - ay
            d = math.hypot(dx, dy) + 1e-6
            w = 0.20 + 1.80 * math.sqrt(max(e.weight, 0.0))
            spring = (d * d / k) * (0.16 * w)
            ux, uy = dx / d, dy / d
            disp[a][0] += ux * spring
            disp[a][1] += uy * spring
            disp[b][0] -= ux * spring
            disp[b][1] -= uy * spring

        for i in ids:
            x, y = positions[i]
            center_pull = 0.010 * (1.0 + 0.03 * degree[i])
            disp[i][0] -= x * center_pull
            disp[i][1] -= y * center_pull

            dx, dy = disp[i]
            mag = math.hypot(dx, dy) + 1e-9
            step = min(temp, mag)
            momentum = 0.75 + 0.35 * math.sqrt(max(weight_by_id[i], 0.0))
            positions[i][0] += (dx / mag) * step * momentum
            positions[i][1] += (dy / mag) * step * momentum

        temp *= 0.987

    xs = [positions[i][0] for i in ids]
    ys = [positions[i][1] for i in ids]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    sx = max(max_x - min_x, 1e-6)
    sy = max(max_y - min_y, 1e-6)

    out = {}
    for i in ids:
        x = (positions[i][0] - min_x) / sx - 0.5
        y = (positions[i][1] - min_y) / sy - 0.5
        out[i] = (x, y)
    return out


def component_bbox(
    comp_ids: Sequence[int],
    local_positions: Dict[int, Tuple[float, float]],
    radii: Dict[int, float],
) -> Tuple[float, float, float, float]:
    x0 = float("inf")
    y0 = float("inf")
    x1 = float("-inf")
    y1 = float("-inf")
    for i in comp_ids:
        x, y = local_positions[i]
        r = radii[i]
        x0 = min(x0, x - r)
        y0 = min(y0, y - r)
        x1 = max(x1, x + r)
        y1 = max(y1, y + r)
    return x0, y0, x1, y1


def rect_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], pad: float = 0.0) -> bool:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 + pad <= bx0 or bx1 + pad <= ax0 or ay1 + pad <= by0 or by1 + pad <= ay0)


def pack_components(
    components: Sequence[List[int]],
    local_positions: Dict[int, Tuple[float, float]],
    radii: Dict[int, float],
    rng: random.Random,
) -> Dict[int, Tuple[float, float]]:
    placed_rects: List[Tuple[float, float, float, float]] = []
    offsets: Dict[int, Tuple[float, float]] = {}

    comp_sizes = []
    for comp_idx, comp in enumerate(components):
        box = component_bbox(comp, local_positions, radii)
        w = box[2] - box[0]
        h = box[3] - box[1]
        comp_sizes.append((comp_idx, w * h, w, h, box))

    for rank, (comp_idx, _, w, h, box) in enumerate(sorted(comp_sizes, key=lambda x: x[1], reverse=True)):
        if rank == 0:
            ox = -((box[0] + box[2]) / 2)
            oy = -((box[1] + box[3]) / 2)
            rect = (box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy)
            offsets[comp_idx] = (ox, oy)
            placed_rects.append(rect)
            continue

        placed = False
        angle = rng.uniform(0.0, math.pi * 2)
        radius = max(0.8, math.sqrt(w * h) * 1.4)
        for _ in range(1400):
            x = math.cos(angle) * radius
            y = math.sin(angle) * radius
            ox = x - (box[0] + box[2]) / 2
            oy = y - (box[1] + box[3]) / 2
            rect = (box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy)
            if all(not rect_overlap(rect, other, pad=0.10) for other in placed_rects):
                offsets[comp_idx] = (ox, oy)
                placed_rects.append(rect)
                placed = True
                break
            angle += 0.31
            radius += 0.0045

        if not placed:
            ox = -((box[0] + box[2]) / 2) + rng.uniform(-0.2, 0.2)
            oy = -((box[1] + box[3]) / 2) + rng.uniform(-0.2, 0.2)
            offsets[comp_idx] = (ox, oy)
            placed_rects.append((box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy))

    out = {}
    for comp_idx, comp in enumerate(components):
        ox, oy = offsets[comp_idx]
        for i in comp:
            x, y = local_positions[i]
            out[i] = (x + ox, y + oy)
    return out


def global_relax(
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    pos: Dict[int, Tuple[float, float]],
    radii: Dict[int, float],
) -> Dict[int, Tuple[float, float]]:
    ids = [n.node_id for n in nodes]
    p = {i: [pos[i][0], pos[i][1]] for i in ids}
    home = {i: [pos[i][0], pos[i][1]] for i in ids}

    temp = 0.10
    for _ in range(260):
        disp = {i: [0.0, 0.0] for i in ids}

        for ix, a in enumerate(ids):
            ax, ay = p[a]
            for b in ids[ix + 1 :]:
                bx, by = p[b]
                dx = ax - bx
                dy = ay - by
                d = math.hypot(dx, dy) + 1e-6
                desired = radii[a] + radii[b] + 0.020
                rep = 0.003 / (d * d)
                if d < desired:
                    rep += (desired - d) * 0.48
                ux, uy = dx / d, dy / d
                disp[a][0] += ux * rep
                disp[a][1] += uy * rep
                disp[b][0] -= ux * rep
                disp[b][1] -= uy * rep

        for e in edges:
            a, b = e.src, e.dst
            ax, ay = p[a]
            bx, by = p[b]
            dx = bx - ax
            dy = by - ay
            d = math.hypot(dx, dy) + 1e-6
            desired = 0.13 + 0.10 * (1.0 - math.sqrt(max(e.weight, 0.0)))
            spring = 0.050 + 0.025 * math.sqrt(max(e.weight, 0.0))
            force = (d - desired) * spring
            ux, uy = dx / d, dy / d
            disp[a][0] += ux * force
            disp[a][1] += uy * force
            disp[b][0] -= ux * force
            disp[b][1] -= uy * force

        for i in ids:
            x, y = p[i]
            hx, hy = home[i]
            disp[i][0] += (hx - x) * 0.018
            disp[i][1] += (hy - y) * 0.018
            disp[i][0] += -x * 0.006
            disp[i][1] += -y * 0.006

            dx, dy = disp[i]
            mag = math.hypot(dx, dy)
            if mag > 1e-9:
                step = min(temp, mag)
                p[i][0] += dx / mag * step
                p[i][1] += dy / mag * step

        temp *= 0.989

    return {i: (p[i][0], p[i][1]) for i in ids}


def normalize_to_canvas(
    pos: Dict[int, Tuple[float, float]],
    radii: Dict[int, float],
    width: int,
    height: int,
    margin: int = 60,
) -> Dict[int, Tuple[float, float]]:
    x0 = min(pos[i][0] - radii[i] for i in pos)
    x1 = max(pos[i][0] + radii[i] for i in pos)
    y0 = min(pos[i][1] - radii[i] for i in pos)
    y1 = max(pos[i][1] + radii[i] for i in pos)

    span_x = max(x1 - x0, 1e-6)
    span_y = max(y1 - y0, 1e-6)
    fit_w = max(100.0, width - 2 * margin)
    fit_h = max(100.0, height - 2 * margin)
    scale = min(fit_w / span_x, fit_h / span_y)

    off_x = (width - span_x * scale) / 2 - x0 * scale
    off_y = (height - span_y * scale) / 2 - y0 * scale

    return {i: (pos[i][0] * scale + off_x, pos[i][1] * scale + off_y) for i in pos}


def drug_box_dimensions(label: str, font_px: float) -> Tuple[float, float, float]:
    """Return rounded-rect width/height and an equivalent collision radius."""
    text_w = len(label) * font_px * 0.54 + 16.0
    box_w = clamp(text_w, 58.0, 118.0)
    box_h = clamp(font_px * 1.95, 26.0, 34.0)
    box_r = math.hypot(box_w / 2.0, box_h / 2.0)
    return box_w, box_h, box_r


def node_layout_radii(nodes: Sequence[Node]) -> Dict[int, float]:
    weights = [n.weight for n in nodes]
    w95 = max(percentile(weights, 0.95), 1e-6)
    out = {}
    for n in nodes:
        nw = math.sqrt(clamp(n.weight / w95, 0.0, 1.4))
        base = 0.014 if n.kind == "drug" else 0.018
        extra = 0.003 if n.kind == "drug" else 0.004
        out[n.node_id] = base + extra * nw
    return out


def node_render_visual_params(nodes: Sequence[Node]) -> Tuple[Dict[int, float], Dict[int, float]]:
    weights = [n.weight for n in nodes]
    w95 = max(percentile(weights, 0.95), 1e-6)

    radii_px = {}
    fonts_px = {}
    for n in nodes:
        nw = math.sqrt(clamp(n.weight / w95, 0.0, 1.4))
        if n.kind == "drug":
            font_px = clamp(10.2 + 0.4 * nw, 10.0, 10.8)
            _, _, box_radius_px = drug_box_dimensions(n.name, font_px)
            radii_px[n.node_id] = box_radius_px + 1.5
            fonts_px[n.node_id] = font_px
            continue
        else:
            font_px = 12.0 + 2.1 * nw
            weight_radius_px = 20.0 + 7.8 * nw

        label_w = max(1.0, len(n.name) * font_px * 0.56)
        label_h = font_px * 1.10
        label_radius_px = math.hypot(label_w / 2.0, label_h / 2.0) + 4.5

        radii_px[n.node_id] = max(weight_radius_px, label_radius_px)
        fonts_px[n.node_id] = font_px

    return radii_px, fonts_px


def relax_positions_for_render(
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    positions_px: Dict[int, Tuple[float, float]],
    radii_px: Dict[int, float],
    width: int,
    height: int,
    seed: int,
) -> Dict[int, Tuple[float, float]]:
    ids = [n.node_id for n in nodes]
    p = {i: [positions_px[i][0], positions_px[i][1]] for i in ids}
    home = {i: [positions_px[i][0], positions_px[i][1]] for i in ids}
    edge_w95 = max(percentile([e.weight for e in edges], 0.95), 1e-6)
    rng = random.Random(seed + 1234567)

    for i in ids:
        p[i][0] += rng.uniform(-0.2, 0.2)
        p[i][1] += rng.uniform(-0.2, 0.2)

    temp = 10.8
    for _ in range(340):
        disp = {i: [0.0, 0.0] for i in ids}

        for ix, a in enumerate(ids):
            ax, ay = p[a]
            for b in ids[ix + 1 :]:
                bx, by = p[b]
                dx = ax - bx
                dy = ay - by
                d = math.hypot(dx, dy) + 1e-6
                desired = radii_px[a] + radii_px[b] + 24.0
                rep = 1300.0 / (d * d)
                if d < desired:
                    rep += (desired - d) * 1.24
                ux, uy = dx / d, dy / d
                disp[a][0] += ux * rep
                disp[a][1] += uy * rep
                disp[b][0] -= ux * rep
                disp[b][1] -= uy * rep

        for e in edges:
            a, b = e.src, e.dst
            ax, ay = p[a]
            bx, by = p[b]
            dx = bx - ax
            dy = by - ay
            d = math.hypot(dx, dy) + 1e-6
            wnorm = clamp(math.sqrt(e.weight / edge_w95), 0.0, 1.3)
            if e.kind == "target-drug":
                desired = radii_px[a] + radii_px[b] + 102.0 + (1.0 - wnorm) * 30.0
                spring = 0.058 + 0.022 * wnorm
            else:
                desired = radii_px[a] + radii_px[b] + 88.0 + (1.0 - wnorm) * 34.0
                spring = 0.060 + 0.026 * wnorm
            force = (d - desired) * spring
            ux, uy = dx / d, dy / d
            disp[a][0] += ux * force
            disp[a][1] += uy * force
            disp[b][0] -= ux * force
            disp[b][1] -= uy * force

        for i in ids:
            x, y = p[i]
            hx, hy = home[i]
            disp[i][0] += (hx - x) * 0.007
            disp[i][1] += (hy - y) * 0.007
            disp[i][0] += (width * 0.5 - x) * 0.00055
            disp[i][1] += (height * 0.5 - y) * 0.00055

            dx, dy = disp[i]
            mag = math.hypot(dx, dy)
            if mag > 1e-9:
                step = min(temp, mag)
                p[i][0] += dx / mag * step
                p[i][1] += dy / mag * step

            margin = radii_px[i] + 8.0
            p[i][0] = clamp(p[i][0], margin, width - margin)
            p[i][1] = clamp(p[i][1], margin, height - margin)

        temp *= 0.990

    return {i: (p[i][0], p[i][1]) for i in ids}


def estimate_label_rects(
    nodes: Sequence[Node],
    positions_px: Dict[int, Tuple[float, float]],
    radii_px: Dict[int, float],
    font_sizes: Dict[int, float],
) -> Dict[int, Tuple[float, float, float, float]]:
    rects = {}
    for n in nodes:
        x, y = positions_px[n.node_id]
        fs = font_sizes[n.node_id]
        label_w = max(2.0 * radii_px[n.node_id], len(n.name) * fs * 0.58)
        label_h = fs * 1.18
        rects[n.node_id] = (x - label_w / 2, y - label_h / 2, x + label_w / 2, y + label_h / 2)
    return rects


def segment_intersect(a1, a2, b1, b2) -> bool:
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1 = orient(a1, a2, b1)
    o2 = orient(a1, a2, b2)
    o3 = orient(b1, b2, a1)
    o4 = orient(b1, b2, a2)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def compute_quality_metrics(
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    positions_px: Dict[int, Tuple[float, float]],
    radii_px: Dict[int, float],
    font_sizes: Dict[int, float],
    width: int,
    height: int,
    max_edge_cross_checks: int,
) -> Dict[str, float]:
    ids = [n.node_id for n in nodes]

    node_overlap = 0
    for i, a in enumerate(ids):
        ax, ay = positions_px[a]
        for b in ids[i + 1 :]:
            bx, by = positions_px[b]
            d = math.hypot(ax - bx, ay - by)
            if d < radii_px[a] + radii_px[b] + 1.0:
                node_overlap += 1

    label_rects = estimate_label_rects(nodes, positions_px, radii_px, font_sizes)
    label_overlap = 0
    for i, a in enumerate(ids):
        ra = label_rects[a]
        for b in ids[i + 1 :]:
            rb = label_rects[b]
            if rect_overlap(ra, rb, pad=0.4):
                label_overlap += 1

    label_node_overlap = 0
    for a in ids:
        rx0, ry0, rx1, ry1 = label_rects[a]
        for b in ids:
            if a == b:
                continue
            cx, cy = positions_px[b]
            r = radii_px[b]
            near_x = clamp(cx, rx0, rx1)
            near_y = clamp(cy, ry0, ry1)
            if (cx - near_x) ** 2 + (cy - near_y) ** 2 < (r * 0.8) ** 2:
                label_node_overlap += 1

    crossing = 0
    checks = 0
    edge_pairs = []
    m = len(edges)
    for i in range(m):
        e1 = edges[i]
        for j in range(i + 1, m):
            e2 = edges[j]
            if len({e1.src, e1.dst, e2.src, e2.dst}) < 4:
                continue
            edge_pairs.append((e1, e2))

    if len(edge_pairs) > max_edge_cross_checks:
        step = len(edge_pairs) / max_edge_cross_checks
        sample_pairs = [edge_pairs[int(k * step)] for k in range(max_edge_cross_checks)]
    else:
        sample_pairs = edge_pairs

    for e1, e2 in sample_pairs:
        checks += 1
        a1, a2 = positions_px[e1.src], positions_px[e1.dst]
        b1, b2 = positions_px[e2.src], positions_px[e2.dst]
        if segment_intersect(a1, a2, b1, b2):
            crossing += 1

    xs = [positions_px[i][0] for i in ids]
    ys = [positions_px[i][1] for i in ids]
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    used_area = max(1.0, (max_x - min_x) * (max_y - min_y))
    canvas_area = float(width * height)
    whitespace_ratio = 1.0 - clamp(used_area / canvas_area, 0.0, 1.0)

    return {
        "node_overlap_pairs": float(node_overlap),
        "label_overlap_pairs": float(label_overlap),
        "label_node_overlap_pairs": float(label_node_overlap),
        "edge_crossings_estimate": float(crossing),
        "edge_crossing_checks": float(checks),
        "whitespace_ratio": float(whitespace_ratio),
        "node_count": float(len(nodes)),
        "edge_count": float(len(edges)),
    }


def score_metrics(metrics: Dict[str, float]) -> float:
    return (
        metrics["node_overlap_pairs"] * 15.0
        + metrics["label_overlap_pairs"] * 4.5
        + metrics["label_node_overlap_pairs"] * 0.9
        + metrics["edge_crossings_estimate"] * 0.14
        + metrics["whitespace_ratio"] * 220.0
    )


def build_layout(
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    width: int,
    height: int,
    seed: int,
    max_edge_cross_checks: int,
) -> LayoutResult:
    rng = random.Random(seed)

    layout_radii_local = node_layout_radii(nodes)
    render_radii_px, font_sizes = node_render_visual_params(nodes)
    weight_by_id = {n.node_id: n.weight for n in nodes}
    components = connected_components(nodes, edges)
    edge_by_comp = []
    comp_index = {}
    for ci, comp in enumerate(components):
        for nid in comp:
            comp_index[nid] = ci
        edge_by_comp.append([])

    for e in edges:
        ci = comp_index[e.src]
        if ci == comp_index[e.dst]:
            edge_by_comp[ci].append(e)

    local_positions = {}
    for ci, comp in enumerate(components):
        comp_seed = seed * 1009 + ci * 37 + 17
        comp_layout = force_layout_component(comp, edge_by_comp[ci], weight_by_id, comp_seed)
        local_positions.update(comp_layout)

    packed = pack_components(components, local_positions, layout_radii_local, rng)
    relaxed = global_relax(nodes, edges, packed, layout_radii_local)
    positions_px = normalize_to_canvas(relaxed, layout_radii_local, width, height, margin=46)
    positions_px = relax_positions_for_render(
        nodes=nodes,
        edges=edges,
        positions_px=positions_px,
        radii_px=render_radii_px,
        width=width,
        height=height,
        seed=seed,
    )

    metrics = compute_quality_metrics(
        nodes,
        edges,
        positions_px,
        render_radii_px,
        font_sizes,
        width,
        height,
        max_edge_cross_checks,
    )
    score = score_metrics(metrics)
    return LayoutResult(
        positions=positions_px,
        radii=render_radii_px,
        font_sizes=font_sizes,
        metrics=metrics,
        score=score,
        seed=seed,
    )


def svg_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def edge_stroke(edge: Edge, w95: float) -> Tuple[str, float, float, Optional[str]]:
    norm = clamp(math.sqrt(edge.weight / max(w95, 1e-9)), 0.0, 1.2)
    if edge.kind == "target-drug":
        width = 1.6 + 2.8 * norm
        opacity = 0.82 + 0.13 * norm
        return "#a16207", width, opacity, "6 4"

    shade = int(round(196 - 136 * norm))
    color = f"#{shade:02x}{shade:02x}{shade:02x}"
    width = 1.2 + 3.1 * norm
    opacity = 0.84 + 0.12 * norm
    return color, width, opacity, None


def gene_node_fill(weight: float, w95: float) -> str:
    norm = clamp(math.sqrt(weight / max(w95, 1e-9)), 0.0, 1.2)
    r = int(round(199 - 66 * norm))
    g = int(round(228 - 82 * norm))
    b = int(round(241 - 68 * norm))
    return f"#{r:02x}{g:02x}{b:02x}"


def drug_node_fill(status: Optional[str]) -> str:
    s = (status or "").strip().lower()
    if "approved" in s:
        return "#d1fae5"
    if "investigational" in s:
        return "#ffedd5"
    return "#e5e7eb"


def node_stroke(node: Node) -> Tuple[str, float]:
    if node.kind == "drug":
        return "#92400e", 1.4
    return "none", 0.0


def build_svg(
    nodes: Sequence[Node],
    edges: Sequence[Edge],
    layout: LayoutResult,
    width: int,
    height: int,
) -> str:
    weights = [n.weight for n in nodes]
    w95 = max(percentile(weights, 0.95), 1e-6)
    gene_weights = [n.weight for n in nodes if n.kind == "gene"]
    hub_threshold = percentile(gene_weights, 0.90) if gene_weights else float("inf")

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<g id="edges" fill="none" stroke-linecap="round">',
    ]
    edge_labels: List[Tuple[float, float, str]] = []

    for idx, e in enumerate(sorted(edges, key=lambda x: x.weight)):
        x1, y1 = layout.positions[e.src]
        x2, y2 = layout.positions[e.dst]
        color, sw, op, dash = edge_stroke(e, w95)
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy) + 1e-6
        px, py = -dy / d, dx / d
        sign = 1 if (idx + e.src) % 2 == 0 else -1
        if e.kind == "target-drug":
            bend = sign * (8.0 + 12.0 * (1.0 - clamp(math.sqrt(e.weight / w95), 0.0, 1.2)))
        else:
            bend = sign * (6.0 + 10.0 * (1.0 - clamp(math.sqrt(e.weight / w95), 0.0, 1.2)))
        cx = (x1 + x2) / 2 + px * bend
        cy = (y1 + y2) / 2 + py * bend
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(
            f'<path d="M {x1:.2f},{y1:.2f} Q {cx:.2f},{cy:.2f} {x2:.2f},{y2:.2f}" '
            f'stroke="{color}" stroke-width="{sw:.2f}" stroke-opacity="{op:.2f}"{dash_attr}/>'
        )
        if e.kind == "target-drug" and e.evidence:
            # Put edge evidence near the curve control point, shifted slightly
            # along its normal direction to keep text off the stroke.
            label_x = cx + px * 8.0
            label_y = cy + py * 8.0
            edge_labels.append((label_x, label_y, e.evidence))

    parts.append("</g>")
    if edge_labels:
        parts.append('<g id="edge-labels">')
        for lx, ly, label in edge_labels:
            fs = 8.6
            text = svg_escape(label)
            tw = len(label) * fs * 0.54 + 8.0
            th = fs * 1.45
            rx = lx - tw / 2.0
            ry = ly - th / 2.0
            parts.append(
                f'<rect x="{rx:.2f}" y="{ry:.2f}" width="{tw:.2f}" height="{th:.2f}" '
                'rx="3.0" ry="3.0" fill="white" fill-opacity="0.84" stroke="#d6b98e" stroke-width="0.6"/>'
            )
            parts.append(
                f'<text x="{lx:.2f}" y="{ly + fs * 0.32:.2f}" text-anchor="middle" '
                f'font-family="Helvetica,Arial,sans-serif" font-size="{fs:.1f}" '
                f'font-weight="600" fill="#7c4f12">{text}</text>'
            )
        parts.append("</g>")
    parts.append('<g id="nodes">')

    for n in sorted(nodes, key=lambda x: x.weight):
        x, y = layout.positions[n.node_id]
        r = layout.radii[n.node_id]
        fs = layout.font_sizes[n.node_id]
        fill = drug_node_fill(n.status) if n.kind == "drug" else gene_node_fill(n.weight, w95)
        stroke, stroke_w = node_stroke(n)
        if n.kind == "drug":
            box_w, box_h, _ = drug_box_dimensions(n.name, fs)
            rx = min(11.0, box_h * 0.42)
            x0 = x - box_w / 2.0
            y0 = y - box_h / 2.0
            parts.append(
                f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{box_w:.2f}" height="{box_h:.2f}" '
                f'rx="{rx:.2f}" ry="{rx:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w:.2f}"/>'
            )
        else:
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r:.2f}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{stroke_w:.2f}"/>'
            )
        if n.kind == "gene" and n.weight >= hub_threshold:
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r + 3.0:.2f}" '
                'fill="none" stroke="#ef7d00" stroke-width="2.0"/>'
            )
        parts.append(
            f'<text x="{x:.2f}" y="{y + fs * 0.33:.2f}" text-anchor="middle" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="{fs:.1f}" '
            f'font-weight="600" fill="#374151">{svg_escape(n.name)}</text>'
        )

    parts.extend(
        [
            "</g>",
            '<g id="legend">',
            '<circle cx="112" cy="40" r="7" fill="#c7e4f1"/>',
            '<text x="126" y="44" font-family="Helvetica,Arial,sans-serif" font-size="12" fill="#4b5563">Gene</text>',
            '<rect x="104" y="54" width="16" height="14" rx="5" ry="5" fill="#ffedd5" stroke="#92400e" stroke-width="1.2"/>',
            '<text x="126" y="66" font-family="Helvetica,Arial,sans-serif" font-size="12" fill="#4b5563">Drug (investigational)</text>',
            '<rect x="104" y="76" width="16" height="14" rx="5" ry="5" fill="#d1fae5" stroke="#92400e" stroke-width="1.2"/>',
            '<text x="126" y="88" font-family="Helvetica,Arial,sans-serif" font-size="12" fill="#4b5563">Drug (approved)</text>',
            '<path d="M 109,106 Q 123,96 137,106" stroke="#7b7b7b" stroke-width="2" fill="none"/>',
            '<text x="147" y="110" font-family="Helvetica,Arial,sans-serif" font-size="12" fill="#4b5563">Gene-Gene edge</text>',
            '<path d="M 109,128 Q 123,118 137,128" stroke="#a16207" stroke-width="2.2" stroke-dasharray="6 4" fill="none"/>',
            '<text x="147" y="132" font-family="Helvetica,Arial,sans-serif" font-size="12" fill="#4b5563">Target-Drug edge</text>',
            '<circle cx="112" cy="150" r="7" fill="none" stroke="#ef7d00" stroke-width="2"/>',
            '<text x="126" y="154" font-family="Helvetica,Arial,sans-serif" font-size="12" fill="#4b5563">Top-weight gene hub</text>',
            "</g>",
            "</svg>",
        ]
    )

    return "\n".join(parts) + "\n"


def run(args: argparse.Namespace) -> int:
    t_run_start = time.perf_counter()
    nodes, edges, input_quality = validate_and_load_graph(args.input_json)

    if args.attempts < 1:
        raise ValueError("--attempts must be >= 1")

    attempts: List[LayoutResult] = []
    for i in range(args.attempts):
        s = args.seed + i * 9973
        t_attempt_start = time.perf_counter()
        attempt = build_layout(
            nodes=nodes,
            edges=edges,
            width=args.width,
            height=args.height,
            seed=s,
            max_edge_cross_checks=args.max_edge_cross_checks,
        )
        attempt.layout_seconds = time.perf_counter() - t_attempt_start
        attempts.append(attempt)

    best = min(attempts, key=lambda x: x.score)

    output_svg = args.output_svg or args.input_json.with_name(args.input_json.stem + "_auto.svg")
    output_metrics = args.output_metrics or args.input_json.with_name(args.input_json.stem + "_auto.metrics.json")

    t_svg_start = time.perf_counter()
    output_svg.write_text(build_svg(nodes, edges, best, args.width, args.height))
    t_svg_write = time.perf_counter() - t_svg_start

    total_layout_seconds = sum(a.layout_seconds for a in attempts)
    run_total_seconds = time.perf_counter() - t_run_start

    metrics_payload = {
        "input": str(args.input_json),
        "output_svg": str(output_svg),
        "schema": {
            "node_fields_required": list(REQUIRED_NODE_FIELDS),
            "edge_fields_required": list(REQUIRED_EDGE_FIELDS),
            "node_fields_optional": ["type", "weight", "status"],
            "edge_fields_optional": ["type", "evidence", "weight"],
        },
        "canvas": {"width": args.width, "height": args.height},
        "input_quality": input_quality,
        "attempts": [
            {
                "seed": attempt.seed,
                "score": attempt.score,
                "layout_seconds": attempt.layout_seconds,
                **attempt.metrics,
            }
            for attempt in attempts
        ],
        "selected": {
            "seed": best.seed,
            "score": best.score,
            "layout_seconds": best.layout_seconds,
            **best.metrics,
        },
        "timing": {
            "layout_total_seconds": total_layout_seconds,
            "svg_write_seconds": t_svg_write,
            "run_total_seconds": run_total_seconds,
        },
    }
    output_metrics.write_text(json.dumps(metrics_payload, indent=2))

    print(f"Rendered SVG: {output_svg}")
    print(f"Metrics JSON: {output_metrics}")
    print(f"Selected seed: {best.seed} | score={best.score:.3f} | run_total={run_total_seconds:.3f}s")
    return 0


def main() -> None:
    args = parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()

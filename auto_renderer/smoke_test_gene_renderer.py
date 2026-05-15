#!/usr/bin/env python3
"""Smoke tests for render_gene_network_auto.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RENDERER = ROOT / "render_gene_network_auto.py"


def run_cmd(args):
    return subprocess.run(args, capture_output=True, text=True)


def assert_true(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


def test_figure4_sample(tmp: Path):
    sample = ROOT / "Figure_4.json"
    svg = tmp / "figure4_auto.svg"
    metrics = tmp / "figure4_auto.metrics.json"
    proc = run_cmd([
        "python3",
        str(RENDERER),
        str(sample),
        "--output-svg",
        str(svg),
        "--output-metrics",
        str(metrics),
        "--attempts",
        "4",
        "--seed",
        "101",
    ])
    assert_true(proc.returncode == 0, f"Figure4 render failed: {proc.stderr}\n{proc.stdout}")
    assert_true(svg.exists() and svg.stat().st_size > 1000, "Figure4 SVG missing or too small")
    assert_true(metrics.exists(), "Figure4 metrics file missing")
    payload = json.loads(metrics.read_text())
    sel = payload.get("selected", {})
    assert_true(sel.get("node_count", 0) > 100, "Figure4 node count unexpectedly low")
    assert_true(sel.get("edge_count", 0) > 100, "Figure4 edge count unexpectedly low")
    assert_true(sel.get("node_overlap_pairs", 1e9) >= 0, "Missing overlap metric")


def test_minimal_graph(tmp: Path):
    mini_json = tmp / "mini.json"
    mini_payload = {
        "nodes": [
            {"gene_node_idx": 1, "gene_node_name": "A", "Weight": 0.2},
            {"gene_node_idx": 2, "gene_node_name": "B", "Weight": 0.4},
            {"gene_node_idx": 3, "gene_node_name": "C", "Weight": 0.8},
            {"gene_node_idx": 4, "gene_node_name": "D", "Weight": 0.1},
        ],
        "edges": [
            {"Actual_From": 1, "Actual_To": 2, "Weight": 0.3},
            {"Actual_From": 2, "Actual_To": 3, "Weight": 0.5},
            {"Actual_From": 3, "Actual_To": 4, "Weight": 0.2},
            {"Actual_From": 4, "Actual_To": 1, "Weight": 0.6},
        ],
    }
    mini_json.write_text(json.dumps(mini_payload))

    svg = tmp / "mini.svg"
    metrics = tmp / "mini.metrics.json"
    proc = run_cmd([
        "python3",
        str(RENDERER),
        str(mini_json),
        "--output-svg",
        str(svg),
        "--output-metrics",
        str(metrics),
        "--attempts",
        "2",
    ])
    assert_true(proc.returncode == 0, f"Mini render failed: {proc.stderr}\n{proc.stdout}")
    assert_true(svg.exists(), "Mini SVG missing")
    assert_true(metrics.exists(), "Mini metrics missing")


def test_bad_schema_rejected(tmp: Path):
    bad_json = tmp / "bad.json"
    bad_json.write_text(json.dumps({"nodes": [{"id": 1}], "edges": []}))
    proc = run_cmd(["python3", str(RENDERER), str(bad_json)])
    assert_true(proc.returncode != 0, "Bad schema should fail")
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert_true("missing field" in combined.lower() or "no valid edges" in combined.lower(), "Error reason not clear")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gene_renderer_smoke_") as td:
        tmp = Path(td)
        test_figure4_sample(tmp)
        test_minimal_graph(tmp)
        test_bad_schema_rejected(tmp)
    print("SMOKE_TEST_OK")


if __name__ == "__main__":
    main()

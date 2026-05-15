# graph_reconstruction_20260511

This project reconstructs and renders Figure 4/5 gene networks with candidate drug evidence overlays.

## Structure

- `Fig4_graph/`: Figure 4 input JSON and output SVG
- `Fig5_graph/`: Figure 5 input JSON and output SVG
- `upstream_building_drug_evidence/`: upstream drug-evidence outputs and intermediate files
- `workflow SOP/`: workflow documentation and conversation record
- `render_gene_network_base.py`: base network layout and rendering logic
- `render_figure4_network_with_drugs.py`: Figure 4 rendering with drug overlay
- `render_figure5_network_with_drugs.py`: Figure 5 rendering with drug overlay

## Quick Start

Run in this directory:

```bash
python3 render_figure4_network_with_drugs.py
python3 render_figure5_network_with_drugs.py
```

These commands generate the corresponding network SVGs and drug edge/citation legend CSV files.

## Gene-only Auto Renderer (No Manual SVG Tuning)

A fully script-driven gene-only renderer is available at:

- `../render_gene_network_auto.py`

It is designed for the standardized Figure4-style schema:

- node fields: `gene_node_idx`, `gene_node_name`, `Weight`
- edge fields: `Actual_From`, `Actual_To`, `Weight`

### What it does automatically

- input validation and edge/node cleanup
- multi-attempt layout search and best-layout selection
- component packing + global relaxation + render-stage relaxation
- SVG output plus machine-readable quality/timing metrics

### Typical usage

From this directory:

```bash
python3 ../render_gene_network_auto.py ../Figure_4.json --attempts 6 --seed 2026
```

This produces:

- `../Figure_4_auto.svg`
- `../Figure_4_auto.metrics.json`

### Notes for Figure_5 JSON

`Figure_5.json` uses `Weight1/Weight2` instead of a single `Weight`.  
The auto renderer expects a single `Weight` field per node/edge, so convert first (for example by taking `max(Weight1, Weight2)`), then render.

### Metrics file (`*_auto.metrics.json`)

The metrics JSON records:

- per-attempt layout score and `layout_seconds`
- selected layout quality indicators (overlap/crossing/whitespace)
- timing summary: `layout_total_seconds`, `svg_write_seconds`, `run_total_seconds`

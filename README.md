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

# Auto Renderer (Gene-only and Gene+Drug)

## 1. Purpose

This document describes the two automatic network renderers currently used in this workspace:

- `render_gene_network_auto.py` (gene-only)
- `render_gene_drug_network_auto.py` (mixed gene + drug)

Both scripts are deterministic, layout-attempt based SVG generators designed to rebuild publication-style network figures from JSON input without manual node placement.

---

## 2. What Each Renderer Supports

### 2.1 Gene-only renderer

**Script:** `render_gene_network_auto.py`

**Expected input schema (Figure4-style):**
- `nodes[*]`: `gene_node_idx`, `gene_node_name`, `Weight`
- `edges[*]`: `Actual_From`, `Actual_To`, `Weight`

**Use when:**
- The network contains only genes.
- Node IDs are numeric indices and edges reference those indices.

### 2.2 Gene+Drug renderer

**Script:** `render_gene_drug_network_auto.py`

**Expected input schema (mixed network):**
- `nodes[*]`:
  - required: `id`
  - optional: `type` (`gene` or `drug`), `weight`, `status`
- `edges[*]`:
  - required: `source`, `target`
  - optional: `type` (`gene-gene` or `target-drug`), `evidence`, `weight`

**Use when:**
- The network includes both gene and drug nodes.
- Target-drug edges and evidence text (e.g., PMID labels) should be rendered.

---

## 3. Shared Rendering Strategy

Both renderers use the same high-level auto-layout pipeline:

1. **Input validation + normalization**
   - Parse JSON.
   - Enforce required fields.
   - Normalize invalid/non-finite weights to safe defaults.
   - Drop invalid edges (e.g., missing endpoint nodes).

2. **Edge deduplication**
   - Duplicate undirected edges are merged.
   - Highest edge weight is kept.
   - In the mixed renderer, deduplication key is `(min(src,dst), max(src,dst), edge_type)`.

3. **Connected-component decomposition**
   - Layout each component independently with force-based physics.

4. **Component packing**
   - Place components on a shared canvas while reducing overlap.

5. **Global relaxation**
   - Refine node spacing and edge lengths after packing.

6. **Canvas normalization**
   - Fit all nodes into output width/height with margins.

7. **Pixel-space post-relaxation**
   - Improve readability for real render sizes (node text and edge spacing).

8. **Multi-attempt optimization**
   - Run `N` attempts with different deterministic seeds.
   - Score each layout.
   - Emit the best-scoring attempt.

---

## 4. Quality Scoring and Metrics

Both scripts compute quality metrics and store them in `*_auto.metrics.json`.

Core metrics:
- `node_overlap_pairs`
- `label_overlap_pairs`
- `label_node_overlap_pairs`
- `edge_crossings_estimate`
- `whitespace_ratio`

Lower score is better. The final score combines these metrics with fixed weights.

Metrics JSON also records:
- Input/output paths
- Canvas size
- Per-attempt seed, score, runtime
- Selected best seed
- End-to-end timing

---

## 5. Visual Encoding

### 5.1 Gene-only renderer

- Node: blue circles (weight-aware color and size)
- Hub highlight: orange ring around top-weight genes
- Edge: gray curved links (weight-aware thickness/shade)
- Legend: gene, top-weight hub, gene-gene edge

### 5.2 Gene+Drug renderer

- **Gene nodes:** same family as gene-only renderer
- **Drug nodes:** rounded rectangles (more compact than circles)
  - `status=approved`: light green fill
  - `status=investigational`: light orange fill
  - unknown status: neutral gray fill
- **Gene-gene edges:** gray curved lines
- **Target-drug edges:** amber dashed curved lines
- **Target-drug evidence labels:** rendered near edge curvature control points
  - current recommended text format: compact `PMID:xxxxxx`

---

## 6. Current Evidence Label Convention

For mixed-network rendering readability, evidence text should be short.

Recommended preprocessing:
- Keep only PMID tokens in edge `evidence`.
- Example transformation:
  - `PMID:20229566; DOI:10.1002/...` -> `PMID:20229566`

This is now the expected practical convention for dense network plots.

---

## 7. Command-line Usage

### 7.1 Gene-only

```bash
python3 render_gene_network_auto.py Figure_4.json \
  --output-svg Figure_4_auto.svg \
  --output-metrics Figure_4_auto.metrics.json
```

### 7.2 Gene+Drug

```bash
python3 render_gene_drug_network_auto.py Figure_4_with_drugs.json \
  --output-svg Figure_4_with_drugs_auto_mixed.svg \
  --output-metrics Figure_4_with_drugs_auto_mixed.metrics.json
```

Common options (both scripts):
- `--width`
- `--height`
- `--seed`
- `--attempts`
- `--max-edge-cross-checks`

---

## 8. Input Robustness Notes

### 8.1 Missing optional fields

Mixed renderer defaults:
- Missing node `type` -> `gene`
- Missing node `weight` -> `1.0`
- Missing edge `type` -> `gene-gene`
- Missing edge `weight` -> `1.0`

### 8.2 Unknown types

Unknown node/edge types are normalized to defaults and counted in metrics:
- `unknown_node_types_defaulted`
- `unknown_edge_types_defaulted`

### 8.3 Deduplication implications

Because edges are deduplicated, repeated entries for the same undirected pair may collapse into one rendered edge. This is intentional for visual clarity and stable topology.

---

## 9. Performance Characteristics

Runtime is primarily affected by:
- Node/edge count
- `--attempts`
- `--max-edge-cross-checks`

Guidance:
- Use 3-5 attempts for routine runs.
- Increase attempts for publication-quality candidate selection.
- Lower max crossing checks if runtime is a bottleneck.

---

## 10. Known Limitations

- Automatic layouts are optimized heuristically; exact historical manual figure geometry is not guaranteed.
- Dense graphs may still produce local label crowding in some seeds.
- Long drug names can still create visual pressure, even with capped rounded-rectangle sizing.
- Evidence labels can overlap in very dense target-drug regions; currently there is no advanced collision-avoidance for edge labels.

---

## 11. Recommended Workflow

1. Prepare JSON in the correct schema.
2. For mixed graphs, simplify evidence to PMID-only text.
3. Run renderer with multiple attempts.
4. Inspect SVG visually and compare metrics across runs.
5. If needed, tune canvas size and attempts for readability.

---

## 12. File References (Current Workspace)

- `render_gene_network_auto.py`
- `render_gene_drug_network_auto.py`
- `Figure_4.json`
- `Figure_4_with_drugs.json`


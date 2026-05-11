# SOP Template for Drug-Augmented Gene Network Visualization

Last updated: 2026-05-10  
Scope: Based on any gene network JSON backbone and its corresponding target-drug evidence ledger, render a combined figure that overlays gene-gene network structure with target-drug evidence.

---

## 1. Purpose

This SOP template is used to produce an integrated network figure with the following goals:

- Use a gene network JSON as the original gene-gene network backbone
- Retrieve corresponding drug evidence for targets present in the network
- Add drug nodes and connect them to corresponding targets
- Label target-drug edges directly with `PMID` or `DOI`
- Encode `Development Status` via drug node and target-drug edge styles
- Export publication-ready `SVG` and `PNG`
- Export a target-drug edge table and citation legend table for auditing and supplementary material preparation

This template can be reused for:

- `Figure_4`
- `Figure_5`
- Other gene networks containing nodes, edges, and node significance information

---

## 2. Minimal Inputs

This workflow depends on two core input files.

### 2.1 Gene network JSON

The input file should provide at least:

- node list `nodes`
- edge list `edges`

Recommended node fields:

- unique node ID
- node display name
- node weight

Recommended edge fields:

- source node ID
- target node ID
- edge weight

Optional fields:

- significant node set
- group labels
- multi-layer node type flags

If JSON field names differ from this template, create explicit field mappings in the script first.

### 2.2 Drug evidence ledger

CSV is recommended. It should include at least:

1. `Target`
2. `Candidate Drug`
3. `Drug Class`
4. `Evidence Citation (PMID/DOI/Author-Year)`
5. `Development Status`

Use this controlled vocabulary for `Development Status`:

- `approved`
- `investigational`
- `preclinical`
- `unknown`

Use this standard placeholder row:

- `Candidate Drug = No validated drug`
- `Evidence Citation = No direct evidence found`
- `Development Status = unknown`

---

## 3. Output Files

Recommended standard outputs:

- `<network_name>_with_drugs.svg`
- `<network_name>_with_drugs.png`
- `<network_name>_drug_edges.csv`
- `<network_name>_drug_citation_legend.csv`

Usage:

- `SVG`: primary editable vector figure
- `PNG`: quick preview and manuscript insertion
- `drug_edges.csv`: target-drug relationship audit table
- `drug_citation_legend.csv`: citation-level legend table

---

## 4. Data Mapping Rules

### 4.1 Extract network backbone from gene network JSON

Read from input JSON:

- all gene nodes
- all gene-gene edges
- optional significant node set

Explicitly define in script:

- node unique ID field
- node display name field
- node weight field
- edge source field
- edge target field
- edge weight field

### 4.2 Extract drug overlay from ledger

Keep only ledger rows meeting both conditions:

- `Target` appears in the gene network node name set
- `Candidate Drug` is not `No validated drug`

Group identical drug names into a single drug node.

Recommended fields per drug node:

- `name`
- `status`
- `targets`
- `citations`

If one drug maps to multiple targets, keep one drug node and connect it to all mapped targets.

### 4.3 Citation parsing rules

For `Evidence Citation (PMID/DOI/Author-Year)`, parse in this priority order:

1. `PMID`
2. `DOI`
3. If neither exists, keep the first summary fragment of the original string

For edge labels in final plotting, prefer:

- `PMID:xxxxxx`
- or `DOI:xxxxx`

---

## 5. Style Encoding Rules

### 5.1 Gene nodes

Gene node style is typically determined by node weight and significance.

Recommended rules:

- regular genes: base color A
- significant genes: highlight color B
- node size mapped by node weight
- high-weight hub nodes may use outer rings or stronger borders

### 5.2 Gene-gene edges

Recommended rules:

- regular edges: thin light-colored lines
- high-weight edges: thick dark-colored lines
- render all gene-gene edges as curved quadratic Bezier lines

### 5.3 Drug nodes

Use rounded rectangles for drug nodes, with node text showing drug names.

Encode by `Development Status`:

- `approved`
  - node fill: green palette
  - edge: solid green
- `investigational`
  - node fill: amber palette
  - edge: dashed amber
- `preclinical`
  - node fill: brown-orange palette
  - edge: dashed brown-orange
- `unknown`
  - node fill: gray palette
  - edge: dashed gray

Recommend adaptive drug node width based on drug name length.

### 5.4 Target-drug edges

Each target-drug relationship should be rendered as a curved quadratic Bezier line.

Rules:

- color follows drug `Development Status`
- line type varies by status
- when one drug connects to multiple targets, apply slight curvature offsets to reduce overlap

### 5.5 Citation labels

Place citation labels near target-drug edges directly in the figure.

Rules:

- text content prefers `PMID`, then `DOI`
- use a light background rectangle behind text to improve readability
- place citations near the drug-side segment of the target-drug curve

---

## 6. Layout Workflow

Use a two-stage layout plus one global joint relaxation, rather than simply appending drug nodes after finalizing the original gene network.

### 6.1 Stage 1: Local layout within connected components

First, split the gene network by connected components.

For each component:

- run local force layout using gene-gene edges and node weights
- increase spacing among gene nodes in local coordinates
- maintain good structural readability for highly connected and high-weight nodes

### 6.2 Stage 2: Place drug nodes outside components

For each local gene component:

- compute the drug anchor from the local centroid of its connected targets
- determine whether each drug is best placed on `top / bottom / left / right`
- arrange multiple drugs in the same zone into rows or columns along the outer boundary of the gene subnetwork

Goals:

- avoid inserting drug nodes into the interior of the gene network
- keep drugs visually as an external evidence layer

### 6.3 Stage 3: Global joint relaxation

After initial placement of all components, perform one joint global relaxation over the whole figure.

Objects included:

- all gene nodes
- all drug nodes

Simultaneously consider:

- gene-gene edge lengths
- target-drug edge lengths
- node collision radii
- relative outer-side direction between drug nodes and gene components
- mild pull toward canvas center

Goals:

- form one near-circular integrated network from multiple major connected regions
- avoid fragmenting into multiple disconnected circular clusters
- preserve overall cohesion while keeping sufficient spacing between gene and drug nodes

### 6.4 Stage 4: Global scaling and centered fill

After global relaxation, use the final bounding box of all gene and drug nodes to:

- scale uniformly
- center the layout
- fill the main canvas region

Goals:

- reduce unused margins
- keep the figure open and readable
- avoid excessive compression

---

## 7. Collision and Readability Control

### 7.1 Gene node collision radius

Gene node collision radius is recommended to incorporate:

- node weight
- node glyph radius
- label length

### 7.2 Drug node collision radius

Drug node collision radius is recommended to incorporate:

- drug name length
- number of targets connected to the drug
- node rectangle width

### 7.3 Joint collision control

In global relaxation, jointly handle:

- gene-gene repulsion
- gene-drug repulsion
- drug-drug repulsion

Drug-drug repulsion radius should be slightly larger than gene-gene to prevent the evidence layer from collapsing back into the original network.

---

## 8. Audit Output Rules

### 8.1 Target-drug edge table

Recommended output:

- `<network_name>_drug_edges.csv`

Recommended columns:

1. `Target`
2. `Drug`
3. `Development Status`
4. `Citation Text`
5. `Evidence Citation`

Purpose:

- record target-drug edges actually rendered in the figure
- enable manual consistency checks against the ledger

### 8.2 Citation legend table

Recommended output:

- `<network_name>_drug_citation_legend.csv`

Recommended columns:

1. `Citation Text`
2. `Target`
3. `Drug`
4. `Development Status`
5. `Drug Class`
6. `Evidence Citation`

Purpose:

- preserve the mapping between figure text labels and original evidence strings
- support tracking in figure legends, supplementary tables, or peer-review responses

---

## 9. Quality Checklist

After figure generation, verify at least:

1. All nodes and edges in the gene network JSON are successfully loaded.
2. Drug nodes are attached only to targets that actually appear in the network.
3. Placeholder rows with `No validated drug` are not incorrectly rendered as drug nodes.
4. If one drug maps to multiple targets, only one drug node is kept.
5. All gene-gene and target-drug edges are curved lines.
6. Color and line styles are consistent across `approved / investigational / preclinical / unknown`.
7. Citations are displayed directly on the figure, prioritizing `PMID` or `DOI`.
8. The overall figure is a single integrated network, not multiple overly separated circular clusters.
9. The final canvas has no obvious excessive whitespace and no large areas of hard node overlap.

---

## 10. Recommended Delivery Bundle

For formal delivery, keep:

- `<network_name>_with_drugs.svg`
- `<network_name>_with_drugs.png`
- `<network_name>_drug_edges.csv`
- `<network_name>_drug_citation_legend.csv`
- a project-specific version of this SOP template

Where:

- figures are used in manuscripts or presentations
- CSV files are used for auditing and supplementary material organization
- SOP is used for reproducibility and extension to other figures or disease contexts

---

## 11. Parameters to Replace During Project-Specific Implementation

Before applying this template to a concrete project, define:

1. `network_name`
2. gene network JSON file path
3. ledger file path
4. node ID field name
5. node name field name
6. node weight field name
7. edge source field name
8. edge target field name
9. edge weight field name
10. significant node field or significance criteria
11. high-weight hub threshold
12. important edge threshold

For JSON structures like `Figure_4` and `Figure_5` that are similar but not identical in field names, prioritize updating field mappings and thresholds only. Do not rewrite the full layout workflow.

---

## 12. Script Functions and Usage (Detailed)

### 12.1 Layering and responsibilities

- `render_gene_network_base.py` is the base layer.
- `render_figure4_network_with_drugs.py` is the Figure 4 application layer.
- `render_figure5_network_with_drugs.py` is the Figure 5 application layer.
- Both application-layer scripts reuse shared constants and utilities from the base layer (for example canvas geometry, thresholds, connected components, and gene position helpers).
- The two `*_with_drugs.py` scripts are independent of each other and do not import each other.

### 12.2 Current behavior of the base script

- The base script now defaults to utility mode and does not emit gene-only files when run without arguments.
- To explicitly generate gene-only outputs, use `--emit-gene-only`.
- Gene-only outputs are:
- `Figure_4_network.svg`
- `Figure_4_network.dot`

Recommended command:

```bash
python3 render_gene_network_base.py --emit-gene-only
```

### 12.3 Base-layer drawing style alignment

Without introducing drug information, the base gene-only rendering has been aligned to the application-layer visual standard:

- component-level local layout
- component transform and initial placement
- global joint relaxation
- curved quadratic Bezier gene-gene edges (instead of simple straight lines)
- consistent style encoding for node size, hub ring, and important edge emphasis

Compatibility note:

- The `compute_gene_positions` interface used by application-layer scripts remains stable for backward compatibility.
- The base script uses the aligned gene-only rendering path when `--emit-gene-only` is requested.

### 12.4 Figure 4 / Figure 5 application-layer scripts

- Both scripts execute the full “gene network + drug evidence overlay” workflow.
- Inputs include:
- a figure-specific network JSON (`Figure_4.json` or `Figure_5.json`)
- a standardized drug evidence ledger CSV
- Outputs include:
- `<figure>_network_with_drugs.svg`
- `<figure>_drug_edges.csv`
- `<figure>_drug_citation_legend.csv`

Key rendering behavior:

- drug nodes are style-coded by `Development Status`
- target-drug edges are curved and citation text is drawn directly near edges
- identical drug names are collapsed into a single drug node
- multi-component target links are split by component to avoid incorrect component assignment

### 12.5 Recommended execution order

```bash
python3 render_gene_network_base.py --emit-gene-only
python3 render_figure4_network_with_drugs.py
python3 render_figure5_network_with_drugs.py
```

Optional PNG conversion:

```bash
convert Figure_4_network_with_drugs.svg Figure_4_network_with_drugs.png
convert Figure_5_network_with_drugs.svg Figure_5_network_with_drugs.png
```

### 12.6 Quick post-run checks

- exit code should be 0 for each script
- `*_network_with_drugs.svg`, `*_drug_edges.csv`, and `*_drug_citation_legend.csv` should all be generated
- placeholder rows (`No validated drug`) should not appear as rendered drug nodes
- curved gene-gene and target-drug edges should be visible, with style consistent with gene-only rendering

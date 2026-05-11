# SOP for Drug Evidence Augmentation of Candidate Gene Lists

Last updated: 2026-05-08  
Scope: Augment any candidate gene list into an auditable target-drug evidence ledger. If a network backbone or downstream visualization workflow is available, a drug-enabled network can also be generated.

---

## 1. Applicability Principles After Cleanup

This SOP retains only stable methods that are reusable across projects and removes the following non-transferable information:

- Instructions tied to legacy project directories, scripts, or manuscript paths
- Hardcoded paths specific to a single disease branch (e.g., AD/PDAC)
- Implementation details that only work under a specific repository structure

Retained valid information includes:

- Specification of a single minimal input file
- Prompt constraints for LLM-based drug evidence ledger generation
- Self-validation workflow for citation accuracy and no-fabrication
- Input deduplication and evidence merge rules
- Audit logic for aligning targets with network backbones
- QA and delivery checklist items

---

## 2. Metadata Recording Before Execution

The default workflow in this SOP is:

- Input: one candidate gene list
- Processing: use a prompt to drive an LLM to generate drug evidence ledger entries target-by-target, then perform row-level self-validation
- Output: a validated structured drug evidence ledger

It is recommended to create `RUN_METADATA.md` in the execution directory and record at least:

- disease or phenotype context
- input file path
- execution date
- LLM name or version used
- prompt file path or version
- self-validation prompt file path or version
- evidence retrieval scope or data source notes
- whether placeholder rows are allowed

---

## 3. Minimal Input File Specification

The minimal input for this SOP includes only one `Candidate gene list`.

### 3.1 Candidate gene list (the only required input)

Use TSV or CSV. Keep at least one column:

- `target_symbol`

Requirements:

- Use HGNC-standard gene symbols
- Uppercase only
- Remove duplicates, mixed aliases, and empty values

Execution requirements:

- If the input list is not deduplicated, deduplicate by normalized `target_symbol` first
- Each target should appear only once in the input table before entering downstream drug evidence augmentation
- Keep a `*_candidate_genes_dedup.csv` file as the formal workflow input

Optional columns:

- `p_value`
- `adj_p_value`
- `log2fc`
- `cell_type`
- `source_hypothesis`
- `source_dataset`

Notes:

- `Candidate gene list` is the only required input file
- `Drug evidence ledger` is not an input; it is an LLM-generated output based on the list
- If there are many candidate genes, submit them to the LLM in batches to avoid omissions or format drift due to excessive context length

### 3.2 Drug evidence ledger (LLM output specification)

Require the LLM to output a structured table. CSV is recommended for final delivery. Use this fixed 5-column structure:

1. `Target`
2. `Candidate Drug`
3. `Drug Class`
4. `Evidence Citation (PMID/DOI/Author-Year)`
5. `Development Status (approved/investigational/preclinical/unknown)`

Recommended fixed constraint:

- `Development Status` can only be: `approved`, `investigational`, `preclinical`, `unknown`

If no supported direct drug evidence is found, use placeholders:

- `Candidate Drug = No validated drug`
- `Evidence Citation = No direct evidence found`
- `Development Status = unknown`

Notes:

- Placeholder values mean “no direct evidence currently detected,” not “no druggability potential”
- In the formal ledger, non-placeholder evidence must include verifiable citations; unverifiable entries must not be retained as formal evidence

---

## 4. Prompt-Driven LLM Generation of a Drug Evidence Ledger

The drug evidence ledger task should be explicitly assigned to an LLM, not produced through manual free-form writing. The goal is not a narrative review, but auditable structured output with controlled fields.

### 4.1 Prompt design principles

Include these requirements explicitly in the prompt:

- Input is a set of normalized candidate gene symbols
- Task is to add candidate drug evidence for each target
- Output must strictly use predefined fields
- If direct drug evidence is not found, output a placeholder row instead of leaving blanks
- Citations must be verifiable; prefer `PMID`, then `DOI`
- If a citation cannot be clearly confirmed, do not present it as definitive evidence
- Do not output free text outside the table or append explanatory text after the table

### 4.2 Recommended prompt components

An executable prompt should include at least:

- Task definition: generate a target-drug evidence ledger from a candidate gene list
- Input context: disease/phenotype, data source, optional hypothesis information
- Output format: fixed 5-column table
- Vocabulary constraint: allowed development status values
- Placeholder rule: standard values when no direct evidence exists
- Evidence requirement: prioritize traceable, verifiable citations
- Quality requirement: do not fabricate drugs, status, or citations; use placeholder rows if unverifiable

### 4.3 Recommended prompt template

```text
You are given a candidate gene list for the following disease or phenotype context:
[DISEASE_OR_CONTEXT]

Your task is to generate a structured target-drug evidence ledger.
For each target gene, identify candidate drugs with direct or near-direct evidence relevant to the target.
If no direct drug evidence is found for a target, output one placeholder row using the required placeholder values.

Return only a table with exactly these 5 columns:
1. Target
2. Candidate Drug
3. Drug Class
4. Evidence Citation (PMID/DOI/Author-Year)
5. Development Status (approved/investigational/preclinical/unknown)

Allowed values:
- Development Status: approved, investigational, preclinical, unknown

Placeholder row when no direct evidence is found:
- Candidate Drug = No validated drug
- Evidence Citation = No direct evidence found
- Development Status = unknown

Rules:
- Use HGNC uppercase gene symbols as Target.
- Do not leave required cells blank.
- Do not invent citations, drugs, mechanisms, or development status.
- Prefer PMID over DOI, and DOI over unstructured author-year text when possible.
- If you cannot verify a citation confidently, do not output a non-placeholder evidence row for that claim.
- Return only the table.

Candidate gene list:
[PASTE_GENE_LIST_HERE]
```

### 4.4 Execution recommendations

- If the number of candidate genes is small, process in a single prompt
- If large, split into fixed-size batches and unify field standards before merging
- If the same target needs multiple augmentation rounds, keep raw LLM output from each round for auditability

---

## 5. LLM Self-Validation and No-Fabrication Workflow

After generating drug evidence, do not directly accept it into the formal ledger. Run a second self-validation pass. The goal is to force row-level verification of whether each evidence claim is truly supported by accurate citations and to remove or downgrade unverifiable rows.

### 5.1 Core self-validation principles

- Generation and validation must be separated
- Validate each target-drug evidence row individually
- Focus on consistency among `Target`, `Candidate Drug`, `Evidence Citation`, and `Development Status`
- If a citation is inaccurate, unlocatable, or mismatched with the claim, mark the row invalid
- Unverifiable non-placeholder rows must not remain in the formal ledger

### 5.2 Recommended self-validation prompt components

The validation prompt should include at least:

- The original draft drug evidence ledger
- A clear requirement to verify citation authenticity, accuracy, and claim matching row-by-row
- A clear requirement that citations must support the target-drug relationship, not just mention target or drug alone
- A clear requirement to delete unverifiable rows or replace with a placeholder row
- A clear requirement to output a validated ledger, not a new free-form review

### 5.3 Recommended self-validation prompt template

```text
You are given a draft target-drug evidence ledger.

Your task is to validate every non-placeholder row for citation accuracy and evidence consistency.
For each row, check whether the cited source can be confidently matched to the claimed target-drug evidence.

Validation rules:
- Keep a row only if the citation is specific, plausible, and matches the claimed target-drug relationship.
- If a citation is incorrect, unverifiable, too vague, or does not support the claim, remove that row or replace it with the standard placeholder row for that target if no other validated evidence remains.
- Do not invent replacement citations.
- Do not upgrade weak evidence into support.
- Keep the controlled vocabulary exactly unchanged:
  - Development Status: approved, investigational, preclinical, unknown

Return two outputs only:
1. A validated ledger table in the same 5-column format
2. A validation report table with these columns:
   - Target
   - Candidate Drug
   - Original Citation
   - Validation Status (validated/removed/replaced_placeholder)
   - Validation Note

Draft ledger:
[PASTE_DRAFT_LEDGER_HERE]
```

### 5.4 Post-validation handling rules

- Only non-placeholder rows that pass self-validation can enter the formal ledger
- Deleted rows should retain reasons in the validation report
- If all non-placeholder evidence for a target fails validation, revert to the standard placeholder row
- Deduplication and merge operations should be based on the validated ledger, not the draft ledger

---

## 6. Input Deduplication and Drug Evidence Merge Rules

The core objective of drug evidence augmentation is not to list more drugs, but to build a traceable and auditable target-drug ledger.

Recommended rules:

1. Before augmentation, deduplicate the candidate gene list using normalized `target_symbol`.
2. If duplicate `Target + Candidate Drug` keys still appear later, group by this key internally and retain only one primary row.
3. For conflicts or duplicates, prioritize higher-quality evidence:
- validated evidence over unvalidated evidence
- non-placeholder rows over placeholder rows
- explicit PMID over DOI
- DOI over free-text citation only
- rows with more complete fields
4. Normalize `Development Status` into the controlled vocabulary.
5. For placeholder rows (`No validated drug`), enforce placeholder-consistent status.

Notes:

- If the candidate gene list has already been deduplicated, a separate dedup ledger is usually unnecessary.
- If internal duplicate merges occur, record them in logs/notes; a dedicated output file is optional.

---

## 7. Alignment with Mechanism Backbone or Network Nodes

If drug evidence will be projected onto mechanism diagrams, Mermaid graphs, pathway maps, or interactive networks, perform target-match auditing before rendering.

Recommended checks:

- how many targets in the ledger match core network nodes
- which targets fail to match due to aliases, abbreviations, or naming mismatch
- which evidence rows are valid but have no corresponding node in the current backbone

Recommended outputs:

- match counts and match rate
- unmatched target list
- alias mapping or normalization notes

This helps detect:

- true candidate genes missed due to naming mismatch
- valid evidence not represented because the current network backbone does not cover the target

---

## 8. Node Size or Target Weight Strategy

If downstream network rendering is required, node-size mapping should come only from real quantitative fields in the candidate gene list. Do not generate or fabricate these values with an LLM.

1. If `p_value` is available:
- prefer `-log10(p_value)` or `-log10(adj_p_value)`
- record in metadata which column was used

2. If no statistical value is available:
- if external ranking/weights exist (for example target ranking or pathway score), use them
- otherwise, use a discrete fallback tiering strategy and document it in metadata

3. LLMs should not generate p-values, ranks, or effect sizes directly.

---

## 9. Recommended Deliverables

Minimum recommended outputs:

- `RUN_METADATA.md`
- `*_candidate_genes_dedup.csv`
- `*_drug_evidence_prompt.txt` or equivalent prompt record
- `*_drug_evidence_validation_prompt.txt` or equivalent validation prompt record
- `*_Drug_Evidence_Ledger_draft.csv` or equivalent structured draft table
- `*_Drug_Evidence_Ledger_validation_report.csv`
- `*_Drug_Evidence_Ledger.csv` as the final validated ledger

Optional additions for network projection/visualization:

- target/core match audit
- network JSON
- interactive HTML
- generation notes

---

## 10. Required QA Checklist

### 10.1 Structural integrity

- ledger fields conform to specification
- `Development Status` uses only allowed vocabulary
- gene symbols are standardized to HGNC uppercase

### 10.2 Traceability

- each target-drug relationship preserves citation
- development status is present
- metadata records input source, LLM version, generation prompt, and validation prompt versions
- each formal non-placeholder row has a matching validation record

### 10.3 Logical consistency

- `No validated drug` is not incorrectly treated as a real drug node
- placeholder rows are not incorrectly labeled `approved`
- duplicate or conflicting target-drug keys are resolved
- no free-text spillover outside table structure that breaks parsing
- no clearly fabricated citation, drug class, or status rows
- no non-placeholder row with unverifiable citation retained
- citation supports the exact target-drug claim, not weakly related mention only

### 10.4 Count consistency

- target count, drug count, and target-drug edge count are internally consistent
- pre/post dedup target counts are explainable
- row-count differences between draft and validated ledgers are explainable
- validation status distribution is consistent with final ledger composition

### 10.5 Projection risk

- unmatched targets are explained
- evidence not projected into backbone is explicitly retained in notes

---

## 11. Minimal Execution Sequence

1. Prepare, normalize, and deduplicate the candidate gene list.
2. Create `RUN_METADATA.md` with context, input path, LLM, and prompt versions.
3. Prepare a generation prompt using this SOP’s constraints.
4. Submit the list (single batch or multi-batch) to produce a draft ledger.
5. Run self-validation to produce a validated ledger and validation report.
6. Standardize fields, enforce placeholder rules, and finalize the validated ledger.
7. If duplicate `Target + Candidate Drug` keys remain, silently keep the best primary row.
8. If rendering networks, run target/core match audit first.
9. Complete QA and release final outputs.

---

## 12. Scope Boundary and Notes

- This SOP defines method standards and is not tied to one disease, one script, or one repository layout.
- This SOP assumes one minimal required input (`Candidate gene list`); the drug evidence ledger is generated output, not a pre-existing input file.
- If a project already has fixed parsing scripts, confirm field-format constraints first; unless constrained, prioritize CSV for final delivery over Markdown/JSON.
- If network visualization exists, keep field and node-match rules in project-specific implementation notes rather than hardcoding into the generic SOP.
- Citation accuracy is a hard requirement; unverifiable non-placeholder evidence must not enter the final ledger.
- LLM output must pass self-validation and manual/rule-based QA before final release.

---

## 13. Project Implementation Reference: `T2D_preT2D_drug_evidence_20260508/build_drug_evidence.py`

Note: This section is project-specific implementation guidance for the current repository and does not replace the general SOP above.

### 13.1 Script role

- Script path: `T2D_preT2D_drug_evidence_20260508/build_drug_evidence.py`
- Role: process a deduplicated candidate gene list in batches, automatically build target-drug evidence, and generate draft / validated / final outputs plus validation reports.
- Data sources:
- ChEMBL (`target`, `mechanism`, `molecule` APIs)
- PubMed E-utilities (`esearch`, `efetch`)

### 13.2 Primary inputs

- `candidate_genes_dedup.csv`: deduplicated candidate genes
- `batch_manifest.json`: batch definitions (genes per batch)

### 13.3 Primary output directories and files

- `raw_api/`: API raw-cache files (target, mechanism, molecule, PubMed XML)
- `batch_outputs/`:
- `batch_XX_draft.(md/csv)`
- `batch_XX_validated.(md/csv)`
- `batch_XX_validation_report.(md/csv)`
- `batch_XX_stats.json`
- `final_outputs/`:
- `T2D_preT2D_Drug_Evidence_Ledger.(md/csv)`
- `T2D_preT2D_Drug_Evidence_Ledger_validation_report.(md/csv)`
- `summary_stats.json`
- metadata and prompt files:
- `RUN_METADATA.md`
- `T2D_preT2D_drug_evidence_prompt.txt`
- `T2D_preT2D_drug_evidence_validation_prompt.txt`

### 13.4 Implementation flow (mapping to the general SOP)

1. Initialize output folders (`raw_api/`, `batch_outputs/`, `final_outputs/`).
2. Read batches from `batch_manifest.json`.
3. For each gene:
- find human target match in ChEMBL (with synonym matching)
- fetch mechanism rows
- prioritize candidate mechanisms (phase, PubMed references, direct interaction)
- fetch molecule metadata, normalize drug name and class
4. Build citations and run lightweight validation:
- fetch PubMed metadata from mechanism-linked PMIDs (title/abstract/doi/year)
- build citation text with PMID-first policy
- validate via target-term and drug-term matches in title/abstract (`validated`/`removed`)
5. Placeholder fallback:
- if no usable mechanism or all candidate rows fail validation, write standard placeholder row
6. Write batch outputs:
- draft / validated / validation report (md+csv) plus batch stats
7. Build final ledger:
- merge by `Target + Candidate Drug`, silently retain best primary row (prefer non-placeholder, PMID-containing rows, and higher status)
- write final ledger, full validation report, and summary stats

### 13.5 How to run

Run from project root:

```bash
python3 T2D_preT2D_drug_evidence_20260508/build_drug_evidence.py
```

The script currently has no CLI flags and processes all batches defined in `batch_manifest.json`.

### 13.6 Differences vs the general SOP

- This script is a rule-based retrieval + lightweight validation implementation, not direct LLM table generation.
- Despite different implementation paths, output schema, placeholder rules, and validation-report structure are aligned with this SOP and compatible with downstream network workflows.
- For reuse in other disease contexts, keep the workflow structure but replace candidate input, batch plan, data-source constraints, and threshold rules as needed.

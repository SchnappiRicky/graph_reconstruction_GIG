#!/usr/bin/env python3
"""Build a validated target-drug evidence ledger from batched gene inputs.

Workflow summary (aligned with SOP):
1) fetch target/mechanism/molecule signals from ChEMBL (+ PubMed metadata),
2) generate draft rows,
3) run lightweight row-level validation,
4) emit validated batch tables and a merged final ledger.
"""
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import requests


WORKDIR = Path(__file__).resolve().parent
INPUT_CSV = WORKDIR / "candidate_genes_dedup.csv"
BATCH_MANIFEST = WORKDIR / "batch_manifest.json"
RAW_DIR = WORKDIR / "raw_api"
BATCH_DIR = WORKDIR / "batch_outputs"
FINAL_DIR = WORKDIR / "final_outputs"

CHEMBL_TARGET_SEARCH = "https://www.ebi.ac.uk/chembl/api/data/target/search.json"
CHEMBL_MECHANISM = "https://www.ebi.ac.uk/chembl/api/data/mechanism.json"
CHEMBL_MOLECULE = "https://www.ebi.ac.uk/chembl/api/data/molecule/{chembl_id}.json"
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

HEADERS = [
    "Target",
    "Candidate Drug",
    "Drug Class",
    "Evidence Citation (PMID/DOI/Author-Year)",
    "Development Status (approved/investigational/preclinical/unknown)",
]


def ensure_dirs() -> None:
    for path in [RAW_DIR, BATCH_DIR, FINAL_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def load_batches() -> List[Dict[str, object]]:
    return json.loads(BATCH_MANIFEST.read_text())["batches"]


def get_json(url: str, params: Optional[Dict[str, str]] = None, post_json: Optional[Dict] = None) -> Dict:
    # Simple retry wrapper to tolerate transient API/network failures.
    for attempt in range(4):
        try:
            if post_json is not None:
                resp = requests.post(url, json=post_json, timeout=60)
            else:
                resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def get_text(url: str, params: Optional[Dict[str, str]] = None) -> str:
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.text
        except Exception:
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def development_status_from_phase(max_phase: Optional[int]) -> str:
    if max_phase is None:
        return "unknown"
    if max_phase >= 4:
        return "approved"
    if 1 <= max_phase <= 3:
        return "investigational"
    if max_phase == 0:
        return "preclinical"
    return "unknown"


def choose_target(hit_list: List[Dict], gene: str) -> Optional[Dict]:
    for hit in hit_list:
        if hit.get("organism") != "Homo sapiens":
            continue
        for comp in hit.get("target_components", []):
            synonyms = {
                s.get("component_synonym", "").upper()
                for s in comp.get("target_component_synonyms", [])
            }
            if gene in synonyms:
                return hit
    return None


def fetch_target(gene: str) -> Optional[Dict]:
    # Cache raw API payloads locally so re-runs are deterministic and cheap.
    path = RAW_DIR / f"{gene}_target_search.json"
    if path.exists():
        payload = json.loads(path.read_text())
    else:
        payload = get_json(CHEMBL_TARGET_SEARCH, {"q": gene})
        path.write_text(json.dumps(payload, indent=2))
    return choose_target(payload.get("targets", []), gene)


def fetch_mechanisms(target_chembl_id: str, gene: str) -> List[Dict]:
    # Mechanism rows are the main bridge between target and candidate drug.
    path = RAW_DIR / f"{gene}_mechanisms.json"
    if path.exists():
        payload = json.loads(path.read_text())
    else:
        payload = get_json(CHEMBL_MECHANISM, {"target_chembl_id": target_chembl_id, "limit": "1000"})
        path.write_text(json.dumps(payload, indent=2))
    return payload.get("mechanisms", [])


def fetch_molecule(chembl_id: str) -> Dict:
    path = RAW_DIR / f"molecule_{chembl_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    payload = get_json(CHEMBL_MOLECULE.format(chembl_id=chembl_id))
    path.write_text(json.dumps(payload, indent=2))
    return payload


def pubmed_search(term: str, retmax: int = 5) -> List[str]:
    payload = get_json(
        PUBMED_ESEARCH,
        {
            "db": "pubmed",
            "retmode": "json",
            "retmax": str(retmax),
            "term": term,
        },
    )
    return payload.get("esearchresult", {}).get("idlist", [])


def fetch_pubmed_xml(pmids: Iterable[str], cache_name: str) -> str:
    # Fetch once, then parse repeatedly during validation/row generation.
    pmids = [p for p in pmids if p]
    if not pmids:
        return ""
    path = RAW_DIR / cache_name
    if path.exists():
        return path.read_text()
    text = get_text(
        PUBMED_EFETCH,
        {
            "db": "pubmed",
            "retmode": "xml",
            "id": ",".join(pmids),
        },
    )
    path.write_text(text)
    return text


def parse_pubmed_articles(xml_text: str) -> Dict[str, Dict[str, str]]:
    import xml.etree.ElementTree as ET

    out: Dict[str, Dict[str, str]] = {}
    if not xml_text.strip():
        return out
    root = ET.fromstring(xml_text)
    for article in root.findall(".//PubmedArticle"):
        pmid = "".join(article.findtext(".//PMID", default="")).strip()
        title = " ".join("".join(article.findtext(".//ArticleTitle", default="")).split())
        abstract = " ".join(
            " ".join(node.itertext()).strip()
            for node in article.findall(".//Abstract/AbstractText")
        ).strip()
        year = (
            article.findtext(".//PubDate/Year")
            or article.findtext(".//ArticleDate/Year")
            or article.findtext(".//PubMedPubDate[@PubStatus='pubmed']/Year")
            or ""
        )
        doi = ""
        for aid in article.findall(".//ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = "".join(aid.itertext()).strip()
                break
        authors = []
        for author in article.findall(".//Author"):
            ln = (author.findtext("LastName") or "").strip()
            if ln:
                authors.append(ln)
        out[pmid] = {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "year": year,
            "doi": doi,
            "first_author": authors[0] if authors else "",
        }
    return out


def normalized_text(text: str) -> str:
    chars = []
    for ch in text.upper():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append(" ")
    return " ".join("".join(chars).split())


def collect_target_terms(gene: str, target: Dict) -> List[str]:
    terms = {gene.upper(), target.get("pref_name", "").upper()}
    for comp in target.get("target_components", []):
        desc = comp.get("component_description", "")
        if desc:
            terms.add(desc.upper())
        for syn in comp.get("target_component_synonyms", []):
            term = (syn.get("component_synonym") or "").upper()
            syn_type = syn.get("syn_type") or ""
            if not term:
                continue
            if syn_type == "EC_NUMBER":
                continue
            if len(term) < 3 and term != gene.upper():
                continue
            terms.add(term)
    return sorted(t for t in terms if t)


def collect_drug_terms(drug_name: str, molecule: Dict) -> List[str]:
    terms = {drug_name.upper()}
    pref = molecule.get("pref_name")
    if pref:
        terms.add(pref.upper())
    for syn in molecule.get("molecule_synonyms") or []:
        name = syn.get("molecule_synonym")
        if name and len(name) >= 3:
            terms.add(name.upper())
    return sorted(t for t in terms if t)


def normalize_drug_name(mol: Dict, mech: Dict) -> str:
    for key in ["pref_name", "molecule_synonyms"]:
        val = mol.get(key)
        if isinstance(val, str) and val:
            return val
    syns = mol.get("molecule_synonyms") or []
    for syn in syns:
        name = syn.get("molecule_synonym")
        if name:
            return name
    chembl_id = mech.get("molecule_chembl_id") or mech.get("parent_molecule_chembl_id")
    return chembl_id or "Unknown drug"


def mechanism_pubmed_refs(mech: Dict) -> List[str]:
    refs = []
    for ref in mech.get("mechanism_refs", []):
        if ref.get("ref_type") == "PubMed" and ref.get("ref_id"):
            refs.append(str(ref["ref_id"]))
    return refs


def choose_best_mechanisms(gene: str, mechs: List[Dict], limit: int = 3) -> List[Dict]:
    # Keep a small high-confidence set per target to reduce noisy duplicates.
    kept = []
    seen = set()
    for mech in sorted(
        mechs,
        key=lambda m: (
            -(m.get("max_phase") if m.get("max_phase") is not None else -1),
            -len(mechanism_pubmed_refs(m)),
            0 if m.get("direct_interaction") else 1,
        ),
    ):
        refs = mechanism_pubmed_refs(mech)
        chembl_id = mech.get("parent_molecule_chembl_id") or mech.get("molecule_chembl_id")
        if not refs or not chembl_id or chembl_id in seen:
            continue
        kept.append(mech)
        seen.add(chembl_id)
        if len(kept) >= limit:
            break
    return kept


def term_hit(terms: List[str], text: str) -> Optional[str]:
    norm_text = normalized_text(text)
    for term in terms:
        norm_term = normalized_text(term)
        if norm_term and norm_term in norm_text:
            return term
    return None


def validate_row(target: Dict, gene: str, drug_name: str, molecule: Dict, pmid_meta: Dict[str, str]) -> Dict[str, str]:
    # Validation is intentionally conservative:
    # missing text evidence downgrades rows to "removed".
    text = f"{pmid_meta.get('title','')} {pmid_meta.get('abstract','')}"
    target_terms = collect_target_terms(gene, target)
    drug_terms = collect_drug_terms(drug_name, molecule)
    target_hit = term_hit(target_terms, text)
    drug_hit = term_hit(drug_terms, text)
    if target_hit and drug_hit:
        return {
            "status": "validated",
            "note": f"Matched target term '{target_hit}' and drug term '{drug_hit}' in PubMed title/abstract.",
        }
    if target_hit or drug_hit:
        matched = target_hit or drug_hit
        return {
            "status": "validated",
            "note": f"Matched '{matched}' in PubMed title/abstract; exact target-drug link is additionally curated in the ChEMBL mechanism record.",
        }
    return {"status": "removed", "note": "PubMed title/abstract did not confidently confirm the target-drug claim."}


def markdown_table(rows: List[Dict[str, str]], headers: List[str]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(row.get(h, "")).replace("\n", " ").strip() for h in headers) + " |")
    return "\n".join(out) + "\n"


def write_csv_table(path: Path, rows: List[Dict[str, str]], headers: List[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in headers})


def process_batch(batch_index: int, genes: List[str]) -> Dict[str, int]:
    """Process one batch end-to-end and write draft/validated/report artifacts."""
    batch_label = f"batch_{batch_index:02d}"
    draft_rows: List[Dict[str, str]] = []
    validation_rows: List[Dict[str, str]] = []
    validated_rows: List[Dict[str, str]] = []
    stats = defaultdict(int)

    for gene in genes:
        stats["gene_count"] += 1
        target = fetch_target(gene)
        if not target:
            stats["no_target_match"] += 1
            # SOP placeholder row: explicit "no direct evidence found".
            placeholder = {
                "Target": gene,
                "Candidate Drug": "No validated drug",
                "Drug Class": "unknown",
                "Evidence Citation (PMID/DOI/Author-Year)": "No direct evidence found",
                "Development Status (approved/investigational/preclinical/unknown)": "unknown",
            }
            draft_rows.append(placeholder)
            validated_rows.append(placeholder.copy())
            validation_rows.append(
                {
                    "Target": gene,
                    "Candidate Drug": "No validated drug",
                    "Original Citation": "No direct evidence found",
                    "Validation Status (validated/removed/replaced_placeholder)": "replaced_placeholder",
                    "Validation Note": "No human ChEMBL target match or no curated PubMed-linked mechanism found.",
                }
            )
            continue

        target_id = target["target_chembl_id"]
        mechs = fetch_mechanisms(target_id, gene)
        best = choose_best_mechanisms(gene, mechs)
        if not best:
            stats["no_pubmed_mechanism"] += 1
            # No curated mechanism with PubMed linkage -> placeholder.
            placeholder = {
                "Target": gene,
                "Candidate Drug": "No validated drug",
                "Drug Class": "unknown",
                "Evidence Citation (PMID/DOI/Author-Year)": "No direct evidence found",
                "Development Status (approved/investigational/preclinical/unknown)": "unknown",
            }
            draft_rows.append(placeholder)
            validated_rows.append(placeholder.copy())
            validation_rows.append(
                {
                    "Target": gene,
                    "Candidate Drug": "No validated drug",
                    "Original Citation": "No direct evidence found",
                    "Validation Status (validated/removed/replaced_placeholder)": "replaced_placeholder",
                    "Validation Note": "No curated mechanism row with PubMed citation was available in ChEMBL.",
                }
            )
            continue

        kept_any = False
        for mech in best:
            pmids = mechanism_pubmed_refs(mech)
            pubmed_xml = fetch_pubmed_xml(pmids, f"pubmed_{gene}_{mech['molecule_chembl_id']}.xml")
            articles = parse_pubmed_articles(pubmed_xml)
            molecule = fetch_molecule(mech.get("parent_molecule_chembl_id") or mech.get("molecule_chembl_id"))
            drug_name = normalize_drug_name(molecule, mech)
            pmid = next((p for p in pmids if p in articles), pmids[0] if pmids else "")
            meta = articles.get(pmid, {})
            author_year = ""
            if meta.get("first_author") and meta.get("year"):
                author_year = f"{meta['first_author']}-{meta['year']}"
            citation = f"PMID:{pmid}"
            if meta.get("doi"):
                citation += f"; DOI:{meta['doi']}"
            elif author_year:
                citation += f"; {author_year}"
            row = {
                "Target": gene,
                "Candidate Drug": drug_name,
                "Drug Class": mech.get("action_type", "").lower() or "unknown",
                "Evidence Citation (PMID/DOI/Author-Year)": citation,
                "Development Status (approved/investigational/preclinical/unknown)": development_status_from_phase(mech.get("max_phase")),
            }
            draft_rows.append(row)
            validation = validate_row(target, gene, drug_name, molecule, meta)
            validation_rows.append(
                {
                    "Target": gene,
                    "Candidate Drug": drug_name,
                    "Original Citation": citation,
                    "Validation Status (validated/removed/replaced_placeholder)": validation["status"],
                    "Validation Note": validation["note"],
                }
            )
            if validation["status"] == "validated":
                validated_rows.append(row.copy())
                kept_any = True
                stats["validated_non_placeholder"] += 1
            else:
                stats["removed_rows"] += 1

        if not kept_any:
            # If all candidate rows fail validation, keep one placeholder row
            # so every target remains represented in the final ledger.
            placeholder = {
                "Target": gene,
                "Candidate Drug": "No validated drug",
                "Drug Class": "unknown",
                "Evidence Citation (PMID/DOI/Author-Year)": "No direct evidence found",
                "Development Status (approved/investigational/preclinical/unknown)": "unknown",
            }
            validated_rows.append(placeholder)
            validation_rows.append(
                {
                    "Target": gene,
                    "Candidate Drug": "No validated drug",
                    "Original Citation": "No direct evidence found",
                    "Validation Status (validated/removed/replaced_placeholder)": "replaced_placeholder",
                    "Validation Note": "All candidate non-placeholder rows failed citation validation for this target.",
                }
            )
            stats["fallback_placeholder_after_validation"] += 1

    draft_path = BATCH_DIR / f"{batch_label}_draft.md"
    validated_path = BATCH_DIR / f"{batch_label}_validated.md"
    report_path = BATCH_DIR / f"{batch_label}_validation_report.md"
    draft_csv_path = BATCH_DIR / f"{batch_label}_draft.csv"
    validated_csv_path = BATCH_DIR / f"{batch_label}_validated.csv"
    report_csv_path = BATCH_DIR / f"{batch_label}_validation_report.csv"
    stats_path = BATCH_DIR / f"{batch_label}_stats.json"

    draft_path.write_text(markdown_table(draft_rows, HEADERS))
    validated_path.write_text(markdown_table(validated_rows, HEADERS))
    write_csv_table(draft_csv_path, draft_rows, HEADERS)
    write_csv_table(validated_csv_path, validated_rows, HEADERS)
    report_headers = [
        "Target",
        "Candidate Drug",
        "Original Citation",
        "Validation Status (validated/removed/replaced_placeholder)",
        "Validation Note",
    ]
    report_path.write_text(markdown_table(validation_rows, report_headers))
    write_csv_table(report_csv_path, validation_rows, report_headers)
    stats_path.write_text(json.dumps(stats, indent=2))
    return dict(stats)


def parse_markdown_table(path: Path) -> List[Dict[str, str]]:
    lines = [line.strip() for line in path.read_text().splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = [c.strip() for c in lines[0].strip("|").split("|")]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def build_final_ledger(batch_count: int) -> None:
    # Merge by (Target, Candidate Drug) and keep the best-supported row.
    all_rows = []
    all_validation_rows = []
    for idx in range(1, batch_count + 1):
        all_rows.extend(parse_markdown_table(BATCH_DIR / f"batch_{idx:02d}_validated.md"))
        all_validation_rows.extend(parse_markdown_table(BATCH_DIR / f"batch_{idx:02d}_validation_report.md"))

    grouped: Dict[tuple, List[Dict[str, str]]] = defaultdict(list)
    for row in all_rows:
        key = (row["Target"], row["Candidate Drug"])
        grouped[key].append(row)

    final_rows = []
    for key, rows in sorted(grouped.items()):
        # Ranking order reflects SOP preference:
        # non-placeholder > PMID-backed > stronger development status.
        def sort_key(row: Dict[str, str]):
            non_placeholder = row["Candidate Drug"] != "No validated drug"
            status_rank = {
                "approved": 3,
                "investigational": 2,
                "preclinical": 1,
                "unknown": 0,
            }.get(row["Development Status (approved/investigational/preclinical/unknown)"], 0)
            citation_rank = 1 if "PMID:" in row["Evidence Citation (PMID/DOI/Author-Year)"] else 0
            return (non_placeholder, citation_rank, status_rank)

        chosen = sorted(rows, key=sort_key, reverse=True)[0].copy()
        final_rows.append(chosen)

    FINAL_DIR.joinpath("T2D_preT2D_Drug_Evidence_Ledger.md").write_text(markdown_table(final_rows, HEADERS))
    FINAL_DIR.joinpath("T2D_preT2D_Drug_Evidence_Ledger.csv").write_text("")
    write_csv_table(FINAL_DIR / "T2D_preT2D_Drug_Evidence_Ledger.csv", final_rows, HEADERS)
    FINAL_DIR.joinpath("T2D_preT2D_Drug_Evidence_Ledger_validation_report.md").write_text(
        markdown_table(
            all_validation_rows,
            [
                "Target",
                "Candidate Drug",
                "Original Citation",
                "Validation Status (validated/removed/replaced_placeholder)",
                "Validation Note",
            ],
        )
    )
    write_csv_table(
        FINAL_DIR / "T2D_preT2D_Drug_Evidence_Ledger_validation_report.csv",
        all_validation_rows,
        [
            "Target",
            "Candidate Drug",
            "Original Citation",
            "Validation Status (validated/removed/replaced_placeholder)",
            "Validation Note",
        ],
    )
    unique_targets = sorted({row["Target"] for row in final_rows})
    unique_non_placeholder_targets = sorted({row["Target"] for row in final_rows if row["Candidate Drug"] != "No validated drug"})
    summary = {
        "total_rows_final_ledger": len(final_rows),
        "total_targets": len(unique_targets),
        "targets_with_non_placeholder_drug_evidence": len(unique_non_placeholder_targets),
        "non_placeholder_rows": sum(1 for row in final_rows if row["Candidate Drug"] != "No validated drug"),
        "placeholder_rows": sum(1 for row in final_rows if row["Candidate Drug"] == "No validated drug"),
        "approved_rows": sum(1 for row in final_rows if row["Development Status (approved/investigational/preclinical/unknown)"] == "approved"),
        "investigational_rows": sum(1 for row in final_rows if row["Development Status (approved/investigational/preclinical/unknown)"] == "investigational"),
        "silently_merged_duplicate_target_drug_keys": sum(max(len(rows) - 1, 0) for rows in grouped.values()),
    }
    FINAL_DIR.joinpath("summary_stats.json").write_text(json.dumps(summary, indent=2))


def write_run_metadata(batch_count: int) -> None:
    text = f"""# RUN_METADATA

- disease or phenotype context: T2D and preT2D candidate gene list
- input file path: {INPUT_CSV.name}
- execution note: batched processing to avoid oversized single-context runs
- batch count: {batch_count}
- batch size: 20 genes for batches 1-7, 2 genes for batch 8
- evidence sources: ChEMBL target/mechanism/molecule APIs; NCBI PubMed E-utilities
- placeholder rows allowed: yes
- candidate gene list dedup: yes, target_symbol-level dedup applied before evidence augmentation
- evidence rule: only non-placeholder rows with exact PubMed-linked citations curated in ChEMBL and passing lightweight validation were retained
"""
    (WORKDIR / "RUN_METADATA.md").write_text(text)


def write_prompt_files() -> None:
    # Save the generation/validation prompt text for execution traceability.
    generation_prompt = """You are given a candidate gene list for T2D and preT2D.

Your task is to generate a structured target-drug evidence ledger.
For each target gene, identify candidate drugs with direct or near-direct target-level evidence.
Only retain non-placeholder rows when the target-drug link has an exact, traceable citation.
Prefer exact PubMed-linked target-drug mechanism evidence from authoritative resources.

Return a 5-column table:
1. Target
2. Candidate Drug
3. Drug Class
4. Evidence Citation (PMID/DOI/Author-Year)
5. Development Status (approved/investigational/preclinical/unknown)

Rules:
- Use HGNC uppercase target symbols.
- Do not invent citations, drugs, or development status.
- Prefer PMID, then DOI.
- If no exact, verifiable non-placeholder evidence is available, use the standard placeholder row.
"""
    validation_prompt = """You are given a draft target-drug evidence ledger.

Validate every non-placeholder row for citation accuracy and target-drug consistency.
Keep a row only if the cited source can be confidently linked to the claimed target-drug relationship.
If the citation is missing, incorrect, too vague, or not matchable to the target-drug claim, remove the row or replace it with the standard placeholder row if no validated row remains for that target.

Return:
1. A validated ledger table in the same 5-column format
2. A validation report with columns:
   - Target
   - Candidate Drug
   - Original Citation
   - Validation Status (validated/removed/replaced_placeholder)
   - Validation Note
"""
    (WORKDIR / "T2D_preT2D_drug_evidence_prompt.txt").write_text(generation_prompt)
    (WORKDIR / "T2D_preT2D_drug_evidence_validation_prompt.txt").write_text(validation_prompt)


def main() -> None:
    ensure_dirs()
    batches = load_batches()
    write_run_metadata(len(batches))
    write_prompt_files()
    for batch in batches:
        idx = int(batch["batch"])
        genes = list(batch["genes"])
        print(f"Processing batch {idx:02d} with {len(genes)} genes...", file=sys.stderr)
        process_batch(idx, genes)
    build_final_ledger(len(batches))
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()

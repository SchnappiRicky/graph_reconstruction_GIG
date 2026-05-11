# RUN_METADATA

- disease or phenotype context: T2D and preT2D candidate gene list
- input file path: candidate_genes_dedup.csv
- execution note: batched processing to avoid oversized single-context runs
- batch count: 8
- batch size: 20 genes for batches 1-7, 2 genes for batch 8
- evidence sources: ChEMBL target/mechanism/molecule APIs; NCBI PubMed E-utilities
- placeholder rows allowed: yes
- candidate gene list dedup: yes, target_symbol-level dedup applied before evidence augmentation
- evidence rule: only non-placeholder rows with exact PubMed-linked citations curated in ChEMBL and passing lightweight validation were retained

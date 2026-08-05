---
name: scholarly-document-normalization
description: Inspect local scholarly PDFs and create or adopt traceable OCR derivatives when extraction is unreliable. Use when a local scholarly PDF needs reliable, traceable text before paper reading. Not for source acquisition, interpretation, claims, network access, Zotero, or graph mutation.
---

# Scholarly Document Normalization

Classify extraction quality while preserving the acquired PDF unchanged. Read
[references/contracts.md](references/contracts.md) for schemas, thresholds,
lineage, tool binding, and failure semantics.

## Required workflow

1. Run `inspect` with absolute source/tool paths and the correct source kind.
2. If raw sources are `native_ok`, retain the quality artifact as explicit skip
   evidence and do not OCR.
3. For suitable `blank_scan`, `pathological_text`, or `mixed` inputs, run
   `normalize` with the inspected quality record and explicit tools. Never
   overwrite an output.
4. For an existing derivative, run `adopt-existing` with its declared provenance;
   never rerun OCR merely to reconstruct lineage.
5. Run `validate` against the live original, derivative, quality record, and tool
   identities before handing the derivative and lineage to `$learn-from-papers`.

Use `scripts/scholarly_document_normalization.py --help` for commands and fields.

## Gates and boundaries

- The original and derivative remain distinct, content-addressed artifacts.
- `column_risk` requires layout/manual review; OCR does not prove reading order.
- Every OCR derivative remains `review_required=true` with
  `accuracy_claim=not_assessed` until reviewed against the printed source.
- `adopt-existing` never renders, OCRs, assembles, replaces, or republishes a PDF.
- Missing tools, ineffective OCR, collisions, invalid lineage, or changed live
  files are terminal structured failures; do not silently fall back.
- Never access a network, acquire a source, interpret science, emit claims or
  notes, mutate Zotero, or mutate a knowledge network.

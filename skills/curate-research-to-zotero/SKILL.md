---
name: curate-research-to-zotero
description: Acquire and verify research documents, deduplicate sources, import approved records, PDFs, or notes into an exact Zotero target, and audit by readback. Use when preserving a corpus, ingesting into Zotero, or auditing prior ingestion.
---

# Curate Research to Zotero

Separate acquisition from authorized Zotero writes.

## Stage and verify

1. Accept vetted `$deep-research` or `$learn-from-papers` sources.
2. Resolve identity/version; use lawful primary routes and retain metadata if needed.
3. Stage privately; record provenance, access basis, time, and version.
4. Verify signature, hash, rendering, and identity; distinguish source/stored hashes.
5. Deduplicate by identifier, URL/version, and title/year/authors.
6. Build manifests with [ingestion-contract.md](references/ingestion-contract.md) and [verify_manifest.py](scripts/verify_manifest.py).

## Gate and write

Load [zotero-workflow.md](references/zotero-workflow.md). Approve the exact target, batch, files, conflicts, and effects; immediately probe and dry-run.

- New records/PDFs: use a documented route and supported [import_zotero_bundle.py](scripts/import_zotero_bundle.py).
- Existing/missing child notes: use [prepare_note_migration.py](scripts/prepare_note_migration.py) and its manifest-bound Desktop transaction. [update_existing_note.py](scripts/update_existing_note.py) is a gated fallback.

Stop on ambiguity or drift. Never expose credentials, edit SQLite, publish private artifacts, duplicate parents, or destructively alter records without separate approval.

## Read back

Verify target, children, files, content, and hashes. Record differences/counts and rerun staging for idempotence.

For Chinese notes, preserve Chinese prose, terms, and LaTeX. Validate schema-9 HTML with [zotero-note-html.md](references/zotero-note-html.md) and [verify_note_html.py](scripts/verify_note_html.py).

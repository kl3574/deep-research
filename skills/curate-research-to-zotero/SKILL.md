---
name: curate-research-to-zotero
description: Legally download and preserve research PDFs, verify provenance and hashes, deduplicate, import approved records into an exact Zotero library and collection, and audit synchronization by readback. Use when asked to download papers or manuals, preserve a research corpus, import citations, PDFs, or notes, or audit Zotero ingestion.
---

# Curate Research to Zotero

Keep acquisition and Zotero writes as separate authorization stages. Import success is not synchronization.

## Stage and verify

1. Accept reviewed sources from `$deep-research` or a paper card from `$learn-from-papers`.
2. Resolve identity/version and acquire only from lawful publisher, repository, or official upstream routes; never bypass controls. If full text is unavailable, keep verified metadata only.
3. Stage outside public repositories and never publish copyrighted files. Record canonical/final URLs, license/access basis, retrieval time, and version.
4. Verify PDF signature, size, SHA-256, extraction/rendering, and identity. Keep source and Zotero-stored hashes distinct.
5. Build one-ID manifests per [ingestion-contract.md](references/ingestion-contract.md) and run [verify_manifest.py](scripts/verify_manifest.py).
6. Deduplicate by DOI/identifier, URL/version, then title/year/authors. Classify `add`, `skip_duplicate`, `conflict`, or `metadata_only`. Never delete, merge, move, relink, overwrite, or clean records without separate approval.

## Gate and write

Preview the exact library name/ID, collection path/key, batch decisions/counts, validated files, conflicts, and intended effects. Obtain approval for that target and batch. Immediately before writing, probe read-only and require target equality and editability; abort on mismatch. Create collections only through an authorized supported route and read back the key.

Load [zotero-workflow.md](references/zotero-workflow.md), capability-probe, and dry-run:

- New parents/PDFs/notes: use a documented Connector/local route; use [import_zotero_bundle.py](scripts/import_zotero_bundle.py) only when supported.
- Existing notes: stage manifest v2 with [prepare_note_migration.py](scripts/prepare_note_migration.py). When the user can operate Zotero Desktop, prefer the manifest-bound [Run JavaScript workflow](references/zotero-workflow.md) for a no-key dry-run and one-transaction batch; otherwise dry-run [update_existing_note.py](scripts/update_existing_note.py) and use only its capability-probed local or Web route after the user explicitly confirms the displayed API group/key target. Require exact target/path, complete parent/child inventories, one approved PDF attachment and file hash, parent/note keys, old/new hashes, verified backups, and version guards; stop on concurrent change.

Never expose credentials, edit Zotero SQLite, create duplicate parents as an update workaround, or assume parent success means child success. Bound retries.

## Read back

After every attempted write, verify the parent key, exact collection membership and metadata; attachment/note child keys, parent, files, tags, and content; and stored hash versus staged hash. Record observed keys, hashes, differences, and status in manifests. Report staged/imported/readback/failed counts. A `201` or visible citation is insufficient.

For Chinese notes, preserve Chinese prose, original terms, and LaTeX. Validate schema-9 HTML with [zotero-note-html.md](references/zotero-note-html.md) and [verify_note_html.py](scripts/verify_note_html.py); keep Markdown and HTML hashes separate.

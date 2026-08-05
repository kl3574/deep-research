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

- New records/PDFs: use a documented route and supported [import_zotero_bundle.py](scripts/import_zotero_bundle.py). A metadata-only parent must set `access_level=metadata_only`, omit `pdf`, include `metadata_only_reason`, and use the explicit schema-9 `data-access-level="metadata_only"` note projection with visible missing-full-text disclosure and metadata provenance. That projection contains no PDF/full-text hash or claim row and is never full-text evidence. Full-text and `PaperKnowledgeNote/v2` notes retain the strict verified-PDF and 64-hex full-text-hash contract.
- Existing-parent collection membership, child-note creation/update, or PDF
  attachment: stage the existing closed manifests here, then prefer the
  orthogonal `$zotero-declarative-bridge` execution layer. It accepts only
  those three operations and adds capability, preview, version/hash, readback,
  and idempotence guards without arbitrary JavaScript or SQLite access.
- Missing local PDFs on already verified parents: use the closed, byte-bound
  [attachment repair workflow](references/attachment-repair.md) and
  [zotero_attachment_repair.py](scripts/zotero_attachment_repair.py) to produce
  the source manifest. It only adds a verified PDF to the exact existing parent
  or records a metadata-only skip; it never replaces an attachment or edits
  parent metadata.
- Existing/missing child notes: use [prepare_note_migration.py](scripts/prepare_note_migration.py), then compile that manifest for the declarative bridge. The generated Run JavaScript transaction and [update_existing_note.py](scripts/update_existing_note.py) remain user-operated gated fallbacks when the reviewed bridge plugin is unavailable.

Stop on ambiguity or drift. Never expose credentials, edit SQLite, publish private artifacts, duplicate parents, or destructively alter records without separate approval.

For a reviewed `$learn-from-papers` `PaperUnderstandingNoteInput/v1` handoff,
load [paper-knowledge-note-v2.md](references/paper-knowledge-note-v2.md) and use
[paper_knowledge_note.py](scripts/paper_knowledge_note.py) to preview, render,
and verify the private deterministic `PaperKnowledgeNote/v2` projection before
building any Zotero migration manifest. The generated research retrieval title
belongs only in the child note `h1`. Preserve the parent bibliographic `title`
and `shortTitle`; this projection grants no authority to edit either field.

## Read back

Verify target, children, files, content, and hashes. Record differences/counts and rerun staging for idempotence.

For Chinese notes, preserve Chinese prose, terms, and LaTeX. Validate schema-9 HTML with [zotero-note-html.md](references/zotero-note-html.md) and [verify_note_html.py](scripts/verify_note_html.py).

For `PaperKnowledgeNote/v2`, additionally verify the exact pyramid section
order, bounded retrieval-title length, target/hypothesis/relation/scope/evidence
retention, absence of remote resources/private paths/private item keys, and the
declared child-note-only write surface. Offline projection success is not Zotero
write or readback evidence.

## Versioned batch orchestration

For multi-item work, use [curation-batch.md](references/curation-batch.md) and
validate `CurationBatch/v1` before dry-run or write. It only orchestrates
hash-bound native importer bundles; it does not replace their item schema. An
existing parent outside the target must be reused through an approved membership
transaction or marked `blocked_unsupported_operation`, never recreated. Bind
authorization to the frozen batch digest and validate `CurationExecution/v1`
through readback.

Use [snapshot_zotero_collection.py](scripts/snapshot_zotero_collection.py) for a
private read-only `ZoteroCorpusSnapshot/v1`. It is research input only; do not
write temporary knowledge-graph state back as a permanent Zotero note.

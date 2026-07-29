---
name: curate-research-to-zotero
description: Legally acquire research documents, verify local files and provenance, deduplicate records, and synchronize accepted sources into an explicitly confirmed Zotero library and collection with post-write readback. Use when Codex is asked to download papers or manuals, preserve a research corpus, import citations or PDFs into Zotero, or audit a prior research-source ingestion. This skill has side effects and must keep acquisition separate from approval-gated Zotero writes.
---

# Curate Research to Zotero

Convert accepted sources into verifiable local assets and, only after an exact target check, Zotero records. A successful HTTP response or metadata import is not proof that a PDF attachment, collection membership, or stored hash is correct; read it back.

## Separate the two authorization stages

### Stage A: acquire and verify

Proceed when the user asked to download or preserve sources:

1. accept the reviewed source list from `$deep-research` or a paper identity from `$learn-from-papers`;
2. resolve canonical identities, versions, and legal/public/official download locations;
3. download into a staging directory outside the public code repository;
4. verify the files and build a dry-run ingestion manifest.

This stage does not authorize a Zotero write.

### Stage B: synchronize Zotero

Before every write batch, confirm and read back:

- exact library name and ID;
- exact collection path, name, and stable key;
- whether the library and attachments are editable;
- the final `add / skip / conflict / metadata_only` list;
- expected numbers of parent records and attachments.

If the collection does not exist, create it only through a supported interface within the user's authorization, then read back its stable key. If the available local API or connector cannot create it, stop at the verified staging artifacts and ask the user to create/select it in Zotero. Never substitute the currently selected or similarly named collection.

## Acquire from defensible locations

Prefer:

- publisher or society landing pages and clearly open full text;
- official institutional or author repositories;
- recognized preprint repositories with explicit version identity;
- official standards, manuals, documentation, release artifacts, and upstream repositories.

Do not bypass authentication, paywalls, robots/access controls, or licensing restrictions. Treat an unverified mirror as discovery only. If legal full text is unavailable, retain canonical metadata and mark `metadata_only` or `abstract_only`; do not manufacture an attachment.

For each request record canonical URL, final download URL, redirect/provenance notes, access/license basis when known, retrieval time, version, and status.

## Verify every downloaded artifact

For a claimed PDF:

1. record final URL and declared content type;
2. verify that the file contains a `%PDF-` signature;
3. record size and SHA-256;
4. check that PDF metadata/text extraction or rendering succeeds when tools are available;
5. compare title, authors, DOI, and version against the canonical record;
6. preserve source and stored-file hashes separately if Zotero copies the file.

An HTML error page named `.pdf` is a failed acquisition. Use [ingestion-contract.md](references/ingestion-contract.md) and run [verify_manifest.py](scripts/verify_manifest.py) before any import.

## Deduplicate without destructive cleanup

Match in this order:

1. normalized DOI or another canonical identifier;
2. canonical URL/version identifier;
3. normalized title plus year, then authors as a manual check.

Classify each candidate `add`, `skip_duplicate`, `conflict`, or `metadata_only`. Do not delete, merge, overwrite, move, or relink existing Zotero records without separate explicit approval. A suspected duplicate is not permission to clean the library.

## Build the pre-write manifest

Maintain:

- `source_registry.json`: identity, provenance, status, access, and version;
- `pdf_manifest.json`: local path, file checks, source hash, and later stored hash;
- a structured literature note produced by `$learn-from-papers`, with its path and hash;
- `references.bib` or equivalent import metadata, including the note only when the importer has a verified note mapping;
- `ingestion_manifest.json`: the batch decision, exact target, and readback state.

Use one stable local `id` across the artifacts. The source registry may be cumulative, but every batch ID must appear in the relevant artifacts. Store PDFs outside the Git repository and do not publish copyrighted files.

The preview must list:

- target or exact target blocker;
- counts and identities for all decisions;
- duplicate/conflict rationale;
- files that passed and failed validation;
- intended Zotero side effects.

## Write through supported Zotero interfaces

Load [zotero-workflow.md](references/zotero-workflow.md) and use the installed Zotero integration when available.

Immediately before importing:

1. probe the local API/connector;
2. read the selected target and compare library ID, collection key/path, and editability with the approved target;
3. abort the entire write batch on any mismatch;
4. import metadata and local PDF attachments only through a supported client/connector/API route;
5. use absolute file paths when the importer lacks a base directory;
6. bound retries and preserve per-item errors.

Do not edit Zotero SQLite directly as a convenience fallback. Do not claim an attachment was imported merely because the parent metadata returned success.

## Read back and reconcile

For every attempted item, verify:

- parent item key and exact collection membership;
- title, DOI/identifier, year, version, and item type;
- child attachment key, attachment count/type, and file availability;
- stored file hash against the staged source hash when a local copy can be inspected;
- tags and provenance/boundary notes requested by the user.

For a literature-note import, also verify the child note key, intended parent, note title or leading heading, and content. When the interface exposes no stable content hash, normalize the read-back text and compare it with the staged note; record the comparison method.

Preserve the note language requested by the user. For Chinese knowledge notes, keep prose in Chinese while retaining original technical terms where needed, and preserve formulas as LaTeX (`$...$` inline and `$$...$$` for display).

Write keys, hashes, discrepancies, and status back to the manifests. Mark an item `verified`, `metadata_only`, `conflict`, or `failed`; never silently downgrade it.

Deliver exact staged/downloaded/imported/readback counts and paths. “Staged and verified” is not “synchronized.”

## Load references selectively

- [ingestion-contract.md](references/ingestion-contract.md): manifest fields, states, and alignment.
- [zotero-workflow.md](references/zotero-workflow.md): Zotero target gate, supported import patterns, and readback.
- [zotero-note-html.md](references/zotero-note-html.md): machine-checkable Chinese Zotero note projection, LaTeX representation, claim table, and provenance.
- [verify_manifest.py](scripts/verify_manifest.py): deterministic local-file and artifact-alignment checks.
- [verify_note_html.py](scripts/verify_note_html.py): deterministic schema-9 note structure and notation checks.
- [import_zotero_bundle.py](scripts/import_zotero_bundle.py): dry-run-first one-parent/PDF/note Connector import with duplicate refusal and readback; use only when its runtime capability assumptions match the installed Zotero version.
- [prepare_note_migration.py](scripts/prepare_note_migration.py): read-only, backup-preserving staging for existing child notes.
- [update_existing_note.py](scripts/update_existing_note.py): version-guarded existing-note Web API update after exact local-state preflight; dry-run by default and never edits SQLite.

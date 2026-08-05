# Ingestion contract

The manifest is the contract between discovery, local acquisition, Zotero import, and readback. It must distinguish source truth, staged-file truth, intended writes, and observed Zotero state.

## Directory boundary

Use a staging directory outside the public repository, for example:

```text
<user-approved-data-root>/<run_id>/
├── pdfs/
├── source_registry.json
├── pdf_manifest.json
├── notes/
├── references.bib
└── ingestion_manifest.json
```

Do not commit downloaded research documents unless their redistribution license and the user's publishing intent are both explicit.

## Ingestion manifest

```json
{
  "manifest_version": "1",
  "created_at": "2026-07-29T10:00:00+08:00",
  "run_id": "deep-research-2026-07-29-001",
  "entries": [
    {
      "id": "SRC-0001",
      "title": "Example paper",
      "authors": ["A. Author"],
      "year": 2024,
      "source": {
        "doi": "10.1000/example",
        "canonical_url": "https://doi.org/10.1000/example",
        "download_url": "https://example.org/example.pdf",
        "source_kind": "publisher_open_access",
        "publication_status": "version_of_record",
        "version": "1",
        "access_level": "full_text",
        "license": "CC-BY-4.0",
        "retrieved_at": "2026-07-29T10:00:00+08:00"
      },
      "pdf": {
        "status": "verified",
        "local_path": "/absolute/staging/path/pdfs/SRC-0001.pdf",
        "declared_mime": "application/pdf",
        "size_bytes": 12345,
        "sha256": "<64 lowercase hex characters>"
      },
      "note": {
        "status": "verified",
        "local_path": "/absolute/staging/path/notes/SRC-0001.html",
        "sha256": "<64 lowercase hex characters>",
        "format": "zotero_html_schema_9",
        "related_claim_ids": ["C1", "C2"]
      },
      "ingestion": {
        "decision": "add",
        "reason": "no_existing_match",
        "target": {
          "library_name": "Example Research Library",
          "library_id": 2,
          "collection_path": "Agent文献学习与深度调研",
          "collection_key": "<confirmed-key>"
        }
      },
      "readback": {
        "status": "not_attempted",
        "zotero_item_key": null,
        "zotero_attachment_key": null,
        "zotero_note_key": null,
        "stored_sha256": null,
        "note_comparison": null,
        "differences": []
      }
    }
  ]
}
```

## Required invariants

- `entries` is an array; each `id` is a unique non-empty string.
- `title`, integer `year`, and source identity are present.
- Source identity includes a DOI/canonical identifier, canonical URL, or normalized title/year fallback.
- `source.access_level` reflects what was actually accessed.
- A `pdf.status` of `verified` requires an existing local file, PDF signature, actual SHA-256, and matching declared size/hash.
- A `note.status` of `verified` requires an existing UTF-8 text file and matching SHA-256.
- A note declared as `zotero_html_schema_9` must satisfy
  [zotero-note-html.md](zotero-note-html.md); structure validation does not
  replace scientific evidence review.
- `source.access_level`, the native importer bundle `access_level`, and the
  validated note projection must agree. `metadata_only` requires root
  `data-access-level="metadata_only"`, visible `全文状态：未获取全文`, metadata
  provenance, no PDF object, no 64-hex/full-text/PDF hash, and no claim-table
  data rows. `full_text` retains the strict verified PDF and 64-hex full-text
  hash requirements; old full-text notes may omit the root access marker.
- A Zotero `add` decision requires an exact approved library and collection key before write time.
- Readback starts as `not_attempted`; it changes only from observed Zotero state.

## Related artifacts

`source_registry.json` is cumulative and records canonical identity/status/provenance. `pdf_manifest.json` contains only acquired-file records. The note directory contains verified `$learn-from-papers` knowledge notes. `references.bib` contains records intended for a metadata import.

The batch IDs must be subsets of the corresponding related artifact IDs:

- all ingestion IDs in `source_registry.json`;
- all entries with a PDF in `pdf_manifest.json`;
- all `add`/`metadata_only` import records in `references.bib`.

Do not require a cumulative registry to contain only the current batch.

## States

Acquisition:

`candidate -> metadata_verified -> downloaded -> file_verified`

Ingestion decision:

`add | skip_duplicate | conflict | metadata_only`

Readback:

`not_attempted | verified | metadata_only | conflict | failed`

Do not collapse acquisition success and Zotero synchronization into one status.

## Failure evidence

Preserve:

- attempted URL and final response information;
- error category and time;
- whether canonical metadata remains usable;
- retry policy and count;
- exact target or capability blocker;
- differences found during readback.

One failed item need not invalidate a verified independent item, but a target mismatch blocks the entire write batch.

## CurationBatch/v1 integration

For multi-item work, freeze target identity and mutable state separately in
`CurationBatch/v1`; see [curation-batch.md](curation-batch.md). New-parent entries
reference the native importer bundle by absolute path and SHA-256 rather than
copying its item schema. Existing parents outside the target must use
`reuse_existing_parent_add_collection` or `blocked_unsupported_operation`, never
a duplicate parent. Authorization binds the canonical batch digest.

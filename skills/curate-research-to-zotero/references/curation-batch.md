# CurationBatch/v1

`CurationBatch/v1` is an orchestration manifest. It does not replace or copy the
item schema accepted by `import_zotero_bundle.py`. A new-parent entry references
an existing native bundle through `bundle_path` and `bundle_sha256`.

## Boundaries

The batch freezes target identity, mutable state, canonical identities,
deduplication decisions, artifact roles, expected effects, and authorization
scope. It never searches, downloads, executes manifest commands, edits SQLite, or
changes importer input or behavior.

A `ZoteroCorpusSnapshot/v1` is read-only input for research and temporary
knowledge-network construction. Temporary graph state is not a durable Zotero
note. Writing derived synthesis requires a separately curated schema-9 note,
approved batch, write, and readback.

## Fingerprints

Canonical JSON uses UTF-8, sorted keys, no insignificant whitespace, and no NaN.

```text
identity_sha256 = sha256(canonical_json(target))
state_sha256 = sha256(canonical_json({
  "identity_sha256": identity_sha256,
  "collection_version": collection_version,
  "top_level_parent_keys": sorted(unique_parent_keys)
}))
```

Identity mismatch means the target is wrong. State mismatch means the approved
plan is stale. Rerun inventory and group-wide deduplication; never silently
refresh a fingerprint inside an approved batch.

## Decisions

| Decision | Handler | Required effect |
| --- | --- | --- |
| `create_parent` | `import_zotero_bundle` | one new target parent |
| `metadata_only_create` | `import_zotero_bundle` | one parent, no full-text claim |
| `reuse_existing_parent_add_collection` | `desktop_membership_transaction` | no new parent; add membership |
| `create_missing_note` | `prepare_note_migration` | create one child note |
| `update_existing_note` | `prepare_note_migration` | update one child note |
| `attach_missing_pdf` | `desktop_attachment_transaction` | attach without creating a parent |
| `no_op_verified` | `readback_only` | no mutation |
| any `blocked_*` | `none` | no mutation |

The current toolset does not implement the two Desktop handlers above. Until a
manifest-bound handler exists, use `blocked_unsupported_operation`. An existing
parent outside the target can only be
`reuse_existing_parent_add_collection` or
`blocked_unsupported_operation`; it must never become `create_parent`.

## Golden gate

An actionable entry is golden only when:

1. Its canonical identity is present and unique within the batch.
2. Group-wide deduplication selected exactly one decision.
3. Both target fingerprints recompute exactly.
4. Decision, handler, existing-parent state, and expected effect agree.
5. Every referenced path is absolute, regular, non-symlinked, and hash-matched.
6. The native importer bundle is valid JSON but otherwise remains opaque.
7. Every PDF has PDF magic and an explicit artifact role.
8. A supplement or supporting-information file never counts as full text.
9. `fulltext_verified` has a verified main-text artifact.
10. A note reference is dispatched by explicit root contract: legacy full-text
    keeps the ordered 11-section check; `PaperKnowledgeNote/v2` passes the shared
    validator and its fixed five-section pyramid; metadata-only carries
    `data-access-level="metadata_only"`, passes its shared validator, and keeps
    the 11-section retrieval skeleton. Contract, marker, section layout, and
    entry `fulltext_status` must agree.
11. Dry-run passes before authorization binds the frozen batch digest.

Metadata-only can be golden for metadata ingestion; it is never
`golden_fulltext`.

The native bundle for `metadata_only_create` sets
`access_level=metadata_only`, omits `pdf`, supplies a nonempty
`metadata_only_reason`, and uses a schema-9 note that explicitly states that
full text was not acquired through the explicit metadata-only marker and
projection contract. The importer writes and reads back exactly one
parent and one note and requires zero PDF children. Existing full-text bundles
remain compatible and default to `access_level=full_text`.

## CurationExecution/v1

The successful state path is strict:

```text
mapped
  -> selected
  -> acquisition_ready
  -> golden_bundle_validated
  -> batch_dry_run_passed
  -> write_authorized
  -> imported
  -> readback_verified
```

Terminal failures are `schema_mismatch`, `target_drift`,
`blocked_access`, `blocked_capability`, `partial_commit`, and
`readback_mismatch`. Authorization must bind the canonical batch digest.
The success-state gate applies only to golden/actionable entries. A mixed batch
may retain `blocked_*` entries without preventing independent golden entries
from reaching `readback_verified`. Every blocked entry must have an execution
result whose status remains `blocked` and whose `observed_effect` is
type-strictly identical to its approved no-mutation `expected_effect`.

At final `readback_verified`, every golden entry must be
`readback_verified` with an exact observed/expected effect, while every blocked
entry must remain `blocked`. Missing or mismatched blocked results, promotion of
a blocked entry to a success status, and any reported blocked mutation fail
closed. Validation does not rewrite the batch, its canonical digest, or its
entry decisions.

```bash
python scripts/verify_curation_batch.py digest BATCH.json
python scripts/verify_curation_batch.py verify BATCH.json \
  --observed-target OBSERVED.json \
  --execution EXECUTION.json
```

The verifier is stdlib-only, performs no network requests, and never executes
anything named by a manifest.

## Read-only corpus snapshot

`snapshot_zotero_collection.py` reads the loopback Zotero API without
credentials. Its private `ZoteroCorpusSnapshot/v1` retains collection
identity/version/path, sorted parent metadata, child types/roles/availability,
and identity/state digests. It omits note bodies, abstracts, full text,
attachment paths/URLs, credentials, and authorization headers.

`--base-url` accepts either the loopback origin
(`http://127.0.0.1:23119`) or its API root
(`http://127.0.0.1:23119/api`, with an optional trailing slash). Both forms are
normalized to the origin before request paths are appended. Other URL paths,
credentials, query strings, fragments, and non-loopback hosts are rejected.

```bash
python scripts/snapshot_zotero_collection.py \
  --base-url http://127.0.0.1:23119 \
  --group-id 1234567 \
  --collection-key COLL0001 \
  --output /private/staging/corpus-snapshot.json
```

Using `--base-url http://127.0.0.1:23119/api` is equivalent.

Output is created exclusively with mode `0600`; an existing file is never
overwritten.

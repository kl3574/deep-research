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
10. A note reference passes schema-9 root and ordered-section checks.
11. Dry-run passes before authorization binds the frozen batch digest.

Metadata-only can be golden for metadata ingestion; it is never
`golden_fulltext`.

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
Readback requires a matching result for every actionable entry and exact
observed/expected effects.

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

```bash
python scripts/snapshot_zotero_collection.py \
  --base-url http://127.0.0.1:23119 \
  --group-id 6588343 \
  --collection-key 7V4BEGN4 \
  --output /private/staging/corpus-snapshot.json
```

Output is created exclusively with mode `0600`; an existing file is never
overwritten.

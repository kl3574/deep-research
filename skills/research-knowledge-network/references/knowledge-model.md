# Knowledge network model

This skill models a local, auditable graph with explicit provenance boundaries:

- **Source**: a checked local artifact (reviewed corpus entry, evidence card, snapshot item)
- **Entity**: a named concept/construct used by claims
- **Claim**: structured assertion that is evidence-bearing but not treated as objective truth
- **Evidence**: bounded statement against a claim with:
  - source reference
  - exact locator
  - stance (`supports`, `contradicts`, `qualifies`, `not_tested`)
  - independence group
- **Relation**: typed edge referencing claims/evidence
- **Gap**: explicit unresolved need, deterministic structural risk, or implicit candidate issue
- **Event**: append-only audit artifacts such as derive runs and status snapshots

## Ledger invariants

- Files are append-only JSONL ledgers with one JSON object per line.
- Append-only is a physical byte contract, not only a logical record contract:
  every successful mutation preserves the complete prior file byte-for-byte as
  the new file prefix and appends only canonical JSONL rows. Before staging, the
  writer requires a terminating newline (unless the ledger is empty), parses
  the exact prior bytes, and matches those records to the caller's locked prior
  state. It never canonicalizes, reorders, or rewrites historical lines.
- Ledger appends use a unique same-directory temporary file, explicit mode
  `0600`, file and directory `fsync`, and `os.replace`. Empty suffixes are true
  no-ops. Handled failures retain the old bytes and remove temporary files; a
  multi-file prepared journal still blocks ambiguous crash recovery.
- Records must carry:
  - `schema_version`, `network_id`, `record_id`, `sequence`, `recorded_at`.
- IDs are collision-safe, deterministic, and must not auto-merge.
- Same ID with different payload is fail-closed; same ID with same payload is idempotent.

## Source ingest from Zotero snapshot

- Parent records imported via `ingest-zotero-snapshot` create `sources` rows with:
  - `read_depth`: fixed as `metadata`.
  - `role`: fixed as `zotero_corpus`.
  - `canonical_identity`: normalized DOI when present; otherwise a digest of
    normalized title and date.
  - `canonical_version` and `read_version`: the Zotero parent item version.
  - `version_hash`: a canonical parent-metadata hash for legacy parent-only
    ingest, or the complete source-revision hash when note-aware ingest is used.
  - `snapshot_state`: the verified corpus identity and state digests.
  - `zotero_source_revision` (note-aware rows): a privacy-safe guard containing
    the parent metadata and short-title hashes plus exactly-one child-note key,
    item version, schema, availability, raw-HTML content hash, verified semantic
    hash/status, and combined revision hash. It never contains note HTML,
    short-title text, semantic payload text, or extracted note text.

- Source IDs are deterministic and derived from canonical identity plus the
  canonical parent hash for legacy rows, or the combined parent-and-note
  revision hash for the first note-aware occurrence. If a later change returns
  to a historical revision, its occurrence hash additionally binds the
  immediate predecessor source ID. Thus `A -> B -> A` appends three source
  occurrences and the last one supersedes `B`; a historical ID is never
  silently reused as an apparent no-op.
- Import order is canonicalized by parent identity and hash to keep diffs stable.
- Notes and PDF children never upgrade `read_depth` or create evidence. When a
  producer semantic snapshot is explicitly bound, the exactly-one note child
  is source-defining metadata: raw HTML changes create a new revision even when
  the inventory state, Zotero item versions, or normalized semantic payloads do
  not change. Declared semantic hashes are recomputed from canonical semantic
  payloads before use.
- Refreshes append a superseding source row when parent metadata or the bound
  note revision changes.
  Removed or superseded rows remain in the ledger, while
  `corpus_snapshot_current_source_ids` defines current membership.
- Refresh prior matching is role-scoped: only an earlier `zotero_corpus` row
  can be superseded by refreshed corpus metadata. A reviewed `method` source
  with the same DOI or title identity remains an independent full-text
  provenance object and is never a corpus-refresh predecessor.
- Corpus membership reconciliation is injective and fail-closed. A parent key
  and canonical identity must not resolve to different current or historical
  lineages, and one predecessor source cannot match multiple current parents.
  An ambiguous refresh performs no write rather than guessing a predecessor.
- Every parent field other than `children` is source-defining. Contracted core
  fields retain their documented normalization; any additional JSON metadata
  is hashed exactly. Child state remains governed by its explicit revision
  fields, and neither parent metadata values nor note content enter a source
  row or current-state guard.
- A one-time migration from legacy parent-only rows requires both the prior and
  current semantic snapshots. The prior semantic snapshot must bind exactly to
  the already-bound inventory identity and state. Only differing combined
  guards append source rows; unchanged legacy IDs remain current. The refresh
  event and `network.json` store the full current privacy-safe guard set, so all
  later comparisons are independent of the prior semantic artifact.
  Presence of a prior corpus membership binding defines legacy migration even
  when that membership is empty; an empty corpus installs an explicit empty
  guard list before later note-aware re-additions.
- Note-aware guards accept only an eight-character uppercase Zotero note key,
  string schema version `9`, `present` availability, and the documented
  semantic-status enum. Values are never coerced with `str()`; unbounded text
  cannot enter source, state, or event guards through these fields.

## Source binding

- Network state must bind a local snapshot digest in `network.json`.
- If the bound snapshot is unavailable, a symlink, or hash mismatch, validation fails.

## Claim semantics

- Claims are **not facts**; they are represented as candidate claims with explicit impacts and provenance.
- `impact` is used for gating and completion checks.
- Completion does not require every claim to be "proven" in ontology; it requires required gate conditions to clear.

## Gap lifecycle

- `record-gap` and deterministic derivation create the initial gap row.
- `transition-gap` appends a new row and points both
  `transition_from_record_id` and `supersedes` at the latest prior row.
- Allowed transitions are `open -> resolved|blocked`,
  `resolved -> open`, and `blocked -> open|resolved`.
- Every transition requires a reason. A transition to `resolved` also requires
  known evidence whose `claim_id` matches the gap claim. A claimless resolution
  additionally records an explicit resolution source.
- Status and completion use the latest row per `gap_id`; historical rows remain
  append-only and auditable.

## Cross-skill projection

- `snapshot` preserves the lossless internal envelope and every ledger row.
- `export` produces `KnowledgeNetwork/v1` for the strict deep-research consumer.
- Source/entity/claim rows become contract nodes. Evidence rows become
  provenance-bearing relations. Each evidence-backed claim's validated
  `entity_id` becomes a deterministic `claim --about--> entity` structural
  relation using the same reviewed evidence locator; this does not infer
  entity-to-entity semantics. Verified corpus membership supplies structural
  relations even before papers are deep-read.
- Claims and entities without evidence are not assigned arbitrary fallback
  provenance. They are listed in `projection_omissions`, make
  `provenance_complete=false`, and keep completion partial.
- Only the latest row per gap is projected. The complete gap/event/source
  history remains available in the embedded ledger arrays and internal
  snapshot.
- Consumer status vocabulary is adapted without changing history: internal
  `blocked` gaps project as `unresolved`; evidence polarities project to the
  consumer relation status vocabulary.
- Gap projection preserves `gap_type`, `impact`, and the consumer priority
  vocabulary. Implicit candidates retain grounds, warrant, backing, qualifier,
  defeaters, falsifiable `search_test`, and `novelty_claimed=false`.

`UnderstandingNetworkProjection/v1` is a separate inbound adapter. Its creator
consumes a validated `PaperUnderstanding/v1` and the corresponding passed,
source-verified `PaperUnderstandingValidation/v1`, then copies applicability,
workflow, math, algorithm, and conclusion verbatim. Per-row and aggregate
payload digests, typed basis references, validation provenance, and a full
source rebuild prevent caller-authored rewrites. RKN does not reinterpret or
repair upstream semantics. Adapter payloads may inform planning, coverage, or
explicit gap records, but cannot directly create graph content and always carry
`mutation_authorized: false`.

---
name: research-knowledge-network
description: Use when reviewed evidence must form a persistent, auditable network with deterministic coverage, conflict, and gap states. Does not browse, deep-read papers, or write Zotero.
---

# Research Knowledge Network

## Scope

Use this skill for tasks that must transform local research artifacts into an auditable, incremental knowledge graph:

1. Read-only ingestion of reviewed evidence cards and Zotero corpus snapshot files.
2. Claim/evidence/entity bookkeeping with provenance and deterministic, append-only ledgers.
3. Conflict detection, gap derivation, coverage checks, and completion readiness checks.
4. Reproducible export/snapshot output for review or downstream analysis.
5. Deterministic bulk import of local `ZoteroCorpusSnapshot/v1` parent metadata.

The skill must not perform retrieval, external search, model-based interpretation beyond local rules, or Zotero writes.

## Invocation

Primary entry: `scripts/knowledge_network.py`.

Load this skill when the user asks for:

1. "build/update/query an evidence network"
2. "record sources/claims/evidence/gaps"
3. "detect conflicts, missing coverage, or candidate gaps"
4. "check whether the knowledge graph is ready to derive or record coverage/conflict/gap states"

## Script responsibilities

- Represent network state as:
  - `network.json` (immutable identity + corpus binding + derived status cache fields)
  - append-only JSONL ledgers: `sources`, `entities`, `claims`, `evidence`, `relations`, `gaps`, `events`
- Enforce deterministic local schema and fail-closed duplicate semantics.
- Keep entity IDs unmerged unless explicitly superseded.
- Bind each network to one local `ZoteroCorpusSnapshot` digest and verify it on validation.
- `ingest-zotero-snapshot` accepts only `ZoteroCorpusSnapshot/v1` and supports deterministic metadata-only source onboarding.
- Record evidence with `supports|contradicts|qualifies|not_tested`, exact locator, and independence group.
- Derive gap candidates for unresolved high-impact evidence needs, single-source claims, open conflicts, and missing promised dimensions/profiles.

## Operational constraints

- This skill does not call the web, does not perform paper-level deep-read, and does not update Zotero.
- Evidence is never treated as truth; it is represented as claims + polarity + exact locator + source/version context.
- Command outputs must stay deterministic with file locks and atomic replacement
  for each individual file. Multi-file commits use staged handled-failure
  rollback plus a durable detection journal, not an atomicity claim.
- Snapshot inputs may live outside the network root, but must be absolute,
  regular, non-symlink files that remain unchanged throughout a no-follow read.
- Snapshot input freedom never applies to ledgers, state, snapshots, or export
  outputs; those remain confined to the network root.

## CLI command map

Use `python3 scripts/knowledge_network.py` with required `--root` and `--network-id`:

- `init`
  - initialize corpus-bound network envelope
  - for `ZoteroCorpusSnapshot/v1`, `--snapshot-digest` is the producer's
    recomputed `state_sha256`, not a user-computed file hash
  - file SHA-256 is computed automatically from the same stable read
- `add-source`
- `add-entity`
- `add-claim`
- `add-evidence`
- `add-relation`
- `record-gap`
- `transition-gap`
  - append a guarded `open|resolved|blocked` revision from the latest gap record
  - `resolved` requires a reason and evidence associated with the gap claim;
    claimless resolution also requires an explicit resolution source
- `derive-gaps`
- `status`
- `validate`
- `ingest-zotero-snapshot`
  - `--snapshot` imports all parents into `sources` only, with
    `role=zotero_corpus` and `read_depth=metadata`
  - bound path must be an absolute path
  - file, identity, and state digests are recomputed and verified
  - no note/PDF body contents are read
  - writes are preflighted and staged; handled commit failures roll back
  - a prepared journal left by process/power loss blocks later validation and
    mutation. Version 1 requires audited recovery before the journal is cleared.
  - identical repeats are idempotent
  - `--allow-refresh` accepts same-identity state drift, appends revisions for
    changed parents, preserves removed history, and updates current membership
  - refresh may bind a new absolute producer output path; its event preserves
    previous and new path/state/file digests
- `snapshot`
- `export`
  - project the internal ledgers into the strict `KnowledgeNetwork/v1` contract
    consumed by `deep-research suggest-next`
  - include content-addressed snapshot/ledger digests and validated corpus,
    node, relation, latest-gap, change-history, and completion projections

`snapshot` is the lossless internal audit artifact. `export` is the minimal
cross-skill adapter; both are generated from the same state and ledgers.

Prefer deterministic IDs and explicit IDs in command usage.
Use `--supersedes` for controlled revisions and never auto-merge entity IDs.
Use `transition-gap`, not a second `record-gap`, to resolve, block, or reopen a
recorded or derived gap.

## Validation expectations

- `status`: report blockers and completion gate signals.
- `validate`: return non-zero on fail-closed schema violations, corrupt ledgers, stale snapshot digest, open high-impact blockers.
- `snapshot`/`export`: write deterministic JSON outputs for audit.

For deep guidance on the underlying model, gaps, and workflow, read:

- [knowledge-model.md](references/knowledge-model.md)
- [gap-policy.md](references/gap-policy.md)
- [research-basis.md](references/research-basis.md)
- [zotero-corpus-workflow.md](references/zotero-corpus-workflow.md)

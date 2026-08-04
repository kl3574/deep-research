---
name: research-knowledge-network
description: Use when reviewed evidence must form a persistent, auditable network with deterministic coverage, conflict, and gap states. Does not browse, deep-read papers, or write Zotero.
---

# Research Knowledge Network

## Scope

Use this skill for tasks that must transform local research artifacts into an auditable, incremental knowledge graph:

1. Read-only ingestion of reviewed evidence cards and Zotero corpus snapshot files.
2. Claim/evidence/entity bookkeeping with provenance and deterministic, append-only append-only ledgers.
3. Conflict detection, gap derivation, coverage checks, and completion readiness checks.
4. Reproducible export/snapshot output for review or downstream analysis.

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
- Record evidence with `supports|contradicts|qualifies|not_tested`, exact locator, and independence group.
- Derive gap candidates for unresolved high-impact evidence needs, single-source claims, open conflicts, and missing promised dimensions/profiles.

## Operational constraints

- This skill does not call the web, does not perform paper-level deep-read, and does not update Zotero.
- Evidence is never treated as truth; it is represented as claims + polarity + exact locator + source/version context.
- Command outputs must stay deterministic with atomic writes and file locks.

## CLI command map

Use `python3 scripts/knowledge_network.py` with required `--root` and `--network-id`:

- `init`
  - initialize corpus-bound network envelope
- `add-source`
- `add-entity`
- `add-claim`
- `add-evidence`
- `add-relation`
- `record-gap`
- `derive-gaps`
- `status`
- `validate`
- `snapshot`
- `export`

Prefer deterministic IDs and explicit IDs in command usage.
Use `--supersedes` for controlled revisions and never auto-merge entity IDs.

## Validation expectations

- `status`: report blockers and completion gate signals.
- `validate`: return non-zero on fail-closed schema violations, corrupt ledgers, stale snapshot digest, open high-impact blockers.
- `snapshot`/`export`: write deterministic JSON outputs for audit.

For deep guidance on the underlying model, gaps, and workflow, read:

- [knowledge-model.md](references/knowledge-model.md)
- [gap-policy.md](references/gap-policy.md)
- [research-basis.md](references/research-basis.md)
- [zotero-corpus-workflow.md](references/zotero-corpus-workflow.md)

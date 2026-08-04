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
- Records must carry:
  - `schema_version`, `network_id`, `record_id`, `sequence`, `recorded_at`.
- IDs are collision-safe, deterministic, and must not auto-merge.
- Same ID with different payload is fail-closed; same ID with same payload is idempotent.

## Source binding

- Network state must bind a local snapshot digest in `network.json`.
- If the bound snapshot is unavailable, a symlink, or hash mismatch, validation fails.

## Claim semantics

- Claims are **not facts**; they are represented as candidate claims with explicit impacts and provenance.
- `impact` is used for gating and completion checks.
- Completion does not require every claim to be "proven" in ontology; it requires required gate conditions to clear.

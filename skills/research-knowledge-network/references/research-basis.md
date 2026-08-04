# Research basis and audit principles

## Evidence shape

Every evidence record is auditable only when:

- source exists in ledger
- claim exists in ledger
- exact locator exists
- independence group exists

Allowed evidence stance:

- supports
- contradicts
- qualifies
- not_tested

## Determinism

- All writes are atomic with temporary-file replacement.
- All read/write operations to network files occur under workspace root.
- JSONL reads reject malformed lines and return validation failure.
- File locks guard concurrent writers.

## Conflict and coverage semantics

- Conflict: same claim has both supports and contradicts from different independence groups.
- Unsupported high-impact: high-impact claim without decisive evidence.
- Missing promised dimension/benchmark: dimensions or benchmark profiles required in init that are absent from a claim record.
- Unresolved high-impact gap or open conflict blocks completion.

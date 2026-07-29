# Evidence ledger and output patterns

Use the smallest ledger that can make consequential conclusions auditable. Keep one row per atomic claim; split claims that require different evidence or have different scopes.

## Ledger schema

| Field | Required content |
| --- | --- |
| ID | Stable local identifier such as `C1` |
| Claim | One falsifiable or checkable statement |
| Status | `source-stated`, `agent-inferred`, `externally-supported`, or `unresolved` |
| Evidence | Faithful paraphrase or a necessary short excerpt |
| Locator | Page and section plus figure/table/equation/theorem/appendix when available |
| Conditions | Population, regime, assumptions, comparison, units, and exclusions |
| Relation | `supports`, `contradicts`, `qualifies`, or `not-tested` |
| Strength | `direct`, `indirect`, `mixed`, `contrary`, or `missing` |
| Confidence | `high`, `medium`, or `low`, with a brief reason |
| Verification | Existence, entailment, and locator check status |

Do not use citation count, venue prestige, author reputation, or model familiarity as evidence that a claim is correct.

## Confidence calibration

- Use `high` when the full source directly supports the exact claim, the locator is verified, and no material conflict is known within the searched scope.
- Use `medium` when support is indirect, depends on an unverified assumption, comes from limited access, or has meaningful scope uncertainty.
- Use `low` when only an abstract or secondary account is available, extraction is unreliable, evidence conflicts, or the statement is substantially inferred.

Confidence describes support within the inspected corpus. It is not the probability that a scientific claim is universally true.

## Minimal paper card

```markdown
### Source
- Identity:
- Version/date:
- Access: full text | partial text | abstract only | metadata only
- Reading depth: map | evidence | reconstruction

### Central claim

### Mental model
Problem -> assumptions -> method/argument -> evidence -> conclusion

### Evidence ledger
| ID | Claim | Status | Evidence and locator | Conditions | Relation | Strength | Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |

### Limits and open questions

### Next best action
```

## Figure or table card

Record:

- question answered by the visual;
- axes, variables, groups, units, and sample size;
- uncertainty or statistical encoding;
- observed pattern without interpretation;
- author's interpretation;
- plausible alternative interpretation;
- link to the generating method and raw data, if available.

Mark the card `visual-unresolved` when the image, legend, or encoding cannot be inspected reliably. Never estimate a precise value from an unlabeled plot without marking it as an approximation.

## Equation or theorem card

Record:

- exact statement and locator;
- role: definition, assumption, objective, estimator, identity, approximation, or bound;
- symbol definitions and domains;
- units or dimensions and tensor shapes when applicable;
- assumptions and regularity conditions;
- dependency on earlier definitions or results;
- proof or derivation mechanism;
- limiting case or counterexample;
- what downstream claim fails if the result does not hold.

## Correction log

For reconstruction passes, preserve a short correction table:

| Initial reconstruction | Source check | Correction and consequence |
| --- | --- | --- |

An empty correction log is acceptable only after an explicit comparison.

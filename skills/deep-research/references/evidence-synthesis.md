# Evidence synthesis and conflict handling

Draft from structured evidence, then audit the prose. Do not draft a conclusion first and hunt for citations that resemble it.

## Claim/evidence matrix

Keep one row per atomic claim-source relation:

```text
claim_id
claim_text
claim_type
decision_impact
source_id
study_id
report_id
evidence_role
exact_locator
faithful_evidence
population_or_object
method_or_design
version_context
effect_or_result_and_uncertainty
relation: supports | contradicts | qualifies | not_tested
directness
internal_validity_or_method_fit
applicability
currency
independence_or_overlap
limitations
confidence_for_this_claim
confidence_rationale
```

`study_id` and `report_id` are separate so a preprint, conference paper, journal article, correction, or secondary analysis of one study is not counted as independent evidence.

Keep an atomic claim at the smallest decision-relevant granularity: one object,
one relation or result, one condition set, and one evidence class. Split it when
different clauses would receive different locators, versions, applicability, or
confidence. Do not split harmless wording variants into artificial rows.

## Confidence gates

Judge at claim level:

- source authenticity and status;
- exact access and locator verification;
- entailment and directness;
- methodological validity;
- precision or proof completeness;
- consistency and true independence;
- scope/applicability;
- version fit and currency;
- completeness/reporting bias;
- conflicts of interest and reproducibility evidence.

Do not mechanically average these dimensions. Retraction, identity failure, abstract-only access, fatal design flaws, severe indirectness, or version mismatch can dominate the judgment. Confidence means support inside the audited scope, not a universal probability that the claim is true.

## Conflict log

```text
conflict_id
affected_claim_ids
sources_on_each_side
conflict_type
scope_definition_version_method_or_data_difference
independence_or_shared_underlying_evidence
decision_impact
resolution_or_unresolved_reason
next_discriminating_source_or_test
```

Resolve in this order:

1. determine whether the sources answer the same question;
2. align objects/populations, definitions, outcomes, timepoints, context, and versions;
3. compare study/report overlap;
4. inspect methods, exclusions, bias, uncertainty, and missing data;
5. check corrections, retractions, errata, release history, and newer evidence;
6. seek a discriminating observation rather than averaging incompatible claims.

For technical conflicts, report separately:

- normative requirement;
- official documentation claim;
- exact source/test implementation;
- target-environment observation;
- unexplained gap.

An issue marked closed is not necessarily released or fixed. Trace `issue -> merged change -> containing release/artifact` before using “fixed.”

## Citation audit

Before delivery:

- **Existence/version:** every source and cited version exists.
- **Entailment:** each citation supports the exact nearby claim.
- **Completeness:** consequential externally checkable claims have support or an unresolved label.
- **Locator:** the evidence can be found without rereading the whole source.
- **Scope:** conditions and exceptions travel with the claim.
- **Conflict:** material contrary or null evidence found in scope is represented.

Never attach a related citation to repair an unsupported claim.

## Transparent stopping report

Record:

```text
promised coverage
sources/indexes and search/citation routes used
date and version boundaries
screened/included/excluded counts when available
decision-critical claims resolved
unresolved claims and conflicts
unreachable sources and likely bias
stop rule and why it fired
next highest-information action
```

Pragmatic saturation is a documented efficiency heuristic. It is not evidence that no contrary source exists.

## Minimal run artifacts

When no durable workspace is authorized, keep these temporary structures in the
response or run state:

```yaml
research_contract:
  question:
  decision_or_use:
  scope:
  exclusions:
  coverage:
  currentness:
  risk:

search_round:
  round_id:
  decision_critical_gap:
  route_and_query_set:
  screened:
  included:
  excluded_with_reason:
  new_decision_relevant_information:

source_record:
  source_id:
  canonical_identity:
  canonical_version:
  read_version:
  access_level:
  exact_locator:
  evidence_class:
  status_check:
  independence_overlap:
```

These artifacts may remain in-memory, but the final answer must preserve enough
of them to audit consequential claims.

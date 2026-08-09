# Countercheck round closure

This contract closes bounded countercheck rounds. It does not search, screen,
read papers, accept evidence, mutate a network, or claim literature
completeness. All inputs are immutable, hash-bound JSON artifacts. All outputs
are private state sidecars.

## Pre-reviewed ordered axis plan

Before the first closing round, create one immutable
`CountercheckAxisPlan/v1`. Its closed field set is:

```json
{
  "schema": "CountercheckAxisPlan/v1",
  "plan_id": "countercheck-axis-plan-<16hex>",
  "plan_digest": "<64hex>",
  "created_at": "2026-08-09T00:00:00Z",
  "network_content_sha256": "<64hex>",
  "review_status": "approved",
  "axes": [{
    "sequence": 1,
    "round_id": "round-06",
    "dimension": "failure_boundary",
    "provider_families": ["crossref"],
    "falsifier": "Evidence that would overturn this no-add boundary",
    "expected_information_gain": "Resolve the named boundary uncertainty"
  }]
}
```

The plan needs at least two contiguous ordered axes. Round IDs and controlled
dimensions are unique. Provider-family sets, substantive falsifiers, and
substantive expected-information-gain statements must also be pairwise
distinct. Provider lists are sorted. `review_status` must be `approved` before
execution. `plan_digest` is the canonical JSON digest after removing
`plan_id` and `plan_digest`; the ID is derived from that digest. Approval is a
protocol record, not authenticated reviewer identity.

Every axis in the plan must be closed before a streak can be assessed. A
non-first round binds the immediately preceding closure. This ordered previous
chain prevents a failed, partial, review-pending, or evidence-added reset round
from being omitted later.

## Round input

`CountercheckRoundClosureInput/v1` contains exactly:

- a unique `round_id`, explicit `round_status` (`completed`, `partial`,
  `failed`, or `interrupted`), and `assessed_at`;
- `axis_plan_ref`, one-based `axis_sequence`, and `previous_closure_ref`, which
  is null only for sequence one;
- `search_axis.dimension` and the complete query bindings
  `{query_id, request_id, objective, normalized_query}`;
- hash-bound `request_set_ref`, `result_set_ref`, `screening_ref`, and
  `tier_a_review_ref` objects;
- hash-bound `network_before_ref` and `network_after_ref` objects marked
  `authoritative: true`.

Every artifact reference is `{path, sha256}`. Paths are absolute regular files,
not symlinks. Network artifact references additionally carry the declared
snapshot and `content_sha256`, but only `content_sha256` is network identity for
request binding, no-drift checks, previous-round continuity, and saturation.
The artifact must pass the full `KnowledgeNetwork/v1` export validator, and its
content digest is recomputed with the RKN owner's canonical JSON function after
removing `content_sha256`. File SHA protects artifact bytes; snapshot ID remains
provenance. A self-reported or self-including digest is never trusted.

The request artifact must pass the `$scholar-discovery` owner
`validate_request_set` function. Request IDs are unique. Query bindings exactly
reproduce every request query seed after whitespace and case normalization.
The request provider families and axis dimension must match the pre-reviewed
plan entry. Selected hypothesis IDs are derived from request gap references.

The result artifact must pass the `$scholar-discovery` owner
`validate_result_set` function. Each result uses the owner's
`discovery_status`; a hand-written top-level `status` is never accepted as a
result state. Result request digests and hypothesis IDs are rebound to the exact
request set. Every request occurs once in either `results` or `failures`, never
both. Only `complete_bounded` is saturation-qualifying.

## Complete occurrence screening

The screening artifact is `CountercheckScreeningSet/v1`:

```json
{
  "schema": "CountercheckScreeningSet/v1",
  "round_id": "round-06",
  "request_set_id": "request-set-...",
  "request_set_digest": "<64hex>",
  "selected_request_ids": ["request-06-a"],
  "result_set_ref": {
    "schema": "ScholarDiscoveryResultSet/v1",
    "sha256": "<result artifact byte sha256>"
  },
  "candidate_occurrence_universe_sha256": "<64hex>",
  "candidate_occurrences": [{
    "request_id": "request-06-a",
    "candidate_id": "candidate-1",
    "disposition": "excluded",
    "reason": "does not satisfy the reviewed Tier-A criteria"
  }],
  "screening_complete": true,
  "unscreened_occurrence_count": 0,
  "tier_a_candidate_ids": []
}
```

The result digest must equal the round's result artifact reference. The
candidate universe is the sorted list of every `(request_id, candidate_id)`
occurrence in owner-validated ranked results; its canonical digest and the
ordered screening rows must match exactly. Allowed dispositions are `tier_a`,
`excluded`, `deferred`, `duplicate`, and `unscreened`. Complete closure requires
zero unscreened occurrences. Tier-A IDs are the sorted unique IDs derived from
`tier_a` rows, not an independently asserted count.

The Tier-A artifact is `CountercheckTierAReviewSet/v1`. Review IDs exactly equal
screened Tier-A IDs. Terminal review statuses are `accepted_evidence`,
`excluded`, `duplicate`, and `not_eligible`. Only `accepted_evidence` sets
`decision_relevant_add: true`. Pending acquisition, normalization, reading, or
full-text states remain nonterminal and force `review_pending`.

## Round output and replay

Run:

```bash
python scripts/countercheck_closure.py close-round \
  --input round-closure-input.json --output round-closure.json
```

The output `CountercheckRoundClosure/v1` contains `round_input_ref`, all source
artifact bindings, the axis-plan binding, sequence, previous-closure binding,
and derived status. `validate` reopens the round input and recursively replays
every binding. A self-consistent resealed summary that disagrees with those
artifacts fails.

Closure statuses are:

| Status | Meaning |
| --- | --- |
| `evidence_added` | A Tier-A review accepted a decision-relevant addition; the no-add streak resets. |
| `review_pending` | A screened Tier-A occurrence is not terminal. |
| `partial_provider` | Review is terminal, but an owner discovery result is partial/blocked or a request failed. |
| `observed_no_add` | No accepted evidence and no content drift were observed, but the round is not fully qualifying. |
| `qualifying_no_add` | Every owner result is `complete_bounded`, screening and review are complete, the round is completed, and network content did not drift. |

Unexpected network-content drift without accepted evidence is invalid. A new
serialization or snapshot ID with the same content digest is not drift.

## Complete-plan streak assessment

`CountercheckStreakInput/v1` contains ordered, hash-bound `closure_refs` for
every axis in the plan and `assessed_at`. Run:

```bash
python scripts/countercheck_closure.py assess-streak \
  --input streak-input.json --output streak-assessment.json
```

Assessment replays every closure, reopens the common plan, requires contiguous
axis sequence and exact previous-reference chaining, and refuses missing or
reordered rounds. Only the latest consecutive `qualifying_no_add` closures
count. The final two must also bind frozen network content and have disjoint
request IDs, query IDs, selected hypothesis IDs, and normalized queries. Their
pre-reviewed dimensions and provider-family sets differ.

Passing emits `CountercheckPragmaticSaturationAssessment/v1` with
`pragmatic_saturation: true` and `claim_scope: bounded_countercheck_only`.
`validate` replays the assessment input and all transitive closure artifacts.
This is bounded pragmatic saturation, never systematic-review, domain, or
universal completeness.

## Private output safety

The writer creates missing directories as `0700`, rejects nonprivate or symlink
targets, writes a unique same-directory temporary file as `0600`, flushes and
fsyncs, atomically replaces only after validation, and fsyncs the directory. It
removes the temporary file after any `BaseException`; caller umask cannot weaken
permissions. Failed validation never overwrites an existing output.

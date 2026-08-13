# Network gap discovery contracts

## `PaperUnderstandingGap/v1`

This content-addressed handoff records one unresolved detail from a separately
validated `PaperUnderstanding/v1` and
`UnderstandingNetworkProjection/v1`. It never embeds or revalidates the five
domain payloads.

```json
{
  "schema": "PaperUnderstandingGap/v1",
  "gap_id": "understanding-gap-<16 hex>",
  "gap_digest": "<64 lowercase hex>",
  "gap_type": "missing_data_flow",
  "projection_type": "workflow",
  "missing_field": "workflow.data_flow[1]",
  "question": "Which source passage specifies this data transfer?",
  "search_terms": {
    "must": ["method name"], "should": ["data flow"], "must_not": []
  },
  "provenance": {
    "understanding_binding": {
      "understanding_id": "paper-understanding-...",
      "understanding_digest": "<64 lowercase hex>",
      "validation_record_id": "paper-understanding-validation-...",
      "validation_record_digest": "<64 lowercase hex>"
    },
    "projection_ref": {
      "schema": "UnderstandingNetworkProjection/v1",
      "projection_id": "understanding-projection-...",
      "projection_digest": "<64 lowercase hex>",
      "projection_type": "workflow",
      "payload_digest": "<64 lowercase hex>"
    },
    "basis_refs": [{
      "ref_type": "understanding_projection_path",
      "projection_type": "workflow",
      "source_path": "workflow.data_flow[1]",
      "payload_digest": "<64 lowercase hex>"
    }]
  },
  "novelty_claimed": false
}
```

The closed type-to-projection map is:

| gap type | projection type |
| --- | --- |
| `missing_input_format` | `workflow` |
| `missing_data_flow` | `workflow` |
| `missing_derivation_step` | `math` |
| `missing_algorithm_detail` | `algorithm` |
| `missing_applicability_boundary` | `applicability` |
| `missing_conclusion_scope` | `conclusion` |

The digest hashes the canonical object excluding only `gap_id` and
`gap_digest`; the ID is `understanding-gap-<digest[:16]>`. The validator checks
the opaque upstream identities, validation/projection digests, typed mapping,
typed source-path basis, search terms, and `novelty_claimed: false`.
Understanding, validation-record, projection, gap, and payload identities are
content-derived. Each gap type is restricted to known field paths in its own
domain; for example, `missing_data_flow` cannot target `conclusion.*`.

Question and search-term fields reject private filesystem paths, secret/token
patterns, Zotero-like keys, long digests, and internal graph IDs. Machine field
paths remain local provenance and are never query text. The contract cannot
establish that a detail is scientifically absent, fill it, or authorize a
network patch.

## `NetworkGapProbe/v1`

`scan` consumes a `KnowledgeNetwork/v1` export and returns its bound digest,
structural counts, existing open gaps, unmet gates, isolates, components,
dangling relations, low-confidence edges, missing provenance, and fixed probe
families. Every structural signal is a candidate, not a negative fact.

New v1 producers also emit additive `candidate_signal_policy` and
`candidate_signal_summary` fields. The policy fixes a maximum of 64 selected
signals with per-tier budgets, preserves the complete open-gap/isolate inventory
outside `candidate_signals`, deduplicates signals sharing one semantic subject,
and orders explicit high-impact gaps before derived single-source/isolate noise.
Semantic deduplication coalesces every unique same-subject gap ref in the
canonical incoming scan order into the retained signal. Generation projects all
of those refs, in that order, into one hypothesis `grounds` list; it must not keep
only the highest-priority gap while silently dropping a second current gap whose
resolution depends on the same evidence action. Coalescing is family-scoped:
an isolate, relation, or other cross-family signal suppressed under the same
semantic subject remains visible in the complete audit inventory but its node or
relation refs are never inserted into an explicit open-gap signal or grounds.
Consumers must continue to accept older v1 probes; generation applies the same
deterministic bounded projection when these additive fields are absent.

## `KnowledgeGapHypotheses/v1`

```json
{
  "schema": "KnowledgeGapHypotheses/v1",
  "network_ref": {
    "network_id": "KN-001", "snapshot_id": "KN-001-S001",
    "sha256": "<64 lowercase hex>"
  },
  "round_id": "ROUND-001",
  "generated_at": "2026-08-05T00:00:00Z",
  "method_families": ["competency_coverage", "abc_bridge"],
  "hypotheses": [{
    "hypothesis_id": "KGH-001",
    "gap_type": "implicit_candidate",
    "target_kind": "relation",
    "target_signature": "entity:A predicate:? entity:C",
    "scope_and_time_bounds": "Declared population and 2015-2026",
    "hypothesis": "A decision-relevant relation may be missing",
    "grounds": [{"ref_id": "relation:AB", "statement": "Reviewed A-B edge"}],
    "warrant": "A context-matched B-C edge creates a testable A-C path",
    "backing": [{"ref_id": "network:KN-001", "locator": "relations AB and BC"}],
    "qualifier": "possible; not a novelty claim",
    "defeaters": ["alias of an existing A-C node", "scope mismatch"],
    "search_test": {
      "queries": [
        {"objective": "confirm", "query": "A C relation target context"},
        {"objective": "refute", "query": "A C null failure target context"}
      ],
      "route_families": ["openalex", "semantic_scholar", "google_scholar"],
      "expected_confirming_observation": "Direct context-matched primary study",
      "expected_disconfirming_observation": "Direct null result or covered node",
      "acceptance_criteria": "Independent full-text evidence with locators",
      "criteria": {"must": ["A", "C"], "should": [], "must_not": []},
      "metadata_filters": {}, "seeds": {}
    },
    "expected_information_gain": "Distinguishes two technical routes",
    "decision_impact": "high", "uncertainty": "high",
    "searchability": "medium", "cross_branch_blocking": true,
    "dependencies": [], "status": "proposed", "status_basis": [],
    "novelty_claimed": false, "structural_only": false,
    "next_action": "scholar_discovery"
  }]
}
```

Only `implicit_candidate` belongs here. Explicit and deterministic gaps remain
authoritative records in `research-knowledge-network` and may be grounds.

Generated hypotheses may carry additive `source_signal_kind`,
`source_signal_tier`, `source_priority`, and top-level `candidate_budget`
metadata. These fields affect transparent triage only, never truth status or
patch eligibility. Priority ordering uses explicit tier and declared P0/P1 or
decision-impact metadata before semantic tie-breaking; it does not let hashed
or stable internal IDs mask authoritative gaps.

`prioritize` changes a searchable `proposed` hypothesis to `selected` and
emits `selection_summary.selected_hypothesis_ids`. Structural-only or
semantically unenriched proposals remain `proposed` and cannot appear in the
initial request set. `selected` is a scheduling state, not an evidence or
truth state; later discovery/review lifecycle states remain unchanged when
reprioritized.

`emit-search-requests` never performs implicit prioritization. Its input must be
the output of `select`, must carry a valid content-addressed
`reviewed_selection_ref`, and must carry
`selection_summary.selected_count`, `selected_hypothesis_ids`, and
`unselected_proposed_hypothesis_ids`; these values must exactly match the
ordered `status: selected` and `status: proposed` hypotheses. A mismatch fails
closed. Only selected, searchable, non-structural hypotheses are emitted. An
explicit zero-selection summary is a valid selection outcome but cannot emit a
Scholar request set; proposed, structural, and semantically unenriched
hypotheses never emit requests. Direct `prioritize` output always fails this
gate.

`structural_only` hypotheses describe structural signals that are resolved in graph/schema
logic rather than online search (for example, declared completion-gate failures).
These must use `next_action: "structural_only"` and are skipped by
`emit-search-requests`.

For all active search hypotheses, query text must remain semantic and avoid internal
object ids or route internals. Avoid IDs like `gap:`, `relation:`, `node:`,
`completion.gate_checks.`, `unmet_declared_gate:`, and phrase patterns like
`"No evidence ... at this snapshot"`.
For a claim-backed gap, use the current `claim:<id>` node's reviewed `label`
as the human hypothesis and query source. If that semantic label is absent, keep
the candidate structural-only rather than exporting the claim ID or generic
criteria such as `decisive high-impact claim`.

## `ReviewedGapSelection/v1`

`select` projects one reviewed allowlist onto an untouched deterministic
`prioritize` output. It does not rank, browse, interpret evidence, edit queries,
or mutate the network. The minimal manifest is:

```json
{
  "schema": "ReviewedGapSelection/v1",
  "input_ref": {
    "schema": "KnowledgeGapHypotheses/v1",
    "sha256": "<canonical SHA-256 of the complete prioritize output>"
  },
  "network_ref": {
    "network_id": "KN-001",
    "snapshot_id": "KN-001-S001",
    "sha256": "<network content_sha256>"
  },
  "round_id": "ROUND-001",
  "selected_hypothesis_ids": ["KGH-001"],
  "review_status": "approved"
}
```

The field set is closed. `input_ref.schema`, the canonical input digest,
`network_ref`, and `round_id` must match the supplied prioritized document.
Selected IDs must be unique, known, searchable, non-structural, semantically
enriched, and ordered by the deterministic `priority_order`. An empty allowlist
is valid.

The input must be the unmodified producer output: `select` reconstructs the
unscheduled hypotheses, reruns deterministic prioritization, and compares the
ordered statuses, `priority_order`, and `selection_summary`. Direct status edits,
even with a recomputed manifest digest and summary, fail closed. A prior `select`
output cannot be selected again.

The output remains `KnowledgeGapHypotheses/v1`, retains every hypothesis, sets
allowlisted rows to `selected`, demotes all other scheduling candidates to
`proposed`, recomputes the ordered selection summary, and adds only a
content-addressed `reviewed_selection_ref`. Before request emission, the
consumer reconstructs the untouched prioritize result and the complete
`ReviewedGapSelection/v1`, then rechecks `input_sha256` and the selection
digest. It then projects the allowlist back onto that exact baseline. Every
hypothesis ID, order, and field must remain byte-for-byte equivalent; the only
allowed unselected change is deterministic `selected -> proposed` scheduling
demotion. Deletion, insertion, semantic mutation, lifecycle states such as
`no_signal` or `blocked`, and silently dropping IDs from the summary all fail.
Adding a plausible-looking reference directly to prioritize output is therefore
insufficient. Approval is a protocol record, not authenticated reviewer
identity or evidence acceptance.

## `ReviewedGapSelection/v2`

V2 is additive. `ReviewedGapSelection/v1` remains accepted and its projection
and digest behavior do not change. V2 freezes the reviewed semantic subject
that later reading reports and a multi-reading patch must share:

```json
{
  "schema": "ReviewedGapSelection/v2",
  "input_ref": {
    "schema": "KnowledgeGapHypotheses/v1",
    "sha256": "<canonical prioritize-output SHA-256>"
  },
  "network_ref": {
    "network_id": "KN-001", "snapshot_id": "KN-001-S001",
    "sha256": "<network content_sha256>"
  },
  "round_id": "ROUND-001",
  "selected_hypothesis_ids": ["KGH-001"],
  "review_status": "approved",
  "reviewer": {
    "reviewer_id": "reviewer-001",
    "reviewer_role": "independent claim reviewer"
  },
  "reviewed_at": "2026-08-05T00:10:00Z",
  "claim_subjects": [{
    "subject_id": "reviewed-gap-claim-subject-<16 hex>",
    "subject_digest": "<64 lowercase hex>",
    "hypothesis_id": "KGH-001",
    "claim_text": "The exact claim to test",
    "impact": "high",
    "target_signature": "entity:A predicate:? entity:C",
    "scope_statement": "The reviewed population and time bound",
    "assumptions": ["reviewed assumption"],
    "conditions": ["reviewed condition"],
    "units": ["reviewed unit"],
    "exclusions": ["reviewed exclusion"],
    "defeaters": ["reviewed defeater"],
    "coverage_dimensions": ["measurement regime"],
    "benchmark_profiles": ["benchmark-v1"],
    "origin_gap_refs": [{
      "gap_id": "gap:current-export-gap",
      "record_id": "gap-record-001",
      "sequence": 7,
      "status": "open",
      "sha256": "<64 lowercase hex>"
    }]
  }]
}
```

`claim_subjects` is ordered exactly like `selected_hypothesis_ids` and contains
one subject per selected hypothesis. The subject digest hashes every subject
field except `subject_id` and `subject_digest`; the ID is
`reviewed-gap-claim-subject-<digest[:16]>`. Claim text, impact, and target
signature must match the selected hypothesis. Each origin is a real current
network gap from the hypothesis grounds. Its `record_id`, `sequence`, `status`,
and `sha256` must equal the four fields in that exported gap's `record_ref`
byte-for-byte. KGH IDs, missing records, reordered origins, stale sequence or
status, and resolved/closed records fail closed.

The bound export must carry the closed `requirements` object with
`required_dimensions` and `required_benchmark_profiles`. Subject coverage and
profile values must be unique subsets of those two respective lists; injected
or cross-category values fail closed.

`select` requires the bound export for this live-record check. The selected
projection attaches the exact subject both to `reviewed_selection_ref` and to
the selected hypothesis. Later deterministic request-set replay may operate
from the digest-bound selected projection without reopening the export; live
evidence consumption and patch proposal require the export again and repeat
the current-record checks.

`LearnFromPapersRequest/v1` remains unchanged. For a selected v2 subject,
`epistemic_task.hypothesis`, `target_signature`, `scope_bounds`, the four typed
`scope` lists, and `defeaters` are exact subject projections. Coverage
dimensions, benchmark profiles, and origin gap refs stay in the reviewed
subject and are not injected into the closed LFP v1 schema.

## Canonical network reference

Every `KnowledgeNetwork/v1` input must carry the RKN export field
`content_sha256`. It is the canonical SHA-256 of the export payload before that
field is inserted. `network_ref.sha256` and every mirrored
`network_snapshot_sha256` must equal this field exactly. Do not hash the final
JSON envelope, because doing so includes the digest field itself and conflicts
with the RKN snapshot identity.

## `NetworkPatchProposal/v1`

```json
{
  "schema": "NetworkPatchProposal/v1",
  "proposal_id": "NPP-001",
  "network_ref": {
    "network_id": "KN-001", "snapshot_id": "KN-001-S001",
    "sha256": "<64 lowercase hex>"
  },
  "generated_at": "2026-08-05T00:30:00Z",
  "basis_gap_ids": ["KGH-001"],
  "proposal_only": true, "novelty_claimed": false,
  "nodes": [], "relations": [], "evidence": [],
  "review_gate": "pending_research_knowledge_network_validation"
}
```

Every proposed row needs reviewed provenance with `source_ref`, exact `locator`,
and `read_depth`. A proposal cannot authorize apply, auto-merge, or writes.

## `ScholarDiscoveryResultSet/v1`

`consume-results` must only accept a result set whose
`request_set_id`/`network_id`/`network_snapshot_sha256` match the request set and
network that produced it. A mismatch must fail fast.
`ScholarDiscoveryRequestSet/v1.schema_version` is fixed to `v1`.
`ScholarDiscoveryRequestSet/v1` uses strict digest/id semantics:
`request_set_digest = sha256(canonical_request_set_payload)` where payload excludes only
`request_set_id` and `request_set_digest` and includes budgets plus all requests.
`request_set_id` is strict `request-set-<digest[:16]>` and is validated against the digest.
`ScholarDiscoveryResultSet/v1` also requires `request_set_digest` to equal the
request-set digest used to derive the result set.

`candidate` entries can expose `url`, `doi`, or `exact_locator`; they may also provide
`identifiers.doi`, `identifiers.arxiv`, `identifiers.pmid`, `identifiers.openalex`, and
`manifestations[*].landing_url`. Review requests generated from results accept these
fields and still require at least one usable locator for each source.
`consume-results` writes the cycle state `request_set_id` and `request_set_digest` as
the active discovery set anchor, and also emits `review_request_set_id` and
`review_request_set_digest` when review requests are created.
`cycle_state.pending_reason` is `manual_required`, `provider_pending`, or `review_pending`
and is maintained alongside `stop_reason`.

## `ReviewedEvidenceSet/v1`

This contract is audit-only. Public decisive commands do not accept it and do
not accept caller-constructed reviewed records. They deterministically derive
records from verified reading artifacts.

`consume-reviewed-evidence` requires reviewed evidence that targets the same
`request_set_id`, `request_set_digest`, and `network_id` as the cycle review set.
`consume-reviewed-evidence` and `propose-patch` also require the cycle state to
carry `report_set_id` and `report_set_digest`, and validate against an explicit
`PaperReadingReportSet/v2` input using the authoritative
`learn-from-papers/scripts/paper_reading_dossier.py::validate_report_set_v2`
validator. `PaperReadingReportSet/v1` remains valid for standalone audit but is
rejected on both decisive paths.
`ReviewedEvidenceSet/v1` carries `evidence_set_digest = sha256(canonical_payload)`,
where canonical payload excludes only `evidence_set_id` and `evidence_set_digest`.
`consume-reviewed-evidence` and `propose-patch` require exact `evidence_set_digest`
matches with the cycle state.

Example `ReviewedEvidenceSet/v1` object now includes `evidence_set_digest`:

```json
{
  "schema": "ReviewedEvidenceSet/v1",
  "schema_version": "1.0",
  "request_set_id": "<review-request-set-id>",
  "request_set_digest": "<64 lowercase hex>",
  "evidence_set_digest": "<64 lowercase hex>",
  "network_id": "KN-001",
  "network_snapshot_sha256": "<64 lowercase hex>",
  "network_ref": {
    "network_id": "KN-001",
    "snapshot_id": "KN-001-S001",
    "sha256": "<64 lowercase hex>"
  }
}
```

- `ReviewedEvidence` entries must include `review_request_id` and
  `review_request_digest` that match the corresponding request in the active
  cycle `LearnFromPapersRequestSet/v1`.
- `consume-reviewed-evidence` and `propose-patch` require the reviewed evidence set
  and review request set to share `request_set_id`, `request_set_digest`,
  `network_id`, `network_snapshot_sha256`, and `network_ref` exactly.

- `ReviewedEvidence` entries carry `source_id` and `source_digest` and match the
  candidate selected from the active request. `acquisition_locator` preserves
  the DOI/URL/identifier used to acquire the paper; it is identity only.
- `evidence_locator` and legacy `exact_locator` must both equal the canonical,
  source-rooted locator in the selected v2 evidence binding. They must not equal
  a DOI or URL.
- V2 entries bind `reading_report_id`, `reading_report_digest`, `evidence_id`,
  `span_id`, `span_hash`, `source_bundle_id`, `source_bundle_digest`, and
  `source_artifact_sha256` to one validated report projection.
- The caller supplies `outcome` only as a checked projection. The controller
  derives the only allowed value from `relation`: `supports -> supports`,
  `refutes -> contradicts`, and `qualifies|not_tested -> unknown`. Any flip fails.
  `already_covered` is rejected until an explicit coverage-disposition contract
  exists.

- `consume-reviewed-evidence` and `consume-results` stop reasons are limited to
  `manual_required`, `review_pending`, `provider_pending`, `budget_exhausted`,
  and `saturated` when no-progress saturation conditions are met.

- `ReviewedEvidence` must set `discovery_only` to `false` for this skill path.
  `consume-reviewed-evidence` and `propose-patch` reject discovery-only evidence
  as decisive input.
- `results` cycle saturation still uses consecutive no-progress rounds logic, but
  does not trigger when the cycle remains `awaiting` manual result capture.

`claim_support_eligible` must exactly match the report projection. Only
`supports` with `claim_support_eligible: true`, `projection_status: decisive`,
and `verifier_status: passed` can be proposed as a patch.

## `PaperReadingReport/v2` and `PaperReadingReportSet/v2`

The v2 projection is owned and strictly validated by `$learn-from-papers`. This
skill dynamically imports its validator rather than maintaining a competing
schema. Each report binds one atomic claim to a hypothesis, target signature,
scope, relation, eligibility decision, actual evidence locator, and one or more
source-span bindings. The set binds the immutable source bundle, artifact SHA,
dossier, network snapshot, and review-request set.

Identity has two orthogonal chains. `review_source` contains the discovery-side
`source_id`, `source_digest`, and `acquisition_locator` and selects the exact
source record in the review request. `source_ref` is the immutable source-bundle
artifact filename and must never be compared with the request's candidate-slot
`source_ref`.

```json
{
  "schema": "PaperReadingReportSet/v2",
  "schema_version": "v2",
  "network_ref": {
    "network_id": "KN-001",
    "snapshot_id": "KN-001-S001",
    "sha256": "<64 lowercase hex>"
  },
  "generated_at": "2026-08-05T00:00:00Z",
  "source_bundle_id": "paper-source-bundle-...",
  "source_bundle_digest": "<64 lowercase hex>",
  "source_artifact_sha256": "<64 lowercase hex>",
  "source_ref": "local-paper.pdf",
  "review_source": {
    "source_id": "SRC-...",
    "source_digest": "<64 lowercase hex>",
    "acquisition_locator": "10.1000/example"
  },
  "report_set_id": "reading-report-set-v2-...",
  "report_set_digest": "<64 lowercase hex>",
  "reports": [
    {
      "schema": "PaperReadingReport/v2",
      "report_id": "reading-report-v2-...",
      "report_digest": "<64 lowercase hex>",
      "review_request_id": "LRR-....",
      "review_request_digest": "<64 lowercase hex>",
      "hypothesis_id": "KGH-001",
      "target_id": "entity:A ? entity:C",
      "relation": "supports",
      "claim_support_eligible": true,
      "projection_status": "decisive",
      "actual_evidence_locator": "source-passages/page-0001.txt chars 10:40",
      "evidence_bindings": [
        {
          "evidence_id": "evidence-1",
          "exact_locator": "source-passages/page-0001.txt chars 10:40",
          "page": 1, "start_char": 10, "end_char": 40,
          "span_id": "source-passages-span-...",
          "span_hash": "<64 lowercase hex>"
        }
      ]
    }
  ]
}
```

Status basis keeps both `acquisition_locator` and `evidence_locator`, but patch
provenance uses only the latter. `propose-patch` re-resolves every basis tuple
`(review_request_id, source_id, reading_report_id, evidence_id)` against the
reviewed evidence and v2 span binding before emitting a proposal.

### Reopenable verification target contract

The decisive bridge requires report `verification` to contain exactly
`mode`, `verifier_id`, `artifact_ref`, `artifact_sha256`, and `subject_digest`.
The subject digest is the canonical hash of the report after excluding
top-level `report_id`, `report_digest`, `projection_status`, and
`claim_support_eligible`, and excluding only nested verification
fields `artifact_ref`, `artifact_sha256`, and `subject_digest`. Mode and verifier
remain inside the subject.

`prepare-attestations` first emits canonical
`VerificationAttestationRequest/v1` artifacts and leaves the report terminal and
non-eligible. The external `attest` step emits canonical
`VerificationAttestation/v1` artifacts. Each attestation binds its request ref
and byte digest, subject, claim/hypothesis/target, scope, complete evidence
bindings, dossier, source bundle and source artifact, mode and verifier,
`origin: external_verifier`, `verdict: passed`, producer/verifier context IDs,
basis, the pending-normalized report-set context (including `network_ref` and
`completion_matrix`), the sorted unique expected report subject identities, and
UTC creation time. The contexts must differ. `finalize-attestations`
reopens both artifacts and deterministically recomputes report/set IDs and
eligibility. The bridge repeats all of these validations; verifier-name denials
are only an additional obvious-self/generated guard.

`attest` processes exactly one prepared request selected by `--report-id`;
heterogeneous sets chain one invocation per report. Verification artifacts must
use the canonical `verification-requests/<sha256>.json` or
`verification-attestations/<sha256>.json` path and be regular files. Aliases,
symlinks, FIFOs, sockets, devices, network retargeting, duplicate claims, and
duplicate frozen subjects fail closed in the strict producer validator.

## `NetworkPatchProposal/v2`

The proposal is a closed, content-addressed action set. Top-level proposal,
each action, and each reviewed-evidence basis row carry canonical digest-derived
IDs. Every basis preserves request, report-set, dossier, reading-report,
source-bundle, artifact, discovery-source, claim, evidence, span, locator, and
verification provenance. Only `supports + full_text + evidence|reconstruction
+ exact scope + decisive + passed + independent/expert verification` is legal.
`NetworkPatchProposal/v1` is audit-only.

`propose_relation` additionally carries exactly one closed
`NetworkPatchTargetClaim/v1` payload with fields `schema`, `schema_version`,
`claim_id`, `claim_text`, `entity_id`, `impact`, `coverage_dimensions`,
`benchmark_profiles`, `supersedes`, `epistemic_status`, `gap_hypothesis_id`,
`target_signature`, `report_claim_id`, `report_claim_digest`, `scope`,
`scope_digest`, and `target_claim_digest`. `scope` is exactly
`scope_statement`, `assumptions`, `conditions`, `units`, `exclusions`,
`defeaters`, `coverage_dimensions`, and `benchmark_profiles`.
`target_claim_digest` hashes the payload without its two identity fields;
`claim_id = "claim-target-" + digest[:16]`. Missing typed scope, defaulted
impact, query-signature-as-claim, or a report-claim/epistemic mismatch fails
closed.

Typed scope categories remain distinct. `assumptions`, `conditions`, and
`units` are not flattened into an unlabelled `coverage_dimensions` list;
`exclusions` and `defeaters` are not benchmark profiles. Coverage dimensions
and benchmark profiles may only come from explicit same-named request fields.
Because `LearnFromPapersRequest/v1.epistemic_task.scope` currently has no such
fields, both lists are empty and any invented non-empty value fails closed.

Action kind dispatch is the following closed map:

| target kind | action type | local status rule |
| --- | --- | --- |
| `relation` | `propose_relation` | `proposed` with a valid target claim |
| `evidence` | `propose_evidence` | `proposed` only when the signature equals the sole reviewed `evidence_id` |
| `node` | `propose_node` | `blocked` until a closed target-node contract exists |
| `boundary`, `counterexample`, `version`, `benchmark`, `benchmark_profile`, `assumption`, `mechanism`, `metric`, `measurement`, `estimator`, `failure_mode`, `context` | `propose_evidence` | `blocked`; audit/proposal only |

Both `proposed` and `blocked` are valid local proposal states. A consumer must
reject `blocked`; it must not infer target kind from an action-type prefix or
materialize unsupported semantic targets as generic evidence.

Every basis source must already appear in the bound live network `sources`
collection under the same `source_id`. A miss is terminal
`onboarding_required`, not a patch proposal. After onboarding, export a new
snapshot and rerun the full audit because all prior request/report bindings are
stale. The RKN consumer materializes evidence with
`independence_group = basis.source_id`.

## `PaperReadingEvidenceCollection/v1` bridge and `NetworkPatchProposal/v3`

The multi-reading path accepts the LFP-owned
`PaperReadingEvidenceCollection/v1` through the producer's public
`validate_collection` function. NGD does not redefine that aggregate schema.
The collection binds one network snapshot and one
`LearnFromPapersRequestSet/v1`, contains at least two canonically ordered
one-paper groups, and uses unique `source_id` values. NGD copies
`collection.reading_groups` order exactly; it never deduplicates or silently
sorts the projected group references.

Collection consumption has one admitted route:
`direct_reviewed_selection`. The preconsumption hypotheses file must be the
exact approved `ReviewedGapSelection/v2` projection. A `results` status is not
authority: NGD rejects it until a future route can owner-replay exact
`ScholarDiscoveryResultSet/v2` files and their execution authorities.

The direct route requires a detached
`ReviewedEvidenceCollectionConsumptionAuthority/v1`. Its closed top-level
field set is:

```json
{
  "schema": "ReviewedEvidenceCollectionConsumptionAuthority/v1",
  "schema_version": "1.0",
  "authority_id": "reviewed-collection-consumption-authority-<16 hex>",
  "authority_digest": "<64 lowercase hex>",
  "route": "direct_reviewed_selection",
  "network_ref": {"network_id": "KN-001", "snapshot_id": "KN-001-S001", "sha256": "<sha>"},
  "consumed_at": "2026-08-05T00:30:00Z",
  "round_id": "ROUND-001",
  "hypotheses_binding": {},
  "review_request_set_binding": {},
  "reading_collection_binding": {},
  "expected_consumed_hypotheses_sha256": "<sha>",
  "decision": "approved",
  "complete_scope": true,
  "no_known_omission": true,
  "reviewer_context": {
    "reviewer_id": "reviewer-002",
    "reviewer_role": "independent collection-consumption reviewer",
    "reviewer_context_id": "review-context-002",
    "reviewed_at": "2026-08-05T00:25:00Z",
    "independent_from_bound_artifact_producers": true
  },
  "producer_context_ids": ["producer-context-001"],
  "seal": {"algorithm": "sha256", "digest": "<authority_digest>"}
}
```

`hypotheses_binding` has exactly `schema`, `raw_file_sha256`,
`canonical_sha256`, `consumable_hypotheses`, `selection_summary`, and the full
`reviewed_selection_ref`. Each consumable row has exactly `hypothesis_id`,
`input_status: selected`, `epistemic_task_sha256`, `subject_ref`, and
`origin_gap_refs`.

`review_request_set_binding` has exactly `schema`, `raw_file_sha256`,
`canonical_sha256`, `request_set_id`, `request_set_digest`, and `requests`.
It deliberately has no `source_discovery_ref`: the detached authority, not a
fabricated Scholar anchor, approves the exact LFR source list. Each request
projection has exactly `request_id`, `request_content_sha256`,
`hypothesis_id`, `epistemic_task_sha256`, and `sources`. This route alone
requires each request to contain one source projection with `source_id`,
`source_digest`, and `source_content_sha256`. Requests must form the exact
Cartesian coverage of every selected hypothesis by every collection source.
Generic `LearnFromPapersRequestSet/v1` validation is not narrowed.

`reading_collection_binding` has exactly `schema`, `raw_file_sha256`,
`canonical_sha256`, `collection_id`, `collection_digest`, and
`reading_groups`. Each ordered group projection has exactly
`reading_group_id`, `reading_group_digest`, `source_id`, `source_digest`,
`source_artifact_sha256`, `report_set_id`, and `report_set_digest`.

Authority construction derives ordered unique `producer_context_ids` from the
finalized reading verification records when those IDs exist. The reviewer
context ID must differ from every bound producer context and the explicit
independence attestation must be true. This is a protocol record, not
cryptographic identity authentication; the independent handoff must separately
hold the exact raw authority-file SHA-256.

Canonical hashes use UTF-8 JSON with sorted keys and compact separators.
`authority_digest` hashes the authority without `authority_id`,
`authority_digest`, and `seal`. The external `expected_authority_file_sha256`
hashes the exact authority file bytes, including formatting and any final
newline; it is never inferred from the authority payload. Every input is a
canonical absolute non-symlink path, is stable-read, and is checked again after
live replay.

Authority creation runs the private deterministic transition. `consumed_at`
and `round_id` are authority-bound. `expected_consumed_hypotheses_sha256`
hashes the consumed hypotheses document after omitting only
`cycle_state.consumption_ref`, which avoids a self-referential digest. Public
consumption reruns that transition and exact-compares the hash.

Every collection group must contribute at least one basis for each reviewed
subject. Every basis must be `full_text`, `supports`, scope-exact, decisive,
verifier-passed, claim-support eligible, and source-onboarded. A high-impact
claim requires at least two distinct group `source_id` values. Status bases set
`independence_group` to exactly `source_id`. Cycle state carries
`reading_collection_id`, `reading_collection_digest`, and the compact
`consumption_ref`, not scalar report-set/dossier/bundle replacements.

The stable public APIs are:

```python
create_reviewed_collection_consumption_authority(
    hypotheses_path, network, review_requests_path, reading_collection_path,
    *, consumed_at, reviewer_context, round_id=None,
    execution_authority_contexts=None,
)
consume_reviewed_evidence_collection(
    hypotheses_path, network, review_requests_path, reading_collection_path,
    authority_path, *, expected_authority_file_sha256,
    execution_authority_contexts=None,
)
```

The stable proposal API is:

```python
propose_patch_v3(
    hypotheses_path, network, review_requests_path, reading_collection_path,
    authority_path, *, expected_authority_file_sha256,
    execution_authority_contexts=None,
)
```

The proposal input is the same preconsumption selection file. Proposal replay
calls the authority-gated consumer internally; a caller cannot inject a
handwritten consumed state.

V3 is the v2 closed envelope plus exactly one `reading_collection_ref` and one
`consumption_ref`:
It is non-empty and relation-only; blocked, node, and generic-evidence actions
remain on the v2 audit path and cannot enter atomic multi-reading acceptance.

```json
{
  "schema": "NetworkPatchProposal/v3",
  "schema_version": "3.0",
  "proposal_id": "network-patch-proposal-<16 hex>",
  "proposal_digest": "<64 lowercase hex>",
  "network_ref": {"network_id": "KN-001", "snapshot_id": "KN-001-S001", "sha256": "<sha>"},
  "request_ref": {
    "request_set_id": "request-set-...", "request_set_digest": "<sha>",
    "review_request_set_id": "LFR-...", "review_request_set_digest": "<sha>"
  },
  "consumption_ref": {
    "schema": "ReviewedEvidenceCollectionConsumption/v1",
    "route": "direct_reviewed_selection",
    "authority_id": "reviewed-collection-consumption-authority-<16 hex>",
    "authority_digest": "<sha>",
    "authority_file_sha256": "<exact raw-file sha>",
    "consumed_hypotheses_sha256": "<deterministic projection sha>"
  },
  "reading_collection_ref": {
    "collection_id": "paper-reading-evidence-collection-...",
    "collection_digest": "<sha>"
  },
  "generated_at": "2026-08-05T00:30:00Z",
  "proposal_only": true,
  "novelty_claimed": false,
  "review_gate": "pending_research_knowledge_network_acceptance",
  "actions": []
}
```

The proposal and consumed cycle carry byte-identical `consumption_ref` values.
`validate_collection_consumption_ref` checks its closed shape and content
identity. `propose_patch_v3` reopens every bound file, reruns consumption, and
rejects any proposal whose ref or consumed projection differs.

A relation action has exactly the v2 identity/type/status/hypothesis/target and
reviewed-basis fields plus `subject_ref`, `origin_gap_refs`,
`reading_group_refs`, and `target_claim`:

```json
{
  "action_id": "network-patch-action-<16 hex>",
  "action_digest": "<64 lowercase hex>",
  "action_type": "propose_relation",
  "action_status": "proposed",
  "hypothesis_id": "KGH-001",
  "target_signature": {"target_kind": "relation", "signature": "entity:A predicate:? entity:C"},
  "hypothesis": "The exact reviewed claim text",
  "subject_ref": {"subject_id": "reviewed-gap-claim-subject-...", "subject_digest": "<sha>"},
  "origin_gap_refs": [{"gap_id": "gap:1", "record_id": "gap-record-1", "sequence": 7, "status": "open", "sha256": "<sha>"}],
  "reading_group_refs": [{
    "reading_group_id": "paper-reading-evidence-group-...",
    "reading_group_digest": "<sha>",
    "source_id": "SRC-1",
    "report_set_id": "reading-report-set-v2-...",
    "report_set_digest": "<sha>"
  }],
  "reviewed_evidence": [],
  "target_claim": {}
}
```

`reading_group_refs` has exactly the same order as
`collection.reading_groups`; reviewed bases are contiguous in that order and
each group contributes at least one. `subject_ref` and `origin_gap_refs` equal
the target-claim projections. The action `hypothesis` equals the reviewed
subject claim text.

`NetworkPatchTargetClaim/v2` has the closed fields `schema`, `schema_version`,
`claim_id`, `claim_text`, `entity_id`, `impact`, `coverage_dimensions`,
`benchmark_profiles`, `supersedes`, `target_signature`, `subject_ref`,
`origin_gap_refs`, `report_claim_refs`, `scope`, `scope_digest`, and
`target_claim_digest`. Its scope contains `scope_statement`, `assumptions`,
`conditions`, `units`, `exclusions`, `defeaters`, `coverage_dimensions`, and
`benchmark_profiles`, all projected from the reviewed subject. Every ordered
`report_claim_ref` binds one basis through exactly `basis_id`, `basis_digest`,
`reading_group_id`, `claim_id`, `claim_digest`, `reading_report_id`, and
`reading_report_digest`. The producer never chooses `eligible[0]` as a scalar
claim surrogate.

Old selection, single-paper consumption, `NetworkPatchProposal/v2`, and
`NetworkPatchTargetClaim/v1` remain independently readable and are never
silently upgraded.

## `NetworkPatchProposal/v4` existing-claim evidence extension

V4 is additive; v1-v3 validation and replay remain unchanged. Its top-level
field set is exactly the v3 field set, with schema
`NetworkPatchProposal/v4` and `schema_version: "4.0"`. The native v4 proposal
digest hashes the complete canonical v4 payload except `proposal_id` and
`proposal_digest`; it is never computed from a v3 projection. The proposal ID
remains `network-patch-proposal-<digest[:16]>`.

Each v4 action preserves the v3 common fields unchanged: `action_id`,
`action_digest`, `action_type`, `action_status`, `hypothesis_id`,
`target_signature`, `hypothesis`, `subject_ref`, `origin_gap_refs`,
`reading_group_refs`, and `reviewed_evidence`. It then carries exactly one
route payload:

- When every current origin gap has no `claim_id`, the action is
  `propose_relation` with one `NetworkPatchTargetClaim/v2`. This is the v3
  new-claim route in the v4 envelope.
- When every current origin gap has the same non-empty `claim_id`, the action is
  `propose_evidence_extension` with one
  `NetworkPatchExistingClaimRef/v1` and no `target_claim`.

Claimless and claim-backed origins may not be mixed. Multiple claim IDs,
missing current claim rows, duplicate claim rows, and a target claim named by
another current claim's `supersedes` field fail closed. The extension subject
must exactly equal the current claim's `claim_text`, `impact`, and complete
typed scope; action `target_signature` and ordered origin-gap refs remain bound
through the reviewed `subject_ref` digest.

`NetworkPatchExistingClaimRef/v1` is closed:

```json
{
  "schema": "NetworkPatchExistingClaimRef/v1",
  "schema_version": "1.0",
  "claim_id": "claim-existing-1",
  "claim_record_ref": {
    "record_id": "claim:claim-existing-1",
    "sequence": 82,
    "sha256": "<canonical SHA-256 of the full current claim ledger row>"
  },
  "claim_semantics": {
    "claim_text": "The exact current claim text",
    "entity_id": null,
    "impact": "high",
    "is_factual": false,
    "scope_statement": "The exact current scope",
    "assumptions": [],
    "conditions": [],
    "units": [],
    "exclusions": [],
    "defeaters": [],
    "coverage_dimensions": [],
    "benchmark_profiles": [],
    "supersedes": null
  },
  "scope_digest": "<sha256 of scope_statement plus the seven typed lists>",
  "claim_semantic_digest": "<sha256 of all thirteen claim_semantics fields>"
}
```

`claim_record_ref.sha256` hashes the entire current claim ledger row exposed by
the bound live network, including its record metadata; it is not a hash of the
smaller semantic projection. `scope_digest` hashes exactly
`scope_statement`, `assumptions`, `conditions`, `units`, `exclusions`,
`defeaters`, `coverage_dimensions`, and `benchmark_profiles`.
`claim_semantic_digest` hashes the complete closed `claim_semantics` object.
Changing and resealing only one projection cannot bypass the other bindings.

The stable public APIs are:

```python
propose_patch_v4(
    hypotheses_path, network, review_requests_path, reading_collection_path,
    authority_path, *, expected_authority_file_sha256,
    execution_authority_contexts=None,
)
validate_patch_v4(value, network=None)
```

`propose_patch_v4` uses the same raw-file-pinned authority route as v3 and
replays collection consumption internally. The validator checks the native v4
identities, the closed route union, and the full v3 common evidence lineage.

## `LearnFromPapersRequest/v1.epistemic_task`

Every emitted request includes a closed epistemic task containing `question`,
`hypothesis`, `target_signature`, `scope_bounds`, `defeaters`, `falsifiers`,
`acceptance_criteria`, canonical `relation_vocabulary`, and
`required_inspection_depth`. The minimum depth is full text plus any
claim-bearing figures, tables, equations, appendices, and supplements;
reconstruction is required only when the acceptance criteria demand it.

## Private CLI output persistence

Every CLI JSON output contains network identity, hypotheses, queries, results,
or provenance and is therefore private. The writer creates missing output
directories with mode `0700`, rejects an existing output directory that grants
group or other access, and never changes the permissions of an existing private
directory. It writes through a unique same-directory temporary file forced to
`0600`, flushes and fsyncs the complete payload, atomically replaces the target,
forces the published file to `0600`, and fsyncs the directory. It rejects
symlink outputs and removes its temporary file if publication fails. These
properties do not depend on the caller's umask.

## CLI

```bash
python scripts/network_gap_discovery.py scan --network network.json --output probe.json
python scripts/network_gap_discovery.py generate-hypotheses \
  --network network.json --round-id ROUND-001 --output hypotheses.json
python scripts/network_gap_discovery.py prioritize --input hypotheses.json \
  --network network.json --output prioritized.json
python scripts/network_gap_discovery.py emit-search-requests \
  --input selected-only.json --network network.json --output scholar-requests.json \
  --google-scholar-policy manual_optional
python scripts/network_gap_discovery.py emit-search-requests \
  --input selected-only.json --network network.json --output scholar-requests.json \
  --google-scholar-policy manual_required
python scripts/network_gap_discovery.py emit-search-requests \
  --input selected-only.json --network network.json --output scholar-requests.json \
  --google-scholar-policy disabled
python scripts/network_gap_discovery.py consume-results \
  --hypotheses hypotheses.json --network network.json \
  --requests scholar-requests.json --result result-set.json --output hypotheses-after-results.json
python scripts/network_gap_discovery.py consume-reviewed-evidence \
  --hypotheses hypotheses.json --network network.json \
  --review-requests review_requests.json --reading-reports reading-reports.json \
  --dossier reading-dossier.json --source-bundle paper-source-bundle.json \
  --source-artifact paper.pdf --verification-root attestations/ \
  --output hypotheses-next.json
python scripts/network_gap_discovery.py propose-patch \
  --input hypotheses.json --network network.json \
  --review-requests review_requests.json \
  --reading-reports reading-reports.json \
  --dossier reading-dossier.json --source-bundle paper-source-bundle.json \
  --source-artifact paper.pdf --verification-root attestations/ \
  --output patch.json
python scripts/network_gap_discovery.py consume-reading-collection \
  --hypotheses hypotheses.json --network network.json \
  --review-requests review_requests.json \
  --reading-collection reading-collection.json \
  --consumption-authority collection-consumption-authority.json \
  --expected-authority-file-sha256 '<trusted exact raw SHA-256>' \
  --output hypotheses-next.json
python scripts/network_gap_discovery.py create-collection-consumption-authority \
  --hypotheses hypotheses.json --network network.json \
  --review-requests review_requests.json \
  --reading-collection reading-collection.json \
  --reviewer-context independent-reviewer-context.json \
  --consumed-at 2026-08-05T00:30:00Z \
  --output collection-consumption-authority.json
python scripts/network_gap_discovery.py propose-patch-v3 \
  --input hypotheses.json --network network.json \
  --review-requests review_requests.json \
  --reading-collection reading-collection.json \
  --consumption-authority collection-consumption-authority.json \
  --expected-authority-file-sha256 '<trusted exact raw SHA-256>' \
  --output patch-v3.json
python scripts/network_gap_discovery.py propose-patch-v4 \
  --input hypotheses.json --network network.json \
  --review-requests review_requests.json \
  --reading-collection reading-collection.json \
  --consumption-authority collection-consumption-authority.json \
  --expected-authority-file-sha256 '<trusted exact raw SHA-256>' \
  --output patch-v4.json
python scripts/network_gap_discovery.py cycle --network network.json \
  --hypotheses-output hypotheses.json --requests-output scholar-requests.json \
  --google-scholar-policy manual_optional
python scripts/network_gap_discovery.py validate --input patch.json
```

## Evidence-appraisal compilation

`compile-appraisal-needs` is the owner path from finalized
`EvidenceChallenge/v1` plus `TargetedEvidenceNeedSet/v1` into
`KnowledgeGapHypotheses/v1`. It requires a validated `SearchHistoryIndex/v1`,
the separately approved `HistoryAuthorityManifest/v1` that fixes its exact
artifact universe, its referenced `ReviewedHistoryAuthority/v1`, and an
exported live network. Only proposed
`scholar_discovery` needs become
hypotheses; all other routes are preserved exactly in `routed_needs`.

Top-level `appraisal_compilation` embeds the exact need set, sorted challenges,
history authority, authority approval, and history index. Each projected hypothesis carries a closed
`EvidenceAppraisalNeedOrigin/v1` with need-set, need, route, challenge, claim,
and appraisal refs. Prioritize, select, and emit preserve the complete
projection; deletion, insertion, mutation, or route substitution fails closed.

Confirm and refute goals use scholar-discovery's
`semantic-concept-bag-v1`. Goal and compiled-query signatures must differ and
both goals must bind the challenge-axis field. `adversarial_observation_pair`
supplies the shared target metric, comparator, boundary, and value/state; only
the closed ordered operator pairs `eq/neq`, `lt/gte`, `lte/gt`,
`inside/outside`, `present/absent`, `reproduced/not_reproduced`, or
`supports/does_not_support`, with `supports/challenges` claim implications,
are accepted. Free-text negation and same-direction rewrites cannot establish
orthogonality. Canonical or high-containment
history overlap fails, including selection leaks and failed, partial, empty,
successful, and candidate records. No-result and partial-provider outcomes do
not close a need and do not imply novelty.

Both goals must byte-match
`target_metric=...; comparator=...; boundary=...; observation=<operator> <value_or_state>; claim_implication=...`
as deterministically regenerated from the structured pair. Provider queries are
compiled from that projection; free prose cannot override its direction. Query
planning reserves non-truncatable slots for `target_metric`, `comparator`,
`boundary`, the objective-specific complementary `operator`, and
`value_or_state` before adding free keywords. Both normalized queries must
retain their operator and state. If the deduplicated structured core cannot fit
the 12-term budget, compilation fails closed rather than emitting a weakened
query.

The embedded history index is owner-replayed from its authority-fixed full
artifact universe; entries and source refs are not trusted merely because an
external caller recomputed their digest. Appraisal-origin request sets embed the entire reviewed
selected document and global Scholar policy. Network-gap-discovery and
scholar-discovery independently replay the ReviewedGapSelection and exact
request projection, so deleting an origin or appending a request fails after
rehashing.

Appraisal-origin request sets use
`AppraisalScholarDiscoveryRequestSet/v1`. Network result consumption requires
that schema whenever hypotheses carry `appraisal_compilation`; changing the
set to generic after deleting every origin/projection cannot enter appraisal
execution.

`dispatch-appraisal-package` is the explicit adapter for the producer's compact
`EvidenceAppraisalPackage/v1`. It preserves package, appraisal-set, need-set,
and exact need bindings in `EvidenceAppraisalRouteDispatch/v1`. Compact
non-search routes are dispatched unchanged; compact `scholar_discovery` fails
closed rather than inventing missing query semantics.

Validation and dispatch require the detached producer approval, prepared
request, and independent review plus an external caller-held
`expected_authority_sha256`. The adapter passes that pin to the producer's
public `validate_appraisal_package`; a missing or incorrect pin fails before
routing, even when the package and approval have been self-resealed.

```bash
python scripts/network_gap_discovery.py compile-appraisal-needs \
  --needs targeted-needs.json --challenge challenge-1.json \
  --history-index search-history.json --history-authority history-authority.json \
  --history-authority-review reviewed-history-authority.json \
  --network network.json \
  --round-id ROUND-APPRAISAL-001 --output hypotheses.json
python scripts/network_gap_discovery.py dispatch-appraisal-package \
  --package appraisal-package.json --approval reviewed-authority.json \
  --prepared prepared-appraisal.json --review independent-review.json \
  --expected-authority-sha256 "$EXPECTED_AUTHORITY_SHA256" \
  --output appraisal-route-dispatch.json
```

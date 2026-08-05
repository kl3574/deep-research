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

`structural_only` hypotheses describe structural signals that are resolved in graph/schema
logic rather than online search (for example, declared completion-gate failures).
These must use `next_action: "structural_only"` and are skipped by
`emit-search-requests`.

For all active search hypotheses, query text must remain semantic and avoid internal
object ids or route internals. Avoid IDs like `gap:`, `relation:`, `node:`,
`completion.gate_checks.`, `unmet_declared_gate:`, and phrase patterns like
`"No evidence ... at this snapshot"`.

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

## `LearnFromPapersRequest/v1.epistemic_task`

Every emitted request includes a closed epistemic task containing `question`,
`hypothesis`, `target_signature`, `scope_bounds`, `defeaters`, `falsifiers`,
`acceptance_criteria`, canonical `relation_vocabulary`, and
`required_inspection_depth`. The minimum depth is full text plus any
claim-bearing figures, tables, equations, appendices, and supplements;
reconstruction is required only when the acceptance criteria demand it.

## CLI

```bash
python scripts/network_gap_discovery.py scan --network network.json --output probe.json
python scripts/network_gap_discovery.py generate-hypotheses \
  --network network.json --round-id ROUND-001 --output hypotheses.json
python scripts/network_gap_discovery.py prioritize --input hypotheses.json \
  --network network.json --output prioritized.json
python scripts/network_gap_discovery.py emit-search-requests \
  --input prioritized.json --network network.json --output scholar-requests.json \
  --google-scholar-policy manual_optional
python scripts/network_gap_discovery.py emit-search-requests \
  --input prioritized.json --network network.json --output scholar-requests.json \
  --google-scholar-policy manual_required
python scripts/network_gap_discovery.py emit-search-requests \
  --input prioritized.json --network network.json --output scholar-requests.json \
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
python scripts/network_gap_discovery.py cycle --network network.json \
  --hypotheses-output hypotheses.json --requests-output scholar-requests.json \
  --google-scholar-policy manual_optional
python scripts/network_gap_discovery.py validate --input patch.json
```

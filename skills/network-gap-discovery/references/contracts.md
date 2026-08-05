# Network gap discovery contracts

## `NetworkGapProbe/v1`

`scan` consumes a `KnowledgeNetwork/v1` export and returns its bound digest,
structural counts, existing open gaps, unmet gates, isolates, components,
dangling relations, low-confidence edges, missing provenance, and fixed probe
families. Every structural signal is a candidate, not a negative fact.

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

`structural_only` hypotheses describe structural signals that are resolved in graph/schema
logic rather than online search (for example, declared completion-gate failures).
These must use `next_action: "structural_only"` and are skipped by
`emit-search-requests`.

For all active search hypotheses, query text must remain semantic and avoid internal
object ids or route internals. Avoid IDs like `gap:`, `relation:`, `node:`,
`completion.gate_checks.`, `unmet_declared_gate:`, and phrase patterns like
`"No evidence ... at this snapshot"`.

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

`consume-reviewed-evidence` requires reviewed evidence that targets the same
`request_set_id`, `request_set_digest`, and `network_id` as the cycle review set.
`consume-reviewed-evidence` and `propose-patch` also require the cycle state to
carry `report_set_id` and `report_set_digest`, and validate against
an explicit `PaperReadingReportSet/v1` input.
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

- `ReviewedEvidence` entries also carry `source_id` and `source_digest` and must
  match the candidate source selected from the active review request, including
  `source_ref`, `exact_locator`, `read_depth`, and url/doi identity.
- `ReviewedEvidence` entries also carry `reading_report_id`, `reading_report_digest`,
  `passage_id`, and `passage_digest`, and must resolve to valid entries in the
  active `PaperReadingReportSet/v1`.

- `consume-reviewed-evidence` and `consume-results` stop reasons are limited to
  `manual_required`, `review_pending`, `provider_pending`, `budget_exhausted`,
  and `saturated` when no-progress saturation conditions are met.

- `ReviewedEvidence` must set `discovery_only` to `false` for this skill path.
  `consume-reviewed-evidence` and `propose-patch` reject discovery-only evidence
  as decisive input.
- `results` cycle saturation still uses consecutive no-progress rounds logic, but
  does not trigger when the cycle remains `awaiting` manual result capture.

`claim_support_eligible` must be `true` for reviewed evidence consumed by this skill.

## `PaperReadingReport/v1` and `PaperReadingReportSet/v1`

`PaperReadingReport/v1` records the reviewed source and passage-level grounding used by reviewed evidence.

```json
{
  "schema": "PaperReadingReportSet/v1",
  "schema_version": "1.0",
  "network_id": "KN-001",
  "network_snapshot_sha256": "<64 lowercase hex>",
  "network_ref": {
    "network_id": "KN-001",
    "snapshot_id": "KN-001-S001",
    "sha256": "<64 lowercase hex>"
  },
  "generated_at": "2026-08-05T00:00:00Z",
  "report_set_id": "report-set-9f...",
  "report_set_digest": "<64 lowercase hex>",
  "reports": [
    {
      "schema": "PaperReadingReport/v1",
      "report_id": "reading-report-9f8...",
      "report_digest": "<64 lowercase hex>",
      "review_request_id": "LRR-....",
      "review_request_digest": "<64 lowercase hex>",
      "source_id": "SRC-....",
      "source_digest": "<64 lowercase hex>",
      "source_ref": "study-doi",
      "exact_locator": "10.1000/example-doi",
      "reading_depth": "full_text",
      "producer": "learn-from-papers",
      "protocol_version": "1.0",
      "source_artifact_sha256": "<64 lowercase hex>",
      "passages": [
        {
          "passage_id": "passage-abc...",
          "passage_digest": "<64 lowercase hex>",
          "locator_type": "page",
          "exact_locator": "p.1",
          "claim_summary": "Claim context summary",
          "evidence_summary": "Evidence summary",
          "passage_sha256": "<64 lowercase hex>"
        }
      ]
    }
  ]
}
```

`consume-reviewed-evidence` and `propose-patch` validate `reading_report_digest` and
passage hashes, and require status-basis provenance to include `reading_report_id`,
`reading_report_digest`, `passage_id`, and `passage_digest`.
`propose-patch` additionally requires proposal basis entries to resolve to entries in the active
`LearnFromPapersRequestSet/v1` and the active `PaperReadingReportSet/v1`, and it checks that each
`status_basis` provenance tuple `(review_request_id, source_id, source_digest, reading_report_id, passage_id)`
matches reviewed evidence in `ReviewedEvidenceSet/v1`.

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
  --review-requests review_requests.json --evidence reviewed-evidence.json \
  --reading-reports reading-reports.json \
  --output hypotheses-next.json
python scripts/network_gap_discovery.py propose-patch \
  --input hypotheses.json --network network.json \
  --reviewed-evidence-set reviewed-evidence.json \
  --review-requests review_requests.json \
  --reading-reports reading-reports.json \
  --output patch.json
python scripts/network_gap_discovery.py cycle --network network.json \
  --hypotheses-output hypotheses.json --requests-output scholar-requests.json \
  --google-scholar-policy manual_optional
python scripts/network_gap_discovery.py validate --input patch.json
```

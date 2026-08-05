# Scholar discovery contracts

## `ScholarDiscoveryRequest/v1`

```json
{
  "schema": "ScholarDiscoveryRequest/v1",
  "request_id": "SDR-GAP-001",
  "paper_need": "Find primary studies that test the proposed missing relation",
  "intent": "topic_set",
  "effort": "diligent",
  "criteria": {
    "must": ["target relation", "applicable regime"],
    "should": ["open data or code"],
    "must_not": ["unrelated use of the same acronym"]
  },
  "metadata_filters": {
    "years": {"from": 2015, "to": 2026},
    "authors": [], "venues": [], "languages": ["en"],
    "work_types": ["primary_study"], "open_access": null
  },
  "seeds": {
    "doi": [], "arxiv": [], "pmid": [], "openalex": [],
    "semantic_scholar": [], "titles": []
  },
  "routes": {
    "automatic": ["openalex", "semantic_scholar", "crossref"],
    "google_scholar": "manual_optional"
  },
  "budgets": {
    "max_rounds": 3, "max_queries": 18,
    "max_candidates": 100, "timeout_seconds": 900
  },
  "query_seeds": [
    {"objective": "confirm", "query": "exact concepts and relation"},
    {"objective": "refute", "query": "exact concepts failure OR limitation"}
  ],
  "as_of": "2026-08-05T00:00:00Z",
  "gap_ref": {"gap_id": "GAP-001", "network_id": "KN-001"}
}
```

`routes.automatic` must never contain `google_scholar`. The request is bounded
targeted discovery unless a separate review protocol governs screening.

### Paper-understanding gap query binding

`compile-understanding-gap` accepts only a valid `PaperUnderstandingGap/v1`.
It embeds that complete object as `understanding_gap`, mirrors its ID/digest/type
in `gap_ref`, preserves `question` as `paper_need`, and preserves
`search_terms` as `criteria`. It emits exactly one `confirm` and one `refute`
query using fixed vocabulary for:

- `missing_input_format`
- `missing_data_flow`
- `missing_derivation_step`
- `missing_algorithm_detail`
- `missing_applicability_boundary`
- `missing_conclusion_scope`

For this request subtype, extra top-level fields, altered query text, rewritten
criteria, and any attempted resolved semantic value fail closed. The ordinary
request digest therefore binds the original gap, upstream validation and
projection provenance, and targeted query intent. This is discovery only; it
does not fill the missing detail.

The compiler uses fixed human-safe vocabulary for each gap type plus validated
human search concepts. It never concatenates `missing_field` or any basis path
into an external query and repeats guards against private paths, tokens,
Zotero-like keys, digests, and internal IDs at the compiler boundary.

## `ScholarResultBatch/v1`

```json
{
  "schema": "ScholarResultBatch/v1",
  "request_digest": "<64 lowercase hex>",
  "query_id": "query-...",
  "provider": "openalex",
  "execution": "documented_api",
  "status": "succeeded",
  "accessed_at": "2026-08-05T00:02:00Z",
  "query": "exact compiled query",
  "search_event": {
    "endpoint": "https://api.openalex.org/works",
    "redacted_request": "search=...",
    "page_or_cursor": "*", "expected_total": 12, "retrieved": 12,
    "truncated": false, "response_sha256": "<64 lowercase hex>",
    "limitations": []
  },
  "candidates": [{
    "title": "Candidate title", "authors": ["Author One"],
    "year": 2024, "venue": "Venue",
    "identifiers": {"doi": "10.0000/example"},
    "work_type": "primary_study", "publication_status": "peer_reviewed",
    "access_level": "abstract_only",
    "landing_url": "https://doi.org/10.0000/example",
    "native_rank": 1, "native_score": null,
    "screening": {"decision": "include", "reason": "meets title criteria"}
  }]
}
```

For Google Scholar, `execution` must be `user_manual_export`. `search_event.artifact_origin`
must be:

- `user_supplied_manual_export` for completed manual-provider exports;
- `not_provided_manual_optional` when manual data was not needed for completion; or
- `not_provided_manual_required` only when manual data is mandatory and unavailable.

Do not store abstract, snippet, or full-text bodies in this contract.

## `ScholarDiscoveryResult/v1`

The deterministic handoff contains request and plan digests, the bounded
coverage promise, complete query plan, sanitized search events, work-family
clusters, ranked manifestations, field conflicts, route provenance, RRF
components, quality flags, exclusions, failures, unresolved queries, and stop
reason. Every candidate remains `discovery_only: true` and
`claim_support_eligible: false` until downstream full-text evidence review.

## `ScholarDiscoveryRequestSet/v1`

```json
{
  "schema": "ScholarDiscoveryRequestSet/v1",
  "schema_version": "v1",
  "request_set_id": "request-set-<16 hex chars>",
  "request_set_digest": "<64 lowercase hex>",
  "network_id": "KN-001",
  "network_snapshot_sha256": "<64 lowercase hex>",
  "network_ref": {
    "network_id": "KN-001",
    "snapshot_id": "snapshot-001",
    "sha256": "<64 lowercase hex>"
  },
  "generated_at": "2026-08-05T00:10:00Z",
  "requests": [
    { ... ScholarDiscoveryRequest/v1 ... }
  ]
}
```

`request_set_digest` is the canonical sha256 of the full request-set payload with
`request_set_id` and `request_set_digest` removed.

`request_set_id` must equal `"request-set-" + request_set_digest[:16]`.

`request_set.network_ref.sha256` must match `request_set.network_snapshot_sha256`
and `request_set.network_ref.network_id` must match `request_set.network_id`.

## `ScholarDiscoveryResultSet/v1`

```json
{
  "schema": "ScholarDiscoveryResultSet/v1",
  "schema_version": "v1",
  "request_set_id": "request-set-<16 hex chars>",
  "request_set_digest": "<64 lowercase hex>",
  "network_id": "KN-001",
  "network_snapshot_sha256": "<64 lowercase hex>",
  "network_ref": {
    "network_id": "KN-001",
    "snapshot_id": "snapshot-001",
    "sha256": "<64 lowercase hex>"
  },
  "generated_at": "2026-08-05T00:15:00Z",
  "results": [
    {
      "...": "...",
      "hypothesis_id": "GAP-001",
      "gap_hypothesis_id": "GAP-001"
    }
  ],
  "failures": [],
  "request_count": 1
}
```

`hypothesis_id` is the canonical field and mirrors `gap_hypothesis_id` for
backward compatibility.

`request_set_id` must match `"request-set-" + request_set_digest[:16]`, and all
`network_ref` fields must be consistent with network fields in the same object.

## CLI

```bash
python scripts/scholar_discovery.py plan --request request.json --output plan.json
python scripts/scholar_discovery.py execute --request-set request-set.json \
  --output discovery-result-set.json
python scripts/scholar_discovery.py handoff --request request.json \
  --plan plan.json --batch openalex.json --output discovery-result.json
python scripts/scholar_discovery.py validate --input discovery-result.json
python scripts/scholar_discovery.py compile-understanding-gap \
  --gap understanding-gap.json --as-of 2026-08-05T00:00:00Z \
  --output scholar-request.json
```

`execute` is the production path for a validated `ScholarDiscoveryRequestSet/v1`.
It compiles each bounded plan and calls only the official API providers named in
`routes.automatic`; provider credentials required by the script must already be
available in the process environment. Per-request provider failures remain
explicit in the result set rather than being replaced with fabricated
candidates. Validate the emitted result set before handing it downstream.

`execute` never automates Google Scholar. If the request makes Scholar optional
and no manual export is supplied, the result records that omission and may
continue through official APIs. If Scholar is mandatory, obtain a user-performed
export and normalize it as a manual batch for `handoff`; an unavailable mandatory
export is a terminal discovery limitation, not permission to scrape, bypass a
CAPTCHA, or silently widen the coverage claim.

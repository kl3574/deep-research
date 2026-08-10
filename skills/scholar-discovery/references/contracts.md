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

`request_count` is the total number of terminally represented requests, not only
the number with result objects. It must equal the number of unique result request
IDs plus unique failure request IDs; a request cannot appear in both arrays.

`request_set_id` must match `"request-set-" + request_set_digest[:16]`, and all
`network_ref` fields must be consistent with network fields in the same object.

## Private CLI output persistence

Every CLI JSON output contains requests, queries, provider events, result
metadata, or provenance and is therefore private. The writer creates missing
output directories with mode `0700`, rejects an existing output directory that
grants group or other access, and never changes the permissions of an existing
private directory. It writes through a unique same-directory temporary file
forced to `0600`, flushes and fsyncs the complete payload, atomically replaces
the target, forces the published file to `0600`, and fsyncs the directory. It
rejects symlink outputs and removes its temporary file if publication fails or
is interrupted by any `BaseException`. These properties do not depend on the
caller's umask.

## CLI

```bash
python scripts/scholar_discovery.py plan --request request.json --output plan.json
python scripts/scholar_discovery.py authorize-request-set \
  --request-set request-set.json --reviewer-id reviewer-2 \
  --reviewer-role independent-execution-reviewer \
  --reviewed-at 2026-08-09T08:00:00Z --attest-independent-reviewer \
  --output reviewed-execution-authorization.json
python scripts/scholar_discovery.py execute --request-set request-set.json \
  --execution-authority reviewed-execution-authorization.json \
  --expected-execution-authority-sha256 "$EXPECTED_EXECUTION_AUTHORITY_SHA256" \
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

## `SearchHistoryIndex/v1`

`HistoryAuthorityCandidate/v1` first fixes the exact artifact refs
(`schema`, `sha256`) in one history universe. The independent
`ReviewedHistoryAuthority/v1` binds the candidate's canonical file SHA, the
same refs, `decision: approved`, a complete-universe/no-known-omission
attestation, and reviewer ID/role/time with independence attested. The final
`HistoryAuthorityManifest/v1` contains a closed `approval_ref`; its digest
binds that separate approval without a content-address cycle.

`build-history` requires both final manifest and approval and accepts only
`ScholarDiscoveryRequest/v1`, request sets,
`ScholarDiscoveryResult/v1`, result sets, and
`KnowledgeGapHypotheses/v1`. It emits a private content-addressed index with
exact fields `schema`, `schema_version`, `history_id`, `history_digest`,
`generated_at`, `authority_ref`, `source_artifacts`, `artifact_universe`, and
`entries`.

Each entry binds sorted canonical terms and a
`semantic-concept-bag-v1` SHA-256 signature to objective, state, request ID,
source schema/digest/logical locator, and selection-leak flag. States cover
requested, selection leak, succeeded, partial, empty, failed, blocked,
budget-exhausted, and candidate. Failure records join their request queries
independently of CLI artifact order. Abstracts, snippets, full text, private
paths, and credentials are excluded.

`artifact_universe` embeds each actual owner-validated source artifact with its
schema and canonical SHA-256. Validation matches that universe exactly to the
separately supplied authority manifest, reconstructs its candidate, recomputes
the approval digest, reconstructs the entire index, and
requires byte-semantic equality. Clearing entries or deleting a complete source
from the universe, source list, and entries cannot be legalized by recomputing
the outer digest. Every result binds the exact
request digest and deterministic compiled-plan digest. Every planned query must
occur in `search_events`, `unresolved_query_ids`, or `provider_failures`; a
partial result with missing query coverage is invalid.

Requests projected from evidence appraisal additionally carry a closed
`EvidenceAppraisalNeedOrigin/v1`. Its exact need route is
`scholar_discovery`, and all need-set, need, challenge, claim, and appraisal
refs remain bound by the request digest.
For appraisal-origin request sets, the full reviewed selected hypotheses and
global Scholar policy are embedded. Both owners replay the reviewed selection
and reconstruct the complete ordered request list; missing origins, deleted
requests, and unreviewed appends cannot be legalized by rehashing.

```bash
python scripts/scholar_discovery.py build-history \
  --artifact round05-requests.json --artifact round06-results.json \
  --authority-manifest history-authority.json \
  --authority-review reviewed-history-authority.json \
  --generated-at 2026-08-09T08:00:00Z --output search-history.json
```

Use `build-history-authority-candidate`, `approve-history-authority` with
both explicit attestation flags, and `finalize-history-authority` before this
command. Each output uses the atomic private writer.

## `AppraisalScholarDiscoveryRequestSet/v1`

This schema is reserved for exact selected projections originating in evidence
appraisal. Only `execute-appraisal` accepts it. Generic
`ScholarDiscoveryRequestSet/v1` cannot enter appraisal execution, and generic
`execute` rejects the appraisal schema.

## `ReviewedSearchExecutionAuthorization/v1`

Request-set validation does not authorize network execution. Both generic
`execute` and appraisal-only `execute-appraisal` require a separate reviewed
authorization plus the caller-provided external
`expected_execution_authority_sha256` pin. That pin is exactly the SHA-256 of
the authorization artifact's original file bytes, not its internal
`authorization_digest`. `authorize-request-set` binds the
actual request-set raw file SHA-256, schema,
request-set ID/digest, global and ordered per-request execution profiles, and
the exact ordered request IDs, request digests, and query rows. It also binds
`decision: approved` and an independently attested reviewer ID, role, and time.

At execution, the authorization owner replays that complete projection from
the supplied request set, independently recomputes the internal content digest,
and compares the actual authorization file SHA to the external pin before the
transport is reachable. CLI execution derives the actual request-set raw SHA
from bytes. Python authorization/execution APIs likewise require the actual
request-set artifact path, and execution APIs additionally require the actual
authorization artifact path. The owner reads only regular, non-symlink files,
requires each parsed object to equal its supplied object, and computes the raw
SHA-256 values internally; caller SHA arguments are optional equality
cross-checks only. Both entrypoints reject a missing artifact path, a
pretty-byte rewrite, or a pin mismatch before transport. An internal digest
used as the pin, a changed
trailing newline, missing authorization, a wrong pin, or rewriting
an appraisal set to generic while changing its typed request IDs cannot be
legalized by resealing either artifact. `validate` may still inspect request
sets without an authorization because it never contacts providers.

`ScholarDiscoveryResult/v1` and `ScholarDiscoveryResultSet/v2` are
cross-field consistent: `complete_bounded` requires all planned queries to be
represented, complete, untruncated, within budget, and free of unresolved rows
or blocking provider failures. Partial/blocked statuses require matching event,
failure, unresolved-query, truncation, or budget evidence. Only an explicitly
optional manual Google Scholar occurrence with
`artifact_origin: not_provided_manual_optional` may remain blocked without
making otherwise complete automatic-provider coverage partial.
Result-set v2 replay uses a conservative raw `pre_truncation_candidate_count`
equal to the sum of `search_events[].candidate_count`, and rejects missing or
inconsistent values (`>= len(ranked_candidates)`).

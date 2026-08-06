# Scholarly source acquisition contracts

These contracts bridge a ranked discovery candidate to local source bytes. They
prove deterministic record structure, byte integrity, and honest execution state.
They do not prove open-access legality, author identity, bibliographic correctness,
paper relevance, or scientific entailment.

## `AcquisitionCandidate/v1`

The input is one explicit candidate, not a query or a discovery result set.

```json
{
  "schema": "AcquisitionCandidate/v1",
  "candidate_id": "candidate-0123456789abcdef",
  "title": "Canonical title from discovery metadata",
  "authors": ["A. Author"],
  "year": 2024,
  "rank": 1,
  "identifiers": {"doi": "10.1234/example"},
  "discovery_ref": {
    "schema": "ScholarDiscoveryResult/v1",
    "artifact_sha256": "<64 lowercase hex>",
    "candidate_id": "candidate-0123456789abcdef"
  },
  "locator": {
    "url": "https://repository.example.edu/paper.pdf?download=1",
    "source_type": "institutional_repository",
    "access_basis": "institutional_public_copy"
  }
}
```

Required fields are `schema`, `candidate_id`, `title`, and `locator`. The script
normalizes omitted optional fields to empty or null values. Unknown fields fail.
`discovery_ref` is optional; when present, bind the exact discovery JSON file by
SHA-256 and repeat the same `candidate_id`.

Allowed source/access pairs are:

| `source_type` | `access_basis` |
| --- | --- |
| `open_repository` | `declared_open_access` |
| `institutional_repository` | `institutional_public_copy` |
| `author_copy` | `author_provided` |
| `preprint_server` | `preprint_public_copy` |
| `publisher_open` | `publisher_open_access` |

The declaration is a caller assertion. The script does not infer legal status from
a domain name. URL user information, fragments, non-default ports, IP literals,
single-label hosts, control characters, and query keys associated with credentials
or signed access are rejected. Query values are used for the request when allowed
but are removed from every output record.

## `AcquisitionResult/v1`

Both `plan` and `fetch` emit the same closed schema:

```json
{
  "schema": "AcquisitionResult/v1",
  "schema_version": "v1",
  "producer": "scholarly-source-acquisition",
  "protocol_version": "1.0",
  "operation": "fetch",
  "status": "acquired",
  "generated_at": "2026-08-05T00:00:00Z",
  "candidate": {"...": "normalized candidate without URL query values"},
  "candidate_digest": "<64 lowercase hex>",
  "request": {
    "requested_url": "https://repository.example.edu/paper.pdf",
    "query_removed": true,
    "source_type": "institutional_repository",
    "access_basis": "institutional_public_copy",
    "destination": "/absolute/path/paper.pdf",
    "request_profile": "anonymous-pdf",
    "transport_profile": "direct",
    "proxy_url": null,
    "max_bytes": 104857600,
    "timeout_seconds": 30.0,
    "redirect_limit": 3
  },
  "http": {
    "attempted": true,
    "status_code": 200,
    "content_type": "application/pdf",
    "final_url": "https://repository.example.edu/paper.pdf",
    "redirects": [],
    "bytes_received": 12345
  },
  "checks": [{"name": "candidate_contract", "status": "passed", "detail": null}],
  "artifact": {
    "path": "/absolute/path/paper.pdf",
    "media_type": "application/pdf",
    "size_bytes": 12345,
    "sha256": "<64 lowercase hex>",
    "pdf_magic_verified": true,
    "content_type_verified": true
  },
  "handoff": {
    "target_schema": "PaperSourceBundle/v1",
    "source_path": "/absolute/path/paper.pdf",
    "source_sha256": "<64 lowercase hex>",
    "builder_contract": "skills/learn-from-papers/scripts/paper_source_bundle.py",
    "recommended_argv": ["build", "--source", "/absolute/path/paper.pdf", "--output", "<bundle-json-path>"]
  },
  "failures": [],
  "result_id": "acquisition-result-<16 hex>",
  "result_digest": "<64 lowercase hex>"
}
```

`candidate_digest` covers the embedded, query-free candidate. `result_digest` is
canonical JSON SHA-256 excluding only `result_id` and `result_digest`; `result_id`
is `acquisition-result-` plus its first 16 hex characters.

### State invariants

| Operation | Status | Network | Artifact | Failures |
| --- | --- | --- | --- | --- |
| `plan` | `planned` | not attempted | null | empty |
| `plan` | `failed` | not attempted | null | non-empty |
| `fetch` | `acquired` | HTTP 200 | verified PDF + handoff | empty |
| `fetch` | `failed` | attempted or preflight | null | non-empty |

The ordered checks are `candidate_contract`, `url_policy`, `transport_policy`,
`destination_exclusive`, `public_dns`, `http_response`, `content_type`,
`pdf_magic`, `size_limit`, `sha256`, and `artifact_publish`. A plan leaves all
network and byte checks `not_run`. A successful fetch passes every check.

Failed results contain controlled codes and messages but never raw response bodies,
request headers, exception URLs, query values, cookies, session material, or
credentials. A malformed input can therefore produce `candidate: null`,
`candidate_digest: null`, and `request: null` while remaining a valid failed result.
CLI-supplied execution limits are validated before the candidate is loaded. A
limit violation remains a structured failed result, but its safe detail starts
with `Acquisition limits are invalid` rather than incorrectly attributing the
failure to the candidate contract. Current hard maxima are 512 MiB, 120 seconds,
and five redirects.

## Fetch policy

- Transport defaults to `direct`, which uses an explicitly empty proxy handler and
  never reads environment proxy settings. `loopback-proxy` is opt-in and requires
  an explicit `http://<loopback-IP>:<port>` URL. Only IPv4/IPv6 loopback literals
  are accepted; user information, query, fragment, non-root path, missing port,
  and remote hosts fail `transport_policy`. The proxy URL is canonicalized into
  the result, contains no credentials, and is never inferred from the environment.
- A loopback proxy changes only the byte transport. The scholarly origin and every
  redirect are still independently checked for HTTP(S), default port, public DNS,
  redirect limit, total deadline, response type, size, PDF magic, and SHA-256.
- Only `http` and `https`, public DNS answers, default ports, and at most the
  declared redirect limit are allowed. `timeout_seconds` is a single monotonic
  wall-clock budget for DNS, redirects, response opening and every body read,
  verification, and exclusive publication. Slow trickling cannot reset it.
- Environment proxies are disabled. Requests send only fixed `User-Agent`,
  `Accept: application/pdf`, and `Accept-Encoding: identity` headers.
- Response status must be `200`, media type must be `application/pdf`, content
  encoding must be absent or `identity`, and the first five bytes must be `%PDF-`.
- The declared and observed byte counts must respect `max_bytes`; a present
  `Content-Length` must equal the completed file size.
- Bytes stream to a mode-0600 temporary file in the destination directory. Only a
  fully verified file is hard-linked to an absent destination. Partial files are
  removed, and a concurrent destination wins rather than being overwritten.
- Deadline expiry emits `fetch_deadline_exceeded`, closes the response, removes
  temporary bytes, and rolls back a just-published link only when it is still the
  same inode. Blocking DNS/open/read operations run behind a bounded wait so the
  CLI can return even when the underlying platform call does not promptly cancel.
  Cancellation first shuts down discovered underlying sockets, then performs
  response-object close on a daemon cleanup thread with a bounded grace period;
  cleanup cannot silently add another full network timeout to CLI wall time.
- Redirect safety checks reduce common SSRF risk but are not a network sandbox or
  proof against DNS rebinding. Run acquisition in an appropriately isolated
  environment when the threat model requires it.

## Validation and handoff

`validate` rejects unknown fields, state contradictions, stale IDs/digests,
query-bearing manifest URLs, and unsafe acquired-artifact paths. For `acquired`, it
reopens the artifact and recomputes size, `%PDF-`, and SHA-256. It does not parse or
interpret the paper.

`handoff` is data for `PaperSourceBundle/v1`; acquisition never invokes the builder.
The builder must independently re-open the source and recompute the SHA-256 before
any passage locator or paper claim can be created.

# Paper-reading report-set contracts

## `PaperReadingReportSet/v1`

Canonical top-level fields:

- `schema`: fixed `PaperReadingReportSet/v1`
- `schema_version`: fixed `v1`
- `producer`: fixed `learn-from-papers`
- `protocol_version`: fixed `1.0`
- `generated_at`: RFC-3339 UTC timestamp
- `review_request_set_id`
- `review_request_set_digest` (64 lowercase hex)
- `network_ref`:
  - `network_id`
  - `snapshot_id`
  - `sha256` (64 lowercase hex)
- `report_set_id`: content id with prefix `reading-report-set-`
- `report_set_digest`: SHA-256 over report-set payload excluding
  `report_set_id` and `report_set_digest`; legacy compatibility fields
  (`network_id`, `network_snapshot_sha256`, `source_artifact_sha256`,
  `reading_report_set_id`, `reading_report_set_digest`) are ignored in digest and
  output canonicalization.
- `reports`: list of per-review reports (minimum one)

For each report:

- `schema`: fixed `PaperReadingReport/v1`
- `report_id`: content id with prefix `reading-report-`
- `report_digest`: SHA-256 over report payload excluding `report_id` and
  `report_digest`
- `review_request_id`
- `review_request_digest` (64 lowercase hex)
- `source_id`
- `source_digest` (64 lowercase hex)
- `source_ref`
- `source_artifact_sha256` (64 lowercase hex)
- `read_depth`: fixed `full_text`
- `evidence_passages`: list of atomic evidence passages (minimum one)

For each passage:

- `passage_id`: content id with prefix `passage-`
- `passage_digest`: SHA-256 over passage payload excluding `passage_id`
  and `passage_digest`
- `locator_type`: one of `page`, `section`, `figure`, `table`, `equation`
- `exact_locator`: non-empty string, not URL-only or DOI-only
- `passage_sha256` (64 lowercase hex)
- `claim_summary`
- `evidence_summary`
- `stance`: one of `support`, `refute`, `mixed`

ID and digest rules (network-compatible strict form):

- `report_set_id = "reading-report-set-" + report_set_digest[:16]`
- `report_id = "reading-report-" + report_digest[:16]`
- `passage_id = "passage-" + passage_digest[:16]`

Failure behavior is fail-closed for:

- missing/invalid top-level `network_ref`, `schema_version`,
  `review_request_set_id`, `review_request_set_digest`
- missing source artifact SHA-256
- missing report/set IDs or digests
- mismatched digests or IDs
- missing evidence passages / locator fields
- exact locator that is URL-only or DOI-only
- duplicate report IDs, report digests, or passage IDs
- discovery metadata without completed extraction payload

## CLI

```bash
python skills/learn-from-papers/scripts/paper_reading_report_set.py create \
  --input structured_extraction.json --output report_set.json
python skills/learn-from-papers/scripts/paper_reading_report_set.py validate \
  --input report_set.json
```

`validate` checks complete structural and contract integrity and reports strict
`report_set_id` and `report_set_digest` consistency, including all report and
passage IDs/digests.

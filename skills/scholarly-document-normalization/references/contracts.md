# Scholarly document normalization contracts

## `ScholarlyDocumentQuality/v1`

`inspect` emits one closed, content-addressed JSON object. Unknown keys fail.
It binds the local PDF path, `%PDF-` magic, byte size, SHA-256, page count,
optional `PaperSourceBundle/v1` reference, exact extraction tool paths/versions,
public thresholds, per-page metrics, aggregate fractions, classification, and
review state.

Classifications are mutually exclusive:

- `native_ok`: extracted text is nonblank and below pathological/column warnings.
- `blank_scan`: at least 80% of pages have at most 20 non-whitespace characters.
- `pathological_text`: at least 50% of pages cross a pathological threshold,
  mean extracted characters per page reach 100,000, or one page contains at
  least 1,000,000 extracted characters.
- `mixed`: blank or pathological pages coexist with usable pages, or a minority
  of abnormal pages remains.
- `column_risk`: at least 25% of pages have layout-preserved lines in which at
  least 20% of nonempty lines contain a four-space inter-column gap.

The exact threshold object is embedded in every artifact and must equal the
validator's supported threshold set. Per-page metrics include extracted,
non-whitespace, alphanumeric, replacement and control characters; line counts,
maximum and mean line lengths; empty, long-line and column-gap fractions; maximum
token repetition; and a page classification.

`quality_digest` is SHA-256 over canonical JSON excluding `quality_digest` and
`quality_id`; `quality_id` is `scholarly-document-quality-<first-16-hex>`.
The caller must declare `source_kind=ocr_derivative` for a known OCR/searchable
derivative. This does not change extractability classification, but it forces
`review_required=true`; byte inspection cannot infer OCR provenance or accuracy.

## `ScholarlyDocumentNormalization/v1`

`normalize` consumes a live-valid quality artifact and publishes exactly two
private `0600` outputs: a new searchable PDF and a closed normalization record.
It never overwrites. Publication rolls back both outputs on failure and its
temporary work directory is removed.

The record binds:

- quality-input path, byte SHA-256, quality ID, and quality digest;
- original and derivative paths, magic, byte size, SHA-256, and page count;
- exact paths, resolved paths, version banners, and version-probe argv for all
  five tools;
- placeholder-based render, per-page OCR, and assembly argv templates;
- DPI, language selection, method, complete before/after quality objects;
- `review_required=true`, explicit review reasons, and
  `accuracy_claim=not_assessed`;
- a canonical lineage digest and derived lineage ID.

`pdftoppm -png` rasterizes pages, Tesseract emits one PDF per page, and
`pdfunite` assembles them. The derivative page count must equal the original.
An after-quality state of `blank_scan`, `pathological_text`, or `mixed` is an
ineffective normalization failure and is not published. `column_risk` may remain
because searchable text does not prove semantic reading order.

`lineage_digest` is SHA-256 over canonical JSON excluding `lineage_digest` and
`lineage_id`; `lineage_id` is
`scholarly-document-normalization-<first-16-hex>`.

### Backward-compatible `adopt-existing` variant

`ScholarlyDocumentNormalization/v1` is a closed discriminated union keyed by
`method`. Existing `method=pdftoppm+tesseract+pdfunite` records retain their
original key set and validation semantics. `method=adopt-existing` records add
`adoption_mode`, `validation_tools`, and `provenance` without changing the schema
identifier or invalidating existing v1 records.

`adopt-existing` is used when both the immutable original and an already-created
searchable OCR derivative exist. The command never renders pages, runs OCR,
assembles a PDF, overwrites a file, or republishes either input. It only publishes
a new `0600` record with exclusive-create semantics.

The adopted record binds full `ScholarlyDocumentQuality/v1` per-page evidence for
the raw original and caller-declared `ocr_derivative`; current validation-tool
identities; all five declared pipeline tools; render, OCR, and assembly argv;
settings; and closed `recorded` or `reconstructed` provenance. All five tools are
version-probed, but `pdftoppm`, `tesseract`, and `pdfunite` are never invoked
operationally. `recorded` provenance requires explicit argv JSON arrays.
`reconstructed` provenance may use canonical placeholder templates, labeled as
reconstruction rather than historical execution proof.

Adoption fails before publication when the raw quality artifact is stale, the
original and derivative are identical, page counts differ, either PDF identity
changes during inspection, the derivative remains blank/pathological/mixed, a
tool identity cannot be validated, or the record path already exists. The record
always has `review_required=true` and `accuracy_claim=not_assessed`.

## `ScholarlyDocumentNormalizationFailure/v1`

CLI failures are closed JSON written to stderr with `command`, stable `code`,
message, missing-tool labels, and `temporary_artifacts_cleaned`. Missing tools
never trigger an implicit PATH search. Scientific text, credentials, and source
contents are never included.

## Validation

`validate` accepts either quality or either normalization-v1 method variant. It reopens regular
non-symlink files, checks `%PDF-`, recomputes bytes/SHA/page count, reruns
layout-preserving extraction for quality metrics, reprobes explicit tools, checks
the optional source-bundle binding, and recomputes content addresses. For a
normalization record it also requires the exact quality input and derivative and
recomputes both quality states and the lineage digest. For adopted records it
also reprobes all five tools and validates the closed provenance/argv fields. It
does not rerun OCR.

Passing validation proves deterministic artifact and tool-lineage coherence. It
does not prove OCR transcription accuracy, equation fidelity, figure fidelity,
or correct multi-column reading order.

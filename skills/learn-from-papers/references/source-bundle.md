# PaperSourceBundle/v1 source bundles

`PaperSourceBundle/v1` materializes a source document into a content-addressed bundle with
per-page private text artifacts and integrity verification.

## Commands

- `build`
  - Inputs: `--source` (file), `--output` (bundle JSON path), optional
    `--generated-at`, optional `--render-pages`
  - Produces:
    - `<output>` manifest JSON
    - `pages/page-####.txt` artifact files under `output` directory
  - Builds all artifacts in a same-directory staging tree first, verifies the staged
    bundle, then transactionally publishes live `pages`, optional `page_renders`, and
    the output manifest with journaled rollback/recovery after verification succeeds.
  - Supports:
    - text/markdown via plain UTF-8 file split on form-feed (`\f`) for pages
    - PDF via `pdfinfo` + `pdftotext` (required); optional `pdftoppm` when
      `--render-pages` is set
- `verify`
  - Inputs: `--bundle`, `--source`
  - Verifies:
    - schema/version/producer constraints
    - source SHA-256 against manifest and source name
    - deterministic page re-derivation from source (`text` split or PDF re-extraction) and page artifact SHA-256/size/path checks
    - strict tool-version coherence for PDF re-extraction checks; version mismatch
      fails verification
- `locate`
  - Inputs: `--bundle`, `--page`, `--start-char`, `--end-char`
  - Validates page artifact SHA-256, byte_count, and char_count before span calculation
  - Recomputes the span hash from bundled page bytes + page index + offsets, returns
    a dual locator (`exact_locator` + `span_hash`)

Rendered image entries in `rendered_pages` are validated for safe paths, exact byte counts,
and exact `artifact_sha256`.

## Manifest fields

- `schema`: `PaperSourceBundle/v1`
- `schema_version`: `v1`
- `producer`: `learn-from-papers`
- `protocol_version`: `1.0`
- `generated_at`: canonical UTC ISO-8601 timestamp ending in `Z`
- `source`:
  - `name`
  - `format` (`text` or `pdf`)
  - `size_bytes`
  - `source_sha256`
- `page_count`
- `tools`: map of checked tool states (`pdfinfo`, `pdftotext`, optional `pdftoppm`)
- `pages`: list of canonical page entries
  - `page_index`
  - `artifact_path` (relative path)
  - `artifact_sha256`
  - `byte_count`
  - `char_count`
- `bundle_digest`
- `bundle_id`
- optional `rendered_pages` when rendering is enabled

## Security invariants

- source input and output bundle path must not be symlinks
- output/bundle root directories are checked as non-symlink paths
- atomic manifest write uses unpredictable temp names and re-checks parent/symlink
  safety before replace
- build publish is staged transactionally and only replaces live artifacts when staged
  `verify_bundle` succeeds
- manifest artifact paths must be relative and cannot contain traversal (`..`)
- manifest artifact paths must use non-symlink path components (including directory aliases)
- unknown manifest fields are rejected
- full text does not appear in manifest; only `artifact_path` + hashes are recorded
- stale artifact directories under `<output>/pages` and `<output>/page_renders` are replaced on each build to keep deterministic outputs
- `locate` always recomputes passage hash from page bytes and ignores any caller hash input

## Validation invariants

- `bundle_id` must equal `paper-source-bundle-<bundle_digest[:16]>`
- `generated_at` must be canonical UTC (`...Z`)

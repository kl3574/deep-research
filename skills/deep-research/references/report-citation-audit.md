# ReportCitationAudit/v1

This workflow seals a bounded statement-to-source citation audit for a concrete report,
with deterministic projection, deterministic digest, and replay validation.

## Purpose

`ReportCitationAudit/v1` is a private, deterministic artifact used to prove that a
final report’s claim rows are bound to exact spans, exact evidence, and a replayed
projection of citation outcomes. It is not a synthesis output and must be validated
again before final report completion.

## Inputs

- Final report JSON.
- Draft report path (private binding target).
- Draft report raw SHA-256 pin.
- Final report raw SHA-256 pin.
- Evidence set JSON.
- Evidence set raw SHA-256 pin.

### Final report schema (`schema`: `ResearchReport/v1`)

```text
schema
schema_version
report_id
report_text
statement_rows[]:
  statement_id
  statement_text
  start_char
  end_char
  decision_impact  (high|medium|low)
  status           (decisive|qualified)
```

`statement_text` must be the exact `report_text[start_char:end_char]`.

### Evidence schema (`schema`: `ReportCitationSet/v1`)

```text
schema
schema_version
citations[]:
  citation_id
  statement_id
  source_id
  source_version
  source_access        (full_text|abstract_only|metadata_only)
  locator
  relation            (supports|contradicts|qualifies|not_tested)
  entailment          (entailed|partial|not_entailed|unknown)
  missing_qualifier
  source_role         (primary|secondary)
  counterevidence_status (represented|missing|not_required)
  evidence_path
  evidence_raw_sha256
```

Evidence rows must bind to ordinary files through absolute paths with no symlink
component and exact raw SHA-256. Hard-link identity checks prevent report, audit,
and evidence roles from aliasing the same inode.

## Sealing behavior

`python scripts/report_citation_audit.py seal ...`:

```text
python scripts/report_citation_audit.py seal \
  --final-report /abs/final.json --final-report-raw-sha256 <final_sha256> \
  --draft-report /abs/draft.json --draft-report-raw-sha256 <draft_sha256> \
  --evidence /abs/evidence.json --evidence-raw-sha256 <evidence_sha256> \
  --output /abs/audit.json
```

- loads all JSON with duplicate-key rejection;
- verifies draft/final pins match observed raw hashes;
- verifies evidence manifest pin matches observed raw SHA-256;
- rejects abstract-only decisive rows;
- allows metadata-only rows for orientation but never lets them close a
  decisive or qualified statement;
- requires at least one entailed primary full-text support or qualification for
  every statement that closes as `decisive` or `qualified`;
- forces a statement to `partial` while any supporting row retains a non-empty
  `missing_qualifier`;
- rejects overlapping statement spans and duplicates;
- scans forbidden credential keys recursively;
- rejects private path-shaped values outside the `private` compartment;
- computes per-statement audit outcome and deterministic projection;
- requires an existing absolute output parent with no symlink component;
- writes `ReportCitationAudit/v1` with 0600 mode using no-replace atomic
  publication, anonymous temporary inodes where supported, and a descriptor-
  identity-checked named-temp fallback otherwise.

## Validation behavior

`python scripts/report_citation_audit.py validate ...`:

```text
python scripts/report_citation_audit.py validate \
  --audit /abs/audit.json --audit-raw-sha256 <audit_sha256> \
  --final-report /abs/final.json --final-report-raw-sha256 <final_sha256> \
  --draft-report /abs/draft.json --draft-report-raw-sha256 <draft_sha256> \
  --evidence-raw-sha256 <evidence_sha256>
```

- requires external final/draft raw pins;
- requires external evidence manifest pin and external audit raw pin;
- replays final report and evidence rows from bound paths;
- recomputes exact projection and projection digest;
- compares stored audit digest, id, and replay projection;
- rejects stale/evidence-drift/self-drift artifacts.

## Optional run-ledger completion gate

Initialize a governed run with `research_run.py init --require-citation-audit`
when final completion must depend on this artifact. After sealing the audit,
start one `citation_audit` action and record the owner replay through the typed
command:

```text
python scripts/research_run.py --root /approved/workspace --run-id RUN \
  record-citation-audit --action-id ACTION \
  --audit /abs/audit.json --audit-raw-sha256 <audit_sha256> \
  --final-report /abs/final.json --final-report-raw-sha256 <final_sha256> \
  --draft-report /abs/draft.json --draft-report-raw-sha256 <draft_sha256> \
  --evidence-raw-sha256 <evidence_sha256>
```

The command appends exactly
`event:citation-audit:<ACTION>` only after owner replay returns
`overall_status=complete`. Finish that action with that exact event as its sole
artifact. Every later `status`, `validate`, and `finalize` reopens all bound files,
rechecks the external raw pins, and recomputes the projection. A missing,
partial, moved, or tampered audit fails closed. Runs created before this optional
contract field are interpreted as `require_citation_audit=false`.

## Required checks in downstream flow

- `overall_status == complete` before claiming complete citation closure.
- no path, path-like, or timestamp fields leak outside `private`.
- no credentials in report/evidence/audit payloads.

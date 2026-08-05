# PaperReadingDossier/v1 and v2 projection notes

## Scope

- Canonical, content-addressed deep-read dossier for source-rooted claims.
- Source evidence is validated against `PaperSourceBundle/v1` using `verify_bundle`,
  `locate_span`, and strict locator checks.
- The bundle binds externally supplied source bytes by digest and reopens them for
  verification. It does not copy, preserve, or archive the original source bytes.
- Outputs include claim-level evidence ids, cross-artifact consistency checks,
  execution-aware reconstruction tasks, and computed gate/audit fields.

## Required dossier top-level fields

- `schema`: fixed `PaperReadingDossier/v1`
- `schema_version`: fixed `v1`
- `producer`: fixed `learn-from-papers`
- `protocol_version`: fixed `1.0`
- `generated_at`: UTC timestamp ending in `Z`
- `request_question_plan` with:
  - `request_text`
  - `subquestions` (`subquestion_id`, `text`, `required`)
  - `abstention_conditions` (`subquestion_id`, `reason`)
- `source_bundle` with bundle id/digest and source binding
- `network_ref` (`network_id`, `snapshot_id`, `sha256`)
- `review_request_set_id`, `review_request_set_digest`, `review_request_id`, `review_request_digest`
- `review_source` (`source_id`, `source_digest`, `acquisition_locator`)
- `access_level`: `full_text|partial_text|abstract_only|metadata_only`
- `inspection_depth`: `map|evidence|reconstruction`
- `reconstruction_status`
- `embedded_documents`, `component_manifest`, `claims`, `evidence_records`,
  `reconstruction_tasks`, `correction_log`, `unresolved_terminal_states`
- each claim includes `verification`:
  - `mode`: `independent_source_check|same_context_diagnostic|expert_review`
  - `verifier_id`: non-empty string
- `verification` carries only `mode` and `verifier_id` in draft dossier
- Computed fields (regenerated): `claim_support_eligible`, `gates`,
  `completion_matrix`, `audit_metrics`, `dossier_id`, `dossier_digest`

## Core invariants

- Strictly reject unknown keys at all object levels.
- Evidence locators cannot be DOI-only or URL-only strings.
- Evidence locators are canonicalized from source spans and preserved in v2 exports.
- Discovery source provenance is preserved separately in top-level `review_source`; do not replace `source_ref` with discovery locator.
- Each evidence record is page-rooted (`page`, `start_char`, `end_char`) and span hash is
  recomputed from the private source bundle.
- Figure/equation cards may require rendered-page support; this is validated from
  bundle `rendered_pages`.
- Render-required central tables also require rendered-page evidence support.
- Reconstruction tasks are PaperBench-style and must not be marked as successful unless
  `executed=True`, `result=passed`, and `result_match=True`.
- Claims declare `claim_id`/`hypothesis_id`/`target_id` bindings and evidence references.
- `claim.scope` must exactly match every referenced evidence record scope.
- Draft `claim.verification` is only a requested mode/verifier declaration. It is
  not an attestation and cannot make a dossier projection eligible or decisive.
- `independent_source_check` and `expert_review` become protocol-eligible only
  after `finalize-attestations` reopens and validates a passed attestation that
  asserts a separate verifier context.
- `same_context_diagnostic`, failed, abstained, missing, and same-context
  attestations are non-decisive.
- `not_tested`/abstention paths can remain terminal when no evidence is supplied, with
  `claim_support_eligible=false` and projection coverage preserved.
- Verified claim/evidence citations must match the referenced evidence canonical locator
  and exact scope.
- A cross-field relation mismatch (`claim.relation` vs `evidence.relation`) is rejected;
  this is a structural contract and does not establish semantic entailment.
- Subquestion bookkeeping:
  - `required` is computed from required `request_question_plan.subquestions`.
  - `answered` counts any claim that carries that `subquestion_id` (including `not_tested` claims).
  - `abstained` counts required subquestions present in `abstention_conditions`.
  - `answered` and `abstained` sets for the same subquestion are rejected; unresolved overlap would make negative `unanswered`.
  - `unanswered = required - (answered ∪ abstained)` so it is never negative.

## Computed outputs

- `claim_support_eligible` is computed from verifier status, evidence quality, tasks,
  access level, inspection depth, verification mode, relation consistency, and task completion.
- `gates`, `completion_matrix`, `audit_metrics`, `claim_support_eligible`, and
  `unresolved_terminal_states` are recomputed (or compared against recomputation) and
  treated as immutable on validation.
- `unresolved_terminal_states` must exactly match canonical per-claim terminal state and reason.

## Projection to v2

Use `project-report-set` to emit:

- `PaperReadingReportSet/v2`
- `PaperReadingReport/v2` records
- Network/review/request/binding preservation, including `review_source`
- `hypothesis_id`, `target_id`, `claim_statement`, `scope`, `evidence_bindings`,
  evidence relation, and actual evidence locator.
- bundle/dossier/report-set id/digest, `source_ref`, `source_artifact_sha256`,
  and discovery `review_source` carried forward to each report.
- `verification` is copied from each projected claim into each report.
- report-set and each report require strict equality for inherited cross-document fields
  (`source_ref`, `source_artifact_sha256`, `review_source`).
- ordinary `project-report-set` output is noneligible and nondecisive even when
  the dossier has a structurally supported claim.
- only structurally supported claims with a finalized, passed, external
  attestation project as `projection_status = "decisive"`.
- non-eligible claims projected as `projection_status = "terminal_coverage"`.

Use `prepare-attestations` to emit request-backed projection:

- it emits one canonical `VerificationAttestationRequest/v1` JSON artifact per
  report under `verification-requests/<sha256>.json`
- the path digest is the SHA-256 of the exact canonical JSON-plus-newline bytes
- each request binds the frozen report subject, producer context, structural
  support candidate, claim/hypothesis/target/scope, complete evidence locators
  and spans, dossier, source bundle, source artifact, the complete network ref,
  normalized report-set context/completion state, and the expected unique report
  subject identities
- the report keeps a closed verification envelope containing only `mode`,
  `verifier_id`, `artifact_ref`, `artifact_sha256`, and `subject_digest`
- prepared reports remain `claim_support_eligible=false` and nondecisive; request
  artifacts never carry a verdict

Use `attest` to consume request artifacts and emit content-addressed
`VerificationAttestation/v1` artifacts. This command requires explicit:

- one `verifier-id` matching the request verifier identity
- one `verifier_context_id`
- one `basis`

Each attestation records the caller-asserted verdict and basis, request artifact
reference/hash, frozen bindings, `origin=external_verifier`, and both context
IDs. These are protocol fields, not authenticated identity or cryptographic
proof of who performed the review. `attest` rejects a verifier context string
equal to the producer context, which prevents accidental same-context reuse but
cannot prove real execution-context separation. It never defaults or
auto-selects `passed`.

For heterogeneous report sets, invoke `attest` once per request with
`--report-id`. Each invocation processes exactly one matching request and leaves
the other request or attestation bindings unchanged; chain the output into the
next invocation before finalization.

Use `finalize-attestations` to reopen both request and attestation artifacts,
verify their exact byte hashes, schemas, asserted origins, declared contexts,
verdicts, and report bindings, then recompute eligibility, projection status,
report IDs, and report-set identity deterministically. This establishes
protocol eligibility under the declared trust policy, not semantic correctness,
verifier identity, or external authentication. The frozen subject excludes only direct
top-level `report_id`, `report_digest`, `projection_status`, and
`claim_support_eligible`, plus direct nested verification `artifact_ref`,
`artifact_sha256`, and `subject_digest`; similarly named deeper fields are not
removed.

Artifact readers require the canonical
`verification-requests/<sha256>.json` or
`verification-attestations/<sha256>.json` name, use no-follow metadata/open
checks, and accept regular files only. Aliases, symlinks, FIFOs, sockets, and
devices are rejected.

`review_source` and acquisition locators are auditable document provenance, not
cryptographic paper identity. `decisive` means only protocol-eligible under the
declared trust policy. A finalized dossier report is still not accepted into a
research knowledge network: explicit RKN governance acceptance remains mandatory
before any graph mutation.

## Deep-understanding bridge from dossier

`PaperReadingDossier/v1` supports evidence reconstruction and claim-level governance.
For non-network handoff, generate `PaperUnderstanding/v1` from a validated understanding draft when route output is `evidence` or `reconstruction`.

Use `project-note-input` only when the deep-understanding object is complete:
- this is the dedicated command layer in `scripts/paper_understanding.py` (`create`, `validate`, `audit`, `project-note-input`);
- `project-note-input` is the only schema-safe path to `PaperUnderstandingNoteInput/v1`;
- `project-note-input` requires `source_binding.reading_depth != "map"`, resolved
  applicability, all five live artifact paths, and exact equality between the
  supplied validation record and deterministic live regeneration.

Run `project-note-input` only for downstream machines that explicitly ingest
`PaperUnderstandingNoteInput/v1`; do not replace these records with Markdown edits.

`map` readings can still produce dossier records and audit traces, but they remain
non-projectable to note-input and should be recorded as terminal coverage when used
as basis for downstream automation.

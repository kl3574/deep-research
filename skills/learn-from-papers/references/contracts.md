# Paper-reading machine contracts

The human-readable paper card and atom ledger remain the scientific record. These JSON contracts make source identity, span provenance, state, and handoffs independently checkable; they do not automatically decide whether prose entails a claim.

## Layers

| Layer | Contract | Authority |
| --- | --- | --- |
| Source | `PaperSourceBundle/v1` | Original bytes, extracted page artifacts, optional renders, tools, hashes, canonical spans |
| Reading | `PaperReadingDossier/v1` | Question plan, document coverage, scoped claims, evidence relations, cards, conflicts, reconstruction tasks, terminal unknowns |
| Handoff | `PaperReadingReportSet/v2` | Minimal content-addressed projection for a bound review request and knowledge-network controller |
| Deep-read handoff | `PaperUnderstanding/v1` | Detailed machine-consumable understanding for a specific route and later `PaperUnderstandingNoteInput/v1` projection |
| Deep-read validation | `PaperUnderstandingValidation/v1` | Content-addressed validator result bound to one exact understanding; source verification is explicit |
| Legacy | `PaperReadingReportSet/v1` | Historical audit only; never new decisive network evidence |

## `PaperUnderstanding/v1`

Core fields:

- `schema`: fixed `PaperUnderstanding/v1`
- `schema_version`: fixed `1.0`
- `producer`: fixed `learn-from-papers`
- `protocol_version`: fixed `1.0`
- `generated_at`: UTC timestamp ending in `Z`
- `research_retrieval_title`: must equal `适用：<applicability_short>｜结论：<conclusion_short>` from `executive_summary`
- `source_binding` with source identity, access and route:
  - `source_id`, `canonical_title`, `authors`, `year`, `venue`, `stable_identifier`, `publication_status`
  - `source_artifact_sha256`, `source_bundle_id`, `source_bundle_digest`
  - `reading_dossier_id`, `reading_dossier_digest`, `paper_card_ref`, `evidence_ledger_ref`
  - `agent_inferences_explicit`, `reading_depth`, `access_level`, `verified_at`
- `executive_summary`: `applicability_short`, `conclusion_short`, `summary`, `claim_ids`
- `applicability`, `workflow`, `mathematical_principles`, `algorithmic_principles`, `conclusion`
- `contributions`, `coverage`, `claims`
- `understanding_id`: `paper-understanding-<16-hex>` (generated)
- `understanding_digest`: 64-lowercase-hex content-addressed digest (generated)

Section and claim invariants:

- `claims` is non-empty and each claim has one of
  `supports`, `qualifies`, `refutes`, `not_tested`, one of
  `answered`/`terminal`, and confidence in `high|medium|low`.
- `coverage.understood_claims` and `coverage.terminal_claims` must partition the
  claim set and keep the same `claim_id` namespace.
- `applicability`, `workflow`, `conclusion`, `mathematical_principles`,
  `algorithmic_principles` keep strict section-level allowed keys and preserve
  claim-ID bindings.
- Workflow graph nodes are `input|intermediate|output` and carry
  `semantic_type`, `representation`, `format`, `shape`, and `unit`. Inputs are
  consumed only, intermediates are produced and consumed, and outputs are
  produced only; every node participates.
- Mathematical derivation steps carry `step_id`, `statement`, `depends_on`,
  `origin`, `locator`, and `evidence_ids`. Dependencies use closed
  `assumption:<text>`, `result:<text>`, or prior `step:<step_id>` references.
- Algorithm steps carry `step_id`, `action`, `depends_on`, `consumes`,
  `produces`, `origin`, `locator`, and `evidence_ids`; step dependencies may
  only point backward.
- Contribution `domain_refs` bind closed workflow, math, algorithm,
  applicability, or conclusion elements.
- Strict unknown keys are rejected at every object level.

Computed/output fields:

- `understanding_id` and `understanding_digest` are recomputed on identity-aware
  validation and must match the exact canonicalized object.
- `executive_summary.claim_ids`, all `*_principles.claim_ids`, `contributions[*].claim_ids`,
  and `conclusion.claim_ids` must each reference known claims.

## `PaperUnderstandingValidation/v1`

`validate` emits this record and optionally writes it with `--output`.

- Exact fields are `schema`, `schema_version`, `understanding_id`,
  `understanding_digest`, `validator_name`, `validator_version`, `status`,
  `source_binding_verified`, `checks`, `record_id`, and `record_digest`.
- Validator identity is `learn-from-papers.paper-understanding` version `1.0`;
  status is `passed`.
- Checks are ordered `closed_schema`, `content_address`, `cross_references`,
  and `source_binding`, each with `passed|not_checked` status.
- `source_binding_verified` is true only when a real source, source bundle, and
  `PaperReadingDossier/v1` are jointly validated and all IDs/digests match.
- `record_digest` is the canonical JSON SHA-256 excluding only `record_id` and
  `record_digest`; `record_id` is
  `paper-understanding-validation-<first-16-digest-hex>`.

## `PaperUnderstandingNoteInput/v1`

Produced only by `project-note-input` from a validated `PaperUnderstanding/v1`.

- `schema`: fixed `PaperUnderstandingNoteInput/v1`
- `understanding_binding` has exactly `understanding_id`,
  `understanding_digest`, `validation_record_id`, and
  `validation_record_digest`.
- Top-level domain sections include `executive_summary`, `applicability`,
  `workflow`, `mathematical_principles`, `algorithmic_principles`, `conclusion`,
  `contributions`, `coverage`, and `source_binding`.
- No top-level `claims` section exists; all claim material remains nested under
  `coverage.claims`.
- `applicability` and `workflow` keep route status in
  `applicable|not_applicable` form.
- `coverage.claims` includes all claims by sorted `claim_id`.
- `coverage.boundaries` records terminal claim reasons.
- Confidence values stay `high|medium|low` and are revalidated in the projection.
- Domain status, rationale, evidence IDs, and missing information remain
  explicit. Workflow graph metadata, structured math/algorithm steps, and
  contribution evidence/domain references are preserved.
- `source_binding` in note input is strict and omits disclosure-only fields.

Route rules:

- Projection fails if `source_binding.reading_depth == "map"`.
- Projection fails if unresolved terminal sections are projected into a note input.
- Projection requires a live source+bundle+dossier validation record with
  `source_binding_verified == true`; a caller-provided self-consistent digest
  cannot substitute for live verification.
- Executive-summary claim IDs are preserved exactly and each must be in
  understood coverage. Note-required applicability boundaries and workflow
  preconditions, steps, data flow, and step checks must be non-empty.

The projection is for internal machine handoff only and must not be treated as
full semantic replacement for prose judgment.

## `PaperSourceBundle/v1`

Build and verify it with `paper_source_bundle.py`. Evidence locators are recomputed from the verified page artifact and `(page, start_char, end_char)`; caller-provided hashes are never trusted. See [source-bundle.md](source-bundle.md).

## `PaperReadingDossier/v1`

Required domains:

- exact review-request and network snapshot bindings;
- question plan with required subquestions and abstention conditions;
- source-bundle ID, digest, source reference, and original artifact SHA-256;
- access, inspection, and reconstruction states kept separate;
- component manifest for main text and material artifacts;
- atomic claims bound to `hypothesis_id`, `target_id`, scope, relation, verifier status, and evidence IDs;
- evidence records bound to canonical page/character spans, typed visual/equation cards, and reconstruction tasks;
- correction log and explicit terminal unresolved states.

Computed fields, digests, IDs, completion matrices, and eligibility gates are regenerated. A fully unanswerable read is valid when required questions are explicitly abstained and all claims remain `not_tested`; it must project as terminal coverage, not support.

## `PaperReadingReportSet/v2`

The projection preserves the dossier ID/digest, network and review-request bindings, source-bundle ID/digest, source artifact SHA-256, access/inspection/reconstruction status, and completion matrix. Each claim report carries:

- report ID/digest and dossier binding;
- hypothesis, target, atomic statement, and complete scope;
- `supports | qualifies | refutes | not_tested`;
- computed claim-support eligibility and decisive/terminal status;
- source-rooted evidence bindings with evidence ID, canonical locator, page/offsets, span ID, and span hash.

Only a decisive, eligible `supports` report can support a patch proposal. `refutes` maps to contrary evidence; `qualifies` and `not_tested` remain non-supporting. A discovery DOI/URL is an acquisition locator and must never replace the source passage locator in network provenance.

## Trust boundary

Validation proves closed schemas, exact content digests, ID derivation, source/bundle linkage, locator integrity, cross-record bindings, and honest execution states. It does not prove author identity, source authenticity beyond the supplied bytes, semantic entailment, correctness of an OCR/parser, or successful scientific replication. Those require identity checks, render inspection, independent relation verification, and task-specific evaluation.

## Failure policy

Fail closed on unknown fields, symlinks/path traversal, stale or missing artifacts,
non-UTC timestamps, digest/ID mismatch, source tampering, locator laundering,
claim/evidence relation mismatch, scope mismatch, false execution state,
missing required render, broken request/network binding, route-ineligible
projection (for example `map` depth), or caller-supplied outcome inconsistent
with the v2 relation.

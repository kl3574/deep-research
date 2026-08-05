# PaperUnderstanding layer and note-input projection

`PaperUnderstanding/v1` is the deep, non-network handoff object for evidence-grade reading routes.

## Role

- Produce a strict, content-addressed understanding artifact for `evidence` and `reconstruction` routes.
- Keep claim structure, assumptions, and section bindings together with stable source/bundle identity.
- Emit a compact machine-consumable projection only through `project-note-input`.
- Bind every projection to a content-addressed
  `PaperUnderstandingValidation/v1` record produced from live source, bundle,
  and dossier verification.
- Avoid replacing this projection with hand-edited Markdown or ad-hoc templates.

## Required contracts

- `PaperUnderstanding/v1` schema:
  - top-level keys include `schema`, `schema_version`, `producer`, `protocol_version`, `generated_at`,
    `research_retrieval_title`, `source_binding`, `executive_summary`, `applicability`,
    `workflow`, `mathematical_principles`, `algorithmic_principles`, `conclusion`,
    `contributions`, `coverage`, `claims`, `understanding_id`, `understanding_digest`.
- `applicability.status`, `workflow.status`, `mathematical_principles.status`,
  `algorithmic_principles.status`, and `conclusion.status` are `answered`,
  `not_applicable`, or `unresolved`.
- `claims` entries must include:
  - `claim_id`, `hypothesis_id`, `target_id`, `statement`, `relation`, `nature`,
    `scope`, `evidence`, `evidence_ids`, `verifier_status`,
    `confidence` (`high|medium|low`), and `status` (`answered|terminal`).
- `source_binding` must carry source identity, artifact binding, and inspection context:
  - `source_id`, `canonical_title`, `authors`, `year`, `venue`, `stable_identifier`,
    `publication_status`, `source_artifact_sha256`, `source_bundle_id`,
    `source_bundle_digest`, `reading_dossier_id`, `reading_dossier_digest`,
    `paper_card_ref`, `evidence_ledger_ref`, `agent_inferences_explicit`,
    `reading_depth`, `access_level`, `verified_at`.
- Strict unknown keys are rejected at all object levels.
- `understanding_id = paper-understanding-<16-hex>`.
- `understanding_digest` is a canonicalized content SHA-256 and is validated as content-addressed.
- Workflow graph node/operation structure, mathematical derivation dependencies,
  algorithm step order, and contribution domain references follow the strict
  invariants in [contracts.md](contracts.md).
- Live validation builds its evidence registry only from the revalidated
  `PaperReadingDossier/v1`. Understanding claim fields and evidence IDs must
  exactly match dossier claim/evidence bindings; an evidence-row `summary` is
  the exact bound dossier claim statement and `locator` is the canonical
  source-rooted dossier locator. Domain, contribution, math, and algorithm
  evidence references must resolve in that registry.
- Draft generators must project claim `statement`, `scope`, `confidence`,
  `verifier_status`, and evidence IDs from the authoritative dossier. Never
  hard-code `medium`, same-context rationale, or a passed status after the
  dossier has changed verification state.
- Each evidence row carries exactly one locator copied verbatim from the
  validated dossier. Do not concatenate several valid locators into a new
  bracketed string; use several evidence rows instead. When a printed equation,
  theorem, figure, or table controls the claim, bind that exact object locator,
  not only its surrounding section.
- Every material workflow datum has `semantic_type`, `representation`,
  `format`, `shape`, and `unit`. If the paper genuinely omits one value, use an
  explicit `unreported` value and bind that exact omission in
  `workflow.missing_information`; never guess a file format or numeric setting.
- Repeat each unresolved setting explicitly in the domain that consumes it.
  Do not use ranges such as `missing-004 through missing-014` as a substitute
  for machine-readable missing-information content.

## CLI workflow

From the repository's `skills/learn-from-papers` directory:

```bash
python scripts/paper_understanding.py create \
  --input /abs/path/understanding-draft.json \
  --bundle /abs/path/paper-source-bundle.json \
  --source /abs/path/paper.pdf \
  --dossier /abs/path/reading-dossier.json \
  --output /abs/path/understanding.json

python scripts/paper_understanding.py validate \
  --input /abs/path/understanding.json \
  --bundle /abs/path/paper-source-bundle.json \
  --source /abs/path/paper.pdf \
  --dossier /abs/path/reading-dossier.json \
  --output /abs/path/understanding-validation.json

python scripts/paper_understanding.py audit \
  --input /abs/path/understanding.json \
  --bundle /abs/path/paper-source-bundle.json \
  --source /abs/path/paper.pdf \
  --dossier /abs/path/reading-dossier.json
```

Projection to machine input:

```bash
python scripts/paper_understanding.py project-note-input \
  --understanding /abs/path/understanding.json \
  --validation-record /abs/path/understanding-validation.json \
  --output /abs/path/note-input.json \
  --source-bundle /abs/path/paper-source-bundle.json \
  --source /abs/path/paper.pdf \
  --dossier /abs/path/reading-dossier.json
```

`--shadow-root` and `--audit-root` are opt-in. With neither flag, the command
writes no copies. All requested outputs are preflighted and committed together
as private `0600` files; any failure rolls back the set.
All output paths are required to be absolute. Normalize them in an orchestrator
before invoking `create`, `validate`, or `project-note-input`; a relative path is
a contract failure, not an invitation to retry in an arbitrary working directory.

## `project-note-input` rules

- `map` depth is rejected. Only `evidence` and `reconstruction` are accepted.
- unresolved domain status is rejected and is never coerced to
  `not_applicable`.
- live source, source-bundle, and dossier validation is mandatory; all three
  paths must be supplied together and must match the understanding binding.
- the supplied validation record is reopened, normalized, regenerated from the
  live artifacts, and compared as an exact object. True flags, IDs, and digests
  supplied by the caller are not proof.
- projection requires at least one `coverage.understood_claims` entry.
- every `executive_summary.claim_ids` entry must be understood and the list is
  preserved exactly.
- `does_not_apply_when`, workflow preconditions/steps/data flow, and every
  workflow step's checks must be non-empty.
- projection returns `PaperUnderstandingNoteInput/v1` with these top-level sections:
  - `schema`, `understanding_binding`, `executive_summary`, `applicability`, `workflow`, `mathematical_principles`,
    `algorithmic_principles`, `conclusion`, `contributions`, `coverage`, `source_binding`.
- coverage includes:
  - all `claims` sorted by `claim_id`,
  - `boundaries` for terminal claims,
  - `access_level`, `reading_depth`, `verified_at`.
- `verifier_status` and `nature` remain explicit on claim objects for downstream auditing.
- domain status/rationale/evidence/missing-information, workflow graph data,
  structured math and algorithm steps, and contribution refs remain explicit.

## Failure handling

- keep projection failures as hard failures from the command.
- do not auto-cast outputs across paths (`schema`/fields) or rename outputs without rerunning the command.
- treat `PaperUnderstanding/v1` projection output as a machine artifact, not a semantic proof.

# Retrospective artifact contracts

The helper uses standard-library Python only. It never invokes a model, network,
browser, shell command, research owner, or mutation path.

## `ResearchWorkflowEvidenceBundle/v1`

Required top-level fields:

```json
{
  "schema": "ResearchWorkflowEvidenceBundle/v1",
  "run_id": "stable-run-id",
  "as_of": "2026-08-13T12:00:00Z",
  "scope": "What run and improvement decision are reviewed",
  "stage_order": ["alignment", "collection", "appraisal", "publication"],
  "run_ref": {
    "path": "/absolute/private/run.json",
    "sha256": "64-lowercase-hex"
  },
  "incidents": [],
  "external_design_refs": []
}
```

`stage_order` is the causal workflow order used to compute escape distance. It
does not need to match the deep-research scenario pipeline, but every incident's
`earliest_detectable_stage` must occur no later than its `detected_stage`.

`run_ref` and every `evidence_ref` must point to an absolute ordinary file. No
path component may be a symlink. The validator opens each leaf once with
`O_NOFOLLOW`, compares `lstat`/descriptor identity, and verifies stable descriptor
metadata through EOF. The review stores paths and hashes under its `private`
compartment, never evidence file contents.

Each incident contains:

```json
{
  "incident_key": "locator-source-alignment",
  "title": "Source reference failed at binding",
  "observation": "What happened, without a proposed explanation",
  "impact": "high",
  "recurrence": "repeated",
  "classification": "contract_seam",
  "owner_skill": "evidence-appraisal",
  "detected_stage": "binding",
  "earliest_detectable_stage": "appraisal_prepare",
  "reproducibility": "reproduced",
  "one_off": false,
  "evidence_refs": [
    {"path": "/absolute/private/audit.json", "sha256": "64-lowercase-hex"}
  ],
  "proposed_change": {
    "kind": "owner_contract",
    "target": "Evidence locator validation",
    "seam": "EvidenceLocatorRef/v1",
    "acceptance_tests": ["Owner A output is accepted unchanged by owner B"],
    "negative_tests": ["Same basename with a different content hash is rejected"],
    "non_goals": ["Do not weaken owner replay"]
  }
}
```

Enums:

- `impact`: `high | medium | low`
- `recurrence`: `repeated | once | potential`
- `classification`: `contract_seam | implementation_bug | workflow_state |
  coordination | presentation | operational_delivery | one_off_environment`
- `reproducibility`: `reproduced | not_reproduced | not_applicable`
- change `kind`: `owner_contract | shared_contract | orchestration_contract |
  new_skill | tests_only | docs_only | local_repair | no_change`

The same normalized `(owner_skill, classification, seam)` may appear only once.
Consolidate repeated symptoms into one incident with multiple evidence refs.
Evidence references are unique by canonical `(absolute path, raw SHA-256)` pair;
distinct deterministic replay files may therefore share the same byte hash.

An optional external design reference contains `title`, an `https` `url`,
`retrieved_at`, `evidence_level`, `claim`, and `use`. Evidence levels are
`official_documentation`, `official_engineering`, `primary_research`, or
`owner_repository`. These references motivate a design; they do not prove a
local incident or a local fix.

Credential-shaped keys and values are rejected. Do not put tokens, cookies,
authorization headers, private keys, source full text, note bodies, or browser
session data in either artifact.

## `ResearchWorkflowReview/v1`

The output binds the input bundle and its evidence. It contains deterministic
ranked issues, counts, design references, and a content digest.

`private.bundle_ref`, `private.run_ref`, and
`private.evidence_refs[incident_key][]` retain the canonical absolute authority
paths and raw hashes. These bindings participate in `review_digest`; callers that
need a public projection must remove the whole `private` compartment and must not
present that projection as a replayable authority artifact.

Priority is derived, not supplied:

```text
score = impact(3/2/1)
      + recurrence(repeated=2, potential=1, once=0)
      + reproducibility(reproduced=2, not_applicable=1, not_reproduced=0)
      + min(escape_distance, 3)
      - 3 when one_off=true

P0 >= 8; P1 >= 5; otherwise P2
```

`implementation_readiness=ready` requires a generalized, reproduced or
not-applicable incident, a non-empty target and seam, and both acceptance and
negative tests. Other values are `needs_reproduction`, `needs_tests`, and
`one_off_local`. A proposed change whose kind is `no_change` has readiness
`no_change`; it records an intentionally bounded non-action rather than an
implementation-ready recommendation.

The derived priority is triage only. It never authorizes a code change and never
overrides scientific impact or an owner contract.

`review_digest` is SHA-256 of canonical UTF-8 JSON after removing
`review_id` and `review_digest`. `review_id` is
`research-workflow-review-<first 16 hex>`.

## Output and replay rules

- `build` and `validate` reject duplicate JSON keys and require caller-provided
  external raw-file pins; a self-reported digest is never its own trust anchor.
- `build` rejects an existing output instead of overwriting it.
- The output parent must already exist; the helper writes a same-directory
  mode-0600 temporary file, fsyncs it, and atomically publishes it.
- `validate` reloads the original bundle from the bound path, rechecks its raw
  hash and every evidence file, rebuilds the review, and requires exact equality.
- A moved bundle needs a fresh review because the absolute authority path is part
  of the binding. Evidence content may not be silently substituted.

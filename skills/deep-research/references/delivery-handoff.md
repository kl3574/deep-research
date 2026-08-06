# Research and delivery handoff

Use this contract when one request combines cross-source research with document
acquisition, structured notes, or Zotero delivery. It prevents research completion
from being mistaken for delivery completion.

## Preflight order

1. Record the research contract and requested deliverables.
2. If Zotero is in scope, inventory the exact target read-only before web search:
   parents, identifiers, versions, attachments, notes, and collection membership.
3. Build and validate a [KnowledgeNetwork/v1](knowledge-network.md) snapshot from
   that corpus. Derive external searches from missing, conflicting, stale, or
   low-confidence relations.
4. Classify sources as Tier A, B, or C.
5. Enumerate every acquisition/Zotero operation and at least two independent
   support paths when two exist. Probe without mutation.
6. Confirm target and batch authorization separately from research authorization.
7. Complete one golden bundle end to end before fan-out.

If two paths for a required operation are `failed` or `unavailable` and no path
is `available`, the operation and aggregate delivery status are
`blocked_capability`. Do not keep trying undocumented mutation routes.

## Reading tiers

| Tier | Role | Minimum evidence |
| --- | --- | --- |
| A | Decision-critical source | `$learn-from-papers` paper card, evidence ledger, full-text inspection, and passed exact-locator audit |
| B | Supporting or benchmark source | Full-text evidence-depth inspection and exact locators for every used claim |
| C | Orientation/discovery | Identity and access status; cannot support a decisive claim |

## Rich paper-understanding route

Deep research orchestrates, but does not reinterpret, a rich one-paper result.
Use a separate `PaperUnderstandingRoute/v1` sidecar that binds:

- `understanding_binding` containing content-derived understanding and
  `PaperUnderstandingValidation/v1` record IDs/digests;
- the `UnderstandingNetworkProjection/v1` ID/digest;
- a content-addressed `PaperUnderstandingRouteValidationBinding/v1` that repeats
  and jointly binds the validation record, understanding, and projection
  identities;
- only `research-knowledge-network` and/or `network-gap-discovery` as
  destinations;
- `orchestration_only: true` and `semantic_rewrite_allowed: false`.

The route digest covers every field except its derived ID/digest, and the ID is
`understanding-route-<digest[:16]>`. Validate it with:

```bash
python3 scripts/paper_understanding_route.py --input paper-understanding-route.json
```

Do not send the underlying five-domain payload to `$scholar-discovery`.
`$network-gap-discovery` may issue a typed missing-detail gap, and only that gap
is compiled into targeted discovery queries.

## ResearchHandoff/v1

The handoff is private JSON with this shape:

```json
{
  "schema": "ResearchHandoff/v1",
  "run_id": "stable-run-id",
  "task_modes": ["research", "acquisition", "zotero"],
  "privacy": {
    "classification": "private",
    "public_export": "redacted_only"
  },
  "research": {
    "status": "complete",
    "contract_ref": "run:contract",
    "coverage_audit_ref": "run:coverage"
  },
  "knowledge_network": {
    "schema": "KnowledgeNetwork/v1",
    "snapshot_id": "network-snapshot-01",
    "path": "/private/run/network.json",
    "sha256": "<64 lowercase hex>"
  },
  "preflight": {
    "completed": true,
    "zotero_corpus_first": true,
    "golden_bundle": {
      "item_id": "SRC-001",
      "status": "passed",
      "bundle_ref": "bundle:SRC-001",
      "validation_ref": "validation:SRC-001"
    }
  },
  "items": [
    {
      "item_id": "SRC-001",
      "source_id": "source:SRC-001",
      "evidence_role": "decisive",
      "reading_tier": "A",
      "learn_from_papers": {
        "paper_card_ref": "paper-card:SRC-001",
        "evidence_ledger_ref": "evidence-ledger:SRC-001",
        "locator_audit_ref": "locator-audit:SRC-001",
        "locator_audit_status": "passed"
      },
      "attachments": [
        {
          "attachment_id": "ATT-001",
          "role": "main_text",
          "source_kind": "version_of_record_main",
          "path": "/private/run/SRC-001.pdf",
          "sha256": "<64 lowercase hex>"
        }
      ],
      "benchmark_use": true,
      "benchmark_ids": ["BENCH-001"]
    }
  ],
  "benchmark_profile_required": true,
  "benchmarks": [
    {
      "schema": "BenchmarkProfile/v1",
      "benchmark_id": "BENCH-001",
      "name": "Lotka-Volterra protocol A",
      "task_modes": ["support_recovery", "fixed_support_calibration"],
      "model": {
        "equations_or_model_ref": "claim:MODEL-001",
        "candidate_library": "constant, linear, and quadratic monomials",
        "ground_truth": "claim:SUPPORT-001",
        "parameters": "source:SRC-001 | PDF p.4 | Table 1",
        "initial_conditions": "source:SRC-001 | PDF p.5 | Experiment setup",
        "inputs_or_perturbations": "none"
      },
      "observation_protocol": {
        "observed_states": "both states",
        "inputs_or_perturbations": "none",
        "noise": "additive Gaussian measurement noise, source-defined scale",
        "sampling": "source-defined uniform grid and horizon",
        "trajectories": "source-defined initial-condition groups"
      },
      "evaluation": {
        "split": "held-out complete trajectories",
        "metrics": ["support TP/FP/FN", "parameter error", "forward error"],
        "equivalence_rule": "exact support"
      },
      "failure_boundaries": [
        "candidate library omission",
        "insufficient excitation from one initial condition"
      ],
      "evidence": {
        "source_claim_refs": ["claim:MODEL-001", "claim:SUPPORT-001"],
        "exact_locators": [
          "source:SRC-001 | PDF p.4 | Eq. (7)",
          "source:SRC-001 | PDF p.5 | Experiment setup"
        ]
      }
    }
  ],
  "request": {
    "requirements": [
      {
        "requirement_id": "REQ-001",
        "required": true,
        "item_ids": ["SRC-001"],
        "operations": [
          "research_note",
          "benchmark_card",
          "acquire_main_text",
          "zotero_note"
        ]
      }
    ]
  },
  "delivery": {
    "status": "complete",
    "authorization": {
      "target_approved": true,
      "batch_approved": true,
      "approval_ref": "private:approval",
      "target_ref": "private:zotero-target"
    },
    "capability_matrix": [
      {
        "operation": "acquire_main_text",
        "required": true,
        "status": "available",
        "paths": [
          {
            "path_id": "publisher",
            "status": "available",
            "evidence_ref": "probe:publisher"
          },
          {
            "path_id": "institutional-repository",
            "status": "unknown",
            "evidence_ref": "probe:repository"
          }
        ]
      },
      {
        "operation": "zotero_note",
        "required": true,
        "status": "available",
        "paths": [
          {
            "path_id": "desktop-transaction",
            "status": "available",
            "evidence_ref": "probe:desktop"
          },
          {
            "path_id": "web-api",
            "status": "unknown",
            "evidence_ref": "probe:web"
          }
        ]
      }
    ],
    "curation_batches": [
      {
        "batch_id": "CUR-001",
        "manifest_path": "/private/run/curation.json",
        "sha256": "<64 lowercase hex>",
        "visibility": "private",
        "target_ref": "private:zotero-target"
      }
    ],
    "completion_matrix": [
      {
        "requirement_id": "REQ-001",
        "item_id": "SRC-001",
        "operation": "research_note",
        "status": "complete",
        "evidence_refs": ["paper-card:SRC-001", "locator-audit:SRC-001"]
      },
      {
        "requirement_id": "REQ-001",
        "item_id": "SRC-001",
        "operation": "benchmark_card",
        "status": "complete",
        "evidence_refs": ["benchmark:BENCH-001"]
      },
      {
        "requirement_id": "REQ-001",
        "item_id": "SRC-001",
        "operation": "acquire_main_text",
        "status": "complete",
        "evidence_refs": ["attachment:ATT-001"]
      },
      {
        "requirement_id": "REQ-001",
        "item_id": "SRC-001",
        "operation": "zotero_note",
        "status": "complete",
        "evidence_refs": ["readback:note"]
      }
    ]
  }
}
```

Allowed research states are `complete`, `partial`, and `blocked`. Allowed
delivery states are `not_requested`, `preflight`, `ready`, `partial`,
`complete`, `blocked_capability`, `blocked_authorization`, and `failed`.
They are independent.

Every required requirement expands to one completion row for each
`item_id x operation` pair. A `complete` delivery requires every required row
to be `complete`. Partial, failed, or blocked rows retain a concrete blocker and
evidence or next-action reference.

## Attachment roles

Use these exact role/source-kind pairs:

| role | source_kind |
| --- | --- |
| `main_text` | `version_of_record_main` |
| `accepted_manuscript` | `accepted_manuscript_main` |
| `preprint` | `preprint_main` |
| `supplement` | `supplementary_information` |
| `metadata_only` | `metadata_only` |

A supporting-information PDF never satisfies `acquire_main_text` and must not be
counted as a main-text attachment.

## CurationBatch references

`curation_batches` contains immutable references to manifests produced by
`$curate-research-to-zotero`. The handoff records the actual manifest path and
SHA-256; validation reads the file and recomputes the digest. Do not copy the
private manifest into a public report.

## Private/public boundary

The full handoff, network snapshot, Zotero target identifiers, local paths,
notes, PDFs, approval evidence, and CurationBatch manifests are private. A public
export may contain only redacted aggregate counts, public bibliographic
identities, bounded findings, and public source links. It must not expose group
IDs, collection keys, item keys, local paths, note contents, file hashes tied to
private holdings, or credentials.

Validate with:

```bash
python scripts/validate_research_handoff.py /private/run/handoff.json
```

## Clean Zotero note handoff

Keep formula order and raw LaTeX, evidence locators, and content-relevant
limitations in the semantic handoff. Keep hashes, paths, timestamps, run and
transaction state in private state artifacts. Route note HTML projection and
validation to `$curate-research-to-zotero`, then route the reviewed mutation to
`$zotero-declarative-bridge`; do not duplicate either contract here.

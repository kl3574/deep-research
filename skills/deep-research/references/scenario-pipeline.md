# Compound research scenario pipeline

Use this controller only for a compound run that crosses discovery, acquisition,
paper understanding, Zotero curation, knowledge-network maintenance, and
publication. It coordinates content-addressed stage state; it does not browse,
interpret a paper, mutate Zotero, apply a network patch, or publish by itself.

## Why it exists

A metadata-only Zotero snapshot can seed source identities, but it cannot seed
domain semantics. A missing coverage dimension such as `validation_target` is a
local structural gap, not a scholarly query. Sending `network dimension
validation_target` to Crossref produces unrelated records. The pipeline therefore
separates two phases:

1. compile domain-grounded `topic_needs` from the research question and
   competency questions;
2. after reviewed evidence has populated the network, run open-world network-gap
   discovery for semantic nodes, relations, boundaries, conflicts, and evidence.

`network-gap-discovery` keeps derived missing-dimension gaps `structural_only`.
`scholar-discovery compile-topic` requires every query to contain an explicit
`criteria.must` domain anchor and rejects internal field names and placeholder
queries.

## Scenario contract

`ResearchScenario/v1` contains:

- question, decision/use, scope, exclusions, currentness, and risk;
- exact Zotero group, library name, collection key, and collection path;
- promised knowledge dimensions;
- bounded semantic topic needs, each with confirm/refute queries;
- automatic API providers and the manual Google Scholar policy.

Do not place tokens, cookies, passwords, authorization headers, private note
bodies, or source text in the scenario. The controller rejects credential-shaped
fields. Keep scenario and execution artifacts in the authorized private research
workspace, not this public repository.

## Commands

```bash
python scripts/research_pipeline.py init \
  --scenario /private/scenario.json \
  --as-of 2026-08-05T00:00:00Z \
  --output /private/pipeline-00.json

python scripts/research_pipeline.py compile-topic \
  --scenario /private/scenario.json \
  --network /private/network.json \
  --as-of 2026-08-05T00:00:00Z \
  --output /private/topic-requests.json

python scripts/research_pipeline.py record-stage \
  --execution /private/pipeline-00.json \
  --stage zotero_baseline \
  --status completed \
  --artifact /private/zotero-before.json \
  --reason "Exact group and collection read back" \
  --as-of 2026-08-05T00:10:00Z \
  --output /private/pipeline-01.json
```

Every completed or partial stage requires at least one regular-file artifact and
binds its absolute path, byte size, and SHA-256. Each state is immutable: write
the next state to a new path. `status` returns ready, active, blocked, partial,
completed, and terminal-stage counts.

`completed` means both that the bounded stage action terminated and that its
promised stage coverage is complete. `partial` means the action terminated with
usable handoff artifacts but provider, route, budget, or another declared
coverage branch remains incomplete. A partial dependency may feed bounded
downstream work, but it keeps `coverage_complete=false`,
`can_finalize_complete=false`, and the final pipeline outcome partial even when
all stage actions are terminal. `blocked` is terminal for the current attempt but
does not satisfy a downstream dependency.

## Explicit legacy migration

Executions created before `source_normalization` have an exact nine-stage legacy
shape. `validate` verifies their original content digest and returns a structured
`ResearchPipelineDiagnostic/v1` with `code=migration_required`; it does not
silently reinterpret them. `record-stage` rejects the same legacy state.

Migrate into a new immutable path:

```bash
python scripts/research_pipeline.py migrate \
  --input /private/pipeline-04.json \
  --as-of 2026-08-05T13:00:00Z \
  --output /private/pipeline-05-migrated.json
```

`migrate` accepts only the exact pre-normalization stage order and dependencies,
revalidates the legacy state digest, and reopens every bound artifact to verify
path, size, and SHA-256. It preserves all legacy statuses, artifact bindings, and
history; updates only the understanding dependency; inserts
`source_normalization` as `pending` by default with reason
`normalization evidence required`; and appends a content-addressed
`ResearchPipelineMigration/v1` provenance record. Use `--inserted-status blocked`
only when normalization evidence cannot currently be produced. Never overwrite
the legacy execution or use migration to fabricate normalization completion.

## Stage authority

| Stage | Owning capability | Completion evidence |
| --- | --- | --- |
| `zotero_baseline` | curator | exact target snapshot and child inventory |
| `network_seed` | RKN | validated network export plus semantic scenario seed |
| `topic_discovery` | scholar discovery | validated request/result sets; `completed` only when every represented result is `complete_bounded` and there are no request failures, otherwise `partial` |
| `source_acquisition` | source acquisition | PDF identity, access route, hash, or explicit failure |
| `source_normalization` | scholarly document normalization | validated quality records plus derivative lineage, or a `native_ok` quality artifact as explicit skip evidence |
| `paper_understanding` | learn from papers | validated understanding/dossier/source bindings |
| `zotero_curation` | curator | per-item write and readback evidence |
| `network_merge` | RKN | accepted patch and fresh validated export |
| `gap_cycle` | gap discovery | terminal or explicitly unresolved prioritized gaps |
| `network_publish` | network publisher | validated privacy-mode HTML |

Google Scholar remains a manual export route. Provider preflight reports whether
OpenAlex is configured, whether Semantic Scholar is using anonymous rate limits,
and whether a Scholar artifact is required. It never prints credential values.

`source_normalization` is operationally optional but never implicit. It depends
on completed acquisition. When every acquired raw PDF is `native_ok`, complete
the stage with the validated `ScholarlyDocumentQuality/v1` artifacts and a reason
stating that derivative generation was skipped. Otherwise bind both the quality
artifact and validated normalization lineage. `paper_understanding` depends on
both acquisition and normalization state so an OCR substitution cannot silently
replace the acquired source.

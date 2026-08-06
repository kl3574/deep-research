---
name: deep-research
description: Use when a task needs auditable multi-source research, field mapping, route comparison, or conflict resolution. Route one-paper reading, Zotero curation, and graph maintenance elsewhere.
---

# Deep Research

Own cross-source investigation and synthesis. Record the question and use,
subquestions, scope/exclusions, currentness, risk, assumptions, and promised
coverage. Never call targeted, rapid, or orientation work systematic; that
requires a prespecified protocol.

## Core loop

Run `scope -> map -> gap -> discover -> inspect -> extract -> countercheck ->
merge -> citation audit -> stop or continue`. Each action must close a named gap
or improve a decision-critical claim. Compare only aligned routes. Use
[research-decomposition.md](references/research-decomposition.md) for mapping and
[execution-loop.md](references/execution-loop.md) for controller, parallelism,
failure, budget, and untrusted-content rules.

Maintain source identity/version/status, exact locators, atomic claim/evidence
relations, conflicts, search provenance, and limits. Orient with reviews; support
decisive academic claims with applicable primary full text. Treat metadata,
abstracts, snippets, roadmaps, issues, and AI summaries as discovery only. Apply
the gates in [source-routing.md](references/source-routing.md) and
[evidence-synthesis.md](references/evidence-synthesis.md). Seek nulls, failures,
counterexamples, corrections, exclusions, alternatives, and incompatible
versions. Explain conflicts; never vote them away.

## Conditional routes

- For a compound real-world run, initialize `ResearchScenario/v1` with
  `scripts/research_pipeline.py` and keep each stage in a new immutable
  `ResearchPipelineExecution/v1` state. Use
  [scenario-pipeline.md](references/scenario-pipeline.md). Do not send a raw
  missing-dimension field name to scholarly search: compile initial queries from
  competency-question-backed semantic `topic_needs`, then run network gap discovery
  only after reviewed evidence has populated the graph.

- Send one decision-critical paper at a time to `$learn-from-papers`; Tier B
  supporting papers still need full-text locators, while Tier C orientation
  cannot carry decisive claims. Pass Tier A an epistemic task with target,
  subquestions, scope, falsifiers, acceptance criteria, required components, and
  inspection depth.
- Route a completed rich reading only as a verified, content-addressed
  `PaperUnderstanding/v1` plus an `UnderstandingNetworkProjection/v1` adapter.
  Record that routing in `PaperUnderstandingRoute/v1`; never copy, repair,
  summarize, or revalidate the five semantic domains inside this orchestrator.
- If a compatible knowledge network is supplied or requested, audit it first,
  then use `$network-gap-discovery` for falsifiable open-world gap hypotheses and
  `$scholar-discovery` for bounded candidate discovery. Otherwise run a bounded
  field study without inventing a network.
- Google Scholar is manual-only: generate bounded queries and ingest only a
  user-supplied export. Never scrape Scholar HTML, bypass robots or CAPTCHA, or
  relabel API results as Scholar results. Autonomous discovery uses documented
  scholarly APIs and reports provider/coverage limits.
- In a compound pipeline, do not equate terminated discovery actions with full
  provider/route coverage. Bind the validated result set: record
  `topic_discovery=completed` only for all-`complete_bounded` results without
  request failures; record usable incomplete results as `partial`. Partial stages
  may feed bounded downstream work but can never enable complete finalization.
- Route accepted candidate identities to `$scholarly-source-acquisition` for a
  legal, hash-verified full-text attempt. Before `$learn-from-papers`, route each
  acquired local PDF through `$scholarly-document-normalization`: a validated
  `native_ok` quality artifact is explicit skip evidence; any OCR/searchable-PDF
  derivative must retain original/derivative lineage and `review_required`.
  Route a
  validated final network to `$research-network-publish` for privacy-safe HTML;
  neither companion owns evidence acceptance, graph mutation, or Zotero writes.
- If acquisition, notes, or Zotero delivery is requested, run the read-only
  preflight in [delivery-handoff.md](references/delivery-handoff.md). Inventory
  the exact Zotero target before searching, validate one golden bundle before
  fan-out, and keep `research_status` separate from `delivery_status`. Two failed
  or unavailable delivery paths with no success yield `blocked_capability`, not
  a fabricated completion.

For Tier A machine handoff, require a verified `PaperSourceBundle/v1`, audited
`PaperReadingDossier/v1`, and `PaperReadingReportSet/v2`. The v2 relation and
attestation fields are protocol records, not semantic truth or authenticated
verifier identity. A `decisive` projection is only eligible under its declared
trust policy. Never relabel `refutes`, `qualifies`, or `not_tested` as support,
and never mutate a research knowledge network without its explicit governance
acceptance.

When rich understanding is requested, additionally require the upstream
`PaperUnderstanding/v1` ID/digest, its content-derived
`PaperUnderstandingValidation/v1` record ID/digest, and the projection adapter
ID/digest. Validate only their route envelope with
`scripts/paper_understanding_route.py`; `$learn-from-papers` remains the sole
semantic validator and `$research-knowledge-network` remains the projection
consumer.

## State, stop, and delivery

With an authorized durable workspace, use [run-state.md](references/run-state.md);
otherwise keep equivalent temporary state. For compound work, validate a private
`ResearchHandoff/v1` with `scripts/validate_research_handoff.py`. The ledger and
handoff record state; they do not browse, invoke models, execute source content,
or authorize writes.

Treat each mutating ledger command's JSON envelope as the commit receipt. Check
its pre/post event counts and state digests plus `committed` and `partial`; an
exit failure is not proof that no append occurred. Never retry a partial commit
or an existing target blindly. Run `status`, follow its machine-readable recovery
plan, and use `resume` to repair caches and append a recovery acknowledgement.
Finalization remains blocked while any action is active and must keep those
action IDs visible.

Stop targeted work only when promised coverage is met, consequential claims have
fit evidence or remain explicitly unresolved, contrary/boundary evidence is
represented, and two auditable rounds add nothing decision-relevant. Call this
`pragmatic saturation`, never completeness. Systematic work stops by protocol;
budget or access exhaustion produces a partial result with open gaps.

Lead with the bounded answer, then coverage, map/deep branches, aligned route
comparison, evidence/conflicts, gaps, limits, and the next highest-information
check. `$curate-research-to-zotero` alone owns approved acquisition, writes, and
readback. `$research-knowledge-network` alone validates and applies accepted
patches. Preserve private Zotero identifiers, paths, notes, PDFs, and handoff
manifests from public output.

[knowledge-network.md](references/knowledge-network.md) defines snapshot
semantics; [research-basis.md](references/research-basis.md) is maintenance-only.

## Clean-note orchestration

When delivery includes Zotero literature notes, keep operational state outside
the prose, route semantic and raw-LaTeX content through `$learn-from-papers`,
HTML projection through `$curate-research-to-zotero`, and only reviewed
mutations through `$zotero-declarative-bridge`.

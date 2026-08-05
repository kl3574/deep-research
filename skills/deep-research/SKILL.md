---
name: deep-research
description: Use when a task needs auditable multi-source research, field mapping, route comparison, or conflict resolution. Not for one-paper reading, Zotero curation, or knowledge-network maintenance.
---

# Deep Research

## Contract and map

Record question/use, subquestions, scope/exclusions, coverage/version/currentness, risk, uncertainty, limits, and assumptions. Never call orientation/targeted/rapid work systematic; that requires a prespecified protocol.

Normalize terms; map globally; traverse `landscape -> branch -> bottleneck -> deep dive`. Decompose by object/scope, mechanism, route, evidence/maturity, context/version, failure/boundary, and implementation/artifact; call dimensions orthogonal only if shown. Prioritize impact, uncertainty, dependencies, and information gain. Compare only aligned routes. See [research-decomposition.md](references/research-decomposition.md) for search/comparison schemas.

Run `scope -> map -> enqueue gap -> discover -> inspect -> extract -> countercheck -> merge -> citation audit -> stop or continue`. Every action must close a named gap or improve a decision-critical claim. Apply the guards, bounded-parallel rules, failure handling, and untrusted-content boundary in [execution-loop.md](references/execution-loop.md).

## Compound research and delivery preflight

When one request combines research with acquisition, notes, or Zotero delivery,
run the read-only preflight in [delivery-handoff.md](references/delivery-handoff.md)
before retrieval fan-out. If Zotero is in scope, inventory the existing target
corpus first, build a [KnowledgeNetwork/v1](references/knowledge-network.md)
snapshot, and derive new searches from missing, conflicting, or low-confidence
network edges. Do not treat an empty web search as proof that the existing corpus
is complete.

Use `$network-gap-discovery` after deterministic network checks when the task
requires open-world discovery of likely missing nodes, relations, boundary
conditions, or evidence. Treat its outputs as falsifiable candidates, never
novelty or completeness claims. Send each accepted gap search test to
`$scholar-discovery`, which owns bounded multi-provider paper discovery,
identity reconciliation, query provenance, and candidate ranking. It does not
own evidence acceptance.

Google Scholar is manual-only: generate a bounded query for the user and ingest
only a user-supplied export. Never scrape Scholar result HTML, automate around
robots.txt, solve CAPTCHA, or label API fallback results as Scholar results.
Use documented scholarly APIs for autonomous routes and disclose provider
failures and coverage limits.

Classify papers before deep reading:

- **Tier A:** decision-critical. Send to `$learn-from-papers` and require its
  paper-card, evidence-ledger, and passed locator-audit references.
- **Tier B:** supporting or benchmark evidence. Inspect full text to evidence
  depth and retain exact locators for every used claim.
- **Tier C:** orientation or discovery. Metadata, abstract, review, or snippet
  evidence cannot carry a decisive claim.

Before parallel acquisition or note generation, complete and validate one golden
bundle end to end: identity/version, lawful attachment role, reading tier,
structured note, exact target, dry-run, and supported readback. Fan-out inherits
that contract; it does not weaken it.

Keep `research_status` and `delivery_status` separate. Research may be complete
while acquisition or Zotero delivery is partial. For each required acquisition
or Zotero operation, record independent support paths and evidence. If two paths
fail or are unavailable and no path succeeds, mark the operation and aggregate
delivery `blocked_capability`; do not manufacture a duplicate or claim delivery
completion.

## Evidence gates

Maintain the registry, atomic claim/evidence ledger, conflict log, locators, and search trail from [source-routing.md](references/source-routing.md) and [evidence-synthesis.md](references/evidence-synthesis.md).

When the user authorizes a durable workspace, use the deterministic ledger in [run-state.md](references/run-state.md) to checkpoint and validate the run. Otherwise keep equivalent temporary state and do not create persistent artifacts. The ledger records research; it never performs web requests, invokes models, or makes source content executable.

For a compound request, materialize a private `ResearchHandoff/v1` even when the
research ledger itself remains temporary. Validate it with
`scripts/validate_research_handoff.py` before calling research or delivery
complete.

Use reviews/textbooks to orient and primary full text for decisive academic claims; applicable versioned standards/official references for norms; exact releases/full commits, source/tests, and authorized runtime evidence for implementation. Issues, roadmaps, snippets, abstracts, and AI summaries are discovery only.

Before citing, pass authenticity/status, access/locator, method, scope/applicability, and `version_fit`. Wrong editions, branches, APIs, platforms, regions, tiers, or configurations cannot support exact claims. Register the inspected identity/version/status; never cite from memory.

Seek nulls, failures, counterexamples, critiques, corrections/retractions, exclusions, alternatives, and incompatible versions. Record support/contradiction/qualification and overlap. Explain conflicts—never vote or average; narrow or mark `unresolved` when a gate fails.

Send every decisive paper to `$learn-from-papers`; consume its card, ledger, and corrections. If unavailable, disclose it and label the fallback. Claim reconstruction only after inspecting full text, equations, figures, tables, and corrections.

## Stop, deliver, and hand off

Stop targeted work only when promised coverage is met; every consequential claim has fit evidence or is `unresolved`; decisive versions/status, boundaries, and contrary/null evidence are represented; and two consecutive auditable rounds add no decision-relevant concept, route, conflict, or evidence. Call this `pragmatic saturation`, not completeness; systematic work stops only by protocol. Budget or access exhaustion yields a partial result with unresolved gaps, never a forced answer. Disclose access, language/year/database, version/runtime, and bias limits.

Lead with the bounded answer. Deliver coverage, map/deep branches, route comparison, registry/ledger, conflicts, gaps, and the next highest-information check. Keep confidence dimensions separate; a hard-gate failure may dominate.

`$deep-research` owns cross-source synthesis. Hand one paper at a time to `$learn-from-papers`. Use `$curate-research-to-zotero` only for requested acquisition/preservation, passing reviewed identity, version, provenance, and exact target. Acquisition never authorizes writes; require explicit target/batch approval and readback.

`$scholar-discovery` owns paper candidate discovery but never claim synthesis.
`$network-gap-discovery` owns open-world gap hypotheses and patch proposals but
never network mutation. Send validated patch proposals to
`$research-knowledge-network`; only reviewed evidence with exact locators may
be merged.

The handoff must preserve the knowledge-network digest, requested-item completion
matrix, attachment roles, and immutable CurationBatch manifest hashes. A
supplement is `supplement`, never `main_text`. Public outputs may summarize the
network but must not contain private Zotero identifiers, local paths, notes, PDFs,
or unredacted handoff manifests.

[research-basis.md](references/research-basis.md): maintenance/audit only.

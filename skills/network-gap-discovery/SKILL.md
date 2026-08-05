---
name: network-gap-discovery
description: Use when an existing research knowledge network must be audited under open-world assumptions to propose, prioritize, search, refute, and document likely missing nodes, relations, boundary conditions, or evidence. Does not browse directly, declare novelty or completeness, merge the graph, or write Zotero.
---

# Network Gap Discovery

## Contract

Act as an auditable gap-hypothesis controller, not an automatic graph completer.
Read an immutable, validated `KnowledgeNetwork/v1`; propose missing-content
hypotheses; make each hypothesis falsifiable; route searches to
`$scholar-discovery`; send decisive papers to `$learn-from-papers`; and emit only
a `NetworkPatchProposal/v1`. The existing `$research-knowledge-network`
controller alone may validate and merge accepted records.

Absence from an open-world graph means `unknown`. It becomes a deterministic
gap only relative to an explicit competency question, promised dimension,
benchmark profile, completeness statement, or schema constraint. Topological
isolates, low degree, analogy, embeddings, co-occurrence, and empty searches can
only generate `implicit_candidate` hypotheses.

Use `scripts/network_gap_discovery.py` for structural scans, contract
validation, transparent prioritization, scholar-request emission, and patch
proposal validation. Read [contracts.md](references/contracts.md) first.

## Autonomous bounded loop

1. Validate the network with `$research-knowledge-network`; bind its exact path,
   `network_id`, `snapshot_id`, and SHA-256. Never reason over a stale export.
2. Run `scan` to inventory declared gaps, unmet gates, isolates, disconnected
   components, dangling relations, low-confidence edges, and provenance
   omissions. Treat scan signals as prompts, never facts.
3. Generate candidates through independent probe families:
   - competency questions, promised dimensions, benchmark grids, and local
     completeness contracts;
   - taxonomy contrast against landmark reviews or reference ontologies;
   - multi-perspective questioning across object, mechanism, method, evidence,
     context, boundary, implementation, and stakeholder views;
   - Swanson-style A-B-C bridging and citation-neighborhood expansion;
   - missing null, failure, replication, correction, retraction, incompatible
     version, counterexample, or discriminating experiment evidence;
   - population/regime/version/measurement applicability holes;
   - pairwise relations hiding necessary context, n-ary events, or conditions.
4. Represent every implicit candidate with grounds, warrant, backing,
   qualifier, defeaters, confirm and refute searches, acceptance criteria,
   decision impact, uncertainty, dependencies, and `novelty_claimed: false`.
   Validate and prioritize it. Do not auto-merge aliases or sibling concepts.
5. Emit `ScholarDiscoveryRequest/v1` requests. For each candidate perform
   internal alias/direct-coverage checks, positive search, direct-relation
   search, counterexample/null search, citation chaining, version/correction
   checks, and full-text locator review. Preserve all routes and exclusions.
6. Transition to `content_found`, `already_covered`, `supported_gap`, `refuted`,
   `unresolved`, or `blocked`. A search miss is `no_signal`, not nonexistence.
7. Draft `NetworkPatchProposal/v1` with candidate nodes, relations, and evidence
   plus exact locators and provenance. Keep `proposal_only: true`; never invoke
   network mutation or Zotero writes.
8. Re-scan the new validated snapshot after the controller merges an accepted
   patch. Continue only while a named high-information gap remains.

11. `consume-results` accepts only `ScholarDiscoveryResultSet/v1` payloads and
   requires request-set/network binding to the current discovery cycle.

## Hypothesis and status rules

- `content_found` means plausible missing content was located, not accepted as
  true or novel.
- `supported_gap` means sources support bounded missing research or corpus
  coverage; it does not validate the proposed scientific relation.
- `already_covered` means alias resolution, a direct study, or an existing node
  defeated the hypothesis.
- `refuted` means a hard negative, scope mismatch, or contrary evidence defeats
  it; `unresolved` preserves inadequate or conflicting evidence.
- Only a controller-reviewed patch can add content.

Do not infer a negative edge from missing data. Do not upgrade a link-prediction
score, LLM suggestion, search rank, abstract, or snippet into evidence. Keep
claims scoped by population/system, regime, intervention, comparator, outcome,
version, and time when those conditions matter.

## Priority and stop rules

Prioritize decision impact, downstream blocking, uncertainty, expected
information gain, and testability. Penalize likely alias/version duplicates and
expensive searches with weak decision effect. The bundled ranker exposes every
component; it is triage, not epistemic confidence.

For an open Web, stop only when promised dimensions have been probed,
high-impact candidates are terminal, contrary and version routes were executed,
and two consecutive independent rounds add no decision-relevant node, relation,
conflict, or evidence. Report `pragmatic_saturation`, never global completeness.
Budget or access exhaustion yields `partial` or `blocked` with the next action.

Read [research-basis.md](references/research-basis.md) when changing candidate
generation, open-world semantics, evidence gates, or evaluation.

## Runbook notes

Use `consume-results` to ingest each `ScholarDiscoveryResultSet/v1`, then use
`consume-reviewed-evidence` for inspected `ReviewedEvidenceSet/v1` when the
review step returns. Inspecting only `discovery_only` candidates does not upgrade
an hypothesis from `results`; it stays `results` for later discoveries or manual
capture.

Saturation is reached after two consecutive no-progress discovery/review rounds,
but only when there is no `awaiting` manual result obligation.

`consume-results` and `consume-reviewed-evidence` must be bound to the exact same
`request_set_id`, `network_id`, and `network_snapshot_sha256` for deterministic
cycle state.

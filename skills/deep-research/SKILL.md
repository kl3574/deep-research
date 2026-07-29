---
name: deep-research
description: Conduct targeted, auditable deep research across high-confidence academic and industry sources. Use when Codex must investigate an unfamiliar or consequential question, map a field, compare technical routes, review literature, verify current product behavior, trace official documentation or source code, reconcile conflicting evidence, or support a research or engineering decision with claim-level provenance. This skill coordinates single-paper deep reading and optional Zotero curation.
---

# Deep Research

Answer the user's actual decision question through a traceable chain from research scope to source selection, evidence, conflicts, and bounded conclusions. Source prestige is not confidence: evidence must fit the exact claim, version, context, and risk.

## Establish the research contract

Record:

- `question`: the precise question and three to seven decision-relevant subquestions;
- `decision_or_use`: what the answer will change;
- `scope`: object or population, context, outcomes, time horizon, and exclusions;
- `risk`: cost and reversibility of error;
- `currentness`: required freshness and exact software, API, hardware, standard, or publication versions;
- `coverage`: orientation, representative targeted coverage, rapid review, or protocol-complete systematic work;
- `acceptable_uncertainty` and resource limits.

Infer missing details only when the assumption is low-risk and state it. Do not call a targeted scan or pragmatic stopping rule a systematic review.

Use these operational definitions:

- An **atomic claim** contains one proposition whose object, conditions,
  evidence class, and confidence can be kept together. Split a sentence when
  one clause could be supported, contradicted, scoped, or versioned
  independently.
- A **decisive source** is one whose removal could change a route choice, a
  consequential conclusion, its scope, or its confidence. Merely useful
  background is not decisive.
- A **search round** starts from one recorded decision-critical gap, executes
  one coherent retrieval route or bounded query set, screens the returned
  candidates, and records what new decision-relevant information was added.
  Parallel queries for the same gap and route count as one round.

## Build the landscape before the tunnel

Start broad enough to avoid optimizing the wrong branch:

1. Normalize vocabulary, synonyms, acronyms, older terms, and disputed definitions.
2. Map the problem boundary, actors or objects, mechanisms, technical route families, evidence types, maturity, timelines, and major disagreements.
3. Use high-quality reviews, scoping/mapping studies, mainstream textbooks or handbooks, and official overview material as orientation seeds.
4. Build a concept-centric matrix rather than a source-by-source narrative.

Decompose along deliberately separated dimensions:

- problem, object, population, and scope;
- mechanism or causal/derivational chain;
- method or technical route family;
- evidence, validation method, and maturity;
- context, version, configuration, and time;
- trade-offs, assumptions, failure modes, and boundary conditions;
- implementation artifacts and operational constraints.

These dimensions reduce overlap; they are not mathematically orthogonal or independent unless evidence establishes that property. Load [research-decomposition.md](references/research-decomposition.md) for detailed maps and technical-route templates.

## Traverse landscape → branch → bottleneck → deep dive

1. **Landscape:** create the global concept map and identify candidate branches.
2. **Branch:** assign each subquestion to the dimensions and source types capable of answering it.
3. **Bottleneck:** rank unresolved items by decision impact, uncertainty, dependency depth, and expected information gain.
4. **Deep dive:** spend depth only on the highest-value bottlenecks; update the landscape when new evidence changes the taxonomy.

For a technical route, trace:

`problem -> mechanism -> requirements -> route families -> concrete implementations -> validation -> failure boundaries -> selection conditions`

Do not compare routes until their objectives, inputs, constraints, outputs, and evaluation criteria are aligned.

## Route each claim to the right source

Split working conclusions into atomic `claim_id`s and label each:

`definition | normative | mechanism | effect | implementation | historical | future`

Use [source-routing.md](references/source-routing.md). Core rules:

- Academic orientation comes from suitable reviews, evidence maps, textbooks, or handbooks; exact effects, methods, proofs, and boundaries must be checked in the decisive primary sources.
- Industry normative behavior comes from the applicable stable standard, versioned official reference, or manual.
- Actual implementation comes from the exact release artifact or full commit SHA, source path, same-ref tests, and—when needed and authorized—a minimal runtime observation.
- Change history comes from release notes, tag/commit diffs, and linked merged changes.
- Issues, discussions, roadmaps, search snippets, and AI summaries are discovery or provisional evidence, not final proof.

`version_fit` is a hard gate. A famous or official source for the wrong edition, release, branch, API revision, platform, firmware, region, tier, or configuration cannot support an exact current-version claim.

Register a source before citing it. Record identity, canonical location, version/status, access level, exact locator, retrieval time, correction/retraction or obsolescence state, and role. Never create a citation from memory.

## Extract, challenge, and synthesize

For each bottleneck:

1. retrieve the best-fit sources and preserve the search route;
2. screen identity, version, status, access, scope, and methodological fitness before deep reading;
3. hand every decisive academic paper to `$learn-from-papers` and import its paper card and evidence ledger;
4. bind each atomic claim to exact passages, figures, equations, sections, source lines, tests, or runtime records;
5. search specifically for null results, failures, critiques, corrections, retractions, incompatible versions, alternative mechanisms, and excluded populations;
6. record support, contradiction, qualification, independence/overlap, and applicability in the claim/evidence matrix;
7. explain conflicts before combining evidence.

If `$learn-from-papers` is unavailable, do not silently skip deep reading.
Create a clearly labelled fallback paper card and claim ledger using that
skill's public schemas, record the missing dependency, and avoid
`reconstruction`-level claims unless the full text, equations, figures, tables,
and correction log were actually checked.

Synthesize by concept and claim, not by author order. Keep normative requirements, documented claims, source implementation, target-environment observations, and future intentions separate. Do not vote by paper count, significance count, review count, or repository popularity.

Use [evidence-synthesis.md](references/evidence-synthesis.md) for the registry/matrix schemas, conflict logic, and claim-confidence gates.

## Iterate and stop transparently

Convert only decision-critical gaps and conflicts into the next search round. A targeted investigation may stop when:

- the research contract is answered at the promised coverage;
- every consequential claim has fit-for-purpose evidence or an explicit unresolved status;
- decisive versions, corrections, retractions, and scope boundaries have been checked;
- material supporting, null, and contrary evidence found within scope is represented;
- further rounds add no new decision-relevant concept, route, conflict, or evidence.

Call the last condition `pragmatic saturation`, not proof of completeness. Protocol-driven systematic work must instead satisfy its prespecified databases, searches, screening, appraisal, reporting, and stopping requirements.

Report unreachable sources, skipped languages/years/databases, access limits, untested runtime behavior, and likely bias direction.

## Deliver decision-ready artifacts

Lead with the bounded answer and decision implication. Include:

1. research contract and coverage claim;
2. global map and the branches actually deepened;
3. technical-route comparison when relevant;
4. source registry and claim/evidence matrix for consequential claims;
5. conflict log, counterevidence, and unresolved gaps;
6. confidence per claim with authority, directness, validity, version fit, applicability, currency, and independence explained;
7. the next highest-information source, experiment, derivation, or implementation check.

Do not average confidence dimensions into a decorative score. A failed authenticity, access, method, or version-fit gate can dominate the conclusion.

## Cooperate with the companion skills

- Use `$learn-from-papers` for one selected academic paper at a time. Receive its paper card, claim/evidence ledger, and reconstruction corrections.
- Use `$curate-research-to-zotero` only after the user asks to acquire or preserve accepted sources. Pass a reviewed source list, identity/version fields, provenance, and target collection request; Zotero writes remain separately gated.
- This skill owns the cross-source map, search log, source selection, contradiction handling, and final synthesis.

Require an exact software/document version only when behavior of that artifact
is decision-critical. For method-only orientation, record the current official
entry point without allowing its version number to masquerade as scientific
validity evidence.

## Load references selectively

- [research-decomposition.md](references/research-decomposition.md): global-to-specific maps, separated dimensions, and technical-route analysis.
- [source-routing.md](references/source-routing.md): claim-relative academic and industry source rules.
- [evidence-synthesis.md](references/evidence-synthesis.md): source registry, matrices, conflict handling, and stopping.
- [research-basis.md](references/research-basis.md): methodological sources and design limits; load only to audit or maintain the skill.

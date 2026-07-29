---
name: learn-from-papers
description: Deeply read and understand one academic paper from a PDF, DOI, preprint, or publisher page using goal-scaled passes, paper-type-specific reconstruction, and claim-level evidence locators. Use when Codex is given a specific paper and asked to explain, learn, critique, reproduce, implement, or verify its methods, results, figures, equations, assumptions, or limits. Do not use this skill alone for field-wide literature searches or multi-source synthesis.
---

# Learn From Papers

Turn one paper into an inspectable external knowledge state. Treat speed as selective depth: spend attention on the claims, methods, visuals, equations, and assumptions that control the user's decision instead of producing a hurried page-by-page summary.

“Learn” here means reconstructing and verifying knowledge that can be saved and retrieved. It does not mean changing model parameters or creating durable memory.

## Fix the reading contract

Record:

- the paper and the user's main question;
- the intended use: triage, explanation, critique, reproduction, or implementation;
- the requested depth and available artifacts;
- the cost of a wrong answer;
- three to seven subquestions that would resolve the request.

If the user requests a “complete read,” inspect every page and inventory every figure, table, numbered equation, theorem, appendix, and supplement. Deeply reconstruct only the items that affect the reading contract; record the rest as inspected. Do not imply that every cited reference was independently verified unless the task requires it.

Choose and report the lightest sufficient route:

| Need | Route | Completion claim |
| --- | --- | --- |
| Decide relevance or reading order | Map | `triaged`, not fully read |
| Explain or reliably summarize | Map + evidence | `evidence-read` |
| Critique, reproduce, implement, or make a consequential decision | Map + evidence + reconstruction | `deeply reconstructed` |

Ask a clarifying question only when different interpretations would materially change the route. Never imply that every page was inspected when an earlier route was sufficient.

## Resolve the exact source

1. Normalize title, authors, year, venue, DOI or stable identifier, publication type, and version.
2. Prefer the Version of Record or the author's/repository's clearly identified full text. Record `full_text`, `partial_text`, `abstract_only`, or `metadata_only`.
3. Check for a later version, correction, retraction, expression of concern, supplement, appendix, code, and data when any could change the answer.
4. Inspect rendered pages as well as extracted text when layout, equations, tables, or figures matter. Broken extraction is missing evidence, not permission to guess.
5. Keep the paper, later commentary, cited background, and agent inference separate.

Never claim a method, result, proof, or limitation was validated from metadata or an abstract alone. If source discovery or status checking becomes a substantive multi-source task, invoke `$deep-research`.

When working offline, mark later-version, correction, and retraction checks `status-unverified-offline`. Do not turn lack of network access into a clean status claim.

## Pass A: Map the paper

Inspect the title, abstract, introduction, headings, conclusion, references, and every figure/table caption. Build a compact paper map:

- paper type and author objective;
- research question and claimed contribution;
- prerequisites and important terminology;
- assumptions, population, operating regime, and exclusions;
- method, proof, or argument skeleton;
- headline result and claimed implication;
- sections and artifacts that answer each subquestion.

Decide whether to stop, retrieve a missing prerequisite, or continue. An out-of-scope decision is a valid result when its reason and inspected evidence are preserved.

## Pass B: Build claim-level evidence

Read by subquestion and dependency, not linearly by default.

1. Split each consequential conclusion into atomic, checkable claims.
2. Build an evidence outline before drafting prose.
3. Record each claim in the ledger from [evidence-ledger.md](references/evidence-ledger.md).
4. Attach a precise locator: page and section plus figure, table, equation, theorem, appendix, or stable HTML heading.
5. Carry conditions with the claim: definitions, population, regime, comparison, units, denominator, uncertainty, and exclusions.
6. Mark each item `source-stated`, `agent-inferred`, `externally-supported`, or `unresolved`.
7. Load the appropriate adapter from [paper-routes.md](references/paper-routes.md).

For a long or composite file, first build the [document manifest](references/document-manifest.md): physical PDF pages, printed page labels, main-text/supplement mapping, artifact inventory, extraction quality, and inspection state.

Keep the map visible while reading slices. Bundle a key visual with its caption, result discussion, and generating method. Bundle an equation or theorem with symbol definitions, assumptions, and dependencies. This prevents section-level chunking from erasing cross-modal and cross-section relationships.

Use short quotations only when wording is itself material; otherwise paraphrase faithfully.

## Pass C: Reconstruct and challenge

Use this pass for deep understanding, critique, reproduction, or implementation.

1. Reconstruct the paper from the evidence notes without copying its prose. When possible, use an independent context containing only the question and evidence notes; otherwise label this as a weaker diagnostic.
2. Recreate the causal chain, derivation, theorem dependency, algorithm, or experimental logic.
3. Explain why each central design choice is needed and what a plausible alternative would change.
4. Produce at least one boundary case, counterexample, rival explanation, or falsifying observation for every central claim.
5. Reopen the source, compare the reconstruction, and preserve corrections in the correction log.
6. Answer a compact teach-back test:
   - What problem is solved?
   - Why should this method solve it?
   - Which evidence actually supports the conclusion?
   - Under what conditions would the conclusion fail or stop applying?
   - What would be needed to reproduce or use it?
7. Separate what the paper establishes, what the authors interpret, what the agent infers, and what remains unknown.

A fluent explanation is only a candidate understanding until it survives source comparison. A reconstructed algorithm is not a successful reproduction unless it was actually implemented and tested.

When an independent context is unavailable, explicitly perform `closed-source reconstruction -> reopen source -> correction log` in the same context and label it `same-context diagnostic`.

## Apply acceptance gates

Before answering, check:

- **Identity:** The exact paper and version are known.
- **Access:** Claimed depth matches the material actually accessed.
- **Entailment:** Every consequential source-stated claim follows from its cited passage.
- **Completeness:** Consequential claims have evidence or an explicit unresolved label.
- **Locator:** Another reader can find each core item without searching the whole paper.
- **Numbers:** Values, units, signs, denominators, comparisons, and uncertainty match.
- **Visuals:** Axes, legend, caption, and generating method were inspected; otherwise mark `visual-unresolved`.
- **Dependencies:** Definitions, assumptions, proof steps, and method/result links remain connected.
- **Cross-artifact consistency:** Central formulas, tables, captions, pseudocode, and prose agree, or their internal inconsistency is recorded.
- **Estimator/UQ consistency:** The reported covariance, interval, or posterior
  corresponds to the estimator actually computed; nominal levels, quantiles,
  nuisance-parameter treatment, and any empirical coverage check are not
  conflated.
- **Scope:** Population, regime, exclusions, and boundary conditions travel with conclusions.
- **Reconstruction:** Corrections were recorded after source comparison.

When a gate fails, retrieve more evidence, narrow the claim, lower confidence, or report the gap. Never repair an unsupported statement with a merely related citation or unsupported self-critique.

## Deliver a reusable paper card

Lead with the answer to the user's question, then include only the detail needed for the chosen route:

1. exact source identity, version/status, and access level;
2. one-sentence central claim;
3. a mental model: `problem -> assumptions -> method/argument -> evidence -> conclusion`;
4. the minimum claim/evidence ledger needed to audit the answer;
5. reconstruction, figure/equation cards, or implementation notes when requested;
6. limitations, boundary cases, rival explanations, and unresolved items;
7. confidence per claim with a reason;
8. the highest-value next test, derivation, source, or implementation step.

Preserve original notation and technical terms when translation would create ambiguity.

Treat the paper card and evidence ledger as the canonical internal fact record. When the result will become a research knowledge base, project that record into the structured note from [knowledge-note.md](references/knowledge-note.md); do not independently rewrite a second fact base. Build the note from full-text-verified claims rather than from the abstract, and keep claim locators and uncertainty inside it.

## Cooperate with the other skills

- Invoke `$deep-research` when the paper requires external prerequisites, version/status investigation, comparison with other evidence, citation-chain verification, or a field-level conclusion. Return this skill's paper card and ledger to that workflow.
- Invoke `$curate-research-to-zotero` only when the user wants legal acquisition, local file verification, or Zotero synchronization. Do not perform library writes inside this skill.
- Do not treat textbooks, standards, product manuals, or source repositories as academic papers; route them through `$deep-research`.

## Load references selectively

- Load [evidence-ledger.md](references/evidence-ledger.md) for any evidence or reconstruction route.
- Load [document-manifest.md](references/document-manifest.md) for long PDFs, supplements, unreliable text layers, or any requested complete read.
- Load [paper-routes.md](references/paper-routes.md) after classifying the paper.
- Load [knowledge-note.md](references/knowledge-note.md) when the user wants Zotero notes or a durable literature knowledge base.
- Load [research-basis.md](references/research-basis.md) only when explaining, auditing, or maintaining this skill's design.

---
name: learn-from-papers
description: Deep-read a specific academic paper from a PDF, DOI, preprint, or publisher text. Use when asked to explain, critique, reproduce, implement, or verify methods, evidence, equations, figures, assumptions, results, and limits with exact locators. Not for field-wide or multi-source synthesis.
---

# Learn From Papers

Build an auditable record for one paper; route broader research to `$deep-research`.

## Contract and depth

Record the question, use, artifacts, error cost, and subquestions. Separate the canonical publication record from the version read; record path/hash, access, and status limits. Abstracts and metadata cannot validate results. Check material later versions, corrections, retractions, supplements, code, and data; when offline mark that status `status-unverified-offline`. Render-check equations and figures.

Choose and report the lightest sufficient route:

- **Map:** relevance/reading order; claim only `triaged`.
- **Map + evidence:** reliable explanation; claim `evidence-read`.
- **Map + evidence + reconstruction:** critique, reproduction, implementation, or consequential decisions; claim `deeply reconstructed`.

For a complete read, count inspected pages, figures, tables, numbered equations/theorems, appendices, and supplements. Distinguish `inspected`, `reconstructed`, `unresolved`, and independently followed citations.

## Passes

1. **Map:** inspect the paper skeleton and all captions; classify the paper, then load its adapter from [paper-routes.md](references/paper-routes.md).
2. **Evidence:** load [evidence-ledger.md](references/evidence-ledger.md); create atomic claims before drafting, label nature, and attach exact page/section/artifact locators and scope. Couple visuals to axes, legend, caption, and generation; couple equations/theorems to notation, units/shapes, assumptions, dependencies, and derivation/proof role. Record conflicts.
3. **Reconstruct:** rebuild the causal chain, derivation, proof, algorithm, or experiment; test central claims with boundaries, counterexamples, rivals, or falsifiers. Reopen the source and preserve `initial -> source check -> correction`. Separate source results, author interpretation, agent inference, and unknowns.

Use [document-manifest.md](references/document-manifest.md) first for complete, long, composite, or extraction-poor files. Prefer an independent evidence-only reconstruction; otherwise label the reopen check `same-context diagnostic`. A reconstructed algorithm is not a reproduction unless implemented and tested.

## Gates and projection

Check identity/version, access-depth, entailment, claim coverage, locators/scope, numeric and cross-artifact consistency. Ensure estimator, covariance/interval/posterior, nominal level, quantiles, nuisance treatment, and empirical coverage are not conflated. Narrow or mark failures unresolved; never fill gaps with related citations.

Lead with the answer, then the minimum paper card: source/status/access; central claim; `problem -> assumptions -> method -> evidence -> conclusion`; auditable claim ledger; requested equation/figure/reproduction cards; limits, confidence, and next test.

The card and ledger are canonical. For a durable note, project them through [knowledge-note.md](references/knowledge-note.md) using Chinese prose and LaTeX. `$curate-research-to-zotero` owns schema-9 HTML, exact-target approval, writes, and readback; this skill performs no Zotero write.

Load [research-basis.md](references/research-basis.md) only when auditing this skill.

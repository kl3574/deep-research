# Research basis and limits

This reference records the methodological basis for maintaining the skill. Reporting guidance does not itself certify research quality, and methods developed for one field require adaptation elsewhere.

## Contents

- [Mapping, decomposition, and technical routes](#mapping-decomposition-and-technical-routes)
- [Search and synthesis](#search-and-synthesis)
- [Academic quality and claim-level confidence](#academic-quality-and-claim-level-confidence)
- [Technical provenance](#technical-provenance)
- [Agent evidence controls](#agent-evidence-controls)
- [Audited implementation patterns](#audited-implementation-patterns)

## Mapping, decomposition, and technical routes

1. Petersen, K., Vakkalanka, S., & Kuzniarz, L. (2015). “Guidelines for conducting systematic mapping studies in software engineering.” *Information and Software Technology*, 64, 1–18. DOI: [10.1016/j.infsof.2015.03.007](https://doi.org/10.1016/j.infsof.2015.03.007)
   - Supports broad evidence classification and the distinction between mapping a field and answering a focused synthesis question.
   - The detailed process is software-engineering specific.

2. Tricco, A. C., et al. (2018). “PRISMA Extension for Scoping Reviews (PRISMA-ScR).” *Annals of Internal Medicine*, 169(7), 467–473. DOI: [10.7326/M18-0850](https://doi.org/10.7326/M18-0850)
   - Supports transparent reporting when mapping concepts, evidence types, and gaps.
   - PRISMA-ScR is reporting guidance, not a guarantee of rigor.

3. Webster, J., & Watson, R. T. (2002). “Analyzing the Past to Prepare for the Future: Writing a Literature Review.” *MIS Quarterly*, 26(2), xiii–xxiii. [AIS record](https://aisel.aisnet.org/misq/vol26/iss2/3/)
   - Motivates concept-centric rather than author-centric synthesis.
   - It is editorial guidance, not a complete search protocol.

4. Phaal, R., Farrukh, C. J. P., & Probert, D. R. (2004). “Technology roadmapping—A planning framework for evolution and revolution.” *Technological Forecasting and Social Change*, 71(1–2), 5–26. DOI: [10.1016/S0040-1625(03)00072-6](https://doi.org/10.1016/S0040-1625(03)00072-6)
   - Supports linking needs, products/capabilities, and technologies over time.
   - Roadmapping is a planning lens, not evidence that one route is scientifically superior.

5. Ritchey, T. (2006). “Problem structuring using computer-aided morphological analysis.” *Journal of the Operational Research Society*, 57, 792–801. DOI: [10.1057/palgrave.jors.2602177](https://doi.org/10.1057/palgrave.jors.2602177)
   - Supports explicit multi-dimensional problem spaces and consistency analysis.
   - Morphological dimensions are not automatically statistically or mathematically orthogonal.

## Search and synthesis

6. Lefebvre, C., et al. (current edition). Cochrane Handbook, Chapter 4, “Searching for and selecting studies.” [Official chapter](https://training.cochrane.org/handbook/current/chapter-04)
   - Supports multi-route searching, search documentation, and study-level selection.
   - Health-review procedures should not be copied mechanically into every domain.

7. Rethlefsen, M. L., et al. (2021). “PRISMA-S.” *Systematic Reviews*, 10, 39. DOI: [10.1186/s13643-020-01542-z](https://doi.org/10.1186/s13643-020-01542-z)
   - Supports reproducible reporting of sources, strategies, limits, dates, and supplementary searches.
   - It is a reporting extension, not proof that a search is complete.

8. Hirt, J., et al. (2024). “TARCiS statement.” *BMJ*, 385, e078384. DOI: [10.1136/bmj-2023-078384](https://doi.org/10.1136/bmj-2023-078384)
   - Supports planned and reported backward/forward citation searching.
   - Citation searching complements rather than guarantees exhaustive database retrieval.

9. Garousi, V., Felderer, M., & Mäntylä, M. V. (2019). “Guidelines for including grey literature and conducting multivocal literature reviews in software engineering.” *Information and Software Technology*, 106, 101–121. DOI: [10.1016/j.infsof.2018.09.006](https://doi.org/10.1016/j.infsof.2018.09.006)
   - Supports explicit source-quality and provenance checks when academic and practitioner evidence are combined.
   - Its rubric requires adaptation beyond software engineering.

## Academic quality and claim-level confidence

10. Shea, B. J., et al. (2017). “AMSTAR 2.” *BMJ*, 358, j4008. DOI: [10.1136/bmj.j4008](https://doi.org/10.1136/bmj.j4008)
    - Supports domain-level appraisal of intervention reviews and explicitly discourages a simple total score.
    - It is not a universal tool for mathematics, physics, qualitative research, or all computer science.

11. Page, M. J., et al. (2021). “The PRISMA 2020 statement.” *BMJ*, 372, n71. DOI: [10.1136/bmj.n71](https://doi.org/10.1136/bmj.n71)
    - Supports transparent systematic-review reporting.
    - Reporting compliance does not prove unbiased methods or correct conclusions.

12. Cochrane Handbook, Chapter 14, “Completing Summary of findings tables and grading the certainty of the evidence.” [Official chapter](https://training.cochrane.org/handbook/current/chapter-14)
    - Supports outcome/claim-specific certainty judgments rather than one label for a whole paper.
    - GRADE is designed for defined health evidence questions and needs domain-aware adaptation.

13. San Francisco Declaration on Research Assessment (DORA). [Declaration](https://sfdora.org/read/)
    - Supports avoiding journal-level metrics as substitutes for individual research assessment.

## Technical provenance

14. GitHub Docs. “Getting permanent links to files.” [Official documentation](https://docs.github.com/en/repositories/working-with-files/using-files/getting-permanent-links-to-files)
    - Supports full-commit permalinks because branch content changes.

15. Semantic Versioning 2.0.0. [Specification](https://semver.org/)
    - Supports compatibility interpretation only for software that declares and follows SemVer.

16. IETF. “Request for Comments.” [Process and status](https://www.ietf.org/process/rfcs/)
    - Supports checking standards-track status, updates, obsolescence, and errata rather than treating every RFC equally.

## Agent evidence controls

17. Asai, A., et al. (2026). “Synthesizing scientific literature with retrieval-augmented language models.” *Nature*. DOI: [10.1038/s41586-025-10072-4](https://doi.org/10.1038/s41586-025-10072-4)
    - Supports retrieval, citation-backed synthesis, and citation verification in the evaluated system.
    - Benchmark results do not prove coverage completeness in a new domain.

18. Gao, T., et al. (2023). “Enabling Large Language Models to Generate Text with Citations.” *EMNLP 2023*. DOI: [10.18653/v1/2023.emnlp-main.398](https://doi.org/10.18653/v1/2023.emnlp-main.398)
    - Separates citation correctness from citation completeness.

19. Min, S., et al. (2023). “FActScore.” *EMNLP 2023*. DOI: [10.18653/v1/2023.emnlp-main.741](https://doi.org/10.18653/v1/2023.emnlp-main.741)
    - Supports atomic claim decomposition for fine-grained evidence checking.

## Audited implementation patterns

20. Jina AI. `node-DeepResearch` at the fork merge-base
    [`f1b9b2f55e01f7158900da125f85957bbfbd0019`](https://github.com/jina-ai/node-DeepResearch/tree/f1b9b2f55e01f7158900da125f85957bbfbd0019).
    - Motivates an explicit search/read/reflect action loop, gap queue, bounded
      retrieval, structured state, and action/token budgets.
    - Its model-chosen actions and evaluators are implementation patterns, not
      evidence that a claim, citation, or stopping decision passed this skill's
      independent gates.

21. Matt Pocock's experimental fork of `node-DeepResearch` at
    [`69f345ef8ef28f725aaa778177f6be181801411e`](https://github.com/mattpocock/node-DeepResearch/tree/69f345ef8ef28f725aaa778177f6be181801411e).
    - The six-commit delta experiments with an `AgentRunner` refactor, prompt
      composition, failure-path control, and forced terminal handling. At the
      2026-08-04 audit it was 6 commits ahead and 308 behind current upstream, so
      it is treated as a historical experiment rather than a current release.
    - This Apache-2.0 TypeScript fork is not a Codex `SKILL.md`; no source code or
      prompt text is copied here. Forced certainty/answers, first-answer bypass,
      optional attribution, model-only judging, and overwrite-style shared debug
      state observed in this snapshot are deliberately not adopted.

22. Matt Pocock. [`research` skill](https://github.com/mattpocock/skills/blob/2ab958093e83e0ec752e6c1c5932da465bf23e0c/skills/engineering/research/SKILL.md).
    - Supports a compact primary-source-oriented research handoff with explicit
      citations.
    - Its brief background-research contract does not replace this skill's
      multi-source coverage, conflict, version, and claim-level evidence gates.

Treat the complete workflow as an evidence-informed design requiring forward tests, not as a formally proven optimal research algorithm.

## High-quality systems and split-skill decomposition evidence

23. llm-for-zotero — [GitHub](https://github.com/yilewang/llm-for-zotero), [AGPL License](https://github.com/yilewang/llm-for-zotero/blob/main/LICENSE), [official README](https://github.com/yilewang/llm-for-zotero/blob/main/README.md)
    - Clean-room idea taken: corpus-wide agent mode, grounded citations, durable evidence cache, and coverage frontier visibility.
    - Constraint: AGPL-3.0 in public repository, so this repo does not copy implementation or prompts.

24. Microsoft GraphRAG — [repository](https://github.com/microsoft/graphrag), [technical docs](https://microsoft.github.io/graphrag/), [paper](https://arxiv.org/abs/2404.02821)
    - Clean-room idea taken: explicit `document / text-unit / entity / relation / claim / community` separation, stable IDs, local-global retrieval, and incremental indexing.
    - Constraint: does not prescribe domain-specific conflict semantics or implicit-gap warrants.

25. OpenScholar — [official website](https://open-scholar.github.io/), [GitHub](https://github.com/akariasai/openscholar), [Nature](https://www.nature.com/articles/s41586-025-10072-4), [license](https://github.com/akariasai/openscholar/blob/main/LICENSE)
    - Clean-room idea taken: full-text retrieval, citation-grounded synthesis, and self-feedback quality checks.
    - Constraint: benchmark-oriented claims need adaptation before procedural adoption; license and API dependencies checked before merge.

26. PaperQA2 — [GitHub](https://github.com/Future-House/paper-qa), [license](https://github.com/Future-House/paper-qa/blob/main/LICENSE)
    - Clean-room idea taken: full-text QA with explicit citation pointers and retraction-aware pipeline.
    - Constraint: this skill treats PaperQA2 as a component pattern, not a full control loop.

27. STORM — [GitHub](https://github.com/stanford-oval/storm), [arXiv](https://arxiv.org/abs/2402.14207)
    - Clean-room idea taken: multi-perspective question generation and collaborative decomposition of long technical questions.
    - Constraint: generic knowledge curation emphasis is strong, but evidence graph persistence and gap gating remain external concerns.

28. HippoRAG — [GitHub](https://github.com/emory-irl-lab/HippoRAG), [license](https://github.com/emory-irl-lab/HippoRAG/blob/main/LICENSE)
    - Clean-room idea taken: hybrid graph + retrieval, PageRank-style ranking, incremental updates.
    - Constraint: only retrieval/re-ranking concepts are adopted, with no direct dependence on its code.

29. ORKG — [official docs](https://www.orkg.org/), [schema docs](https://www.orkg.org/academy), [paper](https://arxiv.org/abs/2208.03366)
    - Clean-room idea taken: semantic contribution objects and comparison-centered knowledge modeling.
    - Constraint: licensing and deployment model depend on the active ORKG deployment target; design is adapted per endpoint.

30. GAPMAP — [arXiv](https://arxiv.org/abs/2510.25055)
    - Clean-room idea taken: explicit gap buckets, implicit-gap hypotheses, and Toulmin-style abductive scaffolding.
    - Constraint: preprint status means no production-grade implementation guarantee.

31. RAGA — [arXiv](https://arxiv.org/abs/2605.17072)
    - Clean-room idea taken: Read-Search-Verify-Construct loop and graph-CRUD consistency constraints.
    - Constraint: early-stage evidence with limited operational maturity.

32. zotero-mcp — [GitHub](https://github.com/54yyyu/zotero-mcp), [license](https://github.com/54yyyu/zotero-mcp/blob/main/LICENSE)
    - Clean-room idea taken: semantic retrieval, PDF/annotation transport, and local cache design around Zotero.
    - Constraint: strong transport/retrieval layer only; not a complete evidence-gap orchestration design.

33. SeerAI — [GitHub](https://github.com/dralkh/seerai), [license](https://github.com/dralkh/seerai/blob/main/LICENSE)
    - Clean-room idea taken: local-first Zotero + systematic-review UX for reproducible curation.
    - Constraint: no direct evidence-network semantics or gap derivation logic.

34. K-Dense scientific skills — [GitHub](https://github.com/K-Dense-AI/scientific-agent-skills), [hypothesis-generation section](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/README.md#scientific-hypothesis-generation-skill), [license](https://github.com/K-Dense-AI/scientific-agent-skills/blob/main/LICENSE)
    - Clean-room idea taken: rival explanations, falsification controls, structured hypotheses.
    - Constraint: not a full library workflow by itself; selected hypothesis-patterns are composable with other skills.

No single reviewed system provides end-to-end, auditable, non-overlapping separation of (1) global deep-research orchestration, (2) single-paper reconstruction, (3) evidence-network governance, and (4) Zotero curation/readback.

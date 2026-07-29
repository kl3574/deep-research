# Research basis and limits

This reference records the methodological basis for maintaining the skill. Reporting guidance does not itself certify research quality, and methods developed for one field require adaptation elsewhere.

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

Treat the complete workflow as an evidence-informed design requiring forward tests, not as a formally proven optimal research algorithm.

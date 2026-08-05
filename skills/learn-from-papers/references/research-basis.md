# Research basis and design limits

This file records why the workflow is structured as it is. It is maintenance evidence, not a reading-time checklist. Human-learning results are design analogies; they do not prove that a language-model agent learns like a human.

## Staged and question-led reading

1. Keshav, S. (2007). “How to Read a Paper.” *ACM SIGCOMM Computer Communication Review*, 37(3), 83–84. DOI: [10.1145/1273445.1273458](https://doi.org/10.1145/1273445.1273458)
   - Motivates staged passes, the five-question map, and explicit stopping decisions.
   - Its suggested timings and computer-science framing are heuristics, not universal requirements.

2. Carey, M. A., et al. (2020). “Ten simple rules for reading a scientific paper.” *PLOS Computational Biology*, 16(7), e1008032. DOI: [10.1371/journal.pcbi.1008032](https://doi.org/10.1371/journal.pcbi.1008032)
   - Supports purpose-driven reading, interrogating figures, taking notes, and consulting cited context.
   - It is practical expert guidance rather than a controlled evaluation of agent workflows.

3. Rayner, K., et al. (2016). “So Much to Read, So Little Time: How Do We Read, and Can Speed Reading Help?” *Psychological Science in the Public Interest*, 17(1), 4–34. DOI: [10.1177/1529100615623267](https://doi.org/10.1177/1529100615623267)
   - Reviews evidence for a speed/comprehension trade-off in human reading.
   - It motivates selective depth, not a fixed agent token or time budget.

## Reconstruction as a diagnostic

4. Chi, M. T. H., et al. (1994). “Eliciting Self-Explanations Improves Understanding.” *Cognitive Science*, 18(3), 439–477. DOI: [10.1207/s15516709cog1803_3](https://doi.org/10.1207/s15516709cog1803_3)
   - Supports self-explanation as a human-learning mechanism for integrating new material with existing knowledge.
   - The skill uses reconstruction by analogy and still requires source comparison.

5. Karpicke, J. D., & Blunt, J. R. (2011). “Retrieval Practice Produces More Learning than Elaborative Studying with Concept Mapping.” *Science*, 331(6018), 772–775. DOI: [10.1126/science.1199327](https://doi.org/10.1126/science.1199327)
   - Supports reconstructive retrieval for human conceptual learning.
   - It does not validate an LLM's internal learning or durable memory.

6. Hodds, M., Alcock, L., & Inglis, M. (2014). “Self-Explanation Training Improves Proof Comprehension.” *Journal for Research in Mathematics Education*, 45(1), 62–101. DOI: [10.5951/jresematheduc.45.1.0062](https://doi.org/10.5951/jresematheduc.45.1.0062)
   - Supports explicit self-explanation in human mathematical-proof comprehension.
   - It motivates theorem and equation cards only for proof-like material.

## Agent-specific reliability controls

7. Liu, N. F., et al. (2024). “Lost in the Middle: How Language Models Use Long Contexts.” *Transactions of the Association for Computational Linguistics*, 12, 157–173. DOI: [10.1162/tacl_a_00638](https://doi.org/10.1162/tacl_a_00638)
   - Shows position-sensitive degradation in the evaluated long-context retrieval and multi-document QA settings.
   - Motivates maps, targeted evidence packs, and locators; it does not establish identical behavior for every model.

8. Wang, Z., et al. (2024). “CharXiv: Charting Gaps in Realistic Chart Understanding in Multimodal LLMs.” *NeurIPS 2024*. DOI: [10.52202/079017-3609](https://doi.org/10.52202/079017-3609)
   - Demonstrates important scientific-chart understanding gaps in the evaluated models.
   - Motivates a distinct visual gate and `visual-unresolved` status.

9. Gao, T., Yen, H., Yu, J., & Chen, D. (2023). “Enabling Large Language Models to Generate Text with Citations.” *EMNLP 2023*. DOI: [10.18653/v1/2023.emnlp-main.398](https://doi.org/10.18653/v1/2023.emnlp-main.398)
   - Separates response quality, citation correctness, and citation completeness.
   - These dimensions motivate separate acceptance gates rather than one fluency judgment.

10. Min, S., et al. (2023). “FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation.” *EMNLP 2023*. DOI: [10.18653/v1/2023.emnlp-main.741](https://doi.org/10.18653/v1/2023.emnlp-main.741)
    - Supports atomic decomposition for checking long-form factual claims.
    - Its metric is not itself a scientific-reading protocol.

11. Gao, L., et al. (2023). “RARR: Researching and Revising What Language Models Say, Using Language Models.” *ACL 2023*. DOI: [10.18653/v1/2023.acl-long.910](https://doi.org/10.18653/v1/2023.acl-long.910)
    - Supports retrieving external evidence before revising unsupported generated claims.
    - Revision can introduce errors, so the final entailment must still be checked.

12. Huang, J., et al. (2024). “Large Language Models Cannot Self-Correct Reasoning Yet.” *ICLR 2024*. [Official paper page](https://proceedings.iclr.cc/paper_files/paper/2024/hash/8b4add8b0aa8749d80a34ca5d941c355-Abstract-Conference.html)
    - Finds unreliable intrinsic self-correction on the evaluated tasks.
    - Motivates evidence-constrained correction; it does not rule out externally supervised correction for every model and task.

13. Asai, A., et al. (2026). “Synthesizing scientific literature with retrieval-augmented language models.” *Nature*. DOI: [10.1038/s41586-025-10072-4](https://doi.org/10.1038/s41586-025-10072-4)
    - Supports passage retrieval, citation-backed synthesis, and citation checks in the evaluated scientific QA system.
    - Benchmark gains do not establish completeness or remove expert review in high-stakes work.

## Scientific document QA and evidence localization

14. Dasigi, P., et al. (2021). “A Dataset of Information-Seeking Questions and Answers Anchored in Research Papers.” *NAACL 2021*. [QASPER](https://aclanthology.org/2021.naacl-main.365/)
    - Couples long-paper questions with answers, supporting evidence, and unanswerable cases.
    - Motivates question plans, evidence locators, and explicit abstention rather than generic summarization.

15. Fröbe, M., et al. (2025). “PeerQA: A Scientific Question Answering Dataset from Peer Reviews.” *NAACL 2025*. [PeerQA](https://aclanthology.org/2025.naacl-long.22/)
    - Evaluates evidence retrieval, unanswerability, and answer generation over long papers.
    - Motivates subquestion-specific retrieval and decontextualized evidence units.

16. Wadden, D., et al. (2020). “Fact or Fiction: Verifying Scientific Claims.” *EMNLP 2020*. [SciFact](https://aclanthology.org/2020.emnlp-main.609/)
    - Separates supporting/refuting rationales from claim labels.
    - Motivates explicit `supports` and `refutes` relations with source rationales.

17. Katsogiannis-Meimarakis, G., et al. (2024). “SciDQA: Learning from Science Demonstrations for Question Answering.” *EMNLP 2024*. [SciDQA](https://aclanthology.org/2024.emnlp-main.1163/)
    - Scientific questions can depend on figures, tables, equations, appendices, and supplements.
    - Motivates component inventory and typed artifact cards instead of text-only reading.

18. Pramanick, S., et al. (2024). “SPIQA: A Dataset for Multimodal Question Answering on Scientific Papers.” [arXiv:2407.09413](https://arxiv.org/abs/2407.09413)
    - Provides large-scale questions grounded in scientific figures and tables.
    - Motivates rendered-page gates for decision-critical visual evidence.

## Reconstruction and system evaluation

19. Starace, G., et al. (2025). “PaperBench: Evaluating AI’s Ability to Replicate AI Research.” [OpenAI benchmark page](https://openai.com/index/paperbench/)
    - Uses author-built hierarchical rubrics to grade paper replication tasks.
    - Motivates task-level reconstruction records and separation of planned, executed, matched, and replicated states.

20. Lála, J., et al. (2024). “PaperQA2: Superhuman scientific literature search.” [arXiv:2409.13740](https://arxiv.org/abs/2409.13740) and [official implementation](https://github.com/Future-House/paper-qa)
    - Uses evidence chunks, contextual summaries, reranking, and contradiction-oriented workflows.
    - Motivates question-directed evidence packs; its multi-paper system is not itself a one-paper truth oracle.

21. Lopez, P. (2025). “GROBID Documentation: Introduction.” [Official documentation](https://grobid.readthedocs.io/en/latest/Introduction/)
    - Structured TEI extraction can expose sections, references, figures, tables, and coordinates.
    - Motivates a document intermediate representation while preserving rendered/source bytes as authority.

22. Parmar, P., et al. (2024). “Docling Technical Report.” [arXiv:2408.09869](https://arxiv.org/abs/2408.09869), and Wang, B., et al. (2024). “MinerU.” [arXiv:2409.18839](https://arxiv.org/abs/2409.18839)
    - Modern parsing systems target structured, layout-aware scientific-document conversion.
    - Multiple parser options motivate explicit tool provenance and fallback, not silent parser substitution.

## Design boundary

The workflow is an evidence-informed engineering design. Validate it with forward tests on real PDFs, preserve source provenance, and keep domain-expert review for high-stakes scientific, medical, legal, safety, or policy decisions.

## Why PaperUnderstanding was added

The workflow separates claim extraction, network projection, and machine handoff by adding `PaperUnderstanding/v1` as an intermediate understanding layer.

The dossier is designed for governance and attestation around explicit evidence claims.
The understanding artifact is designed for structured internal reuse where route-specific downstream systems need a denser, section-level encoding.

`project-note-input` exists to prevent silent shape drift between free-form notes and strict machine contracts.
Projecting from `map` depth is intentionally blocked because the route does not include the reconstruction/evidence commitments that the note-input consumer requires.

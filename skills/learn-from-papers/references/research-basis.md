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

## Design boundary

The workflow is an evidence-informed engineering design. Validate it with forward tests on real PDFs, preserve source provenance, and keep domain-expert review for high-stakes scientific, medical, legal, safety, or policy decisions.

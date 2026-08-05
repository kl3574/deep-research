# Research basis for network gap discovery

## Open-world and requirements-relative completeness

- W3C [OWL guide](https://www.w3.org/TR/owl-guide/) and
  [SHACL](https://www.w3.org/TR/shacl/): open-world semantics and validation
  against explicitly declared shapes.
- Darari et al., [completeness statements](https://arxiv.org/abs/1408.6395):
  completeness is scoped metadata, not a global property inferred from silence.
- Razniewski et al., [Completeness, Recall, and Negation](https://arxiv.org/abs/2305.05403):
  methods and limits for locating incomplete open knowledge bases.
- Grüninger and Fox, [competency questions](https://eil.utoronto.ca/wp-content/uploads/enterprise-modelling/papers/gruninger-onto-ecai94.pdf):
  evaluate content relative to motivating scenarios and questions.

## Candidate generation, not automatic truth

- Shi and Weninger, [Open-World KGC](https://ojs.aaai.org/index.php/AAAI/article/view/11535):
  unseen entities and missing-link prediction motivate external expansion.
- Yang et al., [open-world KGC evaluation](https://papers.nips.cc/paper_files/paper/2022/hash/378226e5df7eded3e401de5c9493143c-Abstract-Conference.html):
  unknown triples include missing facts, so closed-world metrics mislead.
- Poveda-Villalón et al., [OOPS!](https://www.semantic-web-journal.net/content/oops-ontology-pitfall-scanner-supporting-ontology-evaluation-line):
  structural checks are diagnostics, not domain truth.

## Literature-based and agentic discovery

- Swanson, [Undiscovered public knowledge](https://pubmed.ncbi.nlm.nih.gov/3797213/):
  A-B and B-C literatures can generate testable A-C hypotheses.
- Smalheiser, [LBD review](https://pmc.ncbi.nlm.nih.gov/articles/PMC5771422/):
  open/closed discovery and contextual evaluation.
- Kim and Song, [context-based ABC](https://pmc.ncbi.nlm.nih.gov/articles/PMC6481912/):
  raw co-occurrence creates irrelevant paths; context improves precision.
- STORM and Co-STORM, [project](https://github.com/stanford-oval/storm),
  [STORM](https://aclanthology.org/2024.naacl-long.347/), and
  [Co-STORM](https://aclanthology.org/2024.emnlp-main.554/): multi-perspective
  questions, mind maps, and unused information expose unknown unknowns.
- InfraNodus [LLM Wiki skill](https://github.com/infranodus/skills/blob/master/skill-llm-wiki/SKILL.md):
  content-gap, weak-coverage, disconnected-cluster, and missing-source patterns.

Keep graph absence `unknown`; separate deterministic gaps from implicit
candidates; require confirm and refute routes; retain context, n-ary conditions,
version, and time; and treat model suggestions as proposals. Evaluate withheld
node/edge recovery, Precision@K, alias and already-covered false positives,
unknown-vs-negative accuracy, locator audit, replay determinism, and zero
novelty overclaim.


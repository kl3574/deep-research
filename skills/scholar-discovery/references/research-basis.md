# Research basis for scholar discovery

Verify live provider documentation before changing adapters because limits and
schemas drift.

- Google Scholar, [Search Help](https://scholar.google.com/intl/us/scholar/help.html):
  search operators, cited/related/version paths, the 1,000-result display cap,
  no bulk access, and the instruction to respect robots.txt.
- OpenAlex, [searching](https://developers.openalex.org/guides/searching),
  [authentication](https://developers.openalex.org/api-reference/authentication),
  and [pagination](https://developers.openalex.org/guides/page-through-results):
  broad scholarly discovery and current cursor, access, and cost behavior.
  Current live policy requires `OPENALEX_API_KEY` for reliable access; include as
  query parameter `api_key` only in the transport layer when present.
- Semantic Scholar, [Academic Graph API](https://api.semanticscholar.org/api-docs/):
  relevance search, recommendations, identifiers, references, and citations.
- Crossref, [REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
  and [versioning guidance](https://www.crossref.org/documentation/principles-practices/best-practices/versioning/):
  DOI identity, updates, corrections, retractions, and typed relationships.
- OpenCitations, [Index API v2](https://api.opencitations.net/index/v2):
  auditable forward and backward citation expansion.
- Ai2 [Asta Paper Finder](https://github.com/allenai/asta-paper-finder):
  structured intent, planner/router separation, query reformulation, and
  known-item, semantic, metadata, author, and citation-neighborhood routes.
- FutureHouse [PaperQA2](https://github.com/Future-House/paper-qa): iterative
  search, redundant metadata providers, retraction checks, and reranking. Its
  full-text RAG belongs downstream.
- Stanford [STORM](https://github.com/stanford-oval/storm): perspective-guided
  question generation and modular retrieval interfaces.
- ASySD, [code](https://github.com/camaradesuk/ASySD) and
  [evaluation](https://pmc.ncbi.nlm.nih.gov/articles/PMC10483700/): conservative
  multi-field deduplication.
- Cormack et al., [Reciprocal Rank Fusion](https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/):
  fusion of heterogeneous ranks without averaging incomparable native scores.
- PRISMA-S, [search reporting extension](https://pmc.ncbi.nlm.nih.gov/articles/PMC8270366/):
  query, platform, date, count, deduplication, and update provenance. Reusing
  these fields does not make targeted work systematic.

Evaluate known-item resolution, work-family clustering, false merge/split
rates, provider failures, count reconciliation, provenance completeness, and
ranking stability. [AstaBench](https://github.com/allenai/asta-bench) can support
forward tests but cannot prove live-domain completeness.

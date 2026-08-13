# Agentic research systems review — 2026-08-13

## Scope and evidence policy

This is a bounded architecture review for improving this repository's skill
suite. It is not a product leaderboard or a systematic review. Product help and
vendor blogs establish visible features or disclosed design only; they do not
prove hidden implementation, citation entailment, completeness, or current
benchmark superiority. Technical claims below use official documentation,
official engineering accounts, owner repositories, or primary research.

Evidence labels:

- **F** — current official product or interface contract;
- **A** — disclosed architecture or owner implementation;
- **E** — primary evaluation evidence;
- **M** — vendor-reported result or marketing claim that needs independent
  validation.
- **I** — a bounded inference from the cited public material rather than a
  disclosed product or architecture fact.

## Product and research-agent comparison

Each semicolon-delimited assertion below carries its own label. The entire
design-lesson column is **I**: it is this review's inference, not a disclosed
feature of the compared system.

| System | Publicly supported pattern | What it does not establish | Design lesson (**I throughout**) |
| --- | --- | --- | --- |
| [ChatGPT deep research](https://help.openai.com/en/articles/10500283-deep-research-in-chatgpt) and [OpenAI API guide](https://developers.openai.com/api/docs/guides/deep-research) | **F:** select source domains, review/edit a proposed plan, observe and interrupt progress, and inspect citation output. **F:** the API exposes background mode, tool-call output, a tool budget, and separate public-web/private-MCP routes | Whether the hosted controller is single- or multi-agent; whether an inline citation entails the whole nearby statement | **I:** make the plan, source domains, progress, interruption, effort envelope, and public/private execution split explicit |
| [OpenAI deep research system card](https://openai.com/index/deep-research-system-card/) | **A:** describes multi-step browsing over text, images, and PDFs plus code execution. **E:** reports owner-run safety evaluations for prompt injection, privacy, hallucination, and code. **M:** reported scores remain vendor evidence until independently reproduced | Current 2026 product internals or general scientific reliability | **I:** adversarially test retrieved instructions and cross-domain data flow, not only report prose |
| [Anthropic multi-agent research](https://www.anthropic.com/engineering/multi-agent-research-system) | **A:** an orchestrator delegates independent breadth-first branches, workers compress isolated contexts, a citation pass follows synthesis, and checkpointing supports long runs. **M:** the reported 90.2% internal gain is a vendor result, not an independent general benchmark | That multi-agent is best for dependent tasks; citation post-processing is not proof of entailment | **I:** use manager-workers only for genuinely independent gaps; measure quality, duplicate work, tokens, and critical path against a single-controller baseline |
| [Claude Research](https://www.anthropic.com/news/research) and [Claude Code subagents](https://code.claude.com/docs/en/sub-agents) | **F:** Research advertises iterative web/connected-context search. **F:** Claude Code documents isolated subagent contexts, foreground/background behavior, session recovery, worktrees, sandboxes, and permissions | Scholarly coverage or citation correctness; coding-agent persistence can preserve wrong memory as easily as correct state | **I:** adopt isolated worker contexts, explicit permissions, durable receipts, and independent validation; do not treat coding-harness features as research evidence |
| [Gemini Deep Research API](https://ai.google.dev/gemini-api/docs/deep-research) | **F:** plan–search–read–iterate–synthesize, collaborative plan approval, asynchronous execution, effort profiles, and documented search/time envelopes | Hosted planner and stopping internals; older product blogs conflict with the current API on some features, so current docs control | **I:** add an effort profile and plan approval gate, but bind actual budgets instead of copying vendor tier numbers |
| [Google Deep Researcher](https://arxiv.org/html/2507.16075) | **A:** plan-conditioned query generation, iterative draft/search revision, parallel candidate trajectories, judge feedback, and an iteration stop. **E:** the paper evaluates those components and reports weak judge–human correlation | A search-only research prototype is not the production Gemini controller | **I:** retain claim diffs and a counterevidence lane so early draft errors do not become unchallenged search anchors; calibrate judges with humans |
| [Perplexity Advanced Deep Research](https://www.perplexity.ai/help-center/en/articles/13600190-what-s-new-in-advanced-deep-research) and [DRACO](https://research.perplexity.ai/articles/evaluating-deep-research-performance-in-the-wild-with-the-draco-benchmark) | **F:** clarification, mid-run follow-ups, visible progress, code/file tools, and editable reports. **E:** DRACO defines task rubrics for accuracy, breadth/depth, presentation, and primary citations. **M:** its owner-reported product results need independent replication | A disclosed planner/state/stopping algorithm; DRACO is vendor-built, English, single-turn, and snapshot-dependent | **I:** make user steering first-class and use task-specific rubrics, while retaining independent and deterministic graders |
| [Microsoft Magentic-One](https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/) | **A:** an orchestrator keeps task and progress ledgers, assigns specialized web/file/code/terminal agents, and re-plans after repeated stalls. **E:** AutoGenBench evaluates isolated repetitions | Long-form research or citation quality; it is a generalist agent system | **I:** separate semantic state from progress state, detect stalls mechanically, and inject failure/recovery in evaluation |
| Genspark [Workspace 6.0](https://www.genspark.ai/blog/genspark-ai-workspace-6), historical [Deep Research v2](https://www.genspark.ai/es/blog/genspark-autopilot-agent-deep-research-v2), [orchestration account](https://www.genspark.ai/blog/genspark-less-control-more-tools), and [parallel calls](https://www.genspark.ai/blog/genspark-parallel-tool-calls) | **F:** the current Workspace 6.0 surface advertises persistent SecondBrain context, Super Agent, suites, and GenTeam. **A:** older owner accounts describe plan–execute–observe–backtrack, capability routing, and dependency-aware parallel calls. **M:** autonomy, scale, speed, and reliability claims remain vendor claims | Reproducible state, stopping, conflict resolution, source independence, citation entailment, or independently verified reliability; the 2025 Deep Research page is historical, not the current product contract | **I:** borrow the dependency-aware parallelism rule; do not use model agreement, source count, or product-scale claims as evidence quality |
| Current [Kimi Deep Research](https://www.kimi.com/help/deep-research/deep-research-overview), [Kimi-Researcher](https://moonshotai.github.io/Kimi-Researcher/), and [Kimi K2.5 report](https://arxiv.org/html/2602.02276) | **F:** current Deep Research documents clarification, visible search terms/URLs, asynchronous execution, cited reports, and interactive output. **A:** the research reports disclose search/browse/code control, context pruning, resumable partial rollouts, sandboxed training, critical-path rewards, and context-sharded workers. **E:** those papers report bounded research/agent evaluations. **M:** advertised source counts, scale, and comparative results remain owner-reported | That the current hosted product inherits every research-prototype detail; single-vendor benchmark configurations are not fully comparable | **I:** track critical-path steps rather than agent count, validate compression fidelity, and preserve a typed worker card containing qualifiers and conflicts |
| [Kimi Agent Swarm help](https://www.kimi.com/help/agent/agent-swarm) | **F:** visible task lists, subagent spawning, and progress. **M:** very large advertised agent/tool-call counts are vendor scale claims | Coverage, independence, or citation correctness | **I:** treat scale as an operating cost, not a quality metric |
| [Doubao Seed 2.0](https://seed.bytedance.com/zh/blog/seed-2-0-official-launch) | **F:** the owner documents Pro/Lite/Mini roles and an Expert-mode research use case. **M:** stronger long-context/multi-step capability and first-party agent benchmark results are vendor claims | A public independent deep-research planner, visible action trace, interruption/resume contract, citation audit, counterevidence lane, or stopping rule | **I:** treat the model and product entry point as known but the research controller as unknown; do not import UI or citation behavior from adjacent agents |
| [OpenCode agents](https://opencode.ai/docs/agents/) | **F:** docs expose Plan/Build roles, exploration subagents, child sessions, compaction, tool/path/MCP permissions, and a doom-loop permission | Deep-research source governance or scholarly quality | **I:** reuse permission, subcontext, and loop-recovery ideas; retain this suite's separate evidence owners and appraisal gates |
| [LangGraph persistence and interrupts](https://docs.langchain.com/oss/python/langgraph/persistence) | **F:** docs expose per-step checkpoints, threads, pending writes, recovery, and time travel. **A:** the owner design uses isolated subagents and filesystem-backed context | A framework feature is not a research result, and custom tools may bypass built-in permissions | **I:** give resume a typed cursor and terminal receipts; test that successful siblings are not rerun after interruption |
| [Elicit systematic review workflow](https://elicit.com/blog/systematic-review/) and [PRISMA guidance](https://elicit.com/blog/systematic-review-for-prisma-2020) | **F:** product guidance covers question/protocol, multi-database search, screening, extraction, evidence sentences, human override, and synthesis. **M:** claims of PRISMA alignment and review efficiency remain vendor claims | That semantic search alone achieves systematic-review recall or that vendor evaluation generalizes beyond its corpus | **I:** add an explicit academic protocol selector; reserve “systematic” for a prespecified, replayable screening/extraction process |
| [PaperQA2 and ContraCrow](https://arxiv.org/html/2409.13740) | **A:** paper search, evidence gathering, query-conditioned summaries, citation traversal, insufficient-information output, and active contradiction search. **E:** the paper evaluates those components on bounded benchmarks | General superhuman science; some contradiction checks remain overconfident | **I:** preserve evidence cards and insufficient-information states; make counterevidence an explicit lane rather than an optional final query |
| [Consensus Research Agent](https://help.consensus.app/en/articles/12641232-research-agent) | **F:** structured chained search over scholarly metadata, citations, similar papers, author/DOI routes, and study filters | Planner state, stop criteria, recall, or claim-source entailment | **I:** route scholarly discovery through several documented, deduplicated paths but keep candidates discovery-only until full-text review |
| [AstaBench](https://allenai.org/asta/bench) | **A:** separates paper finding, long-form ScholarQA, code reproduction, data analysis, and end-to-end discovery. **E:** reports tools, costs, traces, scorer versions, and benchmark outcomes | Success on one component implies end-to-end scientific capability; scorer changes can move results | **I:** keep component and end-to-end evaluations separate and bind model, tools, corpus date, scorer, cost, and trace |
| [DeepTRACE](https://arxiv.org/html/2509.04499) and [DeepResearch Bench](https://arxiv.org/html/2506.11763) | **E:** evaluate statement–citation matrices, unsupported claims, citation accuracy/thoroughness, source necessity, one-sidedness, report quality, and instruction following separately | Final answer truth, universal grader accuracy, or current product rankings | **I:** use an atomic `ReportCitationAudit/v1`; calibrate LLM graders on human samples and keep deterministic identity/version/locator checks |
| [DeepResearchGym](https://arxiv.org/abs/2505.19253) | **A:** provides a stable retrieval corpus and reproducible evaluation environment. **E:** reports report-quality and faithfulness measurements | Live-web currentness or adversarial drift | **I:** maintain both a frozen replay lane and a live adversarial lane |
| [BrowseComp](https://openai.com/index/browsecomp/) and [Anthropic's contamination analysis](https://www.anthropic.com/engineering/eval-awareness-browsecomp) | **E:** hard web search benefits from test-time exploration; web-enabled agents can also find leaked benchmark material and unintended answer paths; parallelism increases exposure | Comprehensive research quality or uncontaminated performance | **I:** treat benchmark integrity as an ongoing adversarial problem; inspect trajectories and block benchmark artifacts in clean evaluations |

## Cross-system synthesis

**I:** the most defensible shared architecture inferred from this bounded sample is:

```text
visible contract and source permissions
  -> plan/approval gate when material
  -> effort and safety envelope
  -> adaptive gap controller
  -> conditional independent parallelism
  -> context-sharded evidence cards
  -> centralized claim/conflict merge
  -> counterevidence lane
  -> atomic claim-citation audit
  -> bounded stop or explicit partial state
  -> independent presentation/release/install audit
```

Against the sampled public product documentation above, this repository already
made claim/evidence, exact-locator, counterevidence, independent appraisal, and
mutation-governance boundaries more explicit. This bounded comparison therefore
led to targeted runtime controls rather than replacing the evidence pipeline:

1. a visible plan/approval decision instead of unconditional clarification;
2. `simple/comparison/complex` effort envelopes with actual numeric budgets;
3. explicit single-controller/manager-workers/fixed-workflow/swarm selection;
4. public/private/code/mutation execution-domain separation;
5. critical-path and checkpoint/recovery semantics;
6. statement×source citation evaluation and counterevidence balance;
7. distinct ordinary/rapid/scoping/systematic academic protocols;
8. frozen and live adversarial evaluation lanes;
9. a new evidence-bound `$research-workflow-retrospective` skill that converts
   real incidents into owner-placed, test-ready improvements.

## Negative controls retained

- Several models agreeing is not independent evidence.
- Several agents reading one source lineage are not several confirmations.
- More agents, tools, URLs, citations, tokens, or report pages do not prove
  correctness, coverage, balance, or entailment.
- A citation post-processor cannot repair an unsupported claim.
- A framework's persistence or sandbox feature does not prove research quality.
- A scholarly database/filter does not make a review systematic.
- A static benchmark score does not remain current after model, search backend,
  corpus, budget, or scorer changes.
- Two no-add rounds are a disclosed stopping heuristic only when routes are
  pre-audited, orthogonal, complete, and free of provider-partial failures.

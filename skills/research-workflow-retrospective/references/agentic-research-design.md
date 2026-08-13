# Current agentic-research design evidence

This reference records transferable design lessons, not a product ranking. Check
the live official sources before making current product claims.

## Patterns with strong public support

- **Plan, search, inspect, identify gaps, and re-plan.** OpenAI and Google expose
  deep research as long-running, multi-step investigation rather than one-shot
  retrieval. User-visible plan review, progress, interruption, and source
  boundaries improve steerability.
- **Parallelize independent breadth, not every task.** Anthropic's published
  orchestrator-worker research system uses parallel subagents as independent
  filters and reports a strong gain on breadth-first tasks. Its engineering
  account also emphasizes token cost, coordination, tool design, and evaluation.
  LangGraph documentation likewise warns that a single agent with the right
  context and tools can be enough.
- **Separate roles and contexts.** Microsoft Magentic-One separates planning,
  progress tracking, web/file navigation, and code execution. Kimi's published
  research describes context management and dynamic parallel scaling. The
  transferable lesson is bounded context and specialist ownership, not agent
  count as a quality metric.
- **Use fine-grained rubrics.** Anthropic's evaluation guidance combines
  groundedness, coverage, and source-quality graders. Perplexity DRACO uses
  factual accuracy, breadth/depth, presentation, and primary-source citation
  criteria. Deep-research benchmarks increasingly score claim-citation
  correctness separately from report quality.
- **Preserve reproducibility lanes.** DeepResearchGym uses a stable corpus and
  retrieval environment because live commercial search results drift. Microsoft
  AutoGenBench emphasizes repetition and isolation. Run frozen and live lanes for
  different claims.
- **Keep human steering and permission gates.** ChatGPT, Claude, Gemini, coding
  agents, and browser agents expose various plan, progress, source, permission,
  sandbox, and interruption controls. These are operational safeguards, not
  evidence that the final research is correct.

## Product evidence boundaries

- Genspark, Kimi, Doubao, ChatGPT, Claude/Claude Code, and similar products expose
  useful workflow ideas, but public detail varies sharply. Treat help pages and
  product blogs as evidence of visible capability only. Do not infer hidden
  planner topology, stopping rules, citation validation, or benchmark quality.
- OpenCode and Claude Code primarily inform permission, sandbox, subcontext, and
  resumability design. They are not by themselves evidence for scholarly search
  completeness or claim-source entailment.
- Academic assistants such as Elicit, Consensus, AI2/Asta, PaperQA/FutureHouse,
  and related systems are most useful where they publish task definitions,
  retrieval corpora, claim/citation checks, or expert evaluation. Product source
  counts and long reports are not substitutes for evidence balance.

## Evaluation cautions

- BrowseComp measures hard-to-find web facts, not comprehensive scientific
  synthesis. Anthropic documented benchmark-answer discovery and a higher rate of
  unintended solutions in a multi-agent configuration; maintain contamination
  controls and inspect trajectories.
- Static scores do not prove current live behavior. Record model/tool versions,
  source restrictions, search date, run count, and whether the benchmark corpus
  was visible to the agent.
- LLM judges need human calibration, deterministic checks where possible, and
  independent graders. Separate factual accuracy, citation entailment, coverage,
  source quality, instruction following, and presentation.

## Primary and official starting points

- OpenAI, Deep research system card:
  https://openai.com/index/deep-research-system-card/
- OpenAI, BrowseComp:
  https://openai.com/index/browsecomp/
- Anthropic, multi-agent research system:
  https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, agent evaluations:
  https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic, BrowseComp eval awareness:
  https://www.anthropic.com/engineering/eval-awareness-browsecomp
- Google, Gemini Deep Research agent and DeepSearchQA:
  https://blog.google/innovation-and-ai/technology/developers-tools/deep-research-agent-gemini-api/
- Microsoft Research, Magentic-One:
  https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/
- LangChain, multi-agent patterns:
  https://langchain-ai.github.io/langgraph/tutorials/multi_agent/multi-agent-collaboration/
- Perplexity, DRACO benchmark:
  https://research.perplexity.ai/articles/evaluating-deep-research-performance-in-the-wild-with-the-draco-benchmark
- DeepResearchGym paper:
  https://arxiv.org/abs/2505.19253

These sources support the general patterns above. Product-specific additions
must retain their own source, date, and evidence level in each retrospective.

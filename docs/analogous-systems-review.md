# 外部同类系统审计：从文献语料到可审计知识网络

状态：`v0.6.0` 候选设计审计  
证据截点：2026-08-05  
范围：只比较项目官方文档、官方仓库及作者原始论文；不以聚合榜单、二手测评或营销摘要代替能力证据。

## 结论

在本次审查的一手来源中，**没有发现一个单一 Agent Skill 或单一研究系统，同时声明并验证以下完整闭环**：

`Zotero corpus -> 全文深读 -> 带极性的类型化证据网络 -> 开放世界缺口假设 -> 定向学术发现与合法全文获取 -> Zotero 精确目标写入与读回`

这是对下述项目和当前公开材料的有界负结论，不是对所有未审查产品的“不存在证明”。最接近的能力需要组合：PaperQA2 可只读查询 Zotero 语料并执行科学 RAG，ORKG 可保存机器可操作的研究贡献与比较，ASReview 可做主动筛选，STORM/Co-STORM 可做多视角问题发现，Open Deep Research 可做灵活规划、上下文压缩和报告评测；它们没有共享一套能够贯穿上述闭环的类型化状态、治理接受和写后读回契约。

因此，当前项目保持“正交技能组 + 有检查点的场景工作流”比继续膨胀一个 `$deep-research` 巨型技能更合理。`$deep-research` 负责跨来源控制与综合，全文获取、文档规范化、单篇深读、网络维护、开放世界查漏、Zotero 写入和发布分别由独立技能负责。

## 判定方法

只有一手来源明确描述的能力才记为直接支持。能生成带引用文章，不等于能生成原子主张和证据极性；动态 mind map 不等于受治理的证据网络；能从 Zotero 读取 PDF，不等于能向精确 collection 写入并读回；停止启发式也不等于开放世界完整性证明。

符号：`●` 为直接支持，`○` 为相邻或部分能力，`-` 为本次一手材料未声明。

| 系统 | Zotero/既有语料 | 全文证据定位 | 类型化证据网络 | 开放世界缺口 | 定向发现/筛选 | 精确写入与读回 |
| --- | --- | --- | --- | --- | --- | --- |
| LangChain Open Deep Research | ○ 可接搜索/MCP | ○ 面向报告的来源上下文 | - | ○ 灵活规划与反思 | ● | - |
| STORM / Co-STORM | ○ Web 或用户文档 retriever | ○ 引用支撑的信息策展 | - 动态 mind map 不是证据图 | ○ 多视角问题与 unknown unknowns | ● | - |
| FutureHouse PaperQA2 | ● 本地文件；Zotero 只读查询 | ● metadata-aware 检索、重排、页码引用 | - | ○ 可查询矛盾，不维护开放世界 GapQueue | ● 查询扩展与引文遍历 | - |
| ASReview | ○ 题录/摘要数据集 | - | - | - | ● 主动筛选、停止、模拟 | ○ 导出筛选数据，不是 Zotero 事务读回 |
| ORKG | ○ 论文/DOI/CSV 贡献录入 | - | ● triples、templates、comparisons | - | - | ○ ORKG 内发布，不是来源库双向同步 |
| Agent Skills 规范 / Microsoft guidance | - | - | - | - | - | - 这是包装与执行治理规范 |

## 逐项对照与取舍

### 1. LangChain Open Deep Research：规划、压缩和 benchmark

官方仓库把 summarization、research、compression 和 final report 分为可独立配置的模型角色，并提供 Deep Research Bench 的 100 个中英文任务及 RACE 评分接入。维护者对架构演进的复盘还记录了一个重要失败：按报告章节强制并行研究会产生割裂内容，后续改为灵活规划、多 agent 收集上下文、最后统一写作。当前仓库仍保留早期 plan-and-execute 和 supervisor/researcher 实现供比较，而不是把其中任一结构当成永久最优。

**吸收：** 保持规划可修订；并行化证据收集而非独立写最终结论；压缩和最终综合分离；将成本、token 和报告质量纳入可复现实验。

**不直接照搬：** Deep Research Bench 的报告级 LLM-as-a-judge 不能替代全文身份、页码/字符区间、证据极性、Zotero 副作用和读回验证。强制按文章章节分工也不适合以主张和冲突为中心的知识网络。

一手来源：[官方仓库](https://github.com/langchain-ai/open_deep_research)（访问日期：2026-08-05）；[维护者架构复盘](https://rlancemartin.github.io/2025/07/30/bitter_lesson/)（访问日期：2026-08-05）。

### 2. Stanford STORM / Co-STORM：多视角问题、outline 和协作

STORM 在写作前先发现不同视角，让不同视角的“作者”向有来源约束的“专家”连续提问，再把所得信息整理成 outline。原始论文也明确报告 source bias transfer 和错误关联是仍存在的问题。Co-STORM 进一步引入专家、moderator 和人类共同参与的 discourse protocol；moderator 会从尚未用于对话的检索信息中提出问题，动态 mind map 帮助用户追踪 unknown unknowns。

**吸收：** 初始 field map 不只按关键词拆分，还应按立场、假设、尺度、评价目标和使用者决策视角生成 competency questions；gap cycle 应主动检查“已检索但尚未进入主张”的信息；在最终发布前先形成稳定路线图/outline。

**不直接照搬：** 层级 mind map 是认知导航，不具备来源版本、原子主张、`supports / qualifies / refutes / not_tested`、精确 locator 和治理接受，因此不能作为 canonical evidence network。Wikipedia 式文章生成也不是本项目的主要研究状态。

一手来源：[STORM 官方仓库](https://github.com/stanford-oval/storm)（访问日期：2026-08-05）；[STORM 原始论文](https://arxiv.org/abs/2402.14207)（访问日期：2026-08-05）；[Co-STORM 原始论文](https://arxiv.org/abs/2408.15232)（访问日期：2026-08-05）。

### 3. FutureHouse PaperQA2：metadata-aware evidence retrieval

PaperQA2 是本次对照中最值得作为“语料内证据检索层”参考的系统。官方实现会为本地 PDF 获取 Crossref、Semantic Scholar 等元数据，建立全文索引，先用嵌入检索 chunk，再用 LLM 同时重排和生成 contextual summary，最后以少量高相关证据回答。它支持迭代 query expansion、引文图遍历、页码引用和 contradiction 模式。作者论文以 LitQA2、文献综述写作和矛盾检测做了人与 agent 的对照评测。

PaperQA2 也确实有 Zotero 支持，但边界需要说清：官方教程使用 `paperqa.contrib.ZoteroDB` 和具有**只读权限**的 Zotero API key 查询条目，再把已有 PDF 加入 `Docs`。教程要求 PDF 已在 Zotero 中可用；它没有声明把结构化主张、笔记、附件修复或 collection membership 写回 Zotero，也没有写后读回契约。

**吸收：** 在大语料场景增加可选的 metadata-aware chunk retrieval、重排和 contextual summary 层；以页码/原文 span 验证重排结果；用 contradiction query 主动寻找反证；把 locator recall、citation precision 和问题回答正确率分别评估。

**尚未吸收：** 当前技能组依赖问题驱动深读和独立 locator 验证，没有一套经过基准验证的学习式 corpus reranker。只有在固定语料评测中证明提升 locator recall 且不降低引用精度后，才应新增独立的 `scholarly-corpus-retrieval` 能力，而不是把向量库塞进 `$learn-from-papers`。

**不直接照搬：** citation count 和 journal quality 可作为检索上下文或风险提示，不能提升一条主张的证据等级；contextual summary 仍是派生文本，不能替代原文 span；矛盾回答不自动形成持久化冲突状态。

一手来源：[PaperQA2 官方仓库](https://github.com/Future-House/paper-qa)（访问日期：2026-08-05）；[官方 Zotero 教程](https://github.com/Future-House/paper-qa/blob/main/docs/tutorials/where_do_I_get_papers.md)（访问日期：2026-08-05）；[作者工程说明](https://www.futurehouse.org/research/engineering-blog-journey-to-superhuman-performance-on-scientific-tasks)（访问日期：2026-08-05）；[原始论文](https://arxiv.org/abs/2409.13740)（访问日期：2026-08-05）。

### 4. ASReview：active screening、停止与模拟

ASReview 把用户的相关/不相关标签作为 oracle 信号，循环训练模型并优先展示最可能相关的记录。它的 simulation mode 使用全标注数据集比较模型组合和工作量节省；当前文档允许设置“自上一个相关记录后连续多少条不相关”的停止阈值，同时明确说明理想阈值仍在研究，应参考相近主题的模拟。

**吸收：** 对大候选池，将候选筛选视为有反馈的序贯决策；在有历史全标注语料时回放检索与排序策略；同时报告 recall 风险、work saved、预算和停止理由，而不只报告“找到多少篇”。

**尚未吸收：** 当前 `$scholar-discovery` 是规则化多源发现和保守排序，不是学习式 active screening，也没有用标注数据校准停止阈值。若未来任务真的是 systematic screening，应新增职责独立的 `research-screening`，输入协议、候选全集和人工标签；普通 targeted research 不应默认触发它。

**不直接照搬：** “连续 N 条不相关”只能是筛选停止启发式。在开放世界知识网络中，不相关记录的连续出现不能证明不存在遗漏节点，不能被写成研究完整性结论。

一手来源：[ASReview 原始论文](https://www.nature.com/articles/s42256-020-00287-7)（访问日期：2026-08-05）；[官方 simulation 文档](https://asreview.readthedocs.io/en/stable/lab/simulation_overview.html)（访问日期：2026-08-05）；[官方停止与进度文档](https://asreview.readthedocs.io/en/stable/lab/progress.html)（访问日期：2026-08-05）。

### 5. ORKG：machine-actionable comparison graph

ORKG 以 subject-predicate-object triples 表示论文、实体和关系；template 为同一 research problem 下的贡献规定共同属性、值约束和 cardinality，使贡献可比较；comparison 可以把多篇论文的贡献并排组织并发布。这为“知识网络不是一张图片，而是可查询的数据结构”提供了成熟参照。

**吸收：** 保持实体、主张、证据和关系类型化；让 coverage dimension 与 competency question 可机器计算；对同一问题的路线使用显式比较 schema，而不是自由文本表格。

**尚未吸收：** 当前 `KnowledgeNetwork/v1` 是项目内审计模型，还没有 ORKG/RDF 映射、ontology alignment 或 round-trip loss test。只有出现对外互操作需求时才增加独立 `research-graph-interop` adapter。

**不直接照搬：** ORKG contribution template 不能自动证明原文支持；公共图谱也不应成为包含私有 Zotero key、全文 locator 或未审查推断的 canonical store。导出必须是经验证网络的有损、隐私安全投影。

一手来源：[ORKG knowledge graph 概念](https://academy.orkg.org/concepts/knowledge-graph.html)（访问日期：2026-08-05）；[ORKG template 文档](https://academy.orkg.org/courses/template-course.html)（访问日期：2026-08-05）；[ORKG comparison 教程](https://academy.orkg.org/tutorials/comparison-tutorial-ii.html)（访问日期：2026-08-05）；[ORKG 原始系统论文](https://doi.org/10.1145/3360901.3364435)（访问日期：2026-08-05）。

### 6. Agent Skills 规范与 Microsoft guidance：技能不是长事务工作流

Agent Skills 官方规范把 `SKILL.md`、`scripts/`、`references/` 和 `assets/` 作为便携单元，并以 progressive disclosure 依次加载 metadata、技能正文和按需资源。Microsoft Agent Framework 进一步给出明确分界：skill 由模型自适应执行，适合聚焦、低风险或幂等能力；workflow 显式规定路径，支持 checkpoint，适合高成本重试、多 agent、人类审批和有副作用的流程。Microsoft skills 仓库还为每个技能维护 acceptance criteria 和场景，按失败反馈迭代，而不只检查 frontmatter。

**已吸收：** 当前九个研究技能职责正交，入口保持短小，详细依据和脚本按需加载；跨技能真实任务使用不可变 pipeline state 和 append-only run ledger；Zotero 写入保持 preview、授权、版本/哈希和 readback 门。

**仍需加强：** 把每个技能的 trigger、anti-trigger、成功条件、禁止副作用和失败分类固化为统一 acceptance scenario；跨技能评测同时检查语义结果、恢复能力和副作用，而不是只跑 schema validator。

**不直接照搬：** 不把整条研究闭环包装成一个超长 `SKILL.md`；不因脚本通过结构测试就声称科学理解正确；不允许技能自身无门更新高影响外部状态。

一手来源：[Agent Skills 官方规范](https://agentskills.io/specification)（访问日期：2026-08-05）；[Agent Skills 官方仓库](https://github.com/agentskills/agentskills)（访问日期：2026-08-05）；[Microsoft skills 与 workflows 指南](https://learn.microsoft.com/en-us/agent-framework/agents/skills)（访问日期：2026-08-05）；[Microsoft skills acceptance-eval 仓库](https://github.com/microsoft/skills)（访问日期：2026-08-05）。

## 已吸收、真实验证与剩余缺口

### 已吸收到 `v0.6.0` 候选的机制

| 外部机制 | 当前对应设计 | 当前判断 |
| --- | --- | --- |
| Open Deep Research 的灵活规划、独立压缩与统一最终综合 | `ResearchScenario/v1`、分阶段 pipeline、受控 handoff、最终网络发布 | 已吸收架构原则；尚无通用报告 benchmark |
| STORM 的多视角问题和 pre-writing outline | field map、separating dimensions、competency questions、route map | 已吸收；尚无 perspective coverage 指标 |
| PaperQA2 的元数据意识、页码引用和矛盾检索 | source/version identity、全文 locator、claim polarity、countercheck | 已吸收证据契约；未吸收学习式 reranker |
| ASReview 的预算、停止和 simulation 思路 | gap/action budget、两轮无决策增益停止、real-world regression | 部分吸收；停止未做 recall 校准 |
| ORKG 的类型化、可比较、机器可操作状态 | `KnowledgeNetwork/v1`、coverage/conflict/gap、确定性 HTML 投影 | 已吸收项目内模型；未做标准图谱互操作 |
| Agent Skills 的 progressive disclosure 与 skill/workflow 分界 | 九个正交技能、references/scripts、不可变 pipeline state、恢复账本 | 已吸收并因真实故障强化 |

### 本次真实场景验证，不是边界演示

`v0.6.0` 候选在 DoE 与代理模型调研的真实 Zotero 语料上前向运行，产生了以下可审计证据：

- 对 28 个既有父条目和笔记做只读快照，语义投影形成 54 个原子主张、8 个冲突和 12 个待查缺口；这证明 gap 不是从空元数据字段直接猜出的搜索词。
- 新获取并验证 13 份原始 PDF；另有 11 份既有损坏附件完成替代文件的身份、PDF magic 和 SHA-256 暂存验证。审计截点尚未把 Zotero 事务 apply/readback 计为通过。
- 文档质量门实际发现 pathological text 和 blank scan，并生成保留原件、衍生件哈希与工具参数的 OCR lineage，而不是让错误抽取静默进入深读。
- 三个深读批次的独立证据检查分别通过 24/24、21/21 和 28/28 个最终主张；最初失败的宽泛主张被收窄后重验，没有以“整体阅读成功”掩盖局部失败。
- 初始 topic compiler 曾把结构缺失字段编译成无意义检索；真实检索失败促成 competency-question-backed semantic topic needs。Google Scholar 路径不可自动执行时保留 manual-only 状态，没有把其他 API 结果伪装成 Scholar。
- 真实下载暴露总 deadline 超限和残留 `.part`，随后加入单调时钟总期限、socket shutdown 和清理验证；受限网络只允许显式、无凭据 loopback proxy profile。
- 真实批处理暴露“前一事件已提交、后一事件失败”的 ledger 状态，随后加入逐命令 JSONL receipt、pre/post digest、partial commit 和可冲突检测恢复。

这些结果验证的是故障可见性、证据链和恢复机制，不等于本审计截点已经完成最终 Zotero 写回、最终网络 merge、HTML 发布、全套回归和 release。最终发布必须以那些独立门的实际输出为准。

### 仍缺失，按优先级排序

1. **P0：语料内证据召回基准。** 用固定问题、专家标注 locator 和反证构造 corpus retrieval eval，对比当前问题驱动深读与 PaperQA2 式检索/重排；指标至少分开 locator recall、citation precision、contrary-evidence recall、成本和压缩损失。
2. **P0：真实闭环 acceptance eval。** 至少一个授权 Zotero 场景必须从 snapshot 运行到导入、附件/笔记、collection membership、readback 和幂等复跑，并注入目标漂移、重复 DOI、坏 PDF、部分提交和网络失败。
3. **P1：压缩保真测试。** 对 Open Deep Research 式 context compression 增加不可丢字段、主张极性、locator 和反例保持率；token 减少不能单独作为成功。
4. **P1：多视角覆盖。** 为 STORM 式 perspective discovery 定义 coverage，而不是只生成更多问题；检查理论/实验、支持/反证、尺度、输入约束、失败模式和使用决策是否都有证据。
5. **P1：主动筛选作为可选独立技能。** 只有 systematic-review 协议、候选全集和标注反馈齐备时，评估 ASReview 式 active screening 与停止校准；不要让它污染普通 targeted research。
6. **P2：图谱互操作。** 在有真实消费者时实现 ORKG/RDF adapter，并测试 `KnowledgeNetwork -> external graph -> readback` 的类型和证据损失；此前不增加维护面。

## 明确不吸收的做法

- 不用单一巨型 skill 取代正交技能和可恢复 workflow；这会同时破坏 progressive disclosure、职责边界和副作用治理。
- 不把 citation count、venue 或 journal quality 当成证据可靠性的代理；它们最多是检索和风险上下文。
- 不把 contextual summary、Wikipedia 式报告或 mind map 当成原文证据，也不从这些派生物反推精确 locator。
- 不用单一 LLM judge 分数验收研究闭环；报告质量分数无法验证 source identity、claim polarity、附件字节和 Zotero readback。
- 不把 ASReview 的停止阈值或“两轮没有新结果”表述为开放世界完整性；只能称为有预算的 pragmatic saturation。
- 不把公共 ORKG 或任何外部图谱设为私有研究状态的 canonical store；先做隐私安全、经治理接受的投影。

## 对后续技能拆分的决策规则

新增技能必须同时满足三个条件：有独立输入/输出契约，有不应授予相邻技能的权限，且真实评测证明当前组合存在稳定瓶颈。按此规则，`scholarly-corpus-retrieval`、`research-screening` 和 `research-graph-interop` 都只是有条件候选，不应在没有基准或真实消费者时预先加入目录。跨阶段顺序、checkpoint、重试和外部副作用属于 workflow/runtime，不应继续写进一个更长的 `$deep-research` 提示词。


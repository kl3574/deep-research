# research-knowledge-network 设计与评估记录（2026-08-04）

## 1. 问题定义

- `deep-research` 要在已有 Zotero 文献基础上形成“可持续学习—可审计决策—可闭环执行”的研究能力。
- 现有单技能覆盖不足以同时承接四类职责：检索与范围控制、单篇重构、知识图谱治理、以及 Zotero 实体落地。
- 目标是用四技能正交拆分，避免一个技能承担无法可控的全栈责任。

## 2. 候选系统矩阵（参考采样）

| 系统 | 成熟度 | 强项 | 不能直接解决的部分 | 采用方式 | 许可证 |
| --- | --- | --- | --- | --- | --- |
| llm-for-zotero | 中高（维护较久） | grounded citations、coverage/state 框架、语料层治理思路 | 与本仓库授权目标不一致 | 清洁室抽取 evidence 分层与状态轨迹思路 | AGPL-3.0 |
| Microsoft GraphRAG | 高 | 文档-实体-关系-社区分层、社区检索策略 | 无专门缺口治理与科研任务工况映射 | 采用数据模型边界与增量更新理念 | MIT |
| OpenScholar | 中高 | 全文检索、引用溯源、自反馈增强质量 | 非知识网络核心，侧重问答能力 | 采用可复核验证链路模式 | Apache-2.0 |
| PaperQA2 | 中高 | 证据级问答与重引文链处理 | 不替代 GapQueue 与冲突模型 | 采用 citation check 概念化 | Apache-2.0 |
| STORM | 中 | 多视角问题生成和协同拆题 | 未形成持久证据图与闭环治理 | 采用问题生成与复核角度 | MIT |
| HippoRAG | 中 | 图检索、PPR、持续更新思路 | 不是知识网络与策略队列主干 | 采用检索层与排序启发 | MIT |
| ORKG | 中 | 语义贡献对象、比较结构、可机器读模型 | 需绑定到实际端点与许可证策略 | 借鉴实体比较与贡献建模 | 以平台许可为准 |
| GAPMAP | 中（预印本） | 显式/隐式缺口与 Toulmin 式推理框架 | 未达工程成熟度 | 采用缺口分类与反证约束 | 预印本（无明确约束） |
| RAGA | 中（预印本） | Read-Search-Verify-Construct 与图 CRUD 一致性 | 处于探索阶段，缺工程验证闭环 | 采用流程化循环与完整性约束 | 预印本（无明确约束） |
| zotero-mcp | 中 | Zotero 检索/语义检索/存储整合 | 不提供证据网络与缺口治理 | 仅作为采集与传输思路参考 | MIT |
| SeerAI | 中 | 本地优先、系统性回顾 UI、可视化支持 | 缺证据图状态机 | 采用 curator 工作流与清洗提示 | MIT |
| K-Dense scientific skills | 中 | Rival hypotheses、falsification、结构化假设 | 不提供完整控制流 | 采用隐式缺口的验证思维 | MIT |

## 3. 架构决定

- 采用四技能正交拆分。
- `deep-research` 负责领域边界、检索策略、主张-冲突冲刺与停止条件。
- `learn-from-papers` 负责单篇证据级深读，输出可附注到网络的可追溯证据条目。
- `research-knowledge-network` 负责持久化实体关系、覆盖状态、冲突、缺口与可执行优先队列。
- `curate-research-to-zotero` 负责快照、导入、写后读回与本地化同步。

闭环固定为：

`ZoteroCorpusSnapshot -> evidence cards -> KnowledgeNetwork -> GapQueue -> targeted deep research -> curation/readback -> merge/audit`

## 4. schema 与状态机（最小化可执行）

- `Sources`：离线来源登记与可达性说明。
- `Entities`：术语、方法、模型、数据来源。
- `Claims`：从证据卡或人工输入生成的可验证命题。
- `Evidence`：locator、片段类型、可靠性分层、时间戳。
- `Relations`：supports/challenges/replaces/derives/conflicts。
- `Gaps`：explicit/implicit，均有原因、验证条件和优先级。
- `Events`：每次状态变更追加不可变日志。

状态机要点：

- `empty` -> `loaded` -> `normalized` -> `linked` -> `gap_derived` -> `prioritized` -> `investigate` -> `merged` -> `audited` -> `frozen`。
- 状态转换只允许通过 `add_*` 与 `record_gap` 合法命令。
- `audit` 必须在每次归并前后执行。

## 5. 缺口推导护栏

- explicit gap 必须由公开证据和稳定检索范围直接导出；不得来自臆测。
- implicit gap 需要 `grounds / warrant / backing / qualifier / defeaters`。
- implicit gap 不得被当作尚未发表的新事实；只允许作为“缺少何类对照、样例或边界验证”的行动请求。
- 每个 gap 必须绑定可执行测试（搜索、重现实验、术语校验）。
- 对每个缺口必须标注 `max_sweep_depth` 与 `rollback` 条件。

## 6. 测试与发布验收（公开仓库执行边界）

- 文档一致性：`README` 的四技能关系与安装/测试命令保持一致。
- 设计闭环：`research-knowledge-network-design-2026-08-04.md`、`research-basis.md` 同步记录清洁室证据来源和许可边界。
- 运行前置：不提交私有 Zotero ID、PDF、note 内容、个人笔记哈希。
- 真实回归关注方向：稀疏动力学识别与参数校准、WENDy 回归、toy model 场景。

## 7. 拒绝的替代方案

- 拒绝单一大模型一体化技能：会导致检索、记忆、证据合并、仓库同步混杂，难以审计。
- 拒绝“只做网络抓取不做本地证据网络”：回归证据无法在离线工作区重放。
- 拒绝“只做知识图不做 GapQueue”：不会触发可执行收敛。
- 拒绝“只做 GapQueue 不做 Zotero 落库”：可执行性无法闭环。
- 拒绝“直接复用外部系统源码”：许可证和边界不满足本仓库清洁室与可迁移要求。

## 8. 真实回归与迭代结果（2026-08-04 脱敏汇总）

- 真实回归与补全仅基于本地公开可回放材料，未触及私有 artifact；corpus 规模由 59 增加到 62。
- 本轮可审计落点收敛到：10 条 finalized claim、16 条 evidence、8 条 relation。
- 结构覆盖结果为 4/4 的维度已覆盖、4/4 的 benchmark profile 已覆盖。
- top profile 缺口中有 2 个被 3 篇 targeted research evidence 关闭，仍保留 5 个 medium 缺口。
- 任务边界修正后形成 2 条主线：WENDy 与 WSINDy 分离测试。
  - WENDy：聚焦弱形式目标项在含噪声、非光滑项与偏置项条件下的稳定回归验证。
  - WSINDy：聚焦稀疏识别与导数估计耦合边界的可比对基线验证。
- Toy model 回归补齐为 5 个目标模型族，支持后续可复现性分层测试。
- 算法修订方向同步为：
  - DF-SINDy 默认 SI-only 的执行约束；
  - DRGEP reduction 的 adversarial 防错；
  - suggest-next 生成改为高优先级跑分策略，implicit 类型优先 `search_test`，并固定 `novelty=false`。

### 真实回归驱动修复（5 类）
- 修复外部 snapshot path 解析与一致化问题。
- 修复 state/file/identity digest 校验链条。
- 修复 semantic/physical gap ID 编制与映射不一致问题。
- 修复 aggregate coverage 与 Cartesian 扫描边界的统计偏差问题。
- 修复 global priority 的排序与回放一致性问题。

### 回归测试与评估（公开记录）
- deep 模块：`deep53` / `curation173` / `network39` / `root3`。
- 质量检查：`Ruff` + `privacy(8 private identifiers in-memory denylist)` + `quick_validate`。
- 复核策略：independent no-blocking review。
- 插件评测：`deep77/C`、`network72/C`（均为公开验证入口）。
- 明确 `deferred-token / complexity` 的静态 heuristic 仅为先验指标，不得替代真实 outcome evidence。

### 新增公开原始来源（仅标题 + 官方 DOI / arXiv）
- WENDy baseline 相关公开来源（标题 + DOI/arXiv）
- MDBench（官方来源：标题 + DOI/arXiv）
- Benchmarking sparse system identification with low-dimensional chaos（标题 + DOI/arXiv）
- SINDy vs Hard Nonlinearities and Hidden Dynamics（标题 + DOI/arXiv）

### 风险与未完成项
- `59/62` 不是全量深读覆盖；仅为本轮迭代回归可追溯记录。
- 云同步路径与云端一致性未在本轮完成验证。
- `transaction v1 crash journal` 仍需人工审计。
- 未主张“所有 gap 已关闭”；现有网络仍有保留缺口用于下一轮有目标闭环。

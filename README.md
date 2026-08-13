# deep-research

一套面向 Codex agent 的可审计深度调研技能，覆盖十二个核心能力和一个
可选的受约束 Zotero 执行能力：

```text
研究问题
  → $deep-research：全局地图、技术路线、可信源检索、GapQueue 与停止条件
  → $research-knowledge-network：持久化证据网络、coverage 与缺口派生、冲突建模
  → $network-gap-discovery：开放世界查漏、缺失内容假设、反证与 patch proposal
  → $scholar-discovery：多源学术发现、查询留痕、保守去重与候选排序
  → $scholarly-source-acquisition：合法全文获取、PDF身份与哈希验证
  → $scholarly-document-normalization：本地PDF文本质量分类、OCR衍生与谱系验证
  → $learn-from-papers：对关键单篇论文进行证据级深读与重建
  → $evidence-appraisal：对已选主张-证据关系作对抗性审查并产生定向证据需要
  → $research-workflow-retrospective：对完成与失败工作流做可防返工复盘
  → $curate-research-to-zotero：快照、下载、导入、读回，持续同步目标库
  → $repair-zotero-metadata：证据约束的 existing-parent 书目纠错审查
  → $research-network-publish：验证网络的隐私安全自包含 HTML 发布
```

“深度”不是堆积来源，而是把时间和模型开销放在真正控制结论的瓶颈上；“可信”不是固定来源排行榜，而是版本、范围、局部适配和失败边界都能被持续验收。

## 十二个核心技能与一个受约束执行器

| 技能 | 职责 | 典型输入 | 核心产物 |
| --- | --- | --- | --- |
| `$deep-research` | 多来源、全局到具体的针对性深调研 | 领域问题、技术选型、证据争议、版本问题 | 概念地图、技术路线、source registry、claim/evidence matrix、冲突日志、GapQueue |
| `$learn-from-papers` | 给定一篇论文，执行问题驱动且可复核的深度理解 | PDF、DOI、预印本、出版页面 | source bundle、reading dossier、`PaperUnderstanding/v1`、验证记录、金字塔知识笔记输入 |
| `$research-knowledge-network` | 将来源证据、实体、主张、关系持久化为可审计网络并派生知识缺口 | evidence card、术语表、实验摘要、审稿点 | 证据网络、coverage 概览、冲突视图、可复验缺口列表 |
| `$network-gap-discovery` | 在开放世界假设下自主提出并反证可能缺失的节点、关系、边界或证据 | `KnowledgeNetwork/v1`、competency questions、既有 gap | gap hypotheses、定向检索请求、`NetworkPatchProposal/v2` |
| `$scholar-discovery` | 对一个明确证据需要执行可复现的多源论文发现 | gap search test、主题条件、种子论文 | query plan、检索账本、去重 work families、排序候选与失败状态 |
| `$scholarly-source-acquisition` | 将已接受候选合法获取为可复验全文资产 | DOI、开放URL、候选身份 | acquisition plan、PDF magic/大小/哈希、失败状态 |
| `$scholarly-document-normalization` | 分类本地PDF文本质量并生成可追溯OCR衍生物 | 已获取PDF、可选source bundle | 逐页质量、显式skip或searchable PDF谱系、review gate |
| `$evidence-appraisal` | 对已选关系执行 fail-closed 对抗性证据审查 | prepared request、独立 review、owner bundle | `EvidenceAppraisalSet/v1`、挑战、定向证据需要、批准 package |
| `$research-workflow-retrospective` | 对已完成或失败工作流进行复盘并输出可测试改进建议 | 工作流事件、阶段证据、运行工况 | `ResearchWorkflowEvidenceBundle/v1`、`ResearchWorkflowReview/v1` |
| `$curate-research-to-zotero` | 保存经审核的研究资产 | 来源清单、本地文件、Zotero 目标 | 文件哈希、ingestion manifest、PDF/元数据/笔记同步与 readback |
| `$repair-zotero-metadata` | 审查已有 parent 的固定字段书目纠错 | 已验证身份、existing-parent 快照、字段证据 | 私有 reviewed repair source、重复冲突或 bridge handoff |
| `$research-network-publish` | 将验证网络投影为可分享视图 | `KnowledgeNetwork/v1`、可选研究地图 | 自包含 HTML、coverage/gap/conflict 视图、隐私审计 |

十二个核心技能可独立调用，或由 `$deep-research` 统筹。Google Scholar 仅支持用户
手工检索与导出导入；自主检索使用有正式接口的学术数据源，不能抓取 Scholar
结果页或绕过 CAPTCHA。

可选配套执行器 `$zotero-declarative-bridge` 只负责已审核 manifest 的
existing-parent collection membership、书目 `shortTitle`、子笔记、单附件，
以及来自 `$repair-zotero-metadata` 的独立固定 profile parent 修复
事务。本文档对应的目标发布组合为仓库 `v0.8.0` 与 bridge `0.1.11`；候选 XPI 的
确定性 SHA-256 为
`a5aabab25da4b61d321172524a1e961a27420f5887bcb49c76e04e27c70d037c`。
这个摘要只绑定候选构件，不替代真实运行回读。作为历史证据，`v0.6.1` 的
bridge `0.1.4` 完成真实写入，`0.1.5` 在 Zotero `9.0.6` 中完成激活、受约束
probe、正向回读和目标集合成员关系负向回读；详情见
[v0.8.0 release notes](docs/releases/v0.8.0.md)、[v0.7.0 release notes](docs/releases/v0.7.0.md) 与
[historical v0.6.1 release notes](docs/releases/v0.6.1.md)。bridge 仍是显式
opt-in，不扩大研究、选源、全文理解或 Zotero 内容决策职责。

设计取舍与高质量外部方案的一手证据对照见
[外部同类系统审计](docs/analogous-systems-review.md)、[agentic research systems review 2026](docs/agentic-research-systems-review-2026.md) 与 [v0.8.0 真实工作流复盘评估](docs/evaluations/v0.8.0-real-case-retrospective.md)。审计区分报告生成、科学
RAG、主动筛选、研究知识图谱与完整 Zotero 读写闭环，避免把相邻能力夸大为等价实现。

## 核心方法

- 先固定 `question / decision / scope / risk / currentness / coverage`；
- 先建立全局景观，再按分离维度拆分分支，识别决策瓶颈后深挖；
- 用 `problem → mechanism → requirements → route families → implementation → validation → failure boundary → selection conditions` 学习技术路线；
- 学术来源按综述/教材/原始研究用途路由，业界来源按规范/版本化文档/SHA 源码/测试/运行时路由；
- 把 `version-fit`、全文访问、方法适配和来源身份作为硬门，而不是用名望或引用数代替审查；
- 对关键论文执行 `Question plan → Source bundle → Document graph → Evidence → Reconstruction → Separate-context attestation`；attestation 只记录可审计的上下文声明，不认证主体身份，逐项证据仍保留可重算的页码/字符区间以及图、表、公式或定理定位；
- 将适用场景、工作流与结构化 I/O、数据流、数学推导依赖、算法步骤和有边界结论固化为内容寻址的 `PaperUnderstanding/v1`；区分 `answered / unresolved / not_applicable` 与 terminal/understood coverage，禁止把终态覆盖冒充理解；
- `$deep-research` 的当前 11-stage pipeline 在 `paper_understanding` 后执行 `evidence_appraisal`，并在该审查完成前阻止 `network_merge`；
- 从同一理解对象确定性投影 `PaperUnderstandingNoteInput/v1 → PaperKnowledgeNote/v2`：先给适用场景与结论，再给工作流、数学和算法原理，最后保留证据、边界与溯源；研究检索标题默认只进入子笔记 `<h1>`，只有显式审阅并启用 `decision-oriented` 策略时，才把“适用场景：结论/警示”写入书目 `shortTitle`；
- 将 `supports / qualifies / refutes / not_tested` 作为不可随意降维的关系；检索 DOI/URL 与证据段落 locator 永远分离；
- 所有跨来源结论在主张级综合，主动寻找反证并保留未决冲突；
- 对长任务使用显式 gap/action 循环；
- 用开放世界语义区分 deterministic gap、implicit candidate 与 unknown，
  对隐式缺失内容同时设计确认和反证检索；
- 学术发现保留 provider、精确 query、日期、分页/计数、排除、失败与回退，
  搜索候选不会自动升级为证据；
- `ZoteroCorpusSnapshot → evidence card → KnowledgeNetwork → GapQueue → targeted deep research → curation/readback → merge/audit` 形成闭环；
- `JSON/JSONL` 账本中的关系、locator、冲突、预算和停止条件全部显式化。

## 安装

```bash
git clone --branch v0.8.0 --depth 1 https://github.com/kl3574/deep-research.git
cd deep-research
tag_object="$(git rev-parse refs/tags/v0.8.0)"
tag_commit="$(git rev-parse refs/tags/v0.8.0^{commit})"
install_root="$HOME/.codex/skills"
backup_root="$HOME/.codex/skill-backups/v0.8.0-$tag_commit"
stage_root="$(mktemp -d "$HOME/.codex/skills-v0.8.0-stage.XXXXXX")"
mkdir -p "$install_root" "$backup_root"
for skill in deep-research learn-from-papers evidence-appraisal research-knowledge-network network-gap-discovery scholar-discovery scholarly-source-acquisition scholarly-document-normalization research-workflow-retrospective curate-research-to-zotero repair-zotero-metadata research-network-publish; do
  cp -a "skills/$skill" "$stage_root/$skill"
  if [ -e "$install_root/$skill" ] || [ -L "$install_root/$skill" ]; then
    mv --no-copy "$install_root/$skill" "$backup_root/$skill"
  fi
  mv --no-copy "$stage_root/$skill" "$install_root/$skill"
done
printf '%s  %s\n' "$tag_object" refs/tags/v0.8.0 > "$backup_root/tag-pin.txt"
printf '%s  %s\n' "$tag_commit" refs/tags/v0.8.0^{commit} >> "$backup_root/tag-pin.txt"
for skill in deep-research learn-from-papers evidence-appraisal research-knowledge-network network-gap-discovery scholar-discovery scholarly-source-acquisition scholarly-document-normalization research-workflow-retrospective curate-research-to-zotero repair-zotero-metadata research-network-publish; do
  diff -qr "skills/$skill" "$install_root/$skill"
done
codex doctor --json > "$backup_root/codex-doctor.postinstall.json"
```

默认循环故意不安装 `zotero-declarative-bridge`。需要本地 Zotero 受约束写入
时，可在确认运行版本和目标库后另行复制：

```bash
cp -a skills/zotero-declarative-bridge ~/.codex/skills/zotero-declarative-bridge
```

技能安装不等于 Zotero 插件安装。插件必须使用 release 中的 packed XPI，通过
Zotero 可见的 Add-ons UI 安装，并重新执行 capability、probe 与 readback 门；
离线 XPI 构建或单元测试仍不是启用证据。

固定并记录 tag object/peeled commit；旧安装备份必须留在 loader 根之外，避免被
当作重复技能发现。上述 `mv --no-copy` 还会在跨文件系统时失败，而不是静默复制；
若中途失败，从 `$backup_root` 恢复未完成项，再在同一文件系统重试。安装后保留
tag pin、逐技能字节比较与脱敏 `codex doctor` 回读。重启 Codex 会话后技能才会被
重新发现。

## 使用示例

```text
Use $deep-research to investigate sparse dynamical-system identification and
parameter calibration. Start with a field map, compare technical routes, and
focus only on decision-critical bottlenecks with traceable sources.
```

```text
Use $learn-from-papers to deeply reconstruct this paper. Model applicability,
workflow and typed I/O, data flow, mathematical derivation dependencies,
algorithm steps, and bounded conclusions from full-text evidence. Produce a
pyramid-structured Chinese Zotero note without changing bibliographic fields.
```

```text
Use $research-knowledge-network to merge evidence cards, compute coverage status,
mark contradictory claims, and return a validated action queue for the next
research pass.
```

```text
Use $network-gap-discovery to audit this KnowledgeNetwork/v1 under open-world
assumptions, generate falsifiable missing-content hypotheses, and emit bounded
scholar-discovery requests without modifying the network.
```

```text
Use $scholar-discovery to find primary and contrary studies for this gap through
documented academic APIs, preserve exact query provenance, conservatively merge
versions, and return ranked discovery-only candidates.
```

```text
Use $curate-research-to-zotero to download the accepted open sources, verify
their hashes, preview the exact Zotero target, and synchronize only after the
target readback gate passes.
```

## 仓库结构

```text
skills/
├── deep-research/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── learn-from-papers/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── references/
├── evidence-appraisal/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   ├── scripts/
│   └── tests/
├── research-knowledge-network/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   └── references/
├── network-gap-discovery/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── scholar-discovery/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── scholarly-source-acquisition/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── scholarly-document-normalization/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── research-workflow-retrospective/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── research-network-publish/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── zotero-declarative-bridge/        # experimental; not installed by default
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
├── repair-zotero-metadata/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── references/
│   └── scripts/
└── curate-research-to-zotero/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/
    └── scripts/
evals/
├── cases.md
├── learn-from-papers/
├── real-world/
└── research-workflow/
```

`SKILL.md` 只保留执行主干，详细方法与研究依据按需加载。下载的论文和个人 Zotero 数据不会提交到本仓库。

`skills/deep-research/scripts/research_run.py` 是可选的纯 Python 标准库运行账本：
它只记录和验证研究状态，不联网、不调用模型，也不执行来源中的指令。只有用户授权持久工作区后才使用；否则技能继续在临时上下文中维护等价结构。完整字段与命令见 `skills/deep-research/references/run-state.md`。

运行所有本地验证：

```bash
ruff check --no-cache skills evals scripts
python scripts/check_public_privacy.py
python -m unittest discover -s scripts -p 'test_*.py'
python -m unittest discover -s skills/deep-research/scripts -p 'test_*.py'
python -m unittest discover -s skills/research-workflow-retrospective/scripts -p 'test_*.py'
python -m unittest discover -s skills/learn-from-papers/scripts -p 'test_*.py'
python -m pytest -q skills/evidence-appraisal/scripts/test_evidence_appraisal_seam.py skills/evidence-appraisal/tests/test_contract_adversarial.py
python skills/evidence-appraisal/scripts/quick_validate.py
python -m unittest discover -s skills/research-knowledge-network/scripts -p 'test_*.py'
python -m unittest discover -s skills/network-gap-discovery/scripts -p 'test_*.py'
python -m unittest discover -s skills/scholar-discovery/scripts -p 'test_*.py'
python -m unittest discover -s skills/scholarly-source-acquisition/scripts -p 'test_*.py'
python -m unittest discover -s skills/scholarly-document-normalization/scripts -p 'test_*.py'
python -m unittest discover -s skills/research-network-publish/scripts -p 'test_*.py'
python -m unittest discover -s skills/zotero-declarative-bridge/scripts -p 'test_*.py'
node --test \
  skills/zotero-declarative-bridge/scripts/test_*core.js \
  skills/zotero-declarative-bridge/scripts/test_metadata_repair_bootstrap_vm.js
python -m unittest discover -s skills/repair-zotero-metadata/scripts -p 'test_*.py'
python -m unittest discover -s skills/curate-research-to-zotero/scripts -p 'test_*.py'
python -m unittest discover -s evals/real-world -p 'test_*.py'
python -m unittest discover -s evals/learn-from-papers -p 'test_*.py'
python -m unittest discover -s evals/research-workflow -p 'test_*.py'
python -m compileall -q skills evals scripts
```

六技能路由回归见 `evals/research-workflow/`。它用七个小型合成案例检查：
field-only 不虚构知识网络、已有 Zotero 语料先读取再深读并入网、开放世界缺口
经精确快照生成 `ScholarDiscoveryRequestSet/v1`、Google Scholar 仅允许用户手工
导出、新来源先入库并进入新快照、决定性证据必须完成外部 attestation，以及
`NetworkPatchProposal/v2` 必须取得显式治理接受。该回归只调用本地验证器，
不联网、不写 Zotero、不应用网络 patch，也不替代各技能的语义与真实写入测试。

`curate-research-to-zotero` 还提供四层笔记保障：

- `PaperUnderstandingValidation/v1` 证明理解对象、source bundle 与 reading dossier 的内容地址绑定；
- `paper_knowledge_note.py` 将已验证的理解输入确定性渲染为内容寻址的 `PaperKnowledgeNote/v2` 金字塔 HTML；
- `zotero-note-html.md` 定义中文 schema-9 知识笔记契约；
- `verify_note_html.py` 检查章节、Claim ID、定位、LaTeX 与溯源；
- `prepare_note_migration.py` 负责无写入暂存；`render_zotero_desktop_runner.py`
  可生成绑定 manifest 哈希的 Zotero App 预检/事务写入脚本；
  `update_existing_note.py` 是版本保护的 HTTP/Web 备用路线。

已有父条目的一笔记更新或零笔记创建优先使用 Zotero Desktop 官方
`工具 → 开发者 → 运行 JavaScript`：无需 API key。零笔记创建需向
`prepare_note_migration.py` 提供绝对路径的 `--parent-note-map`；一笔记时
同一映射按幂等覆盖处理，多笔记继续阻断。manifest v2 干运行先核验完整目标
路径、父条目/子项/子笔记/附件清单、明确 PDF、版本和文件哈希；创建笔记还核验
父条目稳定书目快照哈希。应用时在一个 Zotero 数据库事务中重枚举并更新或创建；可用短期内存
屏障保持“自动同步”设置开启，并在写后区分字节一致与严格语义一致。若无法由用户
操作 App，再运行时探测 `Zotero-Server-ID`，或回退到通过本机环境变量
提供的专用 Web API key。Web 干运行会核验 key 对目标 group 的读写权限
并预检全部远端对象；由于 Connector 不暴露 local collection ID 到
group/key 的可靠绑定，HTTP/Web 实写还要求用户单独确认预览中的
group_id 与 collection_key。任何路线都不记录 API 凭据，也不直接编辑
SQLite；本地私有审计清单可以记录目标 ID/key，但不得提交到公开仓库。

真实前向测试见
[稀疏动力学识别与参数校准](evals/real-world/sparse-dynamics-2026-07-29.md)。
DoE/代理模型、真实 Zotero 交付、知识网络缺口发现与发布闭环见
[DoE 与代理模型真实场景](evals/real-world/doe-surrogate-2026-08-06.md)。
可复现实验审计可直接运行：

```bash
python evals/real-world/audit_sparse_dynamics_run.py \
  --output /tmp/sparse-dynamics-audit.json
```

默认读取 `~/.local/share/deep-research/sparse-dynamics-2026-07-29` 下的
`manifest.json`、`ingestion_manifest.json`，产出 JSON 报告到标准输出。
该回归主题已覆盖稀疏动力学识别、WENDy 回归与 toy model 场景，公开仓库仍保留脱敏摘要。

## 边界

- Targeted research、rapid review、scoping review 和 systematic review 不可互相冒充。
- 人类阅读/学习研究只作为 agent 工作流的设计类比，不证明模型像人一样学习。
- 流畅解释不是证据；成功导入父条目也不等于 PDF、笔记和 collection 已正确同步。
- 结构验证不证明语义正确；自动语义评分也不能替代对原文、推导和适用边界的独立复核。
- 研究检索标题与 Zotero 书目 `shortTitle` 职责不同；前者写子笔记 `<h1>`，后者默认保持来源元数据不变。若研究工作流明确要求决策型短标题，则必须经审阅并启用指定语言的 `decision-oriented` 策略，使用“适用场景：结论/警示”而不是文献标题缩写。
- 高风险科学、医疗、法律、安全或政策结论仍需要领域专家和适用的正式协议。

## License

[MIT](LICENSE)

# deep-research

一套面向 Codex agent 的可审计深度调研技能，覆盖：

```text
研究问题
  → $deep-research：全局地图、技术路线、可信源检索、跨来源综合
  → $learn-from-papers：对关键单篇论文进行证据级深读与重建
  → $curate-research-to-zotero：合法下载、文件校验、中文知识笔记、Zotero 归档
```

“深度”不是堆积来源，而是把调研深度放在真正控制结论的瓶颈上；“可信”不是固定来源排行榜，而是来源必须适配具体主张、版本、范围和风险。

## 三个技能

| 技能 | 职责 | 典型输入 | 核心产物 |
| --- | --- | --- | --- |
| `$deep-research` | 多来源、全局到具体的针对性深调研 | 领域问题、技术选型、证据争议、版本问题 | 概念地图、技术路线、source registry、claim/evidence matrix、冲突日志 |
| `$learn-from-papers` | 给定一篇论文，快速且深入地学习与理解 | PDF、DOI、预印本、出版页面 | paper card、证据账本、方法/推导重建、中文知识笔记 |
| `$curate-research-to-zotero` | 保存经审核的研究资产 | 来源清单、本地文件、Zotero 目标 | 文件哈希、ingestion manifest、PDF/元数据/笔记同步与 readback |

三个技能既可独立调用，也可由 `$deep-research` 统筹。

## 核心方法

- 先固定 `question / decision / scope / risk / currentness / coverage`；
- 先建立全局景观，再按分离维度拆分分支，识别决策瓶颈后深挖；
- 用 `problem → mechanism → requirements → route families → implementation → validation → failure boundary → selection conditions` 学习技术路线；
- 学术来源按综述/教材/原始研究的用途路由，业界来源按规范/版本化文档/SHA 源码/测试/运行时路由；
- 把 `version-fit`、全文访问、方法适配和来源身份作为硬门，而不是用名望或引用数代替审查；
- 对关键论文执行 `Map → Evidence → Reconstruction`，逐项保留页码、章节、图、表、公式或定理定位；
- 所有跨来源结论在主张级综合，主动寻找反证并保留未决冲突；
- 对长任务使用显式 gap/action 循环；在获准的持久工作区中，可用版本化
  JSON/JSONL 账本断点续跑，并机械检查关系结构、交叉引用、locator 是否存在、
  冲突、预算字段/数值上限和停止门槛；
- 只从合法、公开或官方渠道下载；PDF、笔记和 Zotero 条目都做写后读回；
- 中文 Zotero 笔记保留原始术语，公式统一使用 LaTeX。

## 安装

```bash
git clone https://github.com/kl3574/deep-research.git
cd deep-research
mkdir -p ~/.codex/skills
for skill in deep-research learn-from-papers curate-research-to-zotero; do
  ln -s "$(pwd)/skills/$skill" "$HOME/.codex/skills/$skill"
done
```

如果目标路径已存在，请先检查它，不要覆盖已有技能。重新打开 Codex 会话后技能才会被发现。

## 使用示例

```text
Use $deep-research to investigate sparse dynamical-system identification and
parameter calibration. Start with a field map, compare technical routes, and
deepen only the decision-critical bottlenecks with traceable sources.
```

```text
Use $learn-from-papers to deeply reconstruct this paper. Explain every central
claim from full-text evidence, audit its figures and equations, and produce a
Chinese Zotero knowledge note with LaTeX formulas.
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
└── curate-research-to-zotero/
    ├── SKILL.md
    ├── agents/openai.yaml
    ├── references/
    └── scripts/
evals/
└── cases.md
```

`SKILL.md` 只保留执行主干，详细方法与研究依据按需加载。下载的论文和个人 Zotero 数据不会提交到本仓库。

`skills/deep-research/scripts/research_run.py` 是可选的纯 Python 标准库运行账本：
它只记录和验证研究状态，不联网、不调用模型，也不执行来源中的指令。只有用户
授权持久工作区后才使用；否则技能继续在临时上下文中维护等价结构。完整字段与
命令见 `skills/deep-research/references/run-state.md`。

运行所有本地验证：

```bash
ruff check --no-cache skills evals scripts
python scripts/check_public_privacy.py
python -m unittest discover -s scripts -p 'test_*.py'
python -m unittest discover -s skills/deep-research/scripts -p 'test_*.py'
python -m unittest discover -s skills/curate-research-to-zotero/scripts -p 'test_*.py'
python -m unittest discover -s evals/real-world -p 'test_*.py'
python -m compileall -q skills evals scripts
```

`curate-research-to-zotero` 还提供三层笔记保障：

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
`group_id` 与 `collection_key`。任何路线都不记录 API 凭据，也不直接编辑
SQLite；本地私有审计清单可以记录目标 ID/key，但不得提交到公开仓库。

真实前向测试见
[稀疏动力学识别与参数校准](evals/real-world/sparse-dynamics-2026-07-29.md)。
可复现实验审计可直接运行：

```bash
python evals/real-world/audit_sparse_dynamics_run.py \
  --output /tmp/sparse-dynamics-audit.json
```

默认读取 `~/.local/share/deep-research/sparse-dynamics-2026-07-29` 下的
`manifest.json`、`ingestion_manifest.json`，产出 JSON 报告到标准输出。

## 边界

- Targeted research、rapid review、scoping review 和 systematic review 不可互相冒充。
- 人类阅读/学习研究只作为 agent 工作流的设计类比，不证明模型像人一样学习。
- 流畅解释不是证据；成功导入父条目也不等于 PDF、笔记和 collection 已正确同步。
- 高风险科学、医疗、法律、安全或政策结论仍需要领域专家和适用的正式协议。

## License

[MIT](LICENSE)

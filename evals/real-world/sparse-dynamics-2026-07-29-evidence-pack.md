# 稀疏动力学识别与参数校准：真实前向测试 evidence pack

日期：2026-07-29
整理日期：2026-07-30
研究模式：面向决策的 targeted investigation，不是 systematic review、
scoping review 或算法复现

本文件是
[主测试报告](sparse-dynamics-2026-07-29.md)
的持久审计附件。原始 forward test 与较晚的 completion audit 是两个不同
证据阶段：前者的部分查询输入可从本机运行日志恢复，后者的查询输入与可见
结果在审计时直接记录。没有保存下来的筛选数、完整结果页或运行数据均标为
未记录，不作追溯性补造。

## 1. Research contract

| 字段 | 本次契约 |
| --- | --- |
| Question | 当观测完整性、测量/过程噪声、激励和可辨识性条件变化时，agent 应如何调研并选择稀疏动力学结构识别与参数校准路线？ |
| Decision / use | 一是形成可复用的 `landscape -> route -> bottleneck -> paper reconstruction -> synthesis` 调研流程；二是检验并迭代 `deep-research`、`learn-from-papers`、`curate-research-to-zotero` 三个技能。它不替某个尚未给定的数据集直接选定算法。 |
| Subquestion 1 | “结构/支撑、回归系数、物理参数、不确定性/预测”四个验收对象如何分开？ |
| Subquestion 2 | 直接导数回归、积分/弱形式、ensemble、信息准则、混合整数选择及固定结构校准各解决什么问题？ |
| Subquestion 3 | 坐标、候选库、激励、秩/条件数、全状态/部分状态观测分别怎样限制结论？ |
| Subquestion 4 | 测量噪声、过程噪声和模型差异是否被同一残差模型覆盖？ |
| Subquestion 5 | 结构参数可辨识性、有限弱设计秩、稀疏支撑唯一性和状态可观测性应如何分问；哪些关系有决定性来源，哪些仍未决？ |
| Subquestion 6 | 支撑、系数、短期 rollout、长期动力学、稳定性/吸引子与预测不确定性应怎样分层验证？ |
| Subquestion 7 | 哪些来源只是发现线索，哪些全文证据足以支持决策性主张？ |
| Subquestion 8 | 三个技能在真实下载、深读、跨源综合和可选 Zotero handoff 中暴露了哪些契约缺口？ |
| Risk | 科学风险为高：错误的坐标/字典、不可辨识参数、噪声错模或吸引子内数据不足都可能产生看似稀疏但机制错误的模型。操作风险另行隔离：本 evidence pack 不执行 Zotero 或 GitHub 写入。 |
| Scope | 以 2015–2026 年的 10 篇合法可得 PDF 为小型高信号语料，重点覆盖显式 ODE 的稀疏发现、噪声鲁棒性、全状态受控动力学、候选模型排序、固定结构参数估计和 likelihood/profile 可辨识性；部分观测只做到 orientation，未进入 decisive reconstruction。 |
| Currentness | Web 查询与文件获取发生在 2026-07-29；本文件于 2026-07-30 根据当时实际记录固化。未在整理日重新联网检查版本、勘误、撤稿或新论文。 |
| Exclusions | 不做高召回系统检索、元分析、真实实验性能排名、目标数据集审计、论文代码执行、算法数值复现、统一 benchmark、完整前向/后向引文追踪或全面 correction/retraction 检索。隐式/有理式发现与 SDE 发现只保留为未深挖分支。 |
| Coverage claim | 这是代表性路线地图与四篇关键全文重建，不声称覆盖全部方法或独立复现其性能。 |
| Assumptions | 本地 manifest 中的文件身份、访问来源、页数和哈希是本次资产审计的基准；四篇 schema-9 笔记中的 Claim ID/双定位是决策性全文证据入口。canonical publication 与实际 read copy 始终分开。 |
| Success criteria | 交付全局地图、分离维度矩阵、路线矩阵、10 项 source registry、原子 claim ledger、冲突/缺口、真实 search trail 和诚实 stop decision；所有高影响结论有全文定位、被限定，或明确标成 unresolved。 |

## 1.1 收口修正（2026-07-30）

本回次与补充审计的收口为：

- `v3`：dry-run 先核准 33 parents；一个新同步父条目随后出现，apply
  重枚举得到 34 observed / 33 approved，并在写前 fail-closed
  （`writePerformed=false`）；
- `v4`：fresh inventory 为 `34` parents、`32` existing notes、`28` unchanged、`4` mutations、`2` no_existing_note，`preflight_ok`；
- `v4`：Desktop 事务提交 4 notes，`writePerformed=true`、`rolledBack=false`；自动同步偏好写前/写后均为 `true`，barrier 正常释放；
- identifiability 笔记的 App 立即回读出现 false-positive
  （server-version 保持 `3918`，byte 与语义 hash 都完全匹配）；Zotero
  本地修改在上传前不推进 object version。屏障释放后的独立本地 API
  最终验证四条都为 `version=4034` 且 parent/hash 精确一致，但未做远端
  Web API 读回，因此不声称 Cloud 同步已独立核验；
- `v5` 暴露出 outer-whitespace trim 非幂等问题；第一次修正生成的 `v6`
  虽显示 `0` mutation，但 runner 因 unchanged 文件与旧 hash 不一致而
  fail-closed；
- 最终修正对 storage-normalized 相等的 override 复用 live HTML；`v7`
  只读复核为 `32` unchanged、`2` no existing note、`0` mutation、
  `0` unchanged-hash mismatch，dry-run 与 apply/no-change runner 均成功
  生成；
- 结果收口为 `3` bundles、`10` PDFs、`4` notes 通过；`3` 条研究吸收记录通过核验；
- 审计闭环总计：`141` curator tests + `30` reproducibility tests = `171`；
- 首次 post-v4 审核把已含 `/api` 的 base URL 再拼接 `/api`，请求落到
  `/api/api/...` 并失败；保留该原始 artifact，但它已被正确 endpoint 的
  最终通过报告取代，不作收口证据。

## 2. 有界结论

当前证据支持的最短决策链是：

```text
观测与用途契约
-> 在给定坐标/字典内发现候选支撑
-> 固定支撑后按原观测与噪声模型重估物理参数
-> 分别检查结构可辨识性、有限弱设计秩、支撑唯一性与状态可观测性
-> 对系数、rollout、动力学性质和预测不确定性分层验证
```

直接 SINDy 只是其中一个条件分支。弱式/积分式能避免直接对带噪状态作
点值微分，但不会自动解决字典遗漏、有限激励、部分观测、非线性
errors-in-variables、结构可辨识性或过程噪声。现有语料对显式确定性 ODE
最强；SDE 路线在真实检索中被发现，但没有进入 10 篇全文语料，也没有被
`learn-from-papers` 重建，因此本次不能把“过程噪声与测量噪声应采用何种
不同估计目标”升级成已经审定的跨源结论。

## 3. Global landscape

### 3.1 Vocabulary

| 术语 | 本次采用的有界含义 | 不可偷换为 |
| --- | --- | --- |
| 稀疏结构 / support | 在指定坐标和候选库 $\Theta(X)$ 中非零系数的位置 | 无先验地发现唯一真实方程 |
| 回归系数 | 当前坐标、单位、缩放和估计器下的 $\widehat\Xi$ | 自动可解释的物理参数 |
| 物理参数 | 与已固定机制及观测模型相连、满足单位/约束的参数 | 任意字典系数 |
| 结构可辨识性 | 理想观测契约下，参数到可观测分布/输出的映射是否单射 | 某次优化是否收敛 |
| 实践可辨识性 | 给定有限、带噪数据时 likelihood/profile 的约束程度 | 结构可辨识性的证明 |
| 稀疏支撑唯一性 | 给定字典与实验设计时，活跃项是否可区分 | 状态可观测性或物理参数可辨识性 |
| 状态可观测性 | 已知输入下能否由输出区分/重建隐藏状态 | 支撑恢复成功 |
| 过程噪声 | 动力学演化本身的随机项 | 观测端加性残差 |

### 3.2 Mechanism map

直接路线用

$$
\dot X=\Theta(X)\Xi
$$

把动力学发现转成稀疏回归。弱式路线以测试函数 $\phi$ 分部积分，

$$
-\int \phi'(t)x(t)\,dt=\int \phi(t)F(x(t))\,dt,
$$

将导数移到解析测试函数上。两者在结构发现后仍需进入固定支撑校准：

$$
\widehat\theta
=\arg\min_{\theta\in\Theta_{\mathrm{phys}}}
\mathcal L\!\left(y_{\mathrm{obs}},
                  \mathcal H[x(\theta)]\right),
$$

再通过等价类、profile/posterior、out-of-condition rollout、稳定性或
预测覆盖检查可辨识性与不确定性。弱形式改变了估计器和误差传播机制，
不是对后续识别门的替代。

### 3.3 Evidence tradition, maturity, failure and artifacts

| 景观要素 | 本次观察 |
| --- | --- |
| Evidence tradition | 语料以定理/推导和作者团队的 synthetic benchmark 为主；四篇深读笔记明确区分 source-stated、agent-inferred 和 unresolved。没有本次独立算法复现，也不能由多篇同一团队论文推断独立重复。 |
| Maturity / timeline | 小语料时间线为：2015 直接积分估计理论（S09）；2016 SINDy（S01）；2017 积分选模与 AIC/BIC（S02、S06）；2018 受控动力学与 MPC（S05）；2021 Weak SINDy（S03）；2022 ensemble（S04）；2023 MIO 与 WENDy（S07、S08）；2026 likelihood/profile 教程（S10）。部分观测在本次仍是待补 decisive reconstruction 的分支。这是语料时间线，不是领域完整史。 |
| Principal failures | 坐标或字典遗漏；带噪微分；state-side EIV；单一吸引子/流形激励不足；候选列相关或组合算子降秩；隐藏状态非唯一；闭环输入混淆；物理参数等价类；局部协方差与实际 estimator 不一致；名义区间没有经验覆盖；过程噪声与模型差异未建模。 |
| Validation layers | 支撑、系数、物理参数、短期预测、长期动力学、稳定性/吸引子/不变统计和不确定性覆盖必须分别验收。 |
| Artifacts | 10 项外部 manifest 与 PDF；4 篇 schema-9 中文/LaTeX 重建笔记；3 个 Zotero ingestion bundles 及既有迁移审计；本仓库主报告、技能、测试和本 evidence pack。公开仓库不含论文 PDF 或个人 Zotero 数据。 |
| Maturity gap | 语料对真实实验、独立 replication、SDE、隐式/有理式、部分观测可辨识性和跨方法同条件 benchmark 覆盖不足。 |

## 4. Dimension-separated matrix

本次没有建立任何统计意义上的“正交维度”。下表中的“定义上分离”只表示
问题对象不同、一个成功不蕴含另一个成功；它不表示随机独立，也不表示调参时
没有交互。其余项目只是为了避免混比而设置的分析轴。

| 维度 | 取值示例 | 独立性判定 | 已知交互 | 用途 |
| --- | --- | --- | --- | --- |
| 验收对象 | 支撑；回归系数；物理参数；不确定性/预测 | **定义上分离，非统计独立**；SINDy-C3/C4/C8 提供不蕴含反例 | 支撑选择影响后选择偏差；参数映射依赖坐标/单位；预测放大系数误差 | 防止用一个残差替代全部验收 |
| 四个识别检查 | 结构参数可辨识性；有限弱设计秩；稀疏支撑唯一性；状态可观测性 | 前两者已分别核对；**本次没有 support-uniqueness decisive theorem，也没有来源建立四者的一般蕴含关系，更不能声称正交** | 新输入、输出、初值和实验区间可能同时改变多个检查 | 分开提问；support uniqueness 与 observability 关系保持 unresolved |
| 噪声生成位置 | 测量噪声；过程噪声；模型差异 | 生成位置是必须分问的分析轴；**能否从本次观测区分以及对 estimand 的后果仍 unresolved** | 无重复/高频/独立传感器时可能混淆；本次没有 SDE 全文可用于升级该判断 | 先把生成模型写进 contract，再补 decisive source |
| 观测完整性 | 全状态；部分状态；隐藏状态 | 分析轴 | 直接影响 observability、字典坐标、导数估计和 route | 限定直接/重建后发现 |
| 激励与输入 | 单轨迹；多初值；多工况；开环；闭环 | 分析轴 | 决定候选列秩、off-manifold coverage、输入/反馈可分性 | 设计实验与外推验证 |
| 动力学表示 | 显式；隐式/有理式；随机微分 | 分析轴 | 决定候选库、左端变量、噪声模型与优化器 | 划分技术路线 |
| 证据类别 | 推导；synthetic；real experiment；implementation；runtime | **标签定义分离，但证据强度不独立** | 同一论文可含多类证据；推导不能替代外部有效性 | 防止 prestige 替代 method fit |
| 来源独立性 | 作者、团队、数据、代码、benchmark、study overlap | 审计轴 | S01/S04/S05/S06 共享 Brunton/Kutz 方法谱系；S03/S08 共享 Messenger/Bortz 谱系 | 防止把多个报告计成独立确认 |
| 资源约束 | 求导/求积；bootstrap；MIO solver；前向求解/profile | route-dependent 分析轴 | 计算预算会改变候选数、窗口数、profile 范围和验证深度 | 比较可实施性 |

## 5. 技术路线矩阵

“Validation evidence”只描述本次实际持有的证据层级。`registered-only`
表示 PDF 已核验、但没有 schema-9 reconstruction；不得与四篇深读等同。

| Route | Mechanism | Input -> output | Assumptions | Validation evidence in this run | Resource / operation | Principal failure | Open bottleneck |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Direct SINDy（S01） | 对 $\dot X=\Theta(X)\Xi$ 做逐方程稀疏回归 | 全状态轨迹、导数/导数估计、候选库 -> support 与系数 | 真动力学在所选坐标/库中稀疏；导数可靠；设计可区分列 | 44 页 main+SI reconstruction；SINDy-C1–C8；含噪声与 off-attractor 内部反例 | 导数估计、库矩阵、阈值/稀疏参数 sweep | 字典遗漏、错误坐标、噪声放大、吸引子局部闭包、系数偏差 | 一般 support 唯一性与目标数据上的稳定恢复 |
| Integral / Weak support discovery（S02、S03） | 积分或测试函数矩条件移除点值状态导数；再作稀疏选择 | 带噪全状态轨迹、字典、窗口/测试函数 -> support 与弱回归系数 | 求积可控；测试函数合适；非线性 EIV 近似有效 | S02 registered-only；S03 22/22 页 reconstruction、WSINDy-C1–C13 | 卷积/求积、白化/GLS、窗口与阈值选择 | 仍有 state-side EIV；真值辅助阈值；小系数误差可有大轨迹误差 | 盲选阈值、组合算子秩、现实噪声与独立比较 |
| Ensemble-SINDy（S04） | 对数据/库做 bootstrap ensemble，以 inclusion probability 和系数分布聚合 | 低数据/高噪声轨迹 -> 入选概率、系数集合 | 重采样能代表数据变异；基础库与 estimator 合适 | registered-only；exact-title 检索确认 DOI/仓储版本 | 多次稀疏拟合，成本约随 ensemble size 增加 | 共享基础 estimator 偏差；概率不是校准后的结构后验 | 独立校准与真实条件覆盖 |
| SINDy + AIC/BIC（S06） | SINDy 先缩小候选集，再模拟候选并按信息准则排序 | 候选 supports、时间序列 -> 相对排名 | 候选生成未漏掉目标；likelihood/样本定义与准则假设适用 | registered full text；印刷 pp.2–6、Eqs. (2.1)–(2.2)、Algorithm 1；未做 schema-9 reconstruction | 每个候选需积分/拟合/交叉验证 | 只能在生成池内相对排名；候选遗漏时不能“找回真模型” | 后选择推断、候选生成偏差、真实数据外部验证 |
| Mixed-integer sparse selection（S07） | 以 MIO 表达 exact subset selection、约束和 optimality gap | 库矩阵、导数、稀疏/物理约束 -> support 与证书 | 数值模型正确；solver gap/时间预算可接受 | registered-only publisher VOR | MIO solver、可能较高时间/内存成本 | 大库/高维扩展；证书只针对给定离散问题 | 与近似法在同一数据契约下的收益/成本边界 |
| Controlled SINDYc（S05） | 将已知输入纳入发现并与预测控制连接 | 全状态、已知输入、控制目标 -> controlled model/policy | 输入已知且有独立激励；论文算例明确假设 full-state information | registered full text；PDF p.8 写明 $y=x$，p.16 F-8 算例再次假设 full-state information | 输入设计、稀疏拟合、MPC rollout | 闭环状态-输入相关；训练工况外推失败 | 闭环可辨识性与输入激励设计 |
| Partial-observation discovery | 先做 observability/state reconstruction，再限定可解释的发现对象 | 部分输出、输入与状态模型假设 -> 重建状态/输出闭合模型 | 隐状态可由所给输出与输入辨识；重建坐标有明确物理语义 | discovery/orientation only；S05 只把 limited measurements/delay coordinates 列为可扩展架构，不能作为已验证路线 | 状态估计、delay coordinates、联合识别 | 隐藏状态非唯一；坐标解释困难 | 本次缺 decisive reconstruction 与联合保证 |
| WENDy fixed-support calibration（S08） | 已知结构下，以弱式 EIV 一阶协方差做 IRLS | 全状态带噪轨迹、固定特征/非零项 -> 参数估计与近似协方差 | 参数线性进入；结构正确；一阶 Taylor 与 Cholesky 稳定 | 36/36 页 reconstruction、WENDy-C1–C19 | 求积、多尺度测试函数、IRLS；不需每步解 ODE | 强非线性/大噪声时一阶近似失效；Eq. (15) 与 WLS estimator 不一致 | IRLS 收敛、composed-rank、区间经验覆盖 |
| Direct integral calibration（S09） | 对可分结构 $F(x;\nu)=g(x)h(\nu)$ 引入 natural parameter $\theta=h(\nu)$，经积分化得到线性于 $\theta$ 的估计问题 | 固定 ODE 结构、全轨迹观测、平滑/积分数据 -> $\theta$；仅当 $h$ 可逆/单射时再恢复物理参数 $\nu$ | 状态与参数函数可分；论文条件满足；校准 $\nu$ 还要求 $h$ injective/可逆 | registered-only arXiv v3/journal pairing；正文 pp.1–3 与 Eq. (14) 定点核对 | 平滑、数值积分和线性代数 | $h$ 非单射导致物理参数等价类；模型/观测契约失配 | 与 WENDy/EIV 方法的同条件比较 |
| Likelihood / profile calibration（S10） | 固定模型下做 MLE，并沿 nuisance directions profile；不可辨识时重参数化 | 观测、前向模型、噪声模型 -> 点估计、profile、参数集/预测包络 | likelihood 正确；优化/扫描覆盖相关区域 | 27/27 页 reconstruction、IDENT-C1–C14 | 多次前向求解和条件优化 | 等价类、局部曲率误导、边界/优化失败、区间标签与覆盖不一致 | 结构误设、真实数据、经验预测覆盖 |
| Implicit / rational discovery | 候选左端或隐式关系与稀疏右端联合筛选 | 轨迹、隐式/有理候选 -> 方程关系 | 真关系在候选族内且左右端可区分 | 本次无专门全文；只作为地图分支 | 候选左端搜索、可能非凸/组合优化 | 伪关系、分母奇异、尺度不唯一 | 需新增 decisive paper 与反例 |
| Sparse SDE discovery（D01） | 目标应区分 drift/diffusion，而非把所有偏差当观测残差 | 随机轨迹与采样契约 -> drift/diffusion 候选 | 过程/测量噪声可分；随机采样条件足够 | 仅 exact-title discovery：DOI `10.1063/1.5018409`；未获取/未读全文 | 尚未审计 | 过程噪声、测量噪声和模型差异可混淆 | 本次最高优先级的全文证据缺口之一 |

## 6. Source registry

完整文件大小、SHA-256、PDF magic、页数、加密和 `pdftotext` 状态位于外部
`~/.local/share/deep-research/sparse-dynamics-2026-07-29/manifest.json`。
10/10 文件在本次运行中通过 magic、未加密、页数、哈希和文本提取复核。
除明确写出的共享关系外，数据、代码、benchmark 与 funding overlap
没有完成系统审计；“未发现”不能解释为独立。

| ID / study ID | Canonical identity | Read version in this run | Role | Independence / overlap |
| --- | --- | --- | --- | --- |
| S01 / ST-SINDY-2016 | [Brunton, Proctor & Kutz, 2016, PNAS, DOI 10.1073/pnas.1517384113](https://doi.org/10.1073/pnas.1517384113) | Corpus：arXiv v1，26 页，SHA-256 `018edd…07255`；决定性 reconstruction 另读本地 44 页 main+SI 合并文件，SHA-256 `e58e7c…501b`。两者不得当成两个独立 study。 | orientation、support、qualify | 与 S04/S05/S06 共享 Brunton/Kutz 方法谱系；与 S06 另共享 Proctor。共享 data/code 未审计。 |
| S02 / ST-SCHAEFFER-2017 | [Schaeffer & McCalla, 2017, Physical Review E, DOI 10.1103/PhysRevE.96.023302](https://doi.org/10.1103/PhysRevE.96.023302) | APS VOR，7 页，SHA-256 `77011f…fb95a`；full text registered，未作 schema-9 reconstruction。 | support、alternative route | 与其他 9 项无作者重叠；数据/code overlap 未审计。 |
| S03 / ST-WSINDY-2021 | [Messenger & Bortz, 2021, MMS, DOI 10.1137/20M1343166](https://doi.org/10.1137/20M1343166) | arXiv v3，22 页，SHA-256 `eacc45…f533`；22/22 页 reconstruction。 | support、qualify、conflict | 与 S08 共享 Messenger/Bortz 团队和弱式方法谱系；不是独立团队 replication。 |
| S04 / ST-ENSEMBLE-2022 | [Fasel et al., 2022, Proc. R. Soc. A, DOI 10.1098/rspa.2021.0904](https://doi.org/10.1098/rspa.2021.0904) | arXiv v1，18 页，SHA-256 `17a004…0fc6`；full text registered，未 reconstruction。 | support、alternative route | 与 S01/S05/S06 共享 Brunton/Kutz 谱系；独立数据/code 未审计。 |
| S05 / ST-CONTROL-2018 | [Kaiser, Kutz & Brunton, 2018, Proc. R. Soc. A, DOI 10.1098/rspa.2018.0335](https://doi.org/10.1098/rspa.2018.0335) | arXiv v2 author manuscript，24 页，SHA-256 `38b2d8…1eb`；full text registered，未 reconstruction。 | route support、scope extension | 与 S01/S04/S06 共享 Brunton/Kutz 谱系。 |
| S06 / ST-AIC-2017 | [Mangan et al., 2017, Proc. R. Soc. A, DOI 10.1098/rspa.2017.0009](https://doi.org/10.1098/rspa.2017.0009) | arXiv v1，14 页，SHA-256 `b41260…cee4`；本次仅定点核对 pp.2–6 与 Algorithm 1，非完整 reconstruction。 | support、qualify | 与 S01 共享 Brunton/Kutz/Proctor，与 S04/S05 共享部分团队；候选生成依赖 SINDy。 |
| S07 / ST-MIO-2023 | [Bertsimas & Gurnee, 2023, Nonlinear Dynamics, DOI 10.1007/s11071-022-08178-9](https://doi.org/10.1007/s11071-022-08178-9) | Springer VOR，20 页，SHA-256 `784226…f691`；full text registered，未 reconstruction。 | alternative route、qualify | 与其余语料无作者重叠；benchmark/code overlap 未审计。 |
| S08 / ST-WENDY-2023 | [Bortz, Messenger & Dukic, 2023, Bulletin of Mathematical Biology, DOI 10.1007/s11538-023-01208-6](https://doi.org/10.1007/s11538-023-01208-6) | Springer VOR，36 页，SHA-256 `03986e…a6c9`；36/36 页 reconstruction。 | support、qualify、conflict | 与 S03 共享 Bortz/Messenger 和弱式方法谱系；不是独立团队 replication。 |
| S09 / ST-DIRECT-INTEGRAL-2015 | [Dattner & Klaassen, 2015, EJS, DOI 10.1214/15-EJS1053](https://doi.org/10.1214/15-EJS1053) | arXiv v3、journal-typeset，36 页，SHA-256 `08e829…ffa`；full text registered，未 reconstruction。 | theory support、alternative route | 与其他语料无作者重叠；无独立复现审计。 |
| S10 / ST-IDENT-2026 | [Simpson & Baker, 2026, SIAM Review, DOI 10.1137/24M1667968](https://doi.org/10.1137/24M1667968) | Oxford AAM，文本标示 arXiv v5，27 页，SHA-256 `c9e730…76e1`；27/27 页 reconstruction；canonical SIAM VOR 与 read copy 分离。 | orientation、support、qualify、conflict | 与其他 9 项无作者重叠；教程示例不是对 SINDy/Weak/WENDy 的独立 replication。 |

Discovery-only、未进入 10 项全文 registry 的 D01：
[Boninsegna, Nüske & Clementi, *Sparse Learning of Stochastic Dynamical
Equations*, DOI 10.1063/1.5018409](https://doi.org/10.1063/1.5018409)。
本次只从 PubMed/NSF 搜索结果识别 canonical DOI；无 read version、全文定位、
状态审计或可用于结果主张的证据。

## 7. Cross-source claim ledger

证据类别采用
`theorem_or_derivation | synthetic_benchmark | review_synthesis |
implementation | discovery_only`。每一行是一条 claim-source relation；
同一 claim 的多行不代表相互独立，overlap 见 source registry。
`SINDy-C#`、`WSINDy-C#`、`WENDy-C#` 和 `IDENT-C#` 是本文件为避免四篇
笔记都从 `C1` 编号而添加的 namespace；数字仍指向对应 schema-9 笔记表中
原始 Claim ID。

| Claim ID | Atomic claim | Source / study | Exact locator | Evidence class | Relation | Confidence | Limitation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| K01 | 稀疏发现只相对于给定坐标和候选库成立。 | S01 / ST-SINDY-2016 | SINDy-C2；主文 p.3933｜44 页 read copy PDF 实体页 2 | theorem_or_derivation | supports | high | 说明先验依赖，不证明任意给定库的完备性。 |
| K02 | 正确 support 不蕴含准确 coefficient。 | S01 / ST-SINDY-2016 | SINDy-C3：补充材料 p.13｜PDF 19｜Fig. 7；SINDy-C4：补充 p.19｜PDF 25｜Figs. 15–16 | synthetic_benchmark | supports | high | 置信度来自两个可定位的论文内反例；同一团队的合成/参数化案例，不是一般误差界。 |
| K03a | 在 SINDy 论文的内部反例中，好导数拟合不保证正确长时动力学。 | S01 / ST-SINDY-2016 | SINDy-C8；补充材料 pp.20–29｜PDF 26–35｜Figs. 17–28 | synthetic_benchmark | supports | medium | 置信度限于特定内部案例；不是一般定理，也没有独立复现。 |
| K03b | Weak SINDy 的 Van der Pol 算例中，$0.008$ coefficient error 与 $0.56$ trajectory error 同时出现。 | S03 / ST-WSINDY-2021 | WSINDy-C11；正文 p.18｜PDF 18｜Fig. 3.5 | synthetic_benchmark | supports | high | 数值与图注可直接定位；只限特定设置，trajectory metric 依赖时域和稳定性。 |
| K04 | 只在吸引子/慢流形上取数可能无法区分完整机制；off-attractor 数据可改变识别结果。 | S01 / ST-SINDY-2016 | SINDy-C6；主文 p.3936｜PDF 5；补充 pp.14–17｜PDF 20–23 | synthetic_benchmark | supports | high | 圆柱尾流约化案例有直接前后对照；“多工况总是充分”并未证明。 |
| K05a | Structural parameter identifiability 问的是理想观测下参数到输出映射是否一一对应。 | S10 / ST-IDENT-2026 | IDENT-C1：印刷 pp.2–3｜PDF 2–3；IDENT-C7：印刷 pp.19–21｜PDF 19–21｜Eq. (13)、Fig. 6 | theorem_or_derivation | supports | high | 定义与参数变换例子可直接定位；S10 不研究 sparse support 或 observability。 |
| K05b | WENDy 的 Conditions 1–4 分别约束若干矩阵，但不保证组合弱设计 $\phi\Theta$ 满列秩。 | S08 / ST-WENDY-2023 | WENDy-C14；§2.1，Page 8–9｜PDF 8–9｜Conditions 1–4 | theorem_or_derivation | contradicts | high | 最小线性代数反例可直接构造，反驳正文的 sufficiency assertion；它不是 structural-identifiability 或一般 sparse-support 唯一性定理，冲突另记 CF06。 |
| K05c | 状态 observability 与 parameter/support identifiability 的一般蕴含关系。 | no inspected decisive study | 本次无全文 locator | discovery_only | not_tested | low | 没有 decisive source；这是必须分问的 unresolved gate，不是本次已证明的三向 non-implication。 |
| K06 | MLE 邻域的局部曲率不能代替扩展域内的 profile/等价类检查。 | S10 / ST-IDENT-2026 | IDENT-C13；印刷 pp.23–24｜PDF 23–24｜§5 | review_synthesis | supports | high | Hessian/profile 对照可直接定位；来源不审计 FIM，FIM-specific 延伸只可作为受限 agent inference。 |
| K07 | AIC/BIC 只在已生成的候选模型及其 likelihood/样本假设下作相对排序，不能证明候选池包含真实结构。 | S06 / ST-AIC-2017 | 印刷 pp.2–6｜PDF 2–6；Eqs. (2.1)–(2.2)；Algorithm 1；p.3 明示 BIC consistency 的前提是候选中含 true model | theorem_or_derivation | qualifies | medium | 仅定点全文核对、未做完整 schema-9 reconstruction；S06 与 SINDy 团队/候选生成重叠。 |
| K08a | WENDy 的测量噪声同时进入弱设计与响应，因此论文采用 EIV 协方差近似，而不是普通 OLS 噪声模型。 | S08 / ST-WENDY-2023 | WENDy-C3/C4；§2.1–2.2，Page 9–11｜PDF 9–11｜Eqs. (7)–(13) | theorem_or_derivation | supports | high | 模型明确排除 process noise、correlated noise、heteroscedasticity 和 model discrepancy。 |
| K08b | 过程噪声与测量噪声是否以及如何改变本任务的 estimand。 | D01 / no inspected study | 仅搜索结果中的 DOI；无全文 locator | discovery_only | not_tested | low | D01 未获取、未读、未审计；该关系 unresolved，不能作为已证实结论。 |
| K09a | 紧支撑测试函数经分部积分避免直接计算带噪轨迹的点值导数。 | S03 / ST-WSINDY-2021 | WSINDy-C1；正文 p.3｜PDF 3｜Eqs. (2.1)–(2.3) | theorem_or_derivation | supports | high | 公式可直接定位；需要测试函数正则性与边界条件，不是“没有导数信息”。 |
| K09b | 非线性候选函数中的测量误差使弱回归残差一般有非零均值，领先阶 GLS 协方差没有消除 EIV 偏差。 | S03 / ST-WSINDY-2021 | WSINDy-C3/C4；正文 pp.5–6｜PDF 5–6｜§2.3–2.3.1 | theorem_or_derivation | qualifies | high | 残差展开和近似说明可直接定位；依赖小噪声展开并忽略未知 Jacobian、积分误差和高阶项。 |
| K09c | 论文的大噪声 support 结果使用 $\lambda=\frac14\min_{w_j^\ast\ne0}\lvert w_j^\ast\rvert$，不能直接外推为未知真值时的通用 support-recovery 保证。 | S03 / ST-WSINDY-2021 | WSINDy-C10；正文 p.4｜PDF 4｜阈值条件；正文 p.14｜PDF 14｜实验设置 | synthetic_benchmark | qualifies | high | 阈值和实验设置可直接定位；只限所读版本、给定库和合成实验，不声称 support 必然不唯一。 |
| K10b | WENDy Eq. (15) 不是 Algorithm 2 在固定 $C$ 时 WLS 点估计量的标准协方差。 | S08 / ST-WENDY-2023 | WENDy-C15；§2.2，Page 12｜PDF 12｜Algorithm 2 line 9 与 Eq. (15) | theorem_or_derivation | supports | high | 直接代数比较支持该审计主张；源内不一致另记 CF03，参数依赖 $C$ 和迭代不确定性尚未传播。 |
| K10c | WENDy Figs. 10–11 的平均参数与平均区间没有报告逐试验 $95\%$ 经验覆盖率。 | S08 / ST-WENDY-2023 | WENDy-C18；§3.3，Page 27–29｜PDF 27–29｜Figs. 10–11、Table 2 | synthetic_benchmark | qualifies | high | 这是“未报告”，不是已证明欠覆盖或过覆盖。 |
| K10d | 稳态 BVP 示例的参数变换 Eq. (13) 保持同一输出，所以优化器给出的一个点估计不证明物理参数唯一。 | S10 / ST-IDENT-2026 | IDENT-C3、C7–C9；PDF 8、19–22｜Eq. (13)、Figs. 6–7 | theorem_or_derivation | supports | high | 变换和 profile 可直接定位；例子只针对稳态 synthetic BVP，增加瞬态或输出后结论可能改变。 |

### 冲突与未决项

| Conflict ID | Affected claims | Evidence on each side | Status / decision impact | Next discriminating check |
| --- | --- | --- | --- | --- |
| CF01 | SINDy 参数化 Hopf 系数 | SINDy-C7：补充 Eq. (27) 与 Table 13 的线性交叉项符号相反 | unresolved；不可静默选一个符号用于实现 | 查作者代码、勘误或另一个可配对版本 |
| CF02 | Weak SINDy 小噪声“有效数字” | WSINDy-C8：正文 p.12 的印刷公式与 Figs. 3.2–3.3 的数量级叙述不一致 | unresolved；不影响弱形式机制，但影响精度宣传 | 核对正式版本、代码与作者修正 |
| CF03 | WENDy 参数协方差 | WENDy-C15：Eq. (15) 使用的 OLS 映射与 Algorithm 2 固定 $C$ 时的 WLS 映射不同 | unresolved implementation consequence；名义区间不可直接当作算法 estimator 的已验证协方差 | 从 Algorithm 2 直接推导 sandwich covariance，并运行 coverage simulation |
| CF04 | WENDy 噪声标准差 | WENDy-C16：Table 1 的除法与 §3.1 的乘法冲突 | unresolved；影响 benchmark 重现 | 检查官方代码的数据生成式 |
| CF05 | “95% prediction interval” | IDENT-C12：条件分位用 $5\%$–$95\%$，本身是中央 $90\%$；外层参数集合包络无自动 $95\%$ 预测覆盖保证 | qualified，不能把标签当 calibrated coverage | 以重复数据做逐时点/同时 coverage simulation |
| CF06 | K05b；WENDy 弱设计满秩 | S08 §2.1 声称 Conditions 1–4 足以保证 $G=\phi\Theta$ 满秩；WENDy-C14 的线性代数核验指出分别满秩不排除 $\operatorname{col}(\Theta)\cap\ker(\phi)\ne\{0\}$ | contradicted as a general sufficiency assertion；不能从分量秩直接升级为组合秩或 structural identifiability | 固化一个最小矩阵反例，并核对作者代码、勘误或后续版本 |

## 8. 真实 search trail

查询输入来自两个不同阶段。原始 forward test 的 `search_query` 输入是
2026-07-29 completion audit 从本机只读运行日志恢复的；其结果页、结果
排序、逐候选纳入/排除记录和 round 边界没有持久保存。较晚的
completion-audit 查询则在执行时直接记录了输入和可见结果。两者均不能补出
可靠的 `screened / included / excluded` 数量。

### 8.1 原始 forward test：可恢复的 exact query calls

下表的 log ID 只定位本机操作证据，不是公开来源 ID。它们证明这些查询实际
发生过，但不能把相邻 calls 追溯性包装成当时已预注册的 search rounds。

| Log ID | Exact queries |
| --- | --- |
| `59770583` | `Brunton Proctor Kutz 2016 SINDy foundational arxiv 1517384113`；`"Discovering governing equations from data by sparse identification" arxiv`；`site:arxiv.org Brunton "Discovering governing equations from data"` |
| `59771375` | `"Weak SINDy: Galerkin-Based Data-Driven Model Selection" arxiv`；`Messenger Bortz Weak SINDy Galerkin arxiv 2005.04339`；`site:arxiv.org 20M1343166 Weak SINDy` |
| `59773745` | `Nonlinear System Identification A User-Oriented Road Map IEEE Control Systems Magazine DOI 2019`；`Perspectives on system identification Ljung 2010 DOI full text` |
| `59775841` | `Ensemble-SINDy robust sparse model discovery uncertainty quantification DOI 2022 Royal Society`；`SINDy-PI Proc Royal Society A DOI 2020 476 20200279`；`Weak SINDy for partial differential equations DOI 2021 Journal Computational Physics`；`Sparsifying Priors for Bayesian Uncertainty Quantification in Model Discovery DOI` |
| `59776284` | `errors-in-variables SINDy measurement noise bias sparse identification nonlinear dynamics primary paper`；`SINDy identifiability candidate library coherence excitation sparse recovery primary paper`；`SINDy limitations partial observations measurement noise model misspecification primary source`；`equation discovery measurement error errors in variables ODE sparse regression 2024` |
| `59777188` | `"Sparse Identification of Nonlinear Dynamics with Control" DOI IFAC 2016`；`"Model selection for dynamical systems via sparse regression and information criteria" DOI`；`"A protocol for dynamic model calibration" DOI bbab387`；`"Sparse learning of stochastic dynamical equations" DOI` |
| `59777969` | `"Parameter Identifiability, Parameter Estimation, and Model Prediction for Differential Equation Models" PDF`；`"10.1137/24M1667968" pdf`；`Simpson Baker Parameter Identifiability Parameter Estimation Model Prediction 2026 arxiv`；`site:arxiv.org Simpson Baker identifiability parameter estimation differential equation models` |
| `59778697` | `site:par.nsf.gov "10.1137/24M1667968"`；`site:par.nsf.gov "Parameter Identifiability, Parameter Estimation, and Model Prediction"`；`site:ora.ox.ac.uk "Parameter identifiability, parameter estimation and model prediction"`；`site:researchdata.edu.au "Parameter identifiability, parameter estimation and model prediction" Simpson` |

这组历史输入已经包含 SINDy-PI、SDE、控制、系统辨识路线、EIV、模型选择和
可辨识性查询。因此不能再声称 SDE 是 completion audit 才“首次发现”的
分支。可恢复日志还含随后打开 PDF、定位页面和查词的 calls；由于公开报告
关注 search trail，这里不把 fetch/find 操作混计为新的搜索轮。

### 8.2 Completion audit CA-R1：官方身份复核

CA-R1 是 2026-07-29 较晚执行的一次 `web.search_query` 调用：

1. `site:pnas.org "Discovering governing equations from data" sparse identification nonlinear dynamical systems`
2. `site:epubs.siam.org "Weak SINDy" Galerkin-Based Data-Driven Model Selection`
3. `site:link.springer.com "Direct Estimation of Parameters in ODE Models Using WENDy"`
4. `site:siam.org "Parameter Identifiability, Parameter Estimation, and Model Prediction" differential equation models`

Observed result：query 1 未命中论文正文，后续直接访问 canonical DOI 返回
403；query 2 命中 SIAM DOI `10.1137/20M1343166`；query 3 命中
Springer VOR DOI `10.1007/s11538-023-01208-6`；query 4 命中 SIAM
Review DOI `10.1137/24M1667968`。这轮复核了 S03、S08、S10 的身份，
同时暴露 domain-restricted search 的假阴性和官方页面自动抓取限制。

### 8.3 Completion audit CA-R2：lineage 与 SDE 身份复核

CA-R2 针对同一身份缺口分两次调用。第一次的 exact queries 是：

1. `site:pnas.org/doi/10.1073/pnas.1517384113`
2. `site:royalsocietypublishing.org "Ensemble-SINDy" robust sparse model discovery`
3. `site:royalsocietypublishing.org "Model selection for dynamical systems via sparse regression and information criteria"`
4. `site:pubs.aip.org "Sparse learning of stochastic dynamical equations"`

可见结果只有 PNAS newsletter，非论文，其余 query 没有可用命中。随后执行
exact-title fallback：

1. `"Ensemble-SINDy: Robust sparse model discovery" DOI`
2. `"Model selection for dynamical systems via sparse regression and information criteria" DOI`
3. `"Sparse Learning of Stochastic Dynamical Equations" DOI`

Fallback 分别定位 arXiv `2111.10992` / DOI
`10.1098/rspa.2021.0904`、arXiv `1701.01773` / DOI
`10.1098/rspa.2017.0009`，以及 PubMed/NSF / DOI
`10.1063/1.5018409`。随后直接打开 PNAS、两个 Royal Society 和 AIP
官方 URL：前三个返回 403，AIP 为 safe-open error。论证因此回到已核验的
本地全文和合法仓储版本；抓取失败本身不被解释为来源不存在。二级结果只用于
定位 DOI，不支持方法或结果主张。

## 9. Stop decision

合并原始 forward test 与 completion audit 后，本次停止仍是
**bounded forward-test stop**，不是 `pragmatic saturation`。
理由如下：

- 已完成承诺中的中心确定性 ODE 路线地图、10 项文件 registry、四篇
  reconstruction、主张账本、冲突和技能缺陷回写；
- 原始查询输入虽可恢复，但当时的 round 边界、逐轮新增信息和筛选结果没有
  持久化，因此无法验证主报告旧版所称的“两轮无新增”；
- completion audit 的 CA-R1/CA-R2 是身份复核，不是两轮独立的全域
  saturation search；
- 更没有达到“连续两轮没有新增决策相关概念、路线、冲突或证据”的启发式；
- D01 无全文，隐式/有理式与部分观测分支也没有 decisive reconstruction；
- 搜索筛选数、完整结果页和 correction/retraction trail 未保存。

因此，原主报告的中心确定性 ODE 结论可以在上述边界内使用，K08 的
process-noise 部分保持 unresolved，不能宣称检索完整或停止规则已经触发。

下一项最高信息增益按用途分开：

1. 若继续完善领域地图：合法取得并深读 D01，随后对 SDE、隐式/有理式和
   部分观测各做带精确 query、筛选与排除原因的补充轮，并单列
   correction/contradiction search。
2. 若为具体工程决策：先审计目标系统的已测状态、输入、采样、重复、初值、
   工况、过程/测量噪声、候选物理机制和最终预测/参数用途，再只深挖改变
   路线选择的瓶颈。

## 10. Run environment, loaded skills and artifacts

### Environment and actions

- OS/architecture：`Linux 7.0.0-28-generic x86_64`。
- Python：`3.10.20`。
- Repository baseline：branch `agent/iterate-deep-research-skills`，
  evidence-pack 编写前 HEAD `027b81e337ae`。
- Skills under the original forward test：`deep-research`、
  `learn-from-papers`、`curate-research-to-zotero`。
- 本次 evidence-pack 整理按 `deep-research` 的 contract、registry、
  atomic ledger、conflict 和 transparent stopping 规则执行。
- 本文件的生成没有写 Zotero、没有调用 GitHub mutation、没有下载新论文。

### Durable and external artifacts

| Artifact | Status |
| --- | --- |
| 本主报告 `evals/real-world/sparse-dynamics-2026-07-29.md` | 仓库内、持久 |
| 本 evidence pack | 仓库内、持久 |
| `manifest.json` + 10 PDFs | 外部本地 corpus；10/10 当前文件哈希、magic、未加密、页数和文本提取通过 |
| S03/S08/S10 schema-9 notes | 外部本地 corpus；分别 22/22、36/36、27/27 页 reconstruction |
| S01 schema-9 note | 外部 Zotero migration artifact；44 页 main+SI reconstruction |
| 3 个 ingestion bundles / ingestion manifest | 外部本地 artifact；不复制到公开仓库 |
| Zotero migration/readback reports | 外部本地 artifact；本文件只引用既有证据，不执行写入 |
| Original search calls | 八次 `search_query` 输入由本机只读运行日志恢复；round 边界、完整结果输出与筛选表未持久保存 |
| Completion-audit search calls | CA-R1/CA-R2 的输入与可见结果在执行时记录于本文件；未另存完整结果页快照 |
| Search screened/excluded candidate table | **未持久保存**；数量不可恢复 |
| Observed model-token trace | **没有**；plugin-eval 的 trigger/invoke 数字只是静态估计 |
| Algorithm code/data execution | **没有执行**；没有 numerical reproduction、benchmark 或 empirical coverage run |

### Validation meaning

仓库测试验证的是技能契约、manifest/note 校验和 Zotero runner 的软件行为，
不验证 SINDy、WSINDy、WENDy 或 profile likelihood 的科学性能。PDF
可读/哈希通过也只证明本次读的是固定文件，不证明 canonical/read version
没有实质差异。四篇笔记的逐页 reconstruction 提高了 locator 与内部一致性
审计强度，但仍不是独立复现。

整理后的本地验证（2026-07-30）：

- `python3 -m unittest discover -s skills/curate-research-to-zotero/scripts -p 'test_*.py'`
  运行 141 项 fixture/mock 测试，结果 `OK`；这不是 live Zotero 写入。
- `python3 -m unittest discover -s evals/real-world -p 'test_*.py'`
  运行 30 项只读审计 harness 测试，结果 `OK`。
- 对三个技能分别运行 `skill-creator/scripts/quick_validate.py`，结果
  3/3 `Skill is valid!`。
- 对主报告与本 evidence pack 检查 Markdown fence、相对链接和表格列数，
  全部通过；`git diff --check` 通过。

# S0-Q Quality Feasibility Mission Card

## 状态

`SPEC-ONLY / BLOCKED_ON_INPUT`

本 Mission 只冻结 S0-Q 的真实输入和窄切片验收，不运行抽取，也不把既有
Golden drafts、人工清洗 Markdown 或缺少解析身份的样本写成可用输入。

## 业务目标

在进入 MVP-728 前，以两份真实寿险材料证伪或确认：经批准的弱模型能否在
WeKnora/W1 冻结解析难度下，完成候选区域定位、四类字段抽取、Evidence
回验与 typed fail-closed。S0-Q 只回答窄切片知识编译是否可行，不授予
`QUALITY_APPROVED`、生产准入或 Release 能力。

## Owner、周期与交付

- 唯一写 Owner：`codex/047-s0q-quality-feasibility`
- 执行模型：`gpt-5.6-sol`
- reasoning effort：`high`
- 当前交付：1 个文档/规格 PR，最多 5 个 Markdown 路径
- 后续运行：输入齐备后另获执行授权；不得在本 PR 内调用模型

## 依赖与当前阻断

运行前必须同时具备：

1. 两份真实材料各自对应的 `80a5003` WeKnora 冻结解析输出与 W1 Revision
   Manifest，或完全冻结的等价制品；
2. 一个预置 ProductVersion 的 exact identity；
3. 四个字段的人工确认 Seed Golden；
4. 一个获批准的弱模型运行画像与有限调用预算；
5. 隔离强模型诊断臂的 exact identity 与有限调用预算须另行预批准。

当前仓库未发现同时包含 artifact identity/digest、页码、表格结构与 parser
version 的两份可用制品；`dataset/goldenset/wip-gs-v0.1` 及 drafts 不自动
满足等价条件。因此当前唯一诚实状态是 `BLOCKED_ON_INPUT`。

## 输入冻结清单

每份材料必须在运行清单中记录且可复算：

- `material_id`、原始文件 digest、`source_revision_id`；
- W1 Revision Manifest identity/digest；
- parsed artifact identity/digest；
- parser name/version/build identity；
- 页码顺序与页范围；
- 表格结构 digest，包括跨页、表头、合并单元格和行列关系；
- candidate-region anchor 采用的 block/page/table-cell identity。

缺少任一项、digest 不匹配或使用人工整理 Markdown，均保持
`BLOCKED_ON_INPUT`，不得开始计分。

## 固定窄切片

- 恰好 2 份真实材料；
- 恰好 1 个预置 ProductVersion；
- 恰好 4 个经人工确认的 Seed Golden 字段：
  `present A`、`typed-present B`、`absent_explicitly`、`unknown`；
- 至少一个字段必须依赖真实复杂表格或跨页结构；
- ProductVersion 与四个实际字段 identity 当前均未提供，不得用占位 SHA、
  虚构产品或虚构字段代填。

`typed-present B` 是 v3 的第二个 present 字段：必须验证 typed value 及单位、
条件或日期归一。`absent_explicitly` 必须有原文正向否定 Evidence；
`unknown` 必须 abstain，不能从常识或其他材料猜值。

## 模型与人工边界

- S0-Q 实际运行只允许 exact approved 弱模型画像；模型、版本、prompt/schema
  identity、temperature/seed、最大调用/重试次数与超时必须在开跑前冻结。
- 上述弱模型预算尚未批准时保持 `BLOCKED_ON_INPUT`，不得边跑边扩预算。
- S0-Q 正式弱模型可行性链与 feasible 分子的强模型调用上限为 **0**。
  强模型只可作为隔离的诊断上限臂；须预先冻结 exact identity 与调用预算，
  不得兜底、补值、反馈弱模型链或计入 feasible 分子。
- 每个人工修订动作记录 actor、字段、开始/结束时刻、active duration 与原因。
  可接受时间上限须在运行清单中预先批准；未冻结上限不得输出 feasible。

## 小样本诊断消融

同一 2 材料/4 字段必须完成四臂矩阵，不得扩充样本或建设消融平台：

- A：给定 Seed Golden/oracle span，只测 extractor 与 typed normalization；
- B：固定 span/schema，对照 approved 弱模型与隔离强模型诊断上限；
- C：固定模型原始输出，只测 normalizer 与 comparator；
- D：固定 Claim，只测 Evidence verifier。

四臂分别记录 error bucket、abstention、人工修订动作和 active duration。oracle
span、raw output 与 Claim 都必须绑定同一冻结输入/字段身份，不能用人工清洗
Markdown 重新造输入。任一臂未完成不得输出 feasible。

## Exact 验收

只有以下条件全部满足，才可输出
`KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`：

1. 两份输入身份完整、digest 可复算，且没有人工清洗 Markdown；
2. 候选区域和复杂表格可从冻结 artifact 锚定；
3. ProductVersion exact 命中，不静默错配；
4. 四字段与 Seed Golden 一致；任何无法证明的结果 typed fail-closed；
5. Evidence 引文可回验，独立判定器与人工均确认语义支持；
6. `unknown` abstain，`absent_explicitly` 有正向否定 Evidence；
7. 错误按规定 bucket 记录，弱模型及人工预算均未超限；
8. A–D 四臂诊断消融在同一 2 材料/4 字段上完成；
9. 强模型只出现在预批准隔离诊断臂，没有进入正式弱模型链或 feasible 分子。

任一项失败都不得输出 feasible；报告须保留失败 bucket 与原始计数，不用总分
掩盖错误。

## 非目标

- 不实现 extractor、normalizer、comparator、Evidence verifier 或质量平台；
- 不把消融矩阵扩展到更多材料/字段或通用实验平台；
- 不运行模型/provider/live/PostgreSQL/full；
- 不创建 Candidate、Release、ReviewDecision 或生产数据；
- 不修改源码、migration、workflow、principal、registry 或 README；
- 不复用 S0-R fixture，也不把 S0-Q 结果解释为 S0-R/MVP/生产通过。

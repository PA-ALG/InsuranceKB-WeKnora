# 047 Validation Report

## 状态

`SPEC-ONLY / BLOCKED_ON_INPUT`

本报告只记录 S0-Q 输入/验收规格候选，不是 S0-Q 运行报告，也不表示
`KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE` 或 `QUALITY_APPROVED`。

## Identity 与范围

- base/HEAD：`6605c703282e442a8636d7f323f17396e6f00d49`
- branch：`codex/047-s0q-quality-feasibility`
- delivery：5 个 Markdown 路径
- registry：`NOT MODIFIED`；047 预留由并行 046 Owner 负责
- 源码、migration、workflow、principal、README：零修改

## 输入核验

定向读取已合入 ADR、Authority Amendment 2、V3 S0-Q 与 W1 规格后，确认 W1
Revision Manifest 合同/实现存在；但仓库中未发现两份可直接用于 S0-Q、并同时
冻结以下信息的 parsed artifact bundle：

- 原始材料/SourceRevision/W1 manifest/parsed artifact identity 与 digest；
- parser name/version/build；
- 页码顺序/范围；
- 复杂表格结构；
- candidate-region anchor。

现有 `dataset/goldenset/wip-gs-v0.1` 与 drafts 不自动满足上述等价条件。
因此两份材料、一个 ProductVersion、四个实际字段和弱模型运行预算均不得用
假值补齐，当前状态保持 `BLOCKED_ON_INPUT`。

## 冻结的验收边界

- 2 份真实冻结解析材料、1 个预置 ProductVersion、4 个 Seed Golden 字段；
- candidate region、复杂表格、typed value/归一、Evidence 语义支持；
- `absent_explicitly` 正向否定 Evidence 与 `unknown` abstention；
- typed fail-closed 与八个最小顶层 error buckets；
- exact 弱模型画像/调用预算与人工修订时间上限须在运行前批准；
- 同一 2 材料/4 字段必须完成 oracle span、模型上限、固定 raw output、固定
  Claim 四臂诊断消融，并记录 buckets/abstention/人工时间；
- 正式弱模型链与 feasible 分子的强模型调用上限为零；隔离强模型诊断须另行
  预批准 exact identity/调用预算，不兜底、不计通过；
- 只有全项通过才能输出窄切片 feasible，不授予生产或质量批准。

## 独立最终复审

- `BLOCKER`：0
- Spec Approved：`YES`
- Delivery/YAGNI Approved：`YES`
- 四臂 A–D 均为同一 2 材料/4 字段上的 mandatory 诊断，任一未完成不得输出
  feasible；
- 强模型只用于预批准 exact identity/有限预算的隔离 B 臂，不兜底、不反馈
  正式弱模型链，也不进入 feasible 分子。

复审不改变当前 `BLOCKED_ON_INPUT`，也不把任何 NOT RUN 项写成已执行。

## 文档门禁

- `openspec validate 047-s0q-quality-feasibility --strict`：`PASS`
- new-file no-index `git diff --check`：`PASS`
- exact five-path Markdown scope：`PASS`
- model/provider/live/PostgreSQL/full：`NOT RUN`（spec-only，且输入阻断）

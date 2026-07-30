# 047 Validation Report

## 状态

`SPEC-ONLY / BLOCKED_ON_INPUT`

本报告同时记录已批准运行的首次输入预检结果。它不是 A–D 质量运行报告，也不
表示 `KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`、
`QUALITY_APPROVED` 或 S0-Q 质量失败。

## Identity 与范围

- base/HEAD：`6605c703282e442a8636d7f323f17396e6f00d49`
- branch：`codex/047-s0q-quality-feasibility`
- delivery：5 个 Markdown 路径
- registry：`NOT MODIFIED`；047 预留由并行 046 Owner 负责
- 源码、migration、workflow、principal、README：零修改

以上 identity 是 047 spec-only 历史交付身份。2026-07-30 运行实现从
`origin/main=1650f3bb26fd92af554c22f45d7df0a45e29c160` 的独立 worktree
开始；输入 capture 实现与本次阻断 artifact 已提交为
head/tree=`0d80939ce0562b39b8eb5a54bcf043199c92f80e` /
`378b0da59daaddecd45a2ecfac64a6b5861a5b27`。最终 PR identity 由 exact-head
独立复审记录，不用自引用占位值伪造。

## 2026-07-30 首次有界输入预检

二进制结论：`BLOCKED_ON_INPUT`，bucket=`input_integrity`。

- 两份批准 PDF 均直接从仓库读取，bytes 与 SHA-256 精确匹配 Mission Card；
- 原有固定 digest WeKnora app/docreader/frontend 与依赖容器仍健康，未重置、
  未修改；
- 原有持久化运行环境的 admin identity 与现有 runtime credential 已不匹配；
  只读登录返回 HTTP 401，未尝试重置；
- 为隔离旧 volume 漂移，创建了一次同固定镜像的临时 fresh stack；它在停止前
  健康；
- 创建任何 model/RAW KB/scratch KB/API key/knowledge/upload 之前，唯一一次
  WeKnora 输入基础设施 embedding dimension probe 返回 HTTP 401；
- exact source inspection 同时确认 current W1 v1 manifest 只绑定 text chunk
  id/index/content；revision chunks 未暴露或绑定 page/block/table-cell identity
  与表格结构 digest。只有扁平文本和 `table` 标签时，新的 admission 测试会
  typed fail closed，不允许 Harness 猜表头、合并单元格或行列关系；
- 因输入画像未 admitted，W1 bundle/input manifest 未创建，Harness 弱模型
  调用=0、强模型诊断调用=0，A–D=`NOT RUN`；
- 临时项目的 containers/network/volumes 与含临时配置的目录均已精确删除；
  scratch 资源从未创建，因此不存在遗留 scratch 数据。

非敏感机器证据：
`artifacts/input-capture-report.json`。

本次停止点严格位于 Q1 输入门。外部配置需由用户刷新/替换既有批准的百炼
embedding credential；开发侧下一条唯一主航道是另行批准一个最小 W1
page/block/table-cell identity + table-structure digest 绑定补丁。两项输入
先决条件齐备后，才复用同一隔离 capture 流程重试一次；不得创建假 embedding、
人工整理 PDF 或提前进入模型/A–D。

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
- `pytest tests/test_s0q_047.py tests/test_source_weknora_017.py`：
  `72 passed`
- S0-Q runner/module/tests Ruff 与 mypy：`PASS`
- `git diff --check`：`PASS`
- full、PostgreSQL suite、无关 provider/live：`NOT RUN`
- 已授权的本地 WeKnora 输入预检：`RUN / BLOCKED_ON_INPUT`；仅一次
  embedding 基础设施探测，未运行 Harness 模型链

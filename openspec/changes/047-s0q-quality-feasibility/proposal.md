# 047 · S0-Q Quality Feasibility

## 状态

`SPEC-ONLY / BLOCKED_ON_INPUT`

## Why

在 MVP 投入前，用两份真实、冻结解析难度未被人工清洗的寿险材料，判断弱模型
能否在窄切片上产出可回验、可分桶、会 abstain 的知识结果。失败可以尽早暴露
定位、表格、版本、归一或 Evidence 瓶颈，而不是由强模型兜底或漂亮 Markdown
掩盖。

## What Changes

1. 两份 WeKnora/W1 冻结 parsed artifact（或完全冻结等价制品）的身份合同；
2. 一个预置 ProductVersion，以及从冻结完整产品 Golden 投影的四条诊断记录；
3. candidate region、复杂表格、Evidence 和 typed fail-closed 验收；
4. 最小错误 bucket、abstention 与人工修订时间记录；
5. 只在 2 材料/4 字段上运行 A–D 小样本诊断消融；
6. 弱模型预算须预先冻结；强模型只可作预批准隔离诊断上限，不进入正式弱模型
   链或 feasible 分子；
7. 当前输入不齐时唯一状态为 `BLOCKED_ON_INPUT`。

## 当前阻断

仓库中没有可直接证明为 S0-Q 输入的两份 frozen parsed artifact bundle。
既有 Golden WIP 已覆盖目标产品的完整可抽取字段集，但尚未形成当前
`gpt-5.6-sol` 全字段复核、Evidence/人工批准和不可变 identity/digest；它也
缺少所需的 WeKnora/W1 artifact identity、页码、表格结构和 parser version
完整绑定，不能默认等价。本 change 不造 SHA、材料、ProductVersion 或字段
样本，也不把规格写成 S0-Q PASS。

## Impact

- 原始 spec-only 交付为一个文档/规格 change 与一份 Mission Card；
- 2026-07-30 经业务方另行批准的 authority amendment 增加 exact XLSX、
  authority README 和必要的 provenance/Golden 合同更新；
- 零源码、migration、workflow、principal、运行时 registry 修改；
- 零模型/provider/live/PostgreSQL/full 运行；
- 输入齐备后的实际 S0-Q 运行须另获授权，并按本规格产生真实报告。

## 非目标

不建设完整质量平台、新 Golden 管理平台、模型路由器、在线强模型 judge、
通用消融平台、Release Kernel、S0-R、MVP 集成或生产准入，也不扩大两份材料
与四条诊断记录。不得另建四字段 Golden。

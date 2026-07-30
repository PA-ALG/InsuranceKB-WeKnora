# 047 S0-Q Quality Feasibility Specification

## ADDED Requirements

### Requirement: Q1 S0-Q 只接受冻结的真实解析输入

S0-Q SHALL 恰好消费两份真实材料。每份输入 SHALL 来自当前 `80a5003`
WeKnora 冻结解析输出与 W1 Revision Manifest，或具备完全等价冻结身份的制品。
每份材料 SHALL 绑定原始文件、SourceRevision、W1 manifest、parsed artifact
digest、parser name/version/build、页码顺序/范围和表格结构 digest。

人工清洗 Markdown、缺少任一 identity/digest、页码或表格结构不可复算的制品
SHALL NOT 进入运行。此时状态 SHALL 为 `BLOCKED_ON_INPUT`，且不得计分。

#### Scenario: 只有 Golden draft

- **WHEN** 样本有字段标签，但没有完整 frozen parsed artifact identity
- **THEN** 状态保持 `BLOCKED_ON_INPUT`，不得把 draft 当作等价输入

#### Scenario: 人工整理 Markdown

- **WHEN** 输入将原 PDF/表格人工改写成干净 Markdown
- **THEN** S0-Q 拒绝该输入，不运行 extractor，也不输出 feasible

### Requirement: Q2 窄切片身份必须在运行前冻结

运行清单 SHALL 在开始前冻结恰好一个 ProductVersion exact identity，以及从
同一冻结、获批的完整产品 Golden 投影的四条诊断记录：

1. `present A`：基础成功路径；
2. `typed-present B`：typed value，并验证单位、条件或日期归一；
3. `absent_explicitly`：原文明示否定，并有正向否定 Evidence；
4. `unknown`：材料不足，必须 abstain。

至少一个字段 SHALL 依赖真实复杂表格或跨页结构。字段、ProductVersion、
expected typed value、normalization rule 与 Golden Evidence 未冻结时 SHALL
保持 `BLOCKED_ON_INPUT`。系统 SHALL NOT 以占位 SHA、虚构产品或字段补位，
也 SHALL NOT 为 S0-Q 单独创建四字段 Golden。

业务 Schema 权威 SHALL 绑定
`docs/insurance-kb/schema-authority/产品知识库字段标签维度-20240205.xlsx`
及 SHA-256
`5cd0ed8af0bc10fec488d0d83e8e28c7c0d64408c4fc25cca92b2a365355fdb6`。
每条诊断记录 SHALL 可解析到该工作簿中的来源工作表和现有 registry field
identity。

当前目标医疗产品 Golden WIP 覆盖 60/60 个可抽取字段，但只证明覆盖。R2 SHALL
保持未完成，直到独立 Golden Mission 使用 `gpt-5.6-sol` 对全部 60 字段统一
生成候选或复核，完成 Evidence 回验与既定人工批准，并冻结不可变 artifact
identity/digest。制品 SHALL 区分 49 个工作簿权威字段和 11 个后续 v1.1 扩展；
不得把扩展字段静默提升为工作簿权威。

#### Scenario: ProductVersion 静默错配

- **WHEN** 输入无法 exact 解析到预置 ProductVersion，或解析到其他版本
- **THEN** 结果 typed fail-closed，禁止继承相似产品版本或继续计为成功

#### Scenario: unknown 字段

- **WHEN** 两份冻结材料均不足以支持该完整 Golden 诊断记录
- **THEN** 结果必须 abstain 为 `unknown`，不得猜值或改写为
  `absent_explicitly`

### Requirement: Q3 定位、表格与 Evidence 必须保留真实难度

candidate region SHALL 从冻结 artifact 的 page/block/table-cell identity
定位，不得从人工摘要反推。复杂表格 SHALL 保留跨页、表头、合并单元格及行列
关系。每个非 unknown 结果的 Evidence SHALL 回到 exact artifact/page/region，
并同时通过独立判定器与人工语义支持核对。

Evidence verifier SHALL 区分“引文存在”与“引文支持该 typed claim”。锚点缺失、
跨版本、表格结构不一致或只提供相邻但不支持的文字 SHALL typed 失败。

#### Scenario: 引文存在但不支持结论

- **WHEN** citation 可打开，但没有语义支持结果值、条件或明确否定
- **THEN** 进入 `evidence_verifier` 失败 bucket，不得计为通过

#### Scenario: 表格结构被扁平化

- **WHEN** parsed artifact 丢失决定字段含义的表头、合并单元格或跨页关系
- **THEN** 输入/定位 typed 失败，不用语言模型猜测缺失结构

### Requirement: Q4 失败、abstention 与错误分桶必须可核验

四字段 SHALL 得到冻结完整 Golden 的预期结果，或得到 typed fail-closed 结果；空值、
异常吞没、静默 fallback 或无 Evidence 的猜值 SHALL NOT 表示成功。

报告 SHALL 使用以下最小顶层 bucket：

`input_integrity | candidate_region | product_version | extraction |
normalization | comparator | evidence_verifier | abstention`

实现可增加子码，但不得把失败移出顶层 bucket 或只报总分。每次 attempt SHALL
记录字段、阶段、结果、abstention、bucket 和 Evidence identity。

#### Scenario: 运行时出现未预期异常

- **WHEN** extractor、normalizer、comparator 或 verifier 无法给出合规结果
- **THEN** 对应字段 typed 失败并进入最接近的顶层 bucket，不返回猜测值

### Requirement: Q5 弱模型与人工预算必须预先封闭

S0-Q 实际运行 SHALL 只使用一个 exact approved 弱模型运行画像，并在运行前
冻结 model/version、prompt/schema identity、temperature/seed、最大调用/
重试次数与 timeout。预算缺失或运行中要求扩张时 SHALL 保持或回到
`BLOCKED_ON_INPUT`，不得边跑边放宽。

S0-Q 正式弱模型 extractor、补抽、fallback、judge 与 feasible 分子的强模型
调用上限 SHALL 为零。Q6 隔离诊断上限臂 SHALL 使用强模型，并在运行前冻结
exact model/version identity 与有限调用预算；强模型不得用于该臂之外。
其输出不得兜底、补值、反馈弱模型链或计作 feasible 分子。

每个人工修订 SHALL 记录 actor、字段、原因、开始/结束时间和 active duration。
人工修订时间上限 SHALL 在运行清单中预先批准；未冻结或超出上限时不得输出
feasible。

#### Scenario: 弱模型失败后调用强模型

- **WHEN** 弱模型没有产出合规结果并尝试调用强模型补值或裁决
- **THEN** S0-Q 不通过，强模型结果不进入分子或 Candidate

### Requirement: Q6 四臂诊断消融必须关闭主要误差归因

S0-Q SHALL 只在同一两份材料、完整 Golden 投影的四条诊断记录上完成以下矩阵：

- A：给定绑定冻结 artifact 的 Golden/oracle span，只测 extraction 与 typed
  normalization；
- B：固定相同 span/schema，对照 exact approved 弱模型与预批准隔离强模型
  诊断上限；
- C：固定同一模型原始输出，只测 normalizer 与 comparator；
- D：固定同一 typed Claim，只测 Evidence verifier。

每臂 SHALL 记录字段 identity、固定输入 identity、输出、error bucket、
abstention、人工动作与 active duration。强模型诊断输出 SHALL 与正式弱模型链
隔离，不进入 feasible 分子。矩阵 SHALL NOT 扩大材料/字段、改写 oracle span，
或建设通用实验平台。任一臂未完成时 SHALL NOT 输出 feasible。

#### Scenario: 强模型诊断优于弱模型

- **WHEN** B 臂的隔离强模型上限优于 approved 弱模型
- **THEN** 该差值只定位模型能力瓶颈，不补写弱模型结果，也不增加 feasible 分子

#### Scenario: 固定中间产物定位错误

- **WHEN** A、C 或 D 在固定上游输入后仍失败
- **THEN** 报告把失败归入对应 extraction/normalization/comparator/
  evidence_verifier bucket，并记录 abstention 与人工时间

### Requirement: Q7 Feasible verdict 必须完整且保持窄范围

The S0-Q report SHALL emit the feasible verdict only when Q1–Q6 are all
satisfied。四字段必须均与冻结完整 Golden 一致、Evidence 语义支持通过、
`unknown` 正确 abstain，且预算未超限：

`KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`

输入未齐时 SHALL 只报告 `BLOCKED_ON_INPUT`。运行后的任一验收失败 SHALL NOT
输出 feasible，并 SHALL 保留 error buckets、分子/分母、attempt 与人工修订
证据。不得用总准确率平均掉四类字段中的失败。

该 verdict SHALL NOT 表示 `QUALITY_APPROVED`、模型生产准入、S0-R PASS、
Release Kernel/MVP 完成或 machine_auto 资格。

#### Scenario: 三个字段通过、一个字段失败

- **WHEN** 四字段任一定位、值、状态、Evidence 或预算验收失败
- **THEN** 不得输出 feasible，即使聚合分数看似足够高

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

### Requirement: Q1a Existing-source capture 必须只读且不升级观察证据

047-R1E SHALL 只对两个已存在、显式绑定的 knowledge/revision 执行
`knowledge_get`、`revision_get` 与 `revision_chunks_get`。客户端 capability
allowlist SHALL 恰为这三个 GET operation；出现 upload、reparse、delete 或任一
其他 operation 时 SHALL 在首次 API I/O 前 fail closed。

请求 SHALL 绑定 exact tenant、Space、RAW KB、knowledge id 与两份固定 PDF
SHA-256。validated runtime 中既有 `LOCAL_LIVE_TENANT_ID`（positive decimal）、
`LOCAL_LIVE_SPACE_ID` 与 `LOCAL_LIVE_RAW_KB_ID` SHALL 全部存在、非空并与请求
exact match；否则 SHALL 在创建 client 或首次 GET 前 fail closed。source-reader
credential SHALL 只从独立 process environment 注入，不得加入 runtime mapping、
`.env`、CLI 参数或输出。

两个 source SHALL 按固定顺序执行一个全局 fence：PRE 阶段读取两者
knowledge K0 与 revision R0；BODY 阶段读取两者完整分页 chunks 并重算
manifest；POST 阶段读取两者 revision R1 与 knowledge K1。只有全部 POST
验证完成后才可构造输出。R1 SHALL 与 R0 的 knowledge/attempt/file SHA、
parser identity、manifest algorithm/digest/count 与 completed 字段 exact
相等；K1 SHALL 与 K0 的 id/tenant/RAW KB/status/current attempt/SHA exact
相等。Space SHALL 由 client 创建前已验证的 runtime identity graph 绑定；
authoritative Knowledge GET DTO 不暴露 `space_id`，因此 response fence 不得
要求或推断该字段。descriptor、每页 binding、每个 chunk、总数、attempt 和
text manifest SHALL 一致。capture SHALL 以既有
`weknora.chunk_manifest.v1` 算法从 chunk id/index/content 重算 manifest。
跨 tenant/Space/KB、SHA/attempt 漂移、分页混版或 manifest 不一致 SHALL typed
fail closed，且不得形成 admitted bundle 或改变 revision/manifest。

输出 SHALL 只包含 parser/profile、current attempt、revision/text manifest、
字段名/type/shape与非敏感 digest；不得包含正文、secret、credential 或绝对
路径。远端 mapping key 只有 task-local 固定 structural-key allowlist 中的
page/block/table/cell/row/column/span/header/cross-page 与必要 identity/container
键可进入 shape；未知 key 的原文或 digest 均不得输出，只可省略或聚合
member count/type。API 暴露的 locator/labels/metadata SHALL 只分类为
`PRESENT_UNBOUND` 或 `ABSENT_INSUFFICIENT`。它们不是 cryptographic structure
binding；缺少 page/block/table-cell 与 table-structure digest 的可复算绑定时
状态 SHALL 为 `W1_STRUCTURE_EVIDENCE_INSUFFICIENT`，不得猜测、上传、reparse
或授权后续 S0-Q。

#### Scenario: 已有 chunk 只有 table label

- **WHEN** existing revision 的 metadata/labels 暴露 `table`、page 或 cell
  字段，但 W1 manifest 没有绑定结构内容
- **THEN** capture 记录 `PRESENT_UNBOUND` 并输出
  `W1_STRUCTURE_EVIDENCE_INSUFFICIENT`，`admitted_bundle` 必须为空

#### Scenario: 双读期间 current attempt 漂移

- **WHEN** 任一 source 在另一 source 的 BODY 读取期间漂移，或 R1/K1 与对应
  R0/K0 的冻结 identity 不同
- **THEN** capture typed fail closed，不拼接两次 revision/chunks，也不写
  revision、manifest 或 bundle

#### Scenario: runtime scope 或 credential ingress 不完整

- **WHEN** runtime tenant/Space/RAW KB 任一缺失或不匹配，或独立 process
  environment 没有 source-reader credential
- **THEN** capture 在创建 client 与任何 GET 前 typed fail closed，secret 不得
  出现在报告或错误

#### Scenario: 远端 mapping key 包含敏感值

- **WHEN** response key 是 absolute path、URL、DSN、token 或未知嵌套 key
- **THEN** key 原文及其 digest 均不得进入序列化报告，结构状态仍保持
  `PRESENT_UNBOUND` 或 `ABSENT_INSUFFICIENT`

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

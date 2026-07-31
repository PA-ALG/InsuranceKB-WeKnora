# S0-Q Full Golden Freeze Specification

## ADDED Requirements

### Requirement: F1 两个 blind pass 必须覆盖同一 exact 60 字段

系统 SHALL 从当前 medical Schema registry 取得 60 个 extractable field
identity。candidate 与 review SHALL 分别是 `gpt-5.6-sol` 的隔离 blind pass，
各自形成 field-id exact bijection；模型输入 SHALL NOT 包含旧 60/71 Golden、
pred、keypoints、judge 输出或四字段 oracle。

每个 pass SHALL 冻结独立 pass id、model identity、六批预算、exact prompt
SHA-256、input-manifest digest、输入 allowlist、实际 parse retry 和三份输入
文件 SHA-256。allowlist SHALL 只含 60-field contract、必要 Schema identity、
`596`、`596-1` 与三份 PDF identity，不得包含旧 Golden、pred、keypoints、
draft 或另一个 pass 输出。两个 pass 的 parse retry 合计 SHALL 不超过两次。
任一重复、缺失、额外、field name 漂移、digest 漂移或 forbidden reference
SHALL fail closed。

#### Scenario: 旧 Golden 进入 blind prompt

- **WHEN** 任一 blind pass 输入包含历史答案或另一个 pass 的输出
- **THEN** 该 pass 作废，不得进入 diff、人工审核或 artifact

### Requirement: F2 三 PDF Evidence 必须确定性回验

每个 `present` 或 `absent_explicitly` 记录 SHALL 引用
`保险条款.pdf`、`产品说明书.pdf` 或 `费率表.pdf` 中的 exact 1-based page 与
非空 quote；quote SHALL 经现有 Golden normalize/verify 语义回到原页。
`unknown` SHALL 没有 Evidence。任一未知文档、越界页或 quote mismatch SHALL
fail closed。三份源文件的 path、size 与 SHA-256 SHALL 全部进入 manifest。

#### Scenario: 引文只在旧草稿中存在

- **WHEN** quote 不能从冻结 PDF 原页复算
- **THEN** 字段不得进入 final Golden，也不得由人工批准绕过

### Requirement: F3 三份材料必须归并为唯一 60 行

candidate、review 与 final SHALL 各自只有 60 个 field-id，一字段一行。模型
不得按三份 PDF 输出 180 行。final 每条记录 SHALL 与现有 `GoldenRecord`
兼容，并保留唯一 source document、tri-state、value、Evidence、reasoning、
model 与 Schema version。

#### Scenario: 同一字段在两个文档重复

- **WHEN** 两个文档均给出候选
- **THEN** blind pass 必须合并为一个字段记录；冲突进入人工 review，不得保留
  两行或静默选取

### Requirement: F4 人工 review 集不得抽样遗漏

人工 review 集 SHALL 等于 candidate/review 全部语义差异，并集六个固定必审
字段与以冻结算法预选的三个固定样本。六个固定必审字段为：
`regulatory_filing_no`、`clause_version`、`clause_effective_date`、
`exclusions_official`、`pre_existing_conditions`、
`discontinuation_renewal`。

每个 review 字段 SHALL 有具名人工 action、选择或自定义 final record 与理由；
custom SHALL 保持 exact field identity，并重走相同 tri-state 与 PDF Evidence
校验。差异或必审字段缺 decision 时 SHALL 保持 `PENDING_HUMAN_REVIEW`。
逐项 decision 闭合后，人工还 SHALL 对完整 60 行 subject 整体批准。

#### Scenario: 两 pass 相同便自动批准固定必审字段

- **WHEN** 固定必审字段在两个 pass 中相同但没有人工 decision
- **THEN** approval 仍不可构造

### Requirement: F5 approval 必须绑定 exact immutable identity

系统 SHALL 复用现有 `release_hash` 计算 final 60 行的 Golden identity，并用
C0 `canonical_hash` 计算包含 Schema、ProductVersion、三源文件、两个 blind
pass、diff、人工 decisions 与 final records 的 `artifact_hash`。approval
subject SHALL 同时绑定两者。

approval 前只可在内存或临时目录形成 review subject，并 SHALL 停机请求具名
裁决；不得创建 unsigned release artifact 目录。只有 `actor_type=human` 的具名
principal 对 exact subject 执行显式 approve，且总控基于该用户动作提供绑定
subject/release/artifact hash 与 conversation/user-approval audit provenance
的外部 receipt 后，四件 artifact 才可原子写入全新目录，状态才可为
`FROZEN_FULL_GOLDEN`。脚本 SHALL NOT 提供 self-approve、approve-as 或自动
生成 receipt 的路径。模型、服务、默认或 placeholder principal、hash 漂移、
既有目录或缺失 decision SHALL fail closed，且不得留下部分输出。

#### Scenario: approval hash 过期

- **WHEN** decision、Evidence 或 final record 变化后仍提交旧 subject
- **THEN** 命令拒绝且零 artifact 写入

### Requirement: F6 frozen Golden 只授予 S0-Q 使用资格

成功制品 SHALL 恰好为 `596.jsonl`、`manifest.json`、`disputed.jsonl` 和
`review-and-approval.json`。`disputed.jsonl` SHALL 为空，manifest SHALL 记录
文件 hash、release/artifact/approval subject、49 workbook-authoritative 与
11 extension 字段计数。

该状态 SHALL 仅表示 `S0_Q_FROZEN_FULL_GOLDEN_AVAILABLE`，不得表示
`QUALITY_APPROVED`、生产 Release、`machine_auto`、S0-Q feasible 或 WeKnora
已写入。

#### Scenario: 未运行 S0-Q 即宣称 production ready

- **WHEN** 下游把 frozen Golden 解释为模型或生产资格
- **THEN** 合同拒绝该升级；S0-Q 与生产门禁仍须独立完成

# Parsed Document Contract Specification

## ADDED Requirements

### Requirement: PDC1 exact parser-neutral identity

`ParsedDocumentV1` 与 `ParseManifestV1` SHALL 绑定 exact Space、Source、
SourceRevision、ProductVersion、052 MaterialProfile/binding、source SHA-256、raw
artifact、C0 canonical envelope、parser engine/profile/build/config、attempt identity 与
generation。任何 identity 漂移 SHALL 在下游模型、ExtractionTask 或写入前 fail
closed。

#### Scenario: mixed revision

- **WHEN** document 与 manifest 的 SourceRevision、parser config 或 attempt 不同
- **THEN** 返回 `identity_revision_parser_drift`，零 admitted artifact

### Requirement: PDC2 complete ordered structure and locators

document SHALL 保存 ordered page/block/table/cell facts。每个 element SHALL 有稳定
identity、kind、连续 order、page locator、content digest 与 structure digest；block/
table/cell SHALL 含对应 locator，cell SHALL 含 row/column/span，bbox 若存在必须有效。
正文、secret、绝对路径和未知 vendor 字段 SHALL NOT 进入合同。

#### Scenario: element order or locator is invalid

- **WHEN** element identity 重复、order 不连续、cell 缺 table/row/column/span 或 bbox
  反向
- **THEN** validation fail closed，不生成 manifest

### Requirement: PDC3 deterministic complete manifest

`ParseManifestV1` SHALL 从 validated document 确定性派生 ordered element inventory、
page/block/table/cell counts、capability Evidence、warnings、unsupported facts、snapshot
completeness 与 document hash，并用 C0 canonical hash 生成 manifest hash。调用方不得
手工覆盖 count、order 或 hash。

#### Scenario: manifest is tampered

- **WHEN** count、ordered element id、document hash 或 manifest hash 任一变化
- **THEN** 返回 `manifest_digest_or_count_mismatch`

### Requirement: PDC4 required capability evidence

manifest SHALL 消费 052 MaterialProfile 的 exact `required_parse_capabilities`。只有
subject 类型与结构形状符合当前 capability family 的 Evidence 才能计入 satisfied；
缺失、未知或错类型 subject ref SHALL 保留为未满足事实并由 ParseQuality typed fail
closed。`table_grid` 至少要求同一当前 document 中的 table、归属于该 table 的 cell
及对应 locator；page Evidence 不得冒充 table/cell Evidence。unsupported capability
SHALL 记录 typed reason 且不得同时声明为 supported。

#### Scenario: capability is self-reported without evidence

- **WHEN** parser 声称 `table_grid` 但没有当前 attempt 的 table/cell structure Evidence
- **THEN** 返回 `locator_invalid_or_required_structure_missing`

### Requirement: PDC5 bounded attempt and upstream policy authority

attempt 只允许 `default/1` 或 `bounded_upgrade/2`。ParseQuality SHALL 只消费 052
验证后的完整 `MaterialProfileResolution`，并 exact 绑定 catalog/profile/source、
`binding_hash`、required capabilities 与 default/upgrade/trigger/attempt/privacy-output
policy；裸 receipt、caller flag、parser metadata 或隐式默认不得授予 ESCALATE。
上游 resolution 缺失或任一 preimage 漂移时 SHALL 返回 typed BLOCK+ReviewItem，
不得抛 raw attribute error 或猜测。

#### Scenario: caller requests escalation

- **WHEN** default 不足且 caller 自报 `allow_upgrade=true`，但没有 052 exact policy
- **THEN** `ParseQualityDecisionV1` 返回 BLOCK/ReviewItem，parser calls 不增加

#### Scenario: second attempt is insufficient

- **WHEN** bounded upgrade attempt 仍缺 required capability
- **THEN** 返回 BLOCK/ReviewItem，不执行第三次 parser attempt

### Requirement: PDC6 typed quality decisions

`ParseQualityDecisionV1` SHALL 记录 exact identity、manifest hash、required/measured
facts、threshold version、`ADMIT | ESCALATE | BLOCK` 与以下 reason families：

- `identity_revision_parser_drift`；
- `manifest_digest_or_count_mismatch`；
- `locator_invalid_or_required_structure_missing`；
- `table_grid_or_span_incomplete`；
- `unsupported_material_or_parser_profile`；
- `privacy_or_output_policy_violation`。

ADMIT SHALL 要求全部 required capabilities 有 Evidence、manifest 完整、threshold
version 与 policy exact 匹配；ESCALATE 只允许 default attempt 且有 052 approved
upgrade；BLOCK SHALL 形成非空 typed ReviewItem。

#### Scenario: upstream policy is absent

- **WHEN** quality evaluator 无法取得 052 批准的 exact parser/threshold/privacy policy
- **THEN** 返回 `BLOCK` 与非空 typed ReviewItem，不得由 caller flag 生成
  `ESCALATE`

### Requirement: PDC7 narrow pure-domain boundary

053 SHALL 只有纯 Python DTO/validation/hash 与 focused tests。不得实现 parser、OCR、
VLM、Markdown structure inference、provider/model、DB/migration、WeKnora/API/worker/
queue 或通用平台，也不得读取 049 Golden 答案。

#### Scenario: contract construction is pure

- **WHEN** caller validation document、构建 manifest 或执行 quality decision
- **THEN** 仅执行内存 DTO/validation/hash，不产生网络、数据库、文件或 provider 写入

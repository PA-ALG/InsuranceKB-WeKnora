# MaterialProfile Template Binding Specification

## ADDED Requirements

### Requirement: MPTB1 exact `596/596-1` catalog identity

052 SHALL 只接受 product code `596`、ProductVersion `596-1`、product line
`medical` 与 Schema `v1.1+b31a411c621c`。catalog SHALL 冻结 medical 当前
60 个 extractable field-id，且 field authority union 与该集合 exact 双射。
缺失、重复、额外字段或 Schema 身份漂移 SHALL fail closed。

#### Scenario: 请求了相邻版本

- **WHEN** request 使用 `596-2` 或其他 product code
- **THEN** 产生 `product_identity_mismatch` typed ReviewItem，不调用
  TemplatePackage catalog

### Requirement: MPTB2 三 PDF exact source identity 与确定分类

catalog SHALL 恰好登记三份 source：

| material role | repository-relative path | size | SHA-256 |
|---|---|---:|---|
| `terms` | `dataset/shouxian_product/平安e生保（尊享版）医疗保险/保险条款.pdf` | 1047811 | `88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc` |
| `brochure` | `dataset/shouxian_product/平安e生保（尊享版）医疗保险/产品说明书.pdf` | 492101 | `5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279` |
| `rate_table` | `dataset/shouxian_product/平安e生保（尊享版）医疗保险/费率表.pdf` | 51961 | `7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb` |

material role SHALL 来自这个 approved exact source registration。文件名、模型、
parser 或 caller hint SHALL NOT 铸造或提升 role。caller classification 与登记
role 冲突时 SHALL 输出 `material_role_conflict` ReviewItem。

#### Scenario: 伪造同名文件

- **WHEN** 请求 path 以 `保险条款.pdf` 结尾，但不是 catalog 中 exact path
- **THEN** 拒绝为 `source_not_registered`，不从 basename 推断 `terms`

### Requirement: MPTB3 字段级 primary/support authority

每个 medical field-id SHALL 恰好属于一个 authority group，具有唯一
`primary_role`、与 primary 不相交的有界 `support_roles`、以及
`contract_fact | brochure_fact | rate_numeric` 之一的 authority class。

- `contract_fact` SHALL 只以 `terms` 为 primary；`brochure` 只能 support；
- `brochure_fact` SHALL 以 `brochure` 为 primary，但不得用于覆盖
  contract fact；
- `rate_numeric` SHALL 只以 `rate_table` 为 primary；数字不得只由
  模型或说明书转写。

#### Scenario: 说明书与条款责任不一致

- **WHEN** brochure 对 `exclusions_official` 或 `pre_existing_conditions`
  给出不同摘要
- **THEN** brochure 仍只是 support，不能成为 primary 或覆盖 terms

#### Scenario: 费率数值只出现在说明书

- **WHEN** 一个 `rate_numeric` 候选只有 brochure Evidence
- **THEN** MaterialProfile 不授予 primary authority；后续必须保持 insufficient
  或 ReviewItem

### Requirement: MPTB4 显式 product-family 映射

`product_family_id` SHALL 只由 catalog 中 `approved_product_version_mapping`
将 exact `596-1` 映射到 `pingan-eshengbao-zunxiang-medical`。request SHALL NOT
接受 caller-supplied family；resolver SHALL NOT 从 filename、model、parser metadata
或相似度推断 family。

#### Scenario: 文件名含产品族

- **WHEN** 未登记 source 的文件名包含“尊享版医疗”
- **THEN** family 仍未解析；不得构造 TemplatePackage request

### Requirement: MPTB5 复用四级 TemplatePackage resolver 与 fallback receipt

薄层 SHALL 构造 exact `ResolutionRequest(space, medical, document-type,
pingan-eshengbao-zunxiang-medical)` 并且只调用现有
`resolve_template`。不得修改 resolver、approval 或 content-hash 核心。

receipt SHALL 记录 requested 四级、resolved source chain 的 exact scope/
package/version/content hash、missing levels 与 resolved content hash。产品族层缺失时
MAY 使用同一 request 下已批准的 broader chain，但 SHALL 显式记录
`product-family` missing；不得借用其他 family、Space 或 ProductVersion。

#### Scenario: product-family template 缺失

- **WHEN** global/product-line/document-type 已批准而 exact family 不存在
- **THEN** 返回三层 source chain 与 `missing_levels=("product-family",)`

### Requirement: MPTB6 Golden identity 只作审批引用

catalog SHALL 准确记录 049 Golden identity：

- release `fca06f988bf0310d12a0f6f8d0703a9476c54a5405676fb1a9b3476f91ec21d0`；
- artifact `83032da028ef227071fddac0ed422cbb9d1c2cc31e195972f9878a67d95b44ca`；
- approval subject `6feb2acf4be1ab5ce075b662bc9c9a40024038ca2324b893d3f31b1384f7674b`。

resolver request SHALL NOT 包含 Golden path、Golden records、field values、Evidence 或
review artifact；resolution SHALL 不做任何文件 I/O。三个 hash 只证明本
profile 指向哪个已批准 Golden，不提升 source authority，不表示
S0-Q 或 production admission 完成。

#### Scenario: Golden 答案路径作为输入

- **WHEN** caller 尝试在 request 加入 `596.jsonl` 或 review artifact path
- **THEN** extra-forbid validation 拒绝，不进入 template resolution

### Requirement: MPTB7 C0 identity 与 typed ReviewItem

catalog 与每个 resolved binding SHALL 使用 C0 `canonical_hash` 的独立
object type 生成 64 位小写 hex identity。TemplatePackage `content_hash` 只作为
C0 preimage 内的领域 digest，不得成为第二批准 authority。重排 JSON key
不得改变 catalog hash；任何 authority/profile/template 身份改变必须
改变 binding hash。

product/schema/source/classification/template 冲突 SHALL 产生 typed
`MaterialProfileResolutionError` 和非空 `MaterialProfileReviewItem`；ReviewItem
SHALL 携带 reason、ProductVersion、source 与 expected/observed detail。失败不得
产生部分 binding receipt。

#### Scenario: TemplatePackage 无可用批准层

- **WHEN** 现有 resolver 返回 `unresolved_scope`
- **THEN** 薄层转换为 `template_resolution_failed` ReviewItem，保留
  `unresolved_scope` detail，不自己猜 fallback

### Requirement: MPTB8 窄切片边界

052 SHALL 保持纯 Python 领域实现，零 provider/model、零 DB/migration、零
WeKnora 写入、零 Golden 修改。`ParsedDocument`、ParseManifest、parser
adapter/quality threshold 属于 B；Claim/ChangeSet/conflict merge 属于 D/E；发布
属于 F/G。052 不得预支这些能力或建设通用平台。

#### Scenario: 为验证 profile 顺手解析 PDF

- **WHEN** 实现需要导入 parser/provider/DB/WeKnora 或 Golden answer module
- **THEN** scope gate 拒绝；本 Change 只允许领域 DTO、fixture loader、
  existing resolver seam 和 receipt

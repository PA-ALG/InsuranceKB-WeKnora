# P5a0+ ProductVersion Resolver Kernel 验收规格

## ADDED Requirements

### Requirement: PV041.1 固定优先级只产生唯一 exact ProductVersion

系统 SHALL 在已 attested `KnowledgeScope` 内解析 persisted `ProductVersion`，
优先级固定为：

1. `ProductVersion.terms_revision` 的 exact 备案/注册编号；
2. `InsuranceProduct.product_code` 或 `canonical_name` exact 命中，且该产品在
   Space 内仅有一个可用版本；
3. `ProductAlias(alias_type="manual", source="manual")` exact 命中，且只留下
   一个产品和一个版本。

高优先级命中 SHALL NOT 被低优先级候选覆盖。任意两个强身份信号指向不同产品或
版本时 SHALL typed quarantine，SHALL NOT 按顺序静默忽略冲突。
`InsuranceProduct.filing_no` 与产品级 registration alias SHALL NOT 作为
`ProductVersion.terms_revision` 的 fallback；它们不能把 product identity
升级为 version identity。

#### Scenario: 1072 的两个备案版本分别归属

- **WHEN** 1072-1 与 1072-4 各携带自己的 exact 版本备案编号
- **THEN** 两次解析分别返回对应的 persisted ProductVersion id
- **AND** 两个 result hash 不同

#### Scenario: 多强锚点冲突

- **WHEN** 同一请求中的备案编号与 exact product code/name 指向不同产品
- **THEN** 结果为 typed `anchor_conflict` quarantine
- **AND** 不返回任何 resolved ProductVersion

#### Scenario: 低优先级歧义不得覆盖唯一版本锚点

- **WHEN** exact 版本备案号唯一命中一个 ProductVersion，但较低优先级的
  canonical name 在多个产品间同名且候选集合包含该版本
- **THEN** resolver 返回备案号锁定的 ProductVersion
- **AND** 只有较低优先级候选集合不包含该版本时才 `anchor_conflict`

#### Scenario: 产品根备案号不能替代版本锚点

- **WHEN** 请求中的备案号只命中 `InsuranceProduct.filing_no`，但不命中任何
  `ProductVersion.terms_revision`
- **THEN** 结果为 typed `anchor_not_found` quarantine
- **AND** 即使该产品当前只有一个版本也不得把根字段当作版本证据

### Requirement: PV041.2 歧义、无版本与跨 Space fail closed

ProductVersion Resolver SHALL 对同名产品、同 alias 多产品、产品存在零个或
多个无法由版本锚点区分的版本、以及输入声明 Space 与 attested scope 不一致
执行 typed quarantine。跨 Space
请求 SHALL 在任何产品查询前拒绝。错误 SHALL 使用封闭 reason code，不得以
空值或 guessed identity 表达。
解析器 SHALL 只消费当前数据库事务可读的 persisted 列值；同一 ORM Session
中尚未 flush 的对象属性改写不得成为 product/version/alias authority。

#### Scenario: 同名产品不猜测

- **WHEN** 同一 Space 内两个产品具有相同 canonical name
- **THEN** exact name 请求以 `ambiguous_product` quarantine

#### Scenario: 产品信号不能选定版本

- **WHEN** exact product code 命中一个产品但该产品有两个版本且没有版本锚点
- **THEN** 请求以 `ambiguous_version` quarantine

#### Scenario: 跨 Space 在查询前拒绝

- **WHEN** 请求的 `source_space_id` 不等于当前 attested Space
- **THEN** 请求以 `cross_space` quarantine
- **AND** 不读取任何产品、版本或 alias

#### Scenario: 未落库对象改写不能铸造 identity

- **WHEN** 调用方只在 ORM identity map 中改写 version anchor 或把 auto alias
  改成 manual，但未 flush 到数据库
- **THEN** resolver 仍按 persisted 列快照裁决
- **AND** 临时对象状态不得产生 resolved ProductVersion

### Requirement: PV041.3 只有批准 alias 可作为解析层

只有 persisted `alias_type="manual"` 且 `source="manual"` 的 alias SHALL
进入 code-owned approved alias allowlist；该精确资格规则 SHALL 进入 resolver
policy hash。change 003 自动生成 alias（`source="auto"`，包括
`alias_type="registration_no"`）、fuzzy、embedding、LLM、legacy recall 或
调用方提供的 candidate ids SHALL NOT 单独产生 identity。

#### Scenario: 自动 alias 只作候选

- **WHEN** 唯一文本信号命中 `source="auto"` 的短 alias
- **THEN** 结果为 `no_authoritative_anchor` quarantine

#### Scenario: 自动 registration alias 也不获得版本权威

- **WHEN** 唯一信号命中
  `ProductAlias(alias_type="registration_no", source="auto")`
- **THEN** 结果为 typed quarantine
- **AND** 不得把该产品当前的唯一版本当成 exact version identity

#### Scenario: 人工批准 alias 唯一命中

- **WHEN** exact alias 仅命中一个 `manual/manual` alias 且产品只有一个版本
- **THEN** 返回该版本，basis 明确记录 approved alias

### Requirement: PV041.4 主数据特征只否决候选

category、channel、region 等主数据约束 SHALL 只在 exact identity 候选产生后
用于 veto。约束本身 SHALL NOT 产生候选。任一明确约束不满足时 SHALL typed
`master_data_mismatch` quarantine。

#### Scenario: 特征不能铸造身份

- **WHEN** 请求只有 category/channel/region 而没有任何 authoritative anchor
- **THEN** 结果为 `no_authoritative_anchor`，即使只有一个版本符合特征

#### Scenario: 特征否决 exact 候选

- **WHEN** exact备案命中一个版本但请求 channel 不在该版本 channels
- **THEN** 结果为 `master_data_mismatch`

### Requirement: PV041.5 结果携带完整依据与 C0 内容身份

resolved 结果 SHALL 包含 `space_id/product_id/product_version_id/product_code/
canonical_name/version_label`、resolver version、固定 policy hash、按输入顺序稳定
排序的完整 basis 与 result hash。policy/result hash SHALL 使用 C0
`canonical_hash`，不得另造 JSON/hash 规则。

相同请求与同一主数据快照 SHALL 得到逐字段相同结果；任一 identity/basis 字节
变化 SHALL 改变 result hash。

#### Scenario: 相同输入结果稳定

- **WHEN** 对同一 scope、请求与主数据解析两次
- **THEN** 两个结果逐字段相同且 result hash 相同

### Requirement: PV041.6 Fragment 只继承已解析的文档或章节身份

fragment SHALL 从一个已 resolved 的文档/章节结果纯函数继承
`ProductVersion` identity，并绑定父 result hash。继承函数 SHALL NOT 接受
Session、resolver、模型或 candidate signals，SHALL NOT 重判 identity。继承前
SHALL 重新计算父结果的 C0 hash；字段与 hash 不一致时以 typed
`resolution_hash_mismatch` quarantine 拒绝，不传播被篡改 identity。

#### Scenario: fragment 继承不重判

- **WHEN** 为多个 fragment 绑定同一 resolved section
- **THEN** 每个 fragment 携带相同 product/version identity 与 parent hash
- **AND** 不发生产品查询或模型调用

#### Scenario: 被篡改父结果不得传播

- **WHEN** 父结果的 product_version_id 被 copy/update 改写但保留旧 result hash
- **THEN** fragment 继承以 `resolution_hash_mismatch` quarantine

### Requirement: PV041.7 相似产品不得误挂 Golden Product

exact canonical name SHALL 按完整规范化字符串比较，不得做包含、前缀、相似度或
去“附加/长期/费率可调”等语义词。`平安附加e生保（尊享版）长期医疗保险
（费率可调）` SHALL NOT 解析为 Golden Product
`平安e生保（尊享版）医疗保险`。

#### Scenario: 相似名称隔离

- **WHEN** 请求携带附加长期医疗产品的完整 exact name
- **THEN** 只可命中其自身 product/version，或在其版本不存在时 quarantine
- **AND** 不得返回 Golden Product 596 的版本

### Requirement: PV041.8 新版本登记只写一次版本级锚点

`ProductRegistryService` 在创建新的 `ProductVersion` 时 SHALL 从同一版本目录
已验证的 `ProductMeta` 写入 `terms_revision`：优先备案号，仅在备案号缺失时
使用注册号。已有 `ProductVersion` SHALL NOT 因后续同 label 输入而原地改写
`terms_revision`；缺少锚点的历史版本继续 fail closed，本 PR 不做回填。

#### Scenario: 重放登记不改写已有版本锚点

- **WHEN** 同一 `version_label` 已登记，后续输入携带不同备案/注册号
- **THEN** 既有 `ProductVersion.terms_revision` 保持逐字节不变
- **AND** 不创建第二个同 label 版本

# 038 G0a 金标资产化内核 验收规格

## ADDED Requirements

### Requirement: G038.1 Provenance 分级 fail-closed 且内容自算

系统 SHALL 为每条金标记录派生一个 `GoldenProvenanceClass`，取值封闭为
`attributed | legacy_unattributed`。分级 SHALL 由 receipt 字段的**内容**自算：
仅当 `annotator_model` 非空白、`created_at` 存在、且 `schema_version` 非空白
时为 `attributed`，否则为 `legacy_unattributed`。分级函数 SHALL NOT 接受调用方
传入的分级值、布尔开关或"信任"标记——非法状态在构造期即不可表达。

`legacy_unattributed` 记录 SHALL 被永久排除在验收用途之外：任何声称构造
baseline/approval 输入的 API 收到含 `legacy_unattributed` 的记录集时 SHALL 以
typed error 拒绝，SHALL NOT 降级、过滤后继续或只发警告。种子用途（探针、
调试、覆盖率统计）SHALL 允许，但返回值必须显式携带分级统计。

#### Scenario: 缺 receipt 即 legacy，不可自报升级

- **WHEN** 一条记录的 `annotator_model` 为空白或缺失
- **THEN** 其分级为 `legacy_unattributed`
- **AND** 调用方额外传入任何"已批准/可信"意图的参数都不改变该分级（此类参数不存在）

#### Scenario: 验收输入含 legacy 即拒绝

- **WHEN** 以含至少一条 `legacy_unattributed` 的记录集调用 baseline 构造入口
- **THEN** 调用以 typed error 拒绝并报告该类记录的计数
- **AND** 不产生任何部分 artifact

#### Scenario: 种子用途允许但必须暴露分级

- **WHEN** 以同一记录集调用种子用途入口
- **THEN** 调用成功且返回值含 `attributed`/`legacy_unattributed` 各自计数

### Requirement: G038.2 Lift 装载器只从权威来源补字段

系统 SHALL 提供把 `wip-gs-v0.1` 形态（七字段 JSONL）提升为 `GoldenRecord` 的
装载器。缺失字段 SHALL 且仅 SHALL 从以下权威来源取值：`product_id` ←
产品目录 `product_meta.json` 的 `planCode`；`product_name` ← 同文件的
`clauseName`；`schema_version` ← `manifest.json` 的 `schema_version`。

装载器 SHALL NOT 为 `annotator_model` 或 `created_at` 合成任何值——不得使用
文件 mtime、当前时间、占位字符串或从其他记录推断。二者不可考时记录进入
`legacy_unattributed`，其 receipt 字段保持显式"未知"表达而非伪造值。

权威来源缺失或与记录冲突（如 `product_meta.json` 不存在、`planCode` 为空、
manifest 未登记该产品）SHALL 以 typed error 拒绝该产品，SHALL NOT 静默跳过或
用目录名代替。

#### Scenario: 权威字段正确回填

- **WHEN** 装载一个 `product_meta.json` 含 `planCode`/`clauseName` 且 manifest 已登记的产品
- **THEN** 每条记录的 `product_id`/`product_name`/`schema_version` 等于对应权威值

#### Scenario: 禁止伪造 receipt

- **WHEN** 装载不含 annotator 信息的历史记录
- **THEN** `annotator_model`/`created_at` 不被赋予 mtime、当前时间或占位串
- **AND** 该记录分级为 `legacy_unattributed`

#### Scenario: 权威来源缺失 fail closed

- **WHEN** 某产品缺 `product_meta.json` 或其 `planCode` 为空
- **THEN** 装载该产品以 typed error 拒绝，且错误标识该产品与缺失来源
- **AND** 不以目录名或任何推断值代替

### Requirement: G038.3 引文回验绑定页号且规范化确定

引文回验 SHALL 判定：把 quote 与目标页文本施加同一规范化（Unicode NFKC、
去除全部空白、统一全角标点到半角）后，quote 是否为该页文本的子串。判定结果
SHALL 为封闭枚举 `hit_on_page | hit_wrong_page | not_found | empty_quote |
document_missing` 之一，SHALL NOT 以布尔或 None 表达。

`hit_wrong_page`（内容在文档其他页命中）与 `not_found` SHALL 分开计数，二者
均不得计入通过。规范化 SHALL 是纯函数且对同一输入确定。

#### Scenario: 页内精确命中

- **WHEN** quote 规范化后是其声明页文本的子串
- **THEN** 结果为 `hit_on_page`

#### Scenario: 页号错与找不到分开

- **WHEN** quote 在文档其他页命中但不在声明页
- **THEN** 结果为 `hit_wrong_page`，且不计入通过计数
- **WHEN** quote 在文档任何页均不命中
- **THEN** 结果为 `not_found`

### Requirement: G038.4 短引文唯一性护栏与接受侧全集扫描

quote 在其声明页内 SHALL 唯一命中。同一页内出现 ≥2 次时判定为
`ambiguous_locator` 并计入失败，因为页级 locator 无法唯一定位该证据。

该护栏 SHALL 与接受侧防线成对交付：对 `wip-gs-v0.1` 全库执行全集扫描，
**当前 722 条 `hit_on_page` 的 evidence 在引入本护栏与任何规范化收窄后
SHALL 仍然全部判定为通过**（`ambiguous_locator` 除外，其被判失败必须逐条
可解释）。净通过数下降而无逐条解释 SHALL 视为回归并阻断本 change。

#### Scenario: 同页多处命中判失败

- **WHEN** 一条 quote 规范化后在其声明页内出现两次
- **THEN** 结果为 `ambiguous_locator` 且不计入通过

#### Scenario: 接受侧全集扫描无净回归

- **WHEN** 对 `wip-gs-v0.1` 全库运行验证内核
- **THEN** 每条既有 `hit_on_page` evidence 或仍判 `hit_on_page`，或被判
  `ambiguous_locator` 且报告逐条列出其页内命中次数
- **AND** 不存在既未通过也未被逐条解释的 evidence

### Requirement: G038.5 三态结构不变量与全字段闭合覆盖

系统 SHALL 校验三态结构不变量：`present` 记录必须有 ≥1 条 evidence；
`absent_explicitly` 记录必须有 ≥1 条 evidence；`unknown` 记录必须无 value
且无 evidence。违反 SHALL 产生 typed finding，SHALL NOT 静默通过。

系统 SHALL 校验全字段闭合覆盖：某产品 golden 的 `field_id` 集合必须覆盖其
`fields.json` 声明的全集。缺失字段 SHALL 逐个列出为 typed finding——选择性
标注是 033 §14.1 明令禁止的刷分方式，不得因"未标注即不计入"而消失。

#### Scenario: 结构违规被检出

- **WHEN** 存在 `present` 但 evidence 为空，或 `unknown` 但 value 非空的记录
- **THEN** 各自产生对应 typed finding 并计入失败

#### Scenario: 选择性标注被检出

- **WHEN** 某产品 `fields.json` 声明 60 个字段而 golden 只覆盖 58 个
- **THEN** 报告逐个列出缺失的 2 个 `field_id`，且该产品覆盖率按 58/60 呈现
- **AND** 缺失字段不从分母消失

### Requirement: G038.6 源文档 SHA-256 绑定

验证内核 SHALL 在读取每个源文档时计算其字节 SHA-256，并把
`(产品, 文档名, sha256, 页数)` 写入体检报告。报告 SHALL 以该 digest 而非文件
路径或文件名标识源文档——路径与文件名是可变标签，digest 是内容身份。

对同一产品重复运行 SHALL 得到相同 digest；源文档字节变化 SHALL 使报告
digest 变化，从而使任何基于旧报告的结论失效。

#### Scenario: digest 绑定内容而非路径

- **WHEN** 同一份 PDF 以不同文件名读取
- **THEN** 其记录的 sha256 相同

#### Scenario: 源文档变化使报告失效

- **WHEN** 源文档字节改变后重新运行
- **THEN** 该文档的 sha256 与报告整体 digest 均改变

### Requirement: G038.7 内容寻址体检报告且分母不丢失

体检报告 SHALL 以 C0 的 `canonical_hash` 计算内容寻址 digest，SHALL NOT 另立
第三套哈希规则（`goldenset` 既有 019 哈希与 `template_packages` 自有 domain
separator 的对账不属本 change，但新报告一律走 C0）。

报告 SHALL 对每个指标同时输出 numerator 与 denominator，并逐类列出 typed
findings。任何失败、未覆盖或不可判定项 SHALL NOT 从分母中消失；零观测
SHALL NOT 呈现为满分，而是显式 `INSUFFICIENT_DATA`。

#### Scenario: 同内容同 digest

- **WHEN** 对同一输入两次生成报告
- **THEN** 两份报告的 canonical digest 相同

#### Scenario: 零观测不给满分

- **WHEN** 某维度（如 `absent_explicitly` 准确性）在数据中观测数为 0
- **THEN** 该维度呈现为 `INSUFFICIENT_DATA` 并附 denominator=0
- **AND** 不呈现为 1.0 或 100%

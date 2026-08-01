# Enterprise Knowledge Compiler Architecture Specification

## ADDED Requirements

### Requirement: KCA1 唯一身份链与外层 hash authority

每次知识编译 SHALL 从 exact Space、Product、ProductVersion、Source、
SourceRevision 与 material identity 开始。产品特定知识 SHALL 绑定已批准的
ProductVersion；无法精确归属的材料或片段 SHALL 进入 ReviewItem，不得猜测。

C0 CanonicalEnvelope/artifact hash SHALL 是跨阶段 custody、批准和重放使用的
唯一外层 identity authority。TemplatePackage content hash、ParseManifest digest、
Evidence digest、ExtractionTask input digest 等 SHALL 作为 envelope 内的领域内容
摘要；它们 SHALL NOT 单独授予批准、发布或 serving authority。

#### Scenario: 领域 digest 不能冒充外层批准

- **WHEN** TemplatePackage content hash 与已批准版本相同，但 C0 envelope 中的
  SourceRevision、ProductVersion、Space 或 parser identity 漂移
- **THEN** 旧批准不适用，系统在任何模型调用、ChangeSet 或发布写入前 fail closed

#### Scenario: 产品归属不明确

- **WHEN** 一个 section 同时指向两个 ProductVersion 且确定性 resolver 无法唯一
  归属
- **THEN** 对应任务不生成产品事实，产生 typed attribution ReviewItem，零正式
  Claim/ChangeSet/Release 写入

### Requirement: KCA2 材料分类与字段级 source authority 分离

系统 SHALL 将材料分类结果与来源权威分开。分类器 MAY 建议材料类型、产品候选和
模块路由，但 SHALL NOT 授予或提升 authority。authority SHALL 来自 Space 内已
批准、版本化的 source registration / ingest trust policy，并按字段、材料角色、
产品版本、适用时间和范围求值。

MaterialProfile SHALL 至少表达以下责任边界：

| material role | 主要责任 | 禁止事项 |
|---|---|---|
| terms / 条款 | 保障责任、定义、除外、等待期、给付条件、法定/合同事实 | 不由低权材料覆盖 |
| brochure / 说明书 | 产品概要、投保示例、摘要与导读 | 不改写条款级责任或除外 |
| rate_table / 费率表 | exact 费率维度、单元格数值、表头与适用组合 | 数字不得只由模型转写 |
| faq / approved guidance | 经批准的解释、办理口径、常见问题 | 不创造合同责任 |
| benefits_services | 服务/权益资格、范围、供应与使用条件 | 不冒充保险保障责任 |
| ppt_marketing | 发现、定位和候选知识 | 默认不能单独形成高风险正式事实 |
| structured_json | 经结构映射的字段直入 | 不得绕过 SourceRevision/Evidence/schema 校验 |
| scanned_document | 记录输入形态与 OCR 需求，继承其逻辑材料角色 | 扫描/OCR 质量不得提升 authority |

混合材料 SHALL 在 block/section 级保留 material role 与产品候选。无法证明角色的
区域 SHALL 采用最低允许 authority 或进入 ReviewItem，不得按文件名静默提升。

#### Scenario: 宣传材料被识别为条款

- **WHEN** 分类模型把宣传 PPT 误标为 terms，但 source registration 只允许
  `ppt_marketing`
- **THEN** authority 不提升；高风险合同字段不得由该材料自动进入 Candidate

#### Scenario: 结构化知识快速补全

- **WHEN** approved structured JSON 带 exact SourceRevision、record snapshot
  hash、JSON pointer、schema mapping 与 field authority
- **THEN** 它可跳过文档解析，但仍进入相同 Evidence、ChangeSet、Review 与
  Release 合同，不得直接修改 Wiki Active

### Requirement: KCA3 四级 TemplatePackage 的精确解析与退层

生产 SHALL 复用现有四级 TemplatePackage resolver：
`generic-insurance → line-of-business → document-type → product-family`。后一层
只能收紧或专门化前层，不得降低 Evidence、隐私、风险、预算或人工门禁。

exact `product_family_id` SHALL 只来自已批准 ProductVersion resolution 或
MaterialProfile 显式映射；模型、文件名、相似度或 parser metadata 不得推断。
层缺失时只允许沿 resolver 的显式、已批准 broader chain 退层，并在
ResolvedTemplateReceipt 中记录 exact chain、missing layer、各层 identity 与
最终 C0 envelope hash。不得跨 Space、ProductVersion 或未批准 template version
猜测 fallback。

TemplatePackage `content_hash` SHALL 继续作为 domain content digest，不得成为
第二个批准 authority；TemplateApproval 与运行输入 SHALL 最终绑定 C0 envelope。

#### Scenario: 产品族层缺失

- **WHEN** approved MaterialProfile 没有 product-family template，但已有批准的
  generic/line-of-business/document-type chain
- **THEN** resolver 可显式退到该 broader chain，并记录 missing product-family；
  不把其他产品族模板借用过来

#### Scenario: 文件名推断产品族

- **WHEN** 文件名包含某产品族名称但 ProductVersion/MaterialProfile 没有批准映射
- **THEN** product-family 层保持未解析并产生 typed blocker 或 approved broader
  fallback；不得从文件名生成 family identity

### Requirement: KCA4 显式且有界的解析质量路径

每个 MaterialProfile SHALL 精确绑定一个版本化、approved default parser，并 MAY
精确绑定至多一个 approved bounded upgrade。default attempt 不足时，只有该
MaterialProfile 已冻结 upgrade identity 与触发条件才可执行第二次 parser attempt；
第二次仍不足 SHALL fail closed 并生成 ReviewItem。系统 SHALL 禁止第三次 parser
attempt，也 SHALL 禁止预授权 structure-aware parser→OCR→VLM 等多级顺序链或
常态并跑多个 parser 投票。

native/pdfplumber、MinerU、Paddle、Unlimited-OCR、VLM 或其他实现只作为 G 中
可替换评测的 candidate families；051 不把名称或类别顺序写成生产 ladder。每次
bounded upgrade SHALL 创建新的 parse attempt 并保留 default attempt 的 immutable
receipt；下游只消费一个 exact admitted attempt。winner 只能由 G 的三 PDF 结构门
与 60 字段 Golden 证伪后，经具名批准的 MaterialProfile/TemplatePackage 版本选择。

#### Scenario: simple fast path 通过

- **WHEN** approved default parser 产物满足该 MaterialProfile 已批准的结构能力与
  质量门
- **THEN** 系统消费该 exact attempt，不调用 bounded upgrade

#### Scenario: fast path 不足

- **WHEN** default attempt 缺失 required table grid、cell locator 或跨页结构
- **THEN** 仅在 exact bounded upgrade 已批准时执行第二次 parser attempt；否则
  立即 fail closed。第二次仍不足时生成 ReviewItem，不执行第三次 attempt，也不把
  两个 parser 结果混合成一个未声明 manifest

### Requirement: KCA5 parser-neutral ParsedDocument、ParseManifest 与质量事实

系统 SHALL 在既有 SourceRevision、W1 manifest 与 FrozenW1Bundle 上补充最小的
parser-neutral contract；不得重写 W1，也不得建立巨型 vendor union。

`ParsedDocumentV1` / `ParseManifestV1` 的 architecture-required facts SHALL 至少
包含：

- Space/Source/SourceRevision/ProductVersion/MaterialProfile identity；
- source bytes SHA-256、exact parse attempt/generation；
- parser engine/profile/build/config identity；
- ordered page/block/table/cell identities、counts 与 complete manifest digest；
- page/block/table/cell locator、content/structure digest；
- table row/column/grid/header/span/cross-page facts，在 profile 要求时必须完整；
- snapshot-bound pagination/completeness 与 concurrent reparse/delete fence；
- privacy/output-policy facts，以及可复算的 C0 envelope identity。

`ParseQualityDecisionV1` SHALL 记录 measured facts、required capabilities、决策
`ADMIT | ESCALATE | BLOCK` 与 typed reason codes。051 只冻结以下 reason-code
families，不冻结未经样本验证的数值阈值：

- `identity_revision_parser_drift`；
- `manifest_digest_or_count_mismatch`；
- `locator_invalid_or_required_structure_missing`；
- `table_grid_or_span_incomplete`；
- `unsupported_material_or_parser_profile`；
- `privacy_or_output_policy_violation`。

exact thresholds SHALL 由 B 使用 `596-1` deterministic fixtures 校准并版本化；
不得由调用者 flag 或单次模型输出决定。

#### Scenario: attempt 混版

- **WHEN** page 记录来自 attempt N，table/cell manifest 来自 attempt N+1
- **THEN** manifest/custody 校验失败，模型、ExtractionTask 与发布写入均为零

#### Scenario: 质量数值尚未校准

- **WHEN** B 尚未用冻结 fixtures 批准 exact threshold version
- **THEN** ParseQualityDecision 对依赖该阈值的 profile fail closed；051 文档中的
  reason family 不得被解释为默认数值

### Requirement: KCA6 材料×模块×字段风险任务拆解

系统 SHALL 把编译拆为 material role × knowledge module × field-risk group 的
`ExtractionTask`，而不是把整份 PDF 或整产品 60 字段交给一次模型调用。

每个 task SHALL 冻结：Space、ProductVersion、SourceRevision、admitted parse
attempt/manifest、MaterialProfile、resolved TemplatePackage chain、Schema version、
module、exact field set、risk class、locator candidate manifest、预算和 C0 envelope
hash。Attempt/Receipt SHALL 记录 exact model/model-plan、prompt/template、输入与
输出 digest、typed outcome、token/time/cost facts和 causation，不允许成功覆盖旧
attempt。

固定角色 SHALL 为：

1. **Locator**：确定性地选择 page/block/table/cell 候选与结构化直取位置；
2. **Extractor**：弱模型只在窄上下文、少字段内生成带 Evidence 的候选；
3. **Deterministic Verifier**：校验 schema/type/comparator/locator/quote/table cell/
   跨字段业务规则，不调用模型裁决确定性事实；
4. **Targeted Repairer**：只重定位、重切分或补抽失败字段，受 exact attempt、预算
   和次数限制。

角色是 stage contract，不是通用多 Agent 平台；Host 负责 durable state、budget、
retry、receipt 与 process-control 语义，插件不得自建事实或发布权威。

#### Scenario: 整产品一次生成

- **WHEN** 一个 task 同时接收整份三 PDF 并要求一次生成全部 60 字段
- **THEN** task admission 拒绝；必须按材料、模块和风险拆解

#### Scenario: repair 越界

- **WHEN** Targeted Repairer 为一个失败字段改写已通过字段或使用未冻结 locator
- **THEN** output digest/capability 校验拒绝，原已验证结果保持不变并生成 typed
  ReviewItem

### Requirement: KCA7 Evidence 与业务规则双重回验

任何字段候选 SHALL 同时通过 Evidence 回验与 Schema/业务规则回验，才能进入
ChangeSet 比较。文档 Evidence SHALL 绑定 SourceRevision、parse attempt、
page/block/table/cell locator、quote/value snapshot 与 digest；结构化 Evidence
SHALL 绑定 record snapshot hash、JSON pointer 与 value snapshot。

确定性可直取的表格数值、单位、枚举与关系 SHALL 由代码从 admitted structure
读取，模型只做定位或语义候选。quote 存在只证明逐字回指，不等于语义支持；高风险
字段的语义支持不足 SHALL 进入人工审核或 approved independent weak-model check，
不得以引用命中率代替。

类型、单位、枚举、比较器、适用条件、时间、算术关系及跨字段依赖 SHALL 由版本化
Schema/Template verifier 校验。失败后只允许 bounded targeted repair；预算耗尽、
无共识或 unsupported SHALL 保持 `unknown`/typed insufficient，并生成 Gap/
ReviewItem，不能静默填值。

#### Scenario: quote 存在但不支持字段

- **WHEN** quote 在原页存在，但主语、产品版本或适用条件与候选字段不一致
- **THEN** 逐字门可通过但语义支持门失败，候选不得进入自动 ChangeSet

#### Scenario: 费率数字可确定性直取

- **WHEN** admitted table manifest 提供 exact row/column/header/cell locator 与数值
- **THEN** 数值从 cell snapshot 确定性读取，Extractor 不重新抄写原始数字

### Requirement: KCA8 增量 ChangeSet、冲突与独占来源撤回

新 SourceRevision SHALL 只重编译受其材料、模块、字段和产品版本影响的任务。
已验证未受影响字段 SHALL 保持稳定，不得每批材料全量覆盖。

候选事实 SHALL 经统一 ChangeSet 形成 `add | enrich | supersede | conflict |
retract`。比较 SHALL 先限定相同 Space、subject、ProductVersion、业务时间、地区、
渠道、人群和条件，再按字段级 source authority、reliable time、Evidence 完整性和
批准 comparator 决定；模型意见不得成为 authority。

值一致时 MAY enrich Evidence；值不一致不得把新 Evidence 挂到旧值。无法确定性
裁决时 SHALL 生成 ConflictSet/ReviewItem。`unknown` 不等于
`absent_explicitly`。

对 source-exclusive 字段，只有完整的新权威 SourceRevision 明确覆盖相同 scope，
且证明旧 Claim 的唯一支持来自被替代/撤回 revision 时，才可生成 retract 候选；
仍须进入 ChangeSet/Review/Release。Source disable/delete、法律删除和业务撤回
SHALL 保持各自 typed 语义，不得静默物理删除正式知识。

#### Scenario: 新条款补说明书缺口

- **WHEN** 新条款 revision 为既存 `unknown` 字段提供 verified Evidence
- **THEN** 只生成该字段的 enrich/add ChangeItem，其他已验证字段不重写

#### Scenario: 独占来源内容消失

- **WHEN** 完整新费率表在相同 scope 中不再包含旧费率单元，且旧值只由前一费率表
  支持
- **THEN** 生成带原因和 Evidence custody 的 retract 候选；不直接删除 Claim 或
  Wiki 页面

### Requirement: KCA9 六阶段状态机与失败零发布

编译 SHALL 使用以下六阶段，阶段间只传递 immutable/content-addressed artifact：

1. `SOURCE_FROZEN`：身份、bytes、revision 与 ACL 冻结；
2. `PROFILE_RESOLVED`：材料角色、ProductVersion、MaterialProfile、template chain；
3. `PARSE_ADMITTED`：一个 exact ParsedDocument/ParseManifest 通过质量门；
4. `KNOWLEDGE_VERIFIED`：tasks/attempts/Evidence/schema/verifier 闭合；
5. `CHANGESET_READY`：增量、冲突、Gap、retract 与 ReviewItem 冻结；
6. `RELEASED`：Candidate exact 批审、WeKnora 原子激活并可 pinned read/revert。

每个阶段 SHALL 有 typed success/insufficient/blocked/rejected/failed outcome。identity
drift、OSError/DB error、预算耗尽、parser/model失败、process-control exception、
审核拒绝或发布 CAS loser SHALL 保留原先已发布 Release，零部分 publish。

恢复 SHALL 从 durable receipt/custody 重新读取和验证所有前置，而不是信任内存
report。已成功 artifact MAY 幂等复用，但任何输入/策略/approval/identity 漂移
SHALL 创建新 attempt/job，不覆写历史。KeyboardInterrupt/SystemExit/MemoryError
不得被包装成业务成功。

#### Scenario: 第四阶段崩溃恢复

- **WHEN** 部分 ExtractionTask 已有成功 receipt，进程在剩余 task 前退出
- **THEN** 重启只复用 exact-input 成功 artifact，重跑未完成任务；任何 drift 时
  整个受影响 task 重新建立 identity，旧 Release 不变

#### Scenario: 发布失败

- **WHEN** Candidate 已批准但 WeKnora activation CAS 失败
- **THEN** Harness receipt 不形成第二 Active Head，正式读取继续 pin 旧 Release

### Requirement: KCA10 Candidate、人工门、Wiki Release 与 revert

系统 SHALL 从 accepted ChangeSet 确定性编译原子 Wiki 页面、Claim/Relation/
Evidence membership 与 changelog；模型不得直接生成或改写正式页面。

CandidateRelease SHALL 冻结完整 membership、base release/epoch、Schema、template、
parser/model plan、SourceRevision 与 C0 envelope identity。MVP 默认 `human_batch`：
具名授权人对 exact Candidate 一次批准/拒绝，不逐页批准；任一成员变化使旧
Decision 失效。

WeKnora SHALL 是唯一 serving Active Release authority。成功 activation 后，人、
API、Agent/MCP SHALL 在一个请求内 pin 同一 release；raw chunk 只用于 Evidence
核查和补编，不得作为无已发布答案时的静默 fallback。revert SHALL 原子切换到既有
immutable Release；内容撤回 SHALL 生成新 Candidate/Release，不把 revert 实现为
重新生成或单页 cherry-pick。

#### Scenario: 模型直接写 Wiki

- **WHEN** Extractor 或 Repairer 尝试跳过 ChangeSet/Candidate/Review 写 active Wiki
- **THEN** authority gate 拒绝，Active Release 不变

#### Scenario: revert

- **WHEN** 授权人选择历史 immutable Release 并满足 expected-current CAS
- **THEN** Active Head 原子指向该 Release，epoch 单调递增，pinned request 不混版

### Requirement: KCA11 子 Mission DAG 与准入

执行顺序 SHALL 为：

```text
A(051 architecture)
  ↓
C(material profile + template catalog; fixture-only)
  ↓
B(parsed artifact + parse quality)
  ├─ D(extraction + verification)
  └─ E(incremental fusion + conflict/retraction)
          └──────────────┬──────────────┘
                         F(fixture vertical release/revert)
                         ↓
                         G(596-1 falsification + human gate)
```

- **A exit**：051 exact tree 经 Spec 与 Delivery/YAGNI 独立批准并合入；
- **C entry/exit**：A 已批准；复用现有 resolver/hash/approval，交付
  MaterialProfile exact scope 接缝和 `596-1` fixture catalog；product-family 显式
  映射/fallback receipt 全绿。C 可用 deterministic fixtures，但不得宣称真实
  `596-1` production admission，后者等待 B 闭合三份 exact PDF；
- **B entry/exit**：C 已批准；复用 W1/FrozenW1Bundle 与 C 冻结的 exact
  MaterialProfile required capabilities，用 fixtures 交付三份材料都可表达的
  parser-neutral contracts、reason families 和校准后的 threshold version；不选
  vendor，不把 fixture 写成 production admission；
- **D entry/exit**：B 已批准；固定 task/role/attempt/receipt/budget，以录制 fixture
  证明窄任务、Evidence、bounded repair 与零静默丢失；
- **E entry/exit**：B 已批准；以 deterministic claims/fixtures 证明 add/enrich/
  supersede/conflict/retract、field authority 和 affected-only recompilation；
- **F entry/exit**：D+E 已批准；只用冻结 fixture 证明 Candidate→human_batch→
  WeKnora versioned Release→pinned read→revert，provider/model 调用为零；
- **G entry/exit**：F 已批准且三 PDF exact admitted inputs、049 Golden、模型/parser/
  prompt/template/budget/EvaluationProtocol 与人工流程已冻结；输出在读取 Golden 前
  content-addressed freeze，随后才评分和人工批准。未达门输出 typed NOT FEASIBLE，
  不以继续调参无限延期。

每个子 Mission SHALL 单独占号、OpenSpec/Mission Card、TDD、路径/调用预算与独立
审查；父级不预占 migration 或持久 registry。任一子 Mission 需要第二领域不变量、
通用平台或超出批准预算 SHALL 停止重划，不得扩大 051。

#### Scenario: G 提前看 Golden

- **WHEN** parser/model raw output hash 冻结前读取 049 Golden 或旧答案来调整 prompt
- **THEN** 整次 G attempt 作废，不能形成指标、批准或 parser winner

### Requirement: KCA12 `596-1` 三 PDF/60 字段证伪门

G SHALL 只使用 ProductVersion `596-1` 的 exact 条款、产品说明书和费率表三份
PDF，以及 049 批准的 60-field Golden。每份 PDF SHALL 独立拥有 exact source
bytes hash、SourceRevision、completed W1 attempt、admitted ParsedDocument 与
ParseManifest。047 当前两 PDF 的 read-only evidence capture SHALL NOT 被解释为
三 PDF 门已满足。

G SHALL 冻结 parser chain/material profile、TemplatePackage stack、Schema、字段
批次、weak-model plan、prompt、normalizer/comparator、Evidence verifier、预算与
EvaluationProtocol。至少报告 60 字段 tri-state/value、coverage/abstention、
Evidence locator/quote/structure、关键高风险字段、漏项/幻觉/静默错误、调用与
延迟；exact 数值门来自 G 开工前批准的质量协议，不由 051 发明。

offline parser 候选 MAY 在同一 exact inputs 上比较，但生产 winner SHALL 是一个
具名批准、版本化 MaterialProfile 中的单链。`pdfplumber → weak model` baseline
可以作为对照，不能因成本低或部分字段正确自动成为生产主链。

只有结构门、Golden 门、Evidence/业务规则门和具名人工门全部通过，才可使用 F 的
能力形成 `596-1` versioned Wiki Release，并演示 Wiki 可见、pinned read 与 revert。
任一门失败 SHALL 输出 typed NOT FEASIBLE/BLOCKED，Active Release 不变。

#### Scenario: 只有两份 PDF

- **WHEN** 条款和说明书 admitted，但费率表没有 exact admitted ParsedDocument/
  ParseManifest
- **THEN** G 不得开始模型抽取或宣称 `596-1` production admission complete

#### Scenario: baseline 表现尚可

- **WHEN** simple baseline 的总体 coverage 尚可，但关键字段 Evidence、表格结构或
  静默错误未达到预先冻结门
- **THEN** baseline 不获生产资格；结果只作为诊断，不触发额外无界重试

### Requirement: KCA13 主航道与 YAGNI 边界

051 及其子 Mission SHALL 交付一个寿险知识编译纵切，不建设通用 parser/OCR/table/
Agent 平台。B–F 不得调用 provider/model；G 是唯一模型/parser 实验窗口。强模型
只可离线构造/复核 Golden，不得成为生产 fallback、judge 或 Release 前置。

实现 SHALL 复用现有 W1、C0、TemplatePackage、Job/Worker、Golden、Candidate/
Review/Release authority；不得平行建立共享数据库、Redis/Asynq、Node/TS runtime、
第二 Active Head或新的通用 schema registry。Dashboard、自动 prompt、全产品、
动态路由、几十万材料调度和 vendor 平台化 SHALL 后置。

#### Scenario: parser 候选触发通用平台

- **WHEN** 子 Mission 为接入 MinerU/Unlimited-OCR 提议通用 parser marketplace、
  第二任务运行时或动态投票路由
- **THEN** scope gate 拒绝；只允许当前 MaterialProfile 的最薄 adapter/contract，
  且须经独立子 OpenSpec

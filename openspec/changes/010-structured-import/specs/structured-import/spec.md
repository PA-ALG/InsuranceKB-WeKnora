# 010 结构化直入验收规格

> 二版（2026-07-16）：正式 delta 格式。条款号沿用 I 系（I1~I8），与一版映射：旧 I1→I2、旧 I2→I5、旧 I3→I6、旧 I4→I7、旧 I5→I8、旧 I6→I4/I6；新增 I1（双通道）与 I3（来源登记）。

## ADDED Requirements

### Requirement: I1 双通道边界——元数据不得成为 Claim 证据（Q020）

导入 SHALL 区分两条通道：通道一（产品主数据 bootstrap）把 `product_meta.json` 类元数据写入 003 产品注册（产品/版本/备案文号/销售状态/渠道），SHALL NOT 产生任何 Claim 或 ClaimEvidence；通道二（可信结构化业务源）只接受经 I3 登记的来源，其记录才可经 007 合并产生 Claim。任何把未登记元数据文件包装为 Claim 证据的路径 SHALL 不存在；Q020 的修订只能在 06 §4 显式进行，SHALL NOT 被本通道静默绕过。

#### Scenario: meta 文件走 bootstrap 通道零 Claim

- **WHEN** 对 13 份 `product_meta.json` 执行通道一导入（`--apply`）
- **THEN** 003 产品注册表按 planCode/versionNo/备案文号/销售状态完成登记且幂等（重跑零新增）
- **AND** claims 与 claim_evidence 表零新增（显式断言）

#### Scenario: 未登记来源不得进入 Claim 通道

- **WHEN** 以未在来源登记表（I3）中的 source_system 调用通道二导入
- **THEN** 导入在任何落库前 fail-closed 拒绝，错误指明"来源未登记"

### Requirement: I2 映射与规范化

字段映射规则 SHALL 为 YAML（source_field → field_id + 变换器名），加载 fail-fast（未知 field_id / 未知变换器 / 重复映射即报错并定位）；值规范化 SHALL 复用 goldenset/normalize 与 compiler/cleaning 的既有语义（日期多格式→ISO、金额中文单位→数值、枚举同义映射），规范化失败的记录 SHALL 进 staging 报告而非静默丢弃；对未知 JSON 结构 SHALL 仅生成候选映射草案（字段名相似度+值类型推断，落 `mapping-drafts/` 待人工确认），未确认草案 SHALL NOT 用于正式导入。

#### Scenario: 映射规则错误 fail-fast

- **WHEN** 映射 YAML 含未知 field_id 或重复映射
- **THEN** 加载即报错并定位到具体条目，不进入导入流程

#### Scenario: 未确认草案不得导入

- **WHEN** 对未知结构生成候选映射草案且未经人工确认
- **THEN** 用该草案执行导入被拒绝

### Requirement: I3 可信业务源登记与权威等级

通道二的每个来源 SHALL 在来源登记配置（source registry，YAML/表均可但须单一权威来源）中声明：source_system 标识、权威等级（对齐 03 §6.1 数值序）、数据责任人、记录 schema/映射引用；导入产生的 Claim 候选 SHALL 携带该登记权威等级（data_quality=structured_direct），由 007 权威序统一裁决，SHALL NOT 在导入侧特判覆盖。

#### Scenario: 登记来源的权威等级进入合并裁决

- **WHEN** 已登记来源（权威=系统数据级）的记录与已发布的低权威 Claim 值冲突
- **THEN** 007 按权威序产生 supersede/conflict 并留痕，导入侧无任何绕过裁决的写路径

### Requirement: I4 结构化证据数据模型与全消费链闭合（迁移 0007；knowledge 域改动须 Owner-A 复审）

**正交来源轴**：证据 SHALL 新增 `source_kind ∈ {legacy, weknora, structured}`，与表示链接质量的 `lineage_status` 正交——`lineage_status` 值域**不变**（linked/page_only/ambiguous），且仅对 source_kind=weknora 有意义；SHALL NOT 把来源种类塞进 lineage_status。

迁移 0007 SHALL：新建 `structured_source_records` 表（space_id、source_system、external_record_id、source_revision、record_locator、record_hash、raw_payload、authority_level、batch_id、imported_at；唯一键=space_id+source_system+external_record_id+source_revision），该表 **insert-only**——服务层无更新路径且数据库边界拒绝 UPDATE（对齐 018 不可变触发器风格，SQLite/PostgreSQL 双方言）；`claim_evidence` 新增 `source_kind`（回填既有行：lineage_status 非空→weknora、空→legacy）、可空 `structured_record_id`（FK）与可空 `mapping_version`；CHECK 约束按 kind 分支——weknora ⇒ 017 审计组齐全（既有语义不变）；structured ⇒ structured_record_id 与 mapping_version 非空 ∧ WeKnora 审计组/chunk 字段/page 全空；legacy ⇒ 全空；downgrade 干净可逆。

**record_hash 语义（比较对象定死，防恒真）**：record_hash = canonical raw record（键排序、UTF-8、无多余空白的 JSON 序列化）的 SHA-256；任何"一致性"校验 SHALL 以 raw_payload **重算** canonical hash 与落库值比对（探测绕库改写），SHALL NOT 把表中 record_hash 与其自身比较。**mapping_version 语义**：映射规则内容哈希（YAML canonical SHA-256），单一权威来源；导入批次与证据（及其冻结副本）SHALL 携带——来源内容版本（record_hash）与转换版本（mapping_version）是两条独立轴。

**`knowledge_id` 语义**：SHALL 保持非空，定义为"来源容器标识"——weknora=WeKnora knowledge id（既有）；structured=**source_system 标识**（供页面展示回退名与按来源分组），SHALL NOT 用空串/sentinel。

**全消费链 SHALL 在同一实现 PR 内闭合**（不是只改表；以下均属 knowledge 域、Owner-A 复审）：
- `ProposedEvidence`：新增 source_kind、structured_record_id 与 mapping_version，校验按 kind 分支——structured 必须携带已登记记录身份+映射版本且 WeKnora 审计组全空；weknora/legacy **既有输入继续可解析、校验/裁决行为不变**（接受/拒绝结果与理由一致；不承诺序列化输出字节级不变，兼容策略见下）；
- `merge`：`_evidence_rows` 持久化新字段；enrich 追加与 proposal aggregate 去重 SHALL 保留 structured 身份（去重键含 structured_record_id+mapping_version）；merge 时 SHALL 校验 `ProposedClaim.space_id == structured_source_record.space_id`，不一致在任何写入前 fail-closed（单列 FK 不构成 Space 保证）；
- `pages._evidence_view`：新增 structured 验证分支——验证发生在**发布/冻结时**：structured_record_id 可解析到留存记录 ∧ 以 raw_payload 重算 canonical hash 等于落库 record_hash ⇒ source_verified=true；chunk_verified 恒 false；source_ref 呈现 source_system+external_record_id+revision，SHALL NOT 产生伪 chunk/page 引用；记录缺失或 hash 不匹配 ⇒ 发布在任何 Wiki mutation 前失败（对齐 018 R1.3 stale/不完整证据拒发语义）；
- **冻结合同（018 对齐，文件域含 `snapshots.py` 与 reader 合同）**：`FrozenEvidence` SHALL 扩展为按 source_kind 分支的变体——weknora 组必填集不变；structured ⇒ **发布时去引用冻结** source_system/external_record_id/source_revision/record_locator/record_hash/mapping_version 于 Evidence JSON；SnapshotReader、页面渲染与 013 证据链 SHALL 只读冻结值，发布后 SHALL NOT 回查可变的 structured_source_records（018"发布时事实冻结"语义不破坏）；
- **序列化兼容策略**：冻结/对外 JSON 采用追加式演进——新增字段带默认值、既有 consumer 对未知字段的容忍策略显式声明；weknora/legacy 冻结形态不变。

#### Scenario: 领域模型按 kind 分支且既有行为不变

- **WHEN** 以 structured kind 构造携带已登记记录身份+映射版本的 ProposedEvidence，并以既有 weknora/legacy 夹具重放全部既有校验用例
- **THEN** structured 构造成功且 WeKnora 审计组必须全空（混填被拒）
- **AND** weknora/legacy 既有用例的接受/拒绝结果与理由逐条一致（校验/裁决行为不变）

#### Scenario: 发布时验证不产伪引用、篡改即拒发

- **WHEN** 含 structured 证据的发布进行冻结验证：一条留存记录存在且以 raw_payload 重算 canonical hash 与落库 record_hash 一致，另一条记录缺失或重算 hash 不匹配（模拟绕库改写）
- **THEN** 前者 source_verified=true、source_ref=source_system+external_record_id+revision、chunk_verified=false 且无任何伪 chunk/page 引用
- **AND** 后者使发布在任何 Wiki mutation 前失败（不静默降级、不带病冻结）

#### Scenario: 冻结后读取零回查可变表

- **WHEN** structured 证据的 Claim 完成发布后，令 structured_source_records 不可访问（模拟表缺失/权限收回），再经 SnapshotReader 与证据链读取该事实
- **THEN** locator/hash/mapping_version 等 provenance 全部来自冻结 Evidence JSON，读取零 SQL 触达源记录表
- **AND** 返回值与发布时逐字一致

#### Scenario: Space 不一致 fail-closed

- **WHEN** ProposedClaim.space_id 与其 structured 证据指向记录的 space_id 不一致
- **THEN** merge 在任何写入前 fail-closed（错误指明两个 space），不产生 Claim/ChangeItem

#### Scenario: 迁移回填与 downgrade

- **WHEN** 迁移 0007 应用于含 017 lineage 证据与 007 legacy 证据的库
- **THEN** 既有行回填 source_kind=weknora/legacy 且语义零漂移（017 成组约束照旧）
- **AND** downgrade 移除新增列/表后既有数据完好

### Requirement: I5 幂等、身份不变量、批次与 dry-run

通道二幂等键 SHALL 为 source_system + external_record_id + source_revision，且**身份绑内容、内容与转换分轴**：幂等 no-op 的条件 SHALL 为**（record_hash, mapping_version）双轴均未变**；**同键同 hash 但 mapping_version 变化** ⇒ 显式受控重算（以新映射重导出 ChangeItem 经 007 合并产生新 revision，非 collision、SHALL NOT 静默 no-op——否则映射修正后既无法安全重算、也无法解释历史 Claim 按哪版映射产生）；**同键不同 hash** ⇒ revision collision，在任何副作用前 fail-closed（错误指明幂等键与两个 hash），SHALL NOT 报 unchanged 或静默吞掉内容变化；revision 变化 SHALL 走 007 合并（enrich/supersede/conflict）而非重复建 Claim。每批次 SHALL 生成一个 ChangeSet，批内记录级失败隔离（单条坏记录入错误清单不中断批次）；dry-run SHALL 为默认（输出记录数/产品匹配率/未匹配清单/缺字段/预计 ChangeItem 计数，不落库），`--apply` 执行结果与 dry-run 预测 SHALL 一致（同一输入差异=0）。

#### Scenario: 同键同 hash 同映射版本重导零副作用

- **WHEN** 同一记录（同幂等键、同 record_hash、同 mapping_version）导入两次
- **THEN** 第二次零新增且 unchanged 计数+1

#### Scenario: 映射修正触发受控重算而非静默 no-op

- **WHEN** 同一记录（同幂等键、同 record_hash）在映射规则修正（mapping_version 变化）后重导
- **THEN** 产生新 ChangeSet 经 007 合并（值未变则 enrich/跳过、值变则 supersede/conflict 留痕），新证据携带新 mapping_version
- **AND** 不报 unchanged、不判 collision

#### Scenario: 同键不同 hash 碰撞 fail-closed

- **WHEN** 重导记录的幂等键与已留存记录相同但 record_hash 不同（上游错误复用 revision）
- **THEN** 导入在任何落库/合并副作用前 fail-closed，错误含幂等键与新旧 hash
- **AND** 不产生 unchanged 计数、不产生 ChangeItem

#### Scenario: dry-run 与 apply 一致

- **WHEN** 同一输入先 dry-run 后 `--apply`
- **THEN** apply 产生的 ChangeItem 计数与 dry-run 预测逐类相等

### Requirement: I6 Space 作用域与并发序保证

导入 SHALL 在显式 KnowledgeSpace 内执行（016 fail-closed）；批次、ChangeSet、structured_source_records、qa_staging 均带 space，跨 space 业务键互不可见。通道二实现排在 021 之后（见 proposal 排期）：structured 来源的并发/乱序处理 SHALL 提供 per-source 串行化保证——**复用/对齐 021 的 per-source lock/CAS 模式**（021 原语面向 WeKnora 源，本 change 为 structured 来源实现同模式；若实现选择显式串行替代，须留裁决记录并在 CLI 帮助文本标注），并以并发用例证明同 source 乱序导入不产生交错 ChangeSet。

#### Scenario: 跨 space 隔离

- **WHEN** 同一业务键的记录导入 Space A 与 Space B
- **THEN** 两空间各自成立、互不可见，未绑定 space 的调用 fail-closed

### Requirement: I7 FAQ 通道（qa_staging 暂存）

FAQ 输入（问题/答案/关联产品）SHALL 落 qa_staging 表（迁移 0007 内），字段含问题、答案、product_id、来源、external_record_id、space_id，幂等同 I5；qa_staging SHALL NOT 参与检索与发布（012 接手后消费）。

#### Scenario: FAQ 暂存不外泄

- **WHEN** FAQ 批次导入完成
- **THEN** qa_staging 有记录且幂等，发布/读模型/检索路径查无任何 FAQ 内容

### Requirement: I8 端到端验收（含发布与证据读模型回溯）

CLI SHALL 为 `python -m` 形态（bootstrap 与通道二子命令分离）；端到端 SHALL 覆盖：13 份 meta bootstrap（注册 100%、零 Claim）、构造的已登记业务源夹具（含销售状态变更 revision → supersede/conflict 留痕、同键异 hash 碰撞）、FAQ 暂存，以及**结构化证据的发布链回溯**；全程零模型调用，门禁全绿且不破坏既有测试。

#### Scenario: 双通道端到端

- **WHEN** 依次执行 meta bootstrap、已登记业务源导入（两个 revision）、FAQ 导入
- **THEN** 003 注册齐备且零 Claim 来自通道一；通道二产生带 structured Evidence 的 Claim 且冲突按权威序留痕；qa_staging 就位
- **AND** 全程零真实模型调用

#### Scenario: 结构化证据发布链全程可回溯

- **WHEN** 已登记记录 → ProposedClaim → 007 merge/approve → 发布 → 页面与证据读模型读取
- **THEN** 页面 EvidenceView 对该证据 source_verified=true，读侧从**冻结 Evidence JSON** 取得 source_system/external_record_id/revision/locator/record_hash/mapping_version 全套 provenance（发布后零回查可变源表）
- **AND** 全链无伪 chunk/page/source_ref 产生

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

通道二的每个来源 SHALL 在来源登记配置（source registry，YAML/表均可但须单一权威来源）中声明：source_system 标识、权威等级（对齐 03 §6.1 数值序）、数据责任人、记录 schema/映射引用；导入产生的 Claim 候选 SHALL 以 `source_kind=structured` + `extraction_method=structured_import` + 登记的 `authority_level`（已落库字段）表达来源可信度，由 007 权威序统一裁决，SHALL NOT 在导入侧特判覆盖；**SHALL NOT 引入 Claim 主链尚不存在的 `data_quality` 字段**（该字段的端到端持久化另立 change 026，见注册表）。

#### Scenario: 登记来源的权威等级进入合并裁决

- **WHEN** 已登记来源（权威=系统数据级）的记录与已发布的低权威 Claim 值冲突
- **THEN** 007 按权威序产生 supersede/conflict 并留痕，导入侧无任何绕过裁决的写路径

### Requirement: I4 结构化证据数据模型与全消费链闭合（迁移 0007；knowledge 域改动须 Owner-A 复审）

**正交来源轴**：证据 SHALL 新增 `source_kind ∈ {legacy, weknora, structured}`，与表示链接质量的 `lineage_status` 正交——`lineage_status` 值域**不变**（linked/page_only/ambiguous），且仅对 source_kind=weknora 有意义；SHALL NOT 把来源种类塞进 lineage_status。

迁移 0007 SHALL 按以下 schema 固定（不留实现者二选一）：
- `structured_source_records`：`id`（36-char PK）+ space_id、source_system、external_record_id、source_revision、record_locator、record_hash、raw_payload、authority_level、imported_at；UNIQUE(space_id, source_system, external_record_id, source_revision)；**insert-only**——服务层无 UPDATE/DELETE 路径，SQLite/PostgreSQL 均以 DB trigger 拒绝 UPDATE **与 DELETE**（合规删除须另立显式 purge change，本 change 不暗开口子）；**本表只保存不可变的 raw source identity/content，不含任何批次外键**——一条不可变记录必须能参加多个 mapping batch（单值 batch_id 与重算语义矛盾，五轮复审定案）；
- `structured_import_batch_records`（**append-only 关联表**，记录↔批次 M:N）：`change_set_id`（FK→`change_sets.id`）+ `structured_record_id`（FK→`structured_source_records.id`），PK/UNIQUE(change_set_id, structured_record_id)；服务层无 UPDATE/DELETE，SQLite/PostgreSQL 双方言 trigger 拒绝 UPDATE 与 DELETE；
- `claim_evidence`：新增**非空** `source_kind ∈ {legacy, weknora, structured}`、可空 `structured_record_id`（FK）、可空 `mapping_version`；迁移顺序 SHALL 为"先加 nullable/临时 default → 按'lineage 审计组完整→weknora，否则→legacy'回填 → 再收紧 NOT NULL/CHECK"；CHECK 按 kind 分支——weknora ⇒ 017 审计组齐全（既有语义不变）；structured ⇒ structured_record_id 与 mapping_version 非空 ∧ 禁止伪 page/chunk/raw_kb lineage；legacy ⇒ 全空、**仅存量兼容且不得冻结发布**；
- **downgrade 有条件**：仅当库中无 structured 行、无 structured Evidence、无 v2 快照时允许降级；发现任一项即 fail-closed——SHALL NOT 以"可逆"为名销毁 provenance。

**record_hash 语义（比较对象定死，防恒真）**：record_hash = canonical raw record（键排序、UTF-8、minified JSON 序列化）的 SHA-256；任何"一致性"校验 SHALL 以 raw_payload **重算** canonical hash 与落库值比对（探测绕库改写），SHALL NOT 把表中 record_hash 与其自身比较。

**mapping_version 语义（覆盖全部会改变输出的行为，防"YAML 未变代码变"错误 no-op）**：`mapping_manifest = {parsed_mapping, transformer_registry_version, normalizer_version, target_schema_version}`——YAML 先 parse 为 JSON 兼容树再 canonicalize（sorted-key、minified、UTF-8；注释/缩进/键序不影响结果）；`effective_mapping_version = SHA-256(canonical(mapping_manifest))`；ChangeSet SHALL 持久化 canonical manifest，Evidence 与快照冻结副本携带 digest；transformer/normalizer 行为变更 SHALL bump 对应版本，SHALL NOT 只改代码不改 manifest 版本。来源内容版本（record_hash）与转换版本（effective_mapping_version）是两条独立轴。

**`knowledge_id` 语义**：SHALL 保持非空，定义为"来源容器标识"——weknora=WeKnora knowledge id（既有）；structured=**source_system 标识**（供页面展示回退名与按来源分组），SHALL NOT 用空串/sentinel；**真正的证据身份只认 `structured_record_id`**（knowledge_id 仅展示/分组用途，不参与身份判定）。

**全消费链 SHALL 在同一实现 PR 内闭合**（不是只改表；以下均属 knowledge 域、Owner-A 复审）：
- `ProposedEvidence`：新增 source_kind、structured_record_id 与 mapping_version，校验按 kind 分支——structured 必须携带已登记记录身份+映射版本且 WeKnora 审计组全空；weknora/legacy **既有输入继续可解析、校验/裁决行为不变**（接受/拒绝结果与理由一致；不承诺序列化输出字节级不变，兼容策略见下）；
- `merge`：`_evidence_rows` 持久化新字段；enrich 追加与 proposal aggregate 去重 SHALL 保留 structured 身份（去重键含 structured_record_id+mapping_version）；merge 时 SHALL 校验 `ProposedClaim.space_id == structured_source_record.space_id`，不一致在任何写入前 fail-closed（单列 FK 不构成 Space 保证）；
- `pages._evidence_view`：新增 structured 验证分支——验证发生在**发布/冻结时**：structured_record_id 可解析到留存记录 ∧ 以 raw_payload 重算 canonical hash 等于落库 record_hash ⇒ source_verified=true；chunk_verified 恒 false；source_ref 呈现 source_system+external_record_id+revision，SHALL NOT 产生伪 chunk/page 引用；记录缺失或 hash 不匹配 ⇒ 发布在任何 Wiki mutation 前失败（对齐 018 R1.3 stale/不完整证据拒发语义）；
- **冻结合同 = 快照正式升级 v2（018 对齐；文件域含 `snapshots.py` 与 `reader.py`）**：`ReleaseSnapshot.read_model_version` CHECK SHALL 由 (0,1) 扩为 **(0,1,2)**（0 仍为 coverage gap 不可发布）；**v1 原模型完全不变**；v2 Evidence 为严格判别联合——`weknora`（冻结既有 v1 lineage 字段并显式带 source_kind）/ `structured`（冻结 source_system/external_record_id/source_revision/record_locator/record_hash/mapping_version，禁止制造 page/chunk）——**不提供可发布的 legacy 分支**；010 上线后的新快照统一写 v2，历史 v1 不迁写；Reader SHALL 严格读取 v1 与 v2 两种（判别校验，**禁止用全局 extra=ignore 掩盖 schema 错误**）；**v2 writer 只能在所有线上 reader 已支持 v2 后启用**（rollout gate 有测试或显式部署检查）；回滚只切 current pointer、SHALL NOT 改写历史快照；SnapshotReader、页面渲染与 013 证据链只读 FrozenEvidence，发布后 SHALL NOT 回查可变的 structured_source_records。

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

#### Scenario: 迁移回填与有条件 downgrade

- **WHEN** 迁移 0007 应用于含 017 lineage 证据与 007 legacy 证据的库（先 nullable 回填后收紧）
- **THEN** 既有行回填 source_kind=weknora/legacy 且校验/裁决语义不变（017 成组约束照旧）
- **AND** 空 structured 数据时 downgrade 干净；库中存在任一 structured 行/structured Evidence/v2 快照时 downgrade fail-closed（SQLite 与 PostgreSQL 双方言均验证）

#### Scenario: v1/v2 混合历史与回滚兼容

- **WHEN** 升级后库中同时存在历史 v1 快照与新发布 v2 快照，且 current 从 v2 回滚到 v1
- **THEN** Reader 对 v1/v2 均严格可读（判别校验，无 extra=ignore）、混合历史可枚举、回滚仅移动指针不改写历史
- **AND** legacy Evidence 参与发布被拒（无可发布 legacy 分支）

### Requirement: I5 幂等、身份不变量、批次与 dry-run

通道二幂等键 SHALL 为 source_system + external_record_id + source_revision，且**身份绑内容、内容与转换分轴**：幂等 no-op 的条件 SHALL 为**（record_hash, effective_mapping_version）双轴均未变**；**同键同 hash 但 mapping 变化** ⇒ 显式受控重算——即使 Claim 值相同，也 SHALL **enrich 追加带新 mapping_version 的 Evidence，不得 skip**（否则无法解释历史 Claim 按哪版映射产生）；值变化则走正常 ChangeItem/人工裁决；**同键不同 hash** ⇒ revision collision，在任何副作用前 fail-closed（错误指明幂等键与两个 hash），SHALL NOT 报 unchanged 或静默吞掉内容变化；revision 变化 SHALL 走 007 合并（enrich/supersede/conflict）而非重复建 Claim。每批次 SHALL 生成一个 ChangeSet，批内记录级失败隔离（单条坏记录入错误清单不中断批次）；dry-run SHALL 为默认（输出记录数/产品匹配率/未匹配清单/缺字段/预计 ChangeItem 计数，不落库），`--apply` 执行结果与 dry-run 预测 SHALL 一致（同一输入差异=0）。

#### Scenario: 同键同 hash 同映射版本重导零副作用

- **WHEN** 同一记录（同幂等键、同 record_hash、同 mapping_version）导入两次
- **THEN** 第二次零新增且 unchanged 计数+1

#### Scenario: 映射修正触发受控重算而非静默 no-op

- **WHEN** 同一记录（同幂等键、同 record_hash）在映射行为变更（effective_mapping_version 变化）后重导
- **THEN** 产生新 ChangeSet 经 007 合并：**值相同 ⇒ enrich 追加带新 mapping_version 的 Evidence（不得 skip）**；值变化 ⇒ 正常 ChangeItem/人工裁决留痕
- **AND** 不报 unchanged、不判 collision

#### Scenario: 同键不同 hash 碰撞 fail-closed

- **WHEN** 重导记录的幂等键与已留存记录相同但 record_hash 不同（上游错误复用 revision）
- **THEN** 导入在任何落库/合并副作用前 fail-closed，错误含幂等键与新旧 hash
- **AND** 不产生 unchanged 计数、不产生 ChangeItem

#### Scenario: dry-run 与 apply 一致

- **WHEN** 同一输入先 dry-run 后 `--apply`
- **THEN** apply 产生的 ChangeItem 计数与 dry-run 预测逐类相等

### Requirement: I9 批次与 ChangeSet 身份（batch_fingerprint 合同）

一个 structured import batch SHALL 同 space_id + source_system + effective_mapping_version，包含 N 条记录并对应**一个** ChangeSet；该 ChangeSet 的 `source_kind` SHALL 固定为 `structured_import`（与 Evidence 的 `source_kind="structured"` 是两个不同字段域，SHALL NOT 混用）。`batch_fingerprint = SHA-256(canonical({space_id, source_system, effective_mapping_version, sorted[(external_record_id, source_revision, record_hash)]}))`。`change_sets` SHALL 新增可空 `batch_fingerprint / mapping_version / mapping_manifest`，并加 CHECK：`source_kind='structured_import'` 时三者**全部非空**；structured batch 以 batch_fingerprint 唯一打开/复用 ChangeSet，记录与批次经 `structured_import_batch_records` 关联（I4）。**批次关联语义**：首次导入 ⇒ 创建一个 ChangeSet，插入/复用 N 条 source record，再插入 N 条关联行；相同 batch 重试 ⇒ 复用 ChangeSet 且关联零新增；**mapping 变化 ⇒ 创建新 ChangeSet，复用原 source record，为新 ChangeSet 追加关联行——SHALL NOT 复制或修改 raw record**。迁移 SHALL 把现有 source 唯一约束改为**两条 partial unique index**（predicate 写精确值，消除"structured"指 Evidence 还是 ChangeSet 的歧义）并在 SQLite 与 PostgreSQL migration tests 中同时验证：`WHERE source_kind <> 'structured_import'` ⇒ 维持 UNIQUE(space_id, source_kind, external_record_id, source_revision)（既有行为不变）；`WHERE source_kind = 'structured_import'` ⇒ UNIQUE(space_id, source_kind, batch_fingerprint)。

#### Scenario: 一批 N 记录一个 ChangeSet 且重试幂等

- **WHEN** 同一批（同 space/source_system/mapping，N 条记录）导入两次
- **THEN** 首次恰好产生一个 source_kind=structured_import 的 ChangeSet（batch_fingerprint 唯一）+ N 条源记录 + N 条批次关联行
- **AND** 重试命中相同 fingerprint 返回原 ChangeSet、关联零新增、零新副作用

#### Scenario: 同一源记录参加两个 mapping 批次而记录不可变

- **WHEN** 同一批记录在 effective_mapping_version 变化后重导（受控重算，I5）
- **THEN** fingerprint 变化 ⇒ 创建新 ChangeSet（不与原批唯一键冲突），**复用原 source record 并为新 ChangeSet 追加关联行**
- **AND** 该源记录经关联表同时挂在两个 ChangeSet 下，其 id/raw_payload/record_hash 逐字不变（未被复制、未被修改）

#### Scenario: 非 structured 批次唯一性不变

- **WHEN** document/manual_edit/recompile/rollback 等既有 source_kind 的 ChangeSet 创建与复用流程重放
- **THEN** 维持既有 UNIQUE(space_id, source_kind, external_record_id, source_revision) 行为，既有用例全部通过（SQLite 与 PostgreSQL 双方言迁移测试验证）

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

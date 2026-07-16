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

### Requirement: I4 结构化证据数据模型（迁移 0007，claim_evidence 扩展须 Owner-A 复审）

迁移 0007 SHALL 新建 `structured_source_records` 表：space_id、source_system、external_record_id、source_revision、record_locator（jsonpath/行号）、record_hash（规范化记录内容 SHA-256）、raw_payload（原始记录留存）、authority_level、batch_id、imported_at，唯一键=（space_id, source_system, external_record_id, source_revision）；并 SHALL 扩展 `claim_evidence`：新增可空 `structured_record_id`（FK→structured_source_records）、`lineage_status` 合法值增加 `structured`，CHECK 约束修订为三态互斥——WeKnora lineage 组（既有语义不变）/ structured（structured_record_id 非空且 WeKnora lineage 组与 chunk 字段全空、page 为空、quote=原始记录摘录）/ 007 legacy（全空）。该 DDL 属 knowledge/ 共享域，PR SHALL 由 Owner-A 复审；downgrade SHALL 干净可逆。

#### Scenario: 结构化 Evidence 完整可追溯

- **WHEN** 通道二导入产生 Claim
- **THEN** 其 ClaimEvidence 的 lineage_status=structured 且 structured_record_id 指向留存记录（locator+record_hash+raw_payload 齐备）
- **AND** WeKnora lineage 字段与 chunk 字段全为空（数据库 CHECK 拒绝混填）

#### Scenario: 既有 WeKnora/legacy 证据形态零漂移

- **WHEN** 迁移 0007 应用于含 017 lineage 证据与 007 legacy 证据的库
- **THEN** 既有行不变、既有 CHECK 语义保持（017 成组约束照旧生效）
- **AND** downgrade 移除新增列/值域后既有数据完好

### Requirement: I5 幂等、批次与 dry-run

通道二幂等键 SHALL 为 source_system + external_record_id + source_revision：同键重导零新增（返回 unchanged 计数）；revision 变化 SHALL 走 007 合并（enrich/supersede/conflict）而非重复建 Claim；每批次 SHALL 生成一个 ChangeSet，批内记录级失败隔离（单条坏记录入错误清单不中断批次）；dry-run SHALL 为默认（输出记录数/产品匹配率/未匹配清单/缺字段/预计 ChangeItem 计数，不落库），`--apply` 执行结果与 dry-run 预测 SHALL 一致（同一输入差异=0）。

#### Scenario: 同键重导零副作用

- **WHEN** 同一记录（同幂等键）导入两次
- **THEN** 第二次零新增且 unchanged 计数+1

#### Scenario: dry-run 与 apply 一致

- **WHEN** 同一输入先 dry-run 后 `--apply`
- **THEN** apply 产生的 ChangeItem 计数与 dry-run 预测逐类相等

### Requirement: I6 Space 作用域与 021 前串行限制

导入 SHALL 在显式 KnowledgeSpace 内执行（016 fail-closed）；批次、ChangeSet、structured_source_records、qa_staging 均带 space，跨 space 业务键互不可见。021 落地前，同一 source_system + external_record_id 的 revision 更替 SHALL 仅串行导入（对齐 HANDOFF ⓪-0a 边界），CLI 帮助文本 SHALL 标注此限制。

#### Scenario: 跨 space 隔离

- **WHEN** 同一业务键的记录导入 Space A 与 Space B
- **THEN** 两空间各自成立、互不可见，未绑定 space 的调用 fail-closed

### Requirement: I7 FAQ 通道（qa_staging 暂存）

FAQ 输入（问题/答案/关联产品）SHALL 落 qa_staging 表（迁移 0007 内），字段含问题、答案、product_id、来源、external_record_id、space_id，幂等同 I5；qa_staging SHALL NOT 参与检索与发布（012 接手后消费）。

#### Scenario: FAQ 暂存不外泄

- **WHEN** FAQ 批次导入完成
- **THEN** qa_staging 有记录且幂等，发布/读模型/检索路径查无任何 FAQ 内容

### Requirement: I8 端到端验收

CLI SHALL 为 `python -m` 形态（bootstrap 与通道二子命令分离）；端到端 SHALL 覆盖：13 份 meta bootstrap（注册 100%、零 Claim）、构造的已登记业务源夹具（含销售状态变更 revision → supersede/conflict 留痕）、FAQ 暂存；全程零模型调用，门禁全绿且不破坏既有测试。

#### Scenario: 双通道端到端

- **WHEN** 依次执行 meta bootstrap、已登记业务源导入（两个 revision）、FAQ 导入
- **THEN** 003 注册齐备且零 Claim 来自通道一；通道二产生带 structured Evidence 的 Claim 且冲突按权威序留痕；qa_staging 就位
- **AND** 全程零真实模型调用

# 025 合并前置弱值门槛验收规格

> 三版（2026-07-18，codex PR #17 两轮复审收口；二轮新增：E4 全权威时间切片资格 + `effective_to` 输入链贯通、G5 root+events 双表与双方言触发器、G7 来源 revision 状态机、G8 三类失败语义）。第一性原理修正：**抑制本身是一次裁决，不是中性的前置过滤**——它判定"旧值胜、候选不进入 007 裁决链"。因此抑制必须满足：①候选在更高优先级裁决维度（权威、生效时间、高风险强审、三态语义）**不可能胜出**（G1 资格前提）；②弱化关系**可证明**而非启发式分数推断（G2 偏序）；③被抑制的观察**可恢复**（G7 生命周期）；④审计与丢弃**原子且 exact-once**（G8）。任一无法满足 → fail-open 回 007 既有合并（G3）。informationScore 仅作排序信号，永不触发抑制（G6）。

## ADDED Requirements

### Requirement: G1 抑制资格前提（fail-safe eligibility），不满足即回 007

对同 `(space_id, product_version_id, predicate)` 已存在 published Claim（下称 baseline）的新候选，合并 SHALL 先做抑制资格校验；**全部前提成立**才允许进入 G2 弱化判定，任一不成立 SHALL 直接交回 007 K2/K3 既有合并（不抑制）：

- **E1 三态**：baseline 与候选的 `value_state` SHALL 均为 `present`。候选为 `absent_explicitly`（"明确不存在"是冲突事实，不是弱值）或 `unknown`、或双方语义极性不同 → 不可抑制；
- **E2 风险与裁决**：`risk_level=high` 的 predicate（docs 03 §6.2：高风险 supersede 一律进审核）或候选带 `pending_judge` → 不可抑制（不得绕过强审/未决裁决）；
- **E3 权威**：候选权威**高于** baseline → 不可抑制（照 007 K2 走 supersede，见 G4）；
- **E4 时间切片（适用于全部权威等级，不只同权威）**：仅当双方 effective 区间**逐端相等**才可继续——effective_from 与 effective_to 各端分别比较：双方同有值且相等、或双方同为 null（双方均未主张该端时间边界）视为该端相等；**一方有值一方无值、或值不等、或不可比 → 不可抑制**（不同时间切片不是旧值的弱投影；K3.2 ② 的生效时间裁决权保留给 007，门槛不得吞掉"同权威更新日期"的合法胜出者，也不得吞掉低权威但代表不同有效期的候选）。为使本前提可证明，`effective_to` SHALL 加入 `ProposedClaim` 并贯通 `_prop_dump`/canonical proposal/导入输入/`_create_claim`/revision 审计（现有输入链仅有 effective_from）；字段贯通落地前 E4 视为不可判定 → 不可抑制；
- **E5 基线时效**：baseline SHALL 是当前非 stale 的 published Claim，且抑制提交前 SHALL 在锁内复核仍为同 `claim_id + revision_no`（G8）；复核失败 → 重新裁决。

通过资格校验且 G2 判定 strictly_weaker 的候选：SHALL NOT 开 conflict、SHALL NOT 生成 ReviewItem、SHALL NOT 落 candidate/draft Claim；SHALL 按 G5 落 SuppressedObservation 与审计事件。此判定在 007 K2 冲突/supersede 判定之前执行，但除资格内枚举的情形外，007 权威序/裁决语义一字不改。

#### Scenario: 通过全部资格前提的可证明弱值被抑制

- **GIVEN** 已发布 Claim「犹豫期为 15 天」（低风险 predicate、权威=条款、present、生效区间完整）
- **WHEN** 合并同权威、同生效区间、present 的新候选「有犹豫期」（G2 白名单判定 strictly_weaker：存在性断言是量化断言的投影）
- **THEN** 不开 conflict、不生成 ReviewItem、不落新 Claim；落一条 SuppressedObservation 与审计事件，baseline 保持 published 不变

#### Scenario: 同权威但生效日期更新的候选不得抑制（E4）

- **GIVEN** 已发布「犹豫期为 10 天」（effective_from=2023-01-01）
- **WHEN** 合并同权威候选「有犹豫期」（effective_from=2025-01-01，更新）
- **THEN** 资格校验失败，不抑制；交回 007 按 K3.2 ② 生效时间裁决（新者可胜出）

#### Scenario: 低权威但不同有效期的粗略候选不得抑制（E4）

- **GIVEN** 已发布「犹豫期为 15 天」（effective_from=2023-01-01，effective_to=null）
- **WHEN** 合并**低权威**粗略候选「有犹豫期」（effective_from=2025-01-01——不同时间切片）
- **THEN** E4 失败不抑制；交回 007 按 K2 低权威语义处理（进 conflict 记录，不 supersede）

#### Scenario: effective_to 全链贯通后才可抑制（E4）

- **WHEN** ProposedClaim→canonical proposal→`_create_claim`→revision 审计的 `effective_to` 往返测试未全链通过
- **THEN** E4 视为不可判定，任何候选不得被抑制（fail-open）

#### Scenario: 高风险字段不得抑制（E2）

- **GIVEN** 已发布「等待期为 90 天」（等待期属 docs 03 高风险清单）
- **WHEN** 合并任何同/低权威的更粗略等待期候选（如「有等待期」）
- **THEN** 不抑制；照 007 高风险路径进 ReviewItem 强审

#### Scenario: present→absent_explicitly 是冲突不是弱值（E1）

- **GIVEN** 已发布 present 值「犹豫期为 15 天」
- **WHEN** 合并同权威候选 `value_state=absent_explicitly`（"无犹豫期"）
- **THEN** 不抑制（即便其文本更短、分数更低）；照 007 开 conflict

#### Scenario: pending_judge 候选不得抑制（E2）

- **WHEN** 候选带 pending_judge（存在未裁决项）
- **THEN** 资格校验失败，不抑制，照 007 既有 pending 语义处理

### Requirement: G2 弱化判定必须是可证明的偏序关系，与 informationScore 彻底分离

系统 SHALL 区分两个独立概念，SHALL NOT 混用：

- **InformationFeatures / informationScore**：确定性特征（长度、数值/日期/百分比/单位/枚举项计数、结构完整度）与标量分数，**仅**用于 008 排序信号（G6/G9），SHALL NOT 触发抑制——标量全序无法表达"不可比"，不得当作语义弱化证明；
- **SpecificityRelation**：抑制判据，取值 `strictly_weaker | equivalent | stronger | incomparable` 的**偏序**，SHALL 由 schema/value-type/predicate 级的版本化比较器给出，判定附 `rule_id` 与证明特征。**自由文本默认 incomparable**；仅**白名单化、可证明**的关系可返回 strictly_weaker（如：同谓词同单位同生效区间下，存在性断言是量化断言的投影；schema 明确定义的枚举父子；结构化值的严格子集投影且无新增项）。比较器 SHALL 版本化（`comparator_version`），同一版本同输入恒得同一判定（零模型、无随机、无外部状态）。

#### Scenario: 白名单可证明弱化返回 strictly_weaker

- **WHEN** 比较「犹豫期为 15 天」（量化）与「有犹豫期」（存在性），schema 定义存在性为量化的投影
- **THEN** 判定 strictly_weaker，附 rule_id 与 comparator_version

#### Scenario: 更短但语义不可比或更强的文本不得判弱

- **WHEN** 比较「保障至 80 周岁」与「终身」（更短但保障范围可能更广），或「保证续保 20 年」与「不保证续保」（相反口径）
- **THEN** 判定 incomparable（无白名单规则可证明弱化），不抑制

#### Scenario: 等价改写判 equivalent 不抑制

- **WHEN** 比较「犹豫期 15 天」与「犹豫期为15日」（归一化后同值）
- **THEN** 判定 equivalent，不抑制（照 007 走 enrich 语义）

### Requirement: G3 门槛必须 fail-safe，不确定即不抑制

仅当资格前提（G1）全部成立**且** SpecificityRelation 判定为 strictly_weaker 时才抑制。以下情况 SHALL NOT 抑制，一律 fail-open 到 007 既有合并：判定为 `equivalent / stronger / incomparable`；任一资格前提不成立；baseline 缺失（该字段尚无 published Claim）；比较器无法计算或抛错。门槛的任何计算失败 SHALL NOT 导致丢值，异常 SHALL 被记录。

#### Scenario: 不可比或等价时照常进入既有合并

- **GIVEN** SpecificityRelation 判定为 incomparable 或 equivalent
- **WHEN** 执行弱值门槛
- **THEN** 不抑制，交回 007 K2 按权威/裁决正常处理

#### Scenario: 比较器异常时 fail-open 不丢值

- **WHEN** 比较器对某候选抛出异常或返回不可用结果
- **THEN** 该候选 SHALL NOT 被抑制，照既有合并路径处理，异常被记录

### Requirement: G4 门槛与权威序正交，不得抑制更高权威值

弱值门槛 SHALL 只作用于权威**不高于** baseline 的候选（G1 E3）。更高权威的新值——即便判定更粗略——SHALL NOT 被抑制，照 007 K2 走 supersede 语义（权威胜过信息量：高权威更正是合法修订）。门槛 SHALL NOT 成为高权威更正被静默丢弃的路径。

#### Scenario: 更高权威的更粗略值仍照常 supersede

- **GIVEN** 已发布值「犹豫期为 15 天」（权威=产品说明书）
- **WHEN** 合并更高权威新值「有犹豫期」（权威=条款，但更粗略）
- **THEN** 门槛不抑制，交 007 K2 按权威序处理（进入 K2/K3 既有规则）

### Requirement: G5 抑制落 root+events 双表 append-only 审计，绝不静默、可复盘

每次抑制 SHALL 在迁移 **0011** 的双表落库（docs 03 §8 已先行登记）：

**`suppressed_observations`（root，不可变完整快照）**，SHALL 包含：

- 归属：`space_id`（复合 FK 闭合聚合，跨 Space 永不可见）、`change_set_id`、`product_version_id`、`predicate`；
- 基线：`existing_claim_id + existing_revision_no`（E5 复核后的值）；
- 候选完整快照：canonical value / `value_state` / `value_hash` + **完整 Evidence 与来源身份**（`knowledge_id` / `source_revision` / 引文定位）——抑制不等于丢弃观察，候选必须可重新裁决（G7）；
- 双方 `authority` 与 effective 区间；
- 判定依据：InformationFeatures 特征向量、两方 informationScore、`comparator_version`、`rule_id`、decision；
- `actor`、`created_at`、`proposal_fingerprint`（内容稳定指纹）。

root exact-once 唯一约束：`(space_id, change_set_id, proposal_fingerprint, existing_claim_id, existing_revision_no, comparator_version)`。

**`suppressed_observation_events`（生命周期事件流）**，SHALL 包含：`observation_id`（FK root，space_id 复合闭合）、`event_type ∈ {suppressed, readjudicated, invalidated, source_superseded}`、`causation_id`（触发方稳定标识：baseline revision 变更 / 021 SourceEvent / change_set）、`reason`、`occurred_at`、单调 `ordering`、`event_fingerprint`；事件唯一约束 `(space_id, observation_id, event_type, causation_id)` 防重放；root 创建与其首条 `suppressed` 事件 SHALL 同一事务。

**状态折叠确定性**：observation 当前态 SHALL 仅由事件流确定性折叠得出（无可原地改写的 status 列）；折叠 SHALL 与事件到达顺序无关（按 ordering/occurred_at 排序后折叠），`invalidated`/`source_superseded` 为终态，重复/乱序输入恒得同一状态。

**append-only 双方言强制**：SQLite 与 PostgreSQL 均 SHALL 用触发器拒绝两表的 UPDATE/DELETE（对齐 018 release_guard DDL 模式）；PostgreSQL 另加 REVOKE UPDATE/DELETE 作纵深防御（非唯一数据库边界）；服务层不提供 update/delete。

抑制计数 SHALL 可按 Space/产品/批次查询（G9）。无审计的丢弃即违规（原子性由 G8 规定）。malformed 聚合、跨 Space 引用、`model_copy` 绕构造校验 SHALL fail-closed 拒绝。

#### Scenario: 抑制记录完整可复盘且 exact-once

- **WHEN** 一批合并中 3 个候选被抑制
- **THEN** 恰有 3 条 root（各含基线 claim/revision、候选完整快照+Evidence 来源身份、双方权威/生效区间、特征向量/两分/comparator_version/rule_id）+ 各一条 suppressed 事件
- **AND** 同批重试不产生第 4 条（唯一约束幂等）

#### Scenario: 两方言直接 UPDATE/DELETE 均被拒绝

- **WHEN** 绕过服务层对 root 或 events 表执行 SQL UPDATE/DELETE（sqlite 与 postgres 各验证一次）
- **THEN** 触发器拒绝、行不可变（PostgreSQL 的 REVOKE 仅为额外纵深，不是唯一防线）

#### Scenario: 乱序与重复事件折叠确定

- **WHEN** 同一 observation 的 invalidated 与 readjudicated 事件以不同顺序重放、且重复投递
- **THEN** 重复事件被唯一约束拒绝；折叠结果与到达顺序无关，invalidated 恒为终态

#### Scenario: 跨 Space 与绕构造 fail-closed

- **WHEN** 写入引用另一 Space baseline 的观察，或经 model_copy 绕过构造校验的畸形聚合
- **THEN** 写入被拒绝（数据库复合 FK / 服务层校验 fail-closed）

### Requirement: G6 informationScore 仅作排序信号，SHALL NOT 作替换或抑制判据

informationScore SHALL NOT 触发 auto-supersede、SHALL NOT 以任何方式替换已发布 Claim、SHALL NOT 触发抑制（抑制判据只能是 G2 偏序）——替换 100% 由 007 权威序/裁决决定，本 change 不改。informationScore 仅可作为 008 工作台的排序/优先级信号（W1.1 可选信号）经 G9 合同暴露。系统 SHALL NOT 存在"信息量更高即自动取代已发布值"的路径。

#### Scenario: 信息量更高的新值不自动取代

- **GIVEN** 已发布值与一个 informationScore 更高但权威不更高的新候选
- **WHEN** 执行合并
- **THEN** 不因分数 supersede 或替换已发布 Claim；是否采纳仍交 007 K2 按权威/裁决判定

### Requirement: G7 被抑制观察必须可恢复，且随来源 revision 状态机失效

SuppressedObservation SHALL 有确定性生命周期（事件折叠合同见 G5）：

- **基线失效 → 重评**：baseline Claim 发生 supersede / retract / stale 时，其下所有 active 的 SuppressedObservation SHALL 进入重评流程——防止"强值来源删除后，仍然有效的弱观察随之丢失"；
- **重评资格复核（021 锁内）**：每次重评 SHALL 在 021 per-source lock 下复核：`SourceHead.state=active`、`SourceHead.latest_revision == observation.source_revision`、保存的 Evidence 非 stale——任一不满足 SHALL NOT 重建 proposal，转而追加对应失效事件；
- **来源 revision 失效 → 观察失效**：observation 引用的 source revision 一旦不再是其 SourceHead 的当前 active revision（新 revision 推进 head 致旧 Evidence stale——021 L3.3、supersede、retract、delete）SHALL 追加 `source_superseded`/`invalidated` 事件转终态；此后任何基线失效 SHALL NOT 复活它——只有"来源删除"一种失效触发是不够的，stale 未删的旧 revision 同样不得复活；
- **新 revision 观察独立**：新 revision 自己产生的观察 SHALL 独立走 007/025 全流程，SHALL NOT 借旧 observation 身份覆盖或复用；
- 重评通过资格复核后产生的 proposal 照 007/025 全流程重新裁决（可能落 Claim、开 conflict、或再次被抑制并落新 root+事件）。

#### Scenario: 强基线来源删除后弱观察重新裁决

- **GIVEN** 来源 A 支撑 published「犹豫期为 15 天」；来源 B（r1 为当前 active revision）的「有犹豫期」被抑制为 active observation
- **WHEN** 来源 A 被删除、证据清零、baseline 转 retracted，且重评资格复核通过（B 的 head 仍为 r1、state=active、Evidence 非 stale）
- **THEN** 该 observation 重新进入合并裁决，「有犹豫期」作为候选被重新评估（不再有 published 基线 → 照 007 正常落 Claim 进审核流）

#### Scenario: 新 revision 推进后旧观察不复活

- **GIVEN** 来源 B r1 的「有犹豫期」被抑制为 active observation
- **WHEN** B 推进到 r2（021 L3.3：head 前移、r1 Evidence 转 stale——r1 未被删除），随后 baseline 来源 A retract
- **THEN** r1 观察在重评资格复核中失败（latest_revision ≠ r1），追加 source_superseded 终态事件，永不复活；仅 r2 自己产生的新观察独立参与裁决

#### Scenario: 观察自身来源先删除则不得复活

- **GIVEN** 来源 B 的观察已被抑制，随后来源 B 被删除（invalidated 事件落库）
- **WHEN** baseline 之后也 retract
- **THEN** 该 observation 状态为 invalidated（终态），SHALL NOT 参与重评（防已删来源的值复活）

### Requirement: G8 抑制决定与审计写入必须原子、幂等、并发安全（三类失败各有语义）

- **claim-key 串行化**：抑制判定 SHALL 持有 claim business key `(space_id, product_version_id, predicate)` 的 PostgreSQL advisory/row lock——SHALL NOT 假设 021 的 per-source lock 已覆盖（两个不同来源可并发写同一 claim key）；锁顺序 SHALL 全局一致（source lock → claim-key lock）以避免死锁；
- **锁内复核（E5）**：拿锁后 SHALL 重读 baseline，revision 变化则基于新事实重新裁决；
- **原子性**：root/事件写入与"该候选不进入 007"的决定 SHALL 在同一 DB 事务；
- **三类失败语义，SHALL NOT 混同**：
  1. **计算类失败**（比较器/资格校验异常）：发生在任何 suppression 写入之前 → fail-open，本候选照 007 处理（同一事务内安全——尚无 suppression 写入，事务未失败）；
  2. **持久化失败**（root/事件 INSERT 失败：连接中断、非唯一键约束错误、serialization failure）：SHALL abort 整个 merge unit-of-work——零业务副作用提交（Claim/ChangeSet/observation 均无部分提交），候选保持可重试，由调用方按既有事务重试策略重跑该批；SHALL NOT 在 failed transaction 内继续执行 007 路径（事务已失败，任何"继续处理"都是未定义行为）；
  3. **唯一键冲突**：SHALL 读取既有行比对——payload 完全相同 → 幂等成功（重放）；同键异内容 → fail-closed 报错，SHALL NOT 吞掉或覆盖；
- **幂等**：重试/重放经 G5 唯一约束 exact-once，同一 ChangeSet 重跑不产生重复 root/事件；
- **验收 SHALL 含真实 PostgreSQL 双会话场景**：suppress-vs-supersede、suppress-vs-retract、重复批/事务重试、持久化失败注入——结果等价某个串行顺序且 root/事件 exact-once（缺 PostgreSQL 环境时显式 skip 并记录，沿 021 L5.6 纪律）。

#### Scenario: 并发 supersede 下抑制决定不基于过期基线

- **GIVEN** 会话 1 基于 baseline r1 计算出可抑制；会话 2 并发将该 baseline supersede 至 r2
- **WHEN** 会话 1 提交前锁内复核
- **THEN** 复核发现 revision 变化，放弃本次抑制并基于 r2 重新裁决（结果等价串行执行）

#### Scenario: 持久化失败零部分提交且可重试

- **WHEN** 抑制 root/事件 INSERT 注入故障（连接/约束/serialization）
- **THEN** 整个 merge unit-of-work abort：Claim/ChangeSet/observation 均无部分提交，系统中不存在"已丢弃但无审计"的状态
- **AND** 下一次健康事务重试该批时，该候选被正常处理（抑制或照 007）

#### Scenario: 计算异常与持久化失败语义不混同

- **WHEN** 比较器对候选抛异常（写入前）
- **THEN** 仅该候选 fail-open 照 007 处理，事务继续、其余候选不受影响（区别于持久化失败的整体 abort）

#### Scenario: 同键异内容 fail-closed

- **WHEN** 以相同唯一键但不同 payload 写入 observation（重放伪造/数据漂移）
- **THEN** fail-closed 报错拒绝；payload 完全相同的重放则幂等成功

### Requirement: G9 008 消费合同：评分持久化 + 只读抑制计数

- **评分来源持久化**：经过门槛评估的候选，其 informationScore 与 `comparator_version` SHALL 持久化——被抑制者在 SuppressedObservation（G5）；未被抑制而进入 007 者，随既有 `decision_basis`（K3.3 jsonb）附 `information_score + comparator_version`，无表结构变更。008 W1.1 的"可选辅助排序信号=值信息量评分"SHALL 从持久化值读取（读时不重算，防比较器版本漂移导致排序不稳定）；
- **抑制计数只读 API**：`knowledge/` SHALL 暴露只读查询（Space 强制入参）：按 Space/产品/change_set 聚合的抑制计数与明细分页，供 008 展示"本批抑制 N 条更粗略值"；SHALL NOT 提供任何写入/复活端点（重评只走 G7 服务层流程）。

#### Scenario: 008 排序读持久化分数

- **WHEN** 008 W1 队列按信息量评分辅助排序
- **THEN** 分数来自 ReviewItem 关联 decision_basis 的持久化 information_score（含 comparator_version），比较器升级不改变历史条目排序依据

#### Scenario: 抑制计数按批次可查且只读

- **WHEN** 008 查询某 Space 某 change_set 的抑制计数
- **THEN** 返回该批 SuppressedObservation 计数与明细（分页）；不存在任何修改/复活抑制记录的 HTTP/服务端点

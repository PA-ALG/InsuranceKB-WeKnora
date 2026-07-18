# 012 QA 一等知识对象验收规格

> 三版（2026-07-18）：codex PR #12 复审收口——Q1 由"answer_claim_ids JSON"升级为断言级规范化绑定（qa_revisions/qa_assertions/bindings，复合 FK 闭 Space、冻结事务内重验）；Q5 明确冻结投影合同（SnapshotQA）。二版（2026-07-16）Wave 2 条款化。原 Q1~Q6 条款 ID 沿用。核心不变量：**答案的每个事实断言必须绑定 published Claim——QA 与事实口径不允许分叉，且该不变量必须在数据库边界可守、在冻结事务内可证**。

## ADDED Requirements

### Requirement: Q1 数据模型与发布硬门禁（迁移 0009）

数据模型 SHALL 分层（迁移占号 0009，链序按注册表规则；03 §3 `qa_items + qa_revisions` 对齐）：

- `qa_items`：**只做稳定身份**——id、space_id、source、external_record_id、qa_type(authoritative|derived)、current_revision 指针；SHALL NOT 原地承载可变答案；
- `qa_revisions`：**不可变修订**——qa_item 复合 FK、question、intent_fingerprint、answer、entity_refs、effective 区间、状态（复用 007 状态机）、产生它的 ChangeSet；修改/重编/下架一律**追加新 revision + ChangeSet 留痕**，SHALL NOT 原地覆盖 answer；
- `qa_assertions`：答案拆解出的稳定**事实断言单元**（revision 复合 FK + 断言序号 + 断言值规范化形态）；
- `qa_assertion_claim_bindings`：规范化关联表（assertion ↔ claim），**所有行带 space_id，用复合 FK/唯一约束在数据库边界闭合 QA、断言与 Claim 的 Space 一致性**——不存在、跨 Space、悬挂的绑定 SHALL 被数据库直接拒绝，SHALL NOT 以 JSON 列表作为绑定唯一真相。

**发布硬门禁**：revision 的**每个** assertion SHALL 至少有一条指向 published Claim 的绑定（多断言答案只绑一条 = 拒发）；门禁校验与目标快照冻结 SHALL 在**同一事务**内锁定并重验绑定指向目标快照的事实——校验后发布前的 supersede/retract（TOCTOU）SHALL 导致发布失败或重试，SHALL NOT 带旧绑定发布。未覆盖、非 published、跨 Space、非目标快照、并发变更五类一律 fail-closed 且进 ReviewItem。

#### Scenario: 多断言答案部分覆盖拒发

- **WHEN** 一条 revision 含两个 assertion 但只有一条绑定
- **THEN** 发布在任何写入前被拒（错误指明未覆盖断言），进 ReviewItem 而非静默通过

#### Scenario: 跨 space 绑定被数据库拒绝

- **WHEN** 绕过服务层直接以 SQL 插入指向另一 Space Claim 的绑定行
- **THEN** 复合 FK/约束使插入失败（SQLite 与 PostgreSQL 双方言验证）

#### Scenario: 校验与发布之间并发变更 fail-closed

- **WHEN** 绑定校验通过后、冻结提交前，被绑定 Claim 被并发 supersede
- **THEN** 该次发布失败（或重验后重试），不得携带指向已替换 Claim 的绑定完成发布

#### Scenario: 修订追加不覆盖

- **WHEN** authoritative QA 的答案被修改两次后查询历史
- **THEN** 三个 revision 全部可审计（含各自 ChangeSet），qa_item 指针指向最新，旧 revision 逐字不变

### Requirement: Q2 权威 QA 通道（消费 010 qa_staging）

权威 QA SHALL 消费 010 的 qa_staging：答案中的值与候选 Claim 值做**确定性匹配**（归一化等价，复用 eval v2 要点匹配语义）→ 自动绑定；匹配不到 → ReviewItem(type=qa_unbound)，人工绑定或驳回，SHALL NOT 无 Claim 支撑发布；绑定后进 007 审核门禁（低风险自动阈值默认关）→ published。

#### Scenario: 绑定与未绑定分流

- **WHEN** qa_staging 中两条 FAQ：一条答案值与 published Claim 归一化等价，另一条无匹配
- **THEN** 前者自动绑定并进审核；后者开 qa_unbound 工单且不可发布

### Requirement: Q3 派生 QA 与同步义务（防口径分叉核心）

派生 QA SHALL 由模板化生成器产出：字段模板 YAML（field_id → 问题/答案模板），只从 published Claim 生成，qa_type=derived 且页面标注"由条款字段自动生成"；生成幂等（同 Claim 同模板重跑零新增）。**同步义务**：源 Claim supersede → 派生 QA 自动重编（新 ChangeSet 留痕）；retract → 自动下架；authoritative QA 的源 Claim 变更 → 标记复核（SHALL NOT 自动改人工口径）。

#### Scenario: supersede 触发同步

- **WHEN** 某字段 Claim 被 supersede，其上挂一条 derived QA 与一条 authoritative QA
- **THEN** derived 自动重编为新值（ChangeSet 留痕）；authoritative 进复核队列且文本未被自动修改

#### Scenario: retract 触发下架

- **WHEN** 派生 QA 的源 Claim 被 retract
- **THEN** 该 QA 自动下架（状态流转留痕），页面重发布后不再展示

#### Scenario: 生成幂等

- **WHEN** 同一 published Claim 与同一模板重复运行生成器
- **THEN** 第二次零新增

### Requirement: Q4 相似问合并（确定性）

intent_fingerprint SHALL = 归一化（去停用词/同义归一/字符排序 hash）；同指纹 SHALL 自动合并为一 QA 多问法（alias 问句表）；语义级合并仅留 LLM 接口 stub（默认关）。

#### Scenario: 三问合一

- **WHEN** 三条表述不同但归一化指纹相同的问题进入通道
- **THEN** 合并为一条 QA 携带三个问法别名，答案与绑定唯一

### Requirement: Q5 冻结投影与快照对齐（对 018 读模型的显式扩展）

018 现行冻结投影**只含产品 Claim 的 SnapshotFact 与 rendered pages，不含 QA**——本条款是对 release read model 的**显式扩展合同**，SHALL NOT 只写"对齐 018"而把扩展留给实现者猜：

- **冻结结构**：发布构建 SHALL 在冻结事务内把参与本次发布的 QA 冻结为 `SnapshotQA`（等价冻结结构）——含 qa_revision 全文（question/answer/断言集）、assertion→Claim 绑定（指向**本快照** SnapshotFact 的稳定引用）、qa_type、provenance；QA 区块渲染进 rendered pages（authoritative 在前、derived 标注）；
- **读侧合同**：页面回放与 QA 读取 SHALL 只消费冻结投影（SnapshotQA + rendered pages），发布后 SHALL NOT 回查 mutable `qa_items/qa_revisions/claims`；令 mutable 表不可访问后 Reader/回放 SHALL 仍逐字复现；
- **版本化与兼容**：`ReleaseSnapshot.read_model_version` SHALL 在 012 实现落地时按注册表合入序升级到下一版本（在 010 v2 合同之后），旧版本快照严格可读（判别校验、无 extra=ignore），**新版本 writer 只能在所有线上 reader 支持后启用**（rollout gate，018 既定模式）；
- **回滚**：只切同一 Space 的 current 指针并重放冻结页面/SnapshotQA，SHALL NOT 改写历史快照；冻结后对快照表的 INSERT/UPDATE/DELETE SHALL 被拒（SQLite 与 PostgreSQL 双方言）；
- 独立 QA 检索面（WeKnora FAQ 对接）列后续不在本 change。

#### Scenario: QA 纳入冻结快照且回滚一致

- **WHEN** 发布含 QA 的快照 V2 后，修改 mutable QA revision 与 Claim，再回滚 V1
- **THEN** 页面/QA 区块/绑定证据精确回到 V1（同指针切换，历史不改写），不受 mutable 修改影响

#### Scenario: 冻结后零回查 mutable 表

- **WHEN** V2 发布完成后令 qa_items/qa_revisions 不可访问，经 Reader 读取 QA 区块与绑定
- **THEN** 全部内容来自冻结投影，读取零 SQL 触达 mutable QA 表，返回值与发布时逐字一致

### Requirement: Q6 端到端

端到端 SHALL 覆盖：FAQ 夹具经 010 staging 直入 → 绑定 → 发布；supersede 源 Claim → derived 重编 + authoritative 复核；无 Claim 支撑发布被拒；三条相似问合一；全程零真实模型调用、门禁全绿、不破坏既有测试。

#### Scenario: 全链故事

- **WHEN** 依次执行 staging 消费、绑定发布、源 Claim supersede、相似问导入
- **THEN** 上述四段行为全部符合 Q1~Q5 断言
- **AND** 零真实模型调用

# 009 概念层编译验收规格

> 三版（2026-07-18）：codex PR #12 复审收口——C1 身份改 UUID+(space_id, canonical_key) 唯一并补不可变定义修订；C2 对齐实际 Claim 字段（predicate）并把排除表纳入迁移；C4 断链门禁改验目标快照全图；C5 Purpose 改 Space-scoped；C6 明确冻结投影扩展合同。二版（2026-07-16）Wave 2 条款化。原 C1~C6 条款 ID 沿用；C3.4 混源防护为同事 WeKnora 实证反馈吸收项。

## ADDED Requirements

### Requirement: C1 概念注册与定义版本化（迁移 0008）

概念 SHALL 落 `concepts / concept_revisions / concept_aliases / claim_concepts / concept_match_exclusions` 五表（Alembic 迁移占号 0008，链序按注册表"合入序"规则）：

- **身份**：concept 主键 SHALL 为稳定 UUID；业务唯一键 SHALL 为 `(space_id, canonical_key)`（canonical_key=slug 化规范名）——同名概念在 A/B 两 Space 各自成立且互不冲突，SHALL NOT 以全局 slug 作 PK；别名唯一性同样限定 Space（`(space_id, alias)` 唯一）；**全部关联使用 `(space_id, id)` 复合 FK，跨 Space 边由数据库直接拒绝**（016 fail-closed）；
- **定义版本化**：概念定义 SHALL NOT 直接放在 concepts 行内原地改写——定义/审核口径落不可变 `concept_revisions`（带来源 provenance、审核记录、产生它的 ChangeSet），concepts 行只留 current_revision 指针；定义更新=追加 revision，旧修订可审计、旧快照可回放（03 §3 "可更新、可溯源、可回滚"）；
- 初始概念源 = glossary.yaml 全量导入 + 概念词表 YAML（可扩展），导入幂等；LLM 概念候选接口仅留 stub（claude-session 形态，默认关）——新概念 SHALL 只能经审核转正，SHALL NOT 自动入注册表。

#### Scenario: 概念注册幂等且 Space 隔离

- **WHEN** 同一词表在 Space A 重复导入两次，并在 Space B 导入一次
- **THEN** A 内第二次零新增；A/B 的同名概念（同 canonical_key）各自成立、互不可见
- **AND** 未绑定 space 的调用 fail-closed；直接以 SQL 插入跨 Space 关联边被数据库拒绝

#### Scenario: 定义修订可审计可回放

- **WHEN** 某概念定义被审核更新一次后，读取历史修订并回放旧快照
- **THEN** 新旧两个 revision 均可审计（各自 ChangeSet/provenance）；旧快照页面仍呈现旧定义（冻结语义，见 C6）

#### Scenario: 新概念不得自动转正

- **WHEN** LLM 候选接口产出新概念建议
- **THEN** 建议只入待审队列，注册表零新增（审核通过才落表）

### Requirement: C2 概念-Claim 关联（确定性、可重算、可拉黑）

关联 SHALL 为确定性规则：Claim 的 **`predicate` 与规范化值**（对齐实际 Claim 模型字段——SHALL NOT 使用不存在的 field_name/field_id 名义）命中概念词/别名（归一化子串+词边界）→ 建 claim_concepts 边并记**命中依据与规则版本**（规则行为变更须 bump 版本，边可按版本审计）；`relink-concepts` 全量重算与增量结果 SHALL 一致；误关联 SHALL 可人工拉黑——`concept_match_exclusions` 持久表（space_id、concept、predicate、rule_version、actor、reason），拉黑后重算不再关联且**进程重启后仍生效**。

#### Scenario: 重算一致与拉黑生效

- **WHEN** 增量建边后执行全量 relink，再对一条边拉黑、重启进程并重算
- **THEN** 全量与增量结果一致；拉黑边消失且不复现（排除持久生效），命中依据与规则版本可追溯

### Requirement: C3 概念主页编译与混源防护

概念主页 SHALL = 定义区（术语表/审核口径）+ 跨产品差异表（行=产品，列=该概念下关键字段的 published Claim 值+证据角标）+ 义项索引（链接 `[[产品限定页slug#锚点]]`）；SHALL 只聚合 published Claim；无关联 Claim 的概念不生成页面；Claim 变更（supersede/retract）后重编译并经统一发布链重发布。**混源防护（C3.4）**：定义区 SHALL NOT 合成任何产品特定事实值（只允许术语表/审核口径来源）；产品事实只出现在差异表行内（单一产品+该产品 Claim+证据角标）；QA/MCP 取数一律走产品 Claim/快照，SHALL NOT 引用概念页正文。

#### Scenario: 差异表逐行单源

- **WHEN** 三个产品共享"犹豫期"概念且各有 published Claim
- **THEN** 概念主页差异表恰好三行，每行的值与证据角标只来自该行产品的 Claim
- **AND** 定义区不含任何一个产品的具体值

#### Scenario: Claim 变更驱动重编译

- **WHEN** 差异表中某产品的 Claim 被 supersede
- **THEN** 概念页重编译并重发布后差异表反映新值（旧快照按 018 语义仍可回放）

### Requirement: C4 wikilink 互链与断链硬门禁（验目标快照全图）

产品页渲染 SHALL 将概念词替换为 `[[concept-slug|原词]]`（每页每概念只链首次出现）；概念页 SHALL 出链回产品页；发布前 SHALL 执行无悬挂 wikilink 硬门禁——校验对象是**应用本次发布计划（upsert+delete）之后的完整目标快照页面图**，SHALL NOT 用"本次集合 ∪ 当前已发布集合"近似（否则引用一个将在同次发布删除的旧页会误通过）；断链拒发（在任何 Wiki mutation 前失败）。

#### Scenario: 断链拒发

- **WHEN** 待发布页面引用了不在目标快照页面图中的 slug
- **THEN** 发布在任何 Wiki mutation 前失败并指明断链 slug

#### Scenario: 引用同次发布将删除的页面拒发

- **WHEN** 页面 X 引用 slug Y，而本次发布计划包含删除 Y
- **THEN** 门禁按目标图判定 Y 缺失，发布在任何 Wiki mutation 前失败（不因 Y 当前仍已发布而误通过）

### Requirement: C5 Purpose 注入（Space-scoped、单一注入点、版本化）

Purpose 配置（领域意图/合规口径/引用要求/禁用表述）SHALL 为 **Space/KB scoped**——按 KnowledgeSpace 归属加载（Space-scoped registry 或受控导入物），SHALL NOT 以一个无归属的全局 yaml 服务多租户；加载 fail-fast、内容 hash 版本化；注入点 SHALL 唯一（compiler prompts 的 system 组装函数，抽取/补漏/编译共用）；run/release manifest SHALL 冻结 `(space_id, purpose_version, digest)`；**Space A 的 purpose SHALL NOT 进入 Space B 的任何 prompt/manifest**。

#### Scenario: 注入唯一且可追溯

- **WHEN** 组装任一抽取/编译 prompt 并检查 run manifest
- **THEN** prompt 快照含 purpose 段与版本标识；manifest 冻结 (space_id, purpose_version, digest)
- **AND** purpose 缺失/非法时加载即失败（不静默降级）

#### Scenario: 跨 Space purpose 隔离

- **WHEN** Space A 与 B 配置不同 purpose，对 B 执行编译
- **THEN** B 的 prompt/manifest 只含 B 的 purpose，A 的内容零出现

### Requirement: C6 冻结投影扩展与端到端（对 018 读模型的显式扩展）

018 现行冻结投影**只含产品 Claim 的 SnapshotFact 与 rendered pages，不含概念页**——本条款是对 release read model 的**显式扩展合同**，SHALL NOT 只写"对齐 018"而把扩展留给实现者猜：

- **冻结结构**：发布构建 SHALL 在冻结事务内冻结参与本次发布的概念内容——concept_revision 定义全文、concept→Claim 绑定（指向**本快照** SnapshotFact 的稳定引用）、页面 provenance；概念主页/义项页进入 rendered pages 的**完整目标页面集**；
- **读侧合同**：Wiki 渲染、回放与在线读取 SHALL 只消费冻结投影，发布后 SHALL NOT 回查 mutable `concepts/concept_revisions/claims`；令 mutable 表不可访问后 Reader/回放 SHALL 仍逐字复现；
- **版本化与兼容**：`ReleaseSnapshot.read_model_version` SHALL 在 009 实现落地时按注册表合入序升级到下一版本（在 010 v2 合同之后），旧版本严格可读（判别校验、无 extra=ignore），**新版本 writer 只能在所有线上 reader 支持后启用**（rollout gate，018 既定模式）；
- **回滚**：只切同一 Space 的 current 指针并重放冻结页面，SHALL NOT 改写历史；冻结后快照表 INSERT/UPDATE/DELETE 被拒（双方言）。

端到端：3 产品共享 2 概念的夹具 → 概念页含差异表、义项链接可解引用、产品页互链无悬挂；supersede 一条 Claim → 概念页重编重发布；零真实模型调用、门禁全绿。

#### Scenario: 概念页纳入冻结快照且回滚一致

- **WHEN** 发布含概念页的快照 V2 后，修改 mutable 概念定义与 Claim，再回滚到 V1
- **THEN** 概念页与产品页精确回到 V1 内容（指针切换、历史不改写），不受 mutable 修改影响

#### Scenario: 冻结后零回查 mutable 表

- **WHEN** V2 发布完成后令 concepts/concept_revisions 不可访问，经 Reader 回放概念页
- **THEN** 内容全部来自冻结投影，读取零 SQL 触达 mutable 概念表，与发布时逐字一致

#### Scenario: 端到端零模型调用

- **WHEN** 运行 3 产品×2 概念端到端夹具
- **THEN** 概念主页/义项/互链/差异表全部就位且无悬挂链接
- **AND** 全程零真实模型调用

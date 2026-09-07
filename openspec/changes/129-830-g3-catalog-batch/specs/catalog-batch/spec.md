# G3 · 目录与批次合同

## ADDED Requirements

### Requirement: G3-R1 工作簿无损目录
系统 MUST 从 B0 持久 v5 工作簿实测 hash 编译 11/11 版本化 pack；字段计数 67/70/62/67/66/75/79/82/74/83/76，按工作簿字段名统计 154 去重、47 全产品共有。统计同名不等于共享语义身份。各 pack 保留 11 列原值及 sheet/row；字段 key 使用原英文名，身份由 pack+key 限定，语义 hash 包含说明/取值/来源等，不仅按名字合并。必选意味着 attempt 及三态独立页，绝不补造非空事实。

#### Scenario: 真实工作簿导入与重算
- WHEN 编译 exact v5 输入及冻结映射配置两次
- THEN 每包数据及 Catalog hash 一致，11 包计数及全部元数据可回放，错 hash 或遗漏/重复字段拒绝。

### Requirement: G3-R2 独立展示 Profile
系统 MUST 复用 presentation-profile.v1 的有序 sections/fields 合同，每 pack 独立 id/version/hash；FieldDefinition 不保存 presentation_section。映射只由 Profile 拥有，业务分类不直接用作 UI 目录；每字段恰好一次主映射、空 section/孤儿/重复为零。Catalog entry 绑定 exact pack 和 Profile，包内容 hash 不循环依赖 Profile hash。所有 Profile 先为 PENDING_PRODUCT_OWNER_CONFIRMATION；结构生成不伪造具名产品负责人整包确认，质量持续 DEFERRED_TO_Q0。

#### Scenario: 多节点及重排
- WHEN 使用非医疗可变节点配置或重排展示
- THEN 通过同一 Profile validator，字段 key 和语义 hash 不变；孤儿/重复/空节点确定性拒绝。

### Requirement: G3-R3 既有平台目录接线
系统 MUST 用既有 WeKnora 目录/页面/审核链读取 Catalog/Profile 及同版字段值、条件、来源；保持 legacy 医疗链，禁止第二 Wiki。注册目录不得冒充内容 Release 或质量准入。

#### Scenario: 目录与隔离知识分层
- WHEN 打开 11 包目录及已选 pack 样本映射
- THEN 可核对 pack/profile identity；未质量准入知识不得发布生产；未发布 Candidate 不进入正式搜索。

#### Scenario: 多产品候选复用同一发布链
- WHEN 批次自动身份结果进入 G3 候选编译
- THEN 按 `docs/insurance-kb/evidence/830-g3/lane-d-consolidated-contract-v2.md`（SHA-256 `75c81f582b2ace94efba6d016f0d24c00eb3e10a836f6673612bb7aaa3bfb94d`）严格验证完整 Catalog、确认回执、C 输入及结果、每实体 binding、原 G2 base request、模型 delta/机械合成/独立审核记录与同一 page manifest。
- THEN 所有既有实体必须有实际 C 自动 MATCH；新实体必须有实际 C 自动 CREATE，不增加主数据注册前置；缺失资格在编译及 Draft 前拒绝。
- THEN 首切片正向和容量 fixture 使用 actual G2 base 两医疗实体与重疾、两全、意外三新实体，合计 342 个标准字段页；完整 POST 使用真实 serializer 测量且不得超过现有 8 MiB，容量闭合前不得实施 handler/service/UI。
- THEN 旧 134 行 existing input 原样进入 request；132 行事实逐字继承，仅按修订6冻结的两行 exact unknown-only lineage 对齐旧单数 key 到新 Profile key，旧 Release 不变；每医疗仍恰好 67 页，禁止额外 legacy 页或删 base 压缩容量。
- THEN 使用既有 Draft/Ready/Review/Activate 和唯一 Head CAS；preparation 与 active 读取分开，真实 source authority 在 Draft/Review/Activate 按原 G1/C5 链重开；fixture 不替代实际模型、来源或业务验收。

### Requirement: G3-R4 批量身份与材料采信
系统 MUST 在后续同 G3 切片冻结 10–15 真实材料/revisions 和 Seed 标签来源，分别冻结 identity/classification 阈值，证明 MATCH/CREATE/MULTI/NEEDS_CONFIRM/QUARANTINE 真实场景。明确高置信自动 Candidate，歧义/版本冲突隔离；配置式 TrustPolicy 按来源、字段、版本、作用域、有效期求值，不以上传次序或模型自信提权。

#### Scenario: 自动与隔离
- WHEN exact 身份及依据满足独立阈值
- THEN 幂等 Candidate 沿唯一链形成；多实体有独立 Evidence，低置信/冲突不静默 MATCH。

### Requirement: G3-R5 分类稳定与真实隔离验收
系统 MUST 保持重分类前后实体/字段/Evidence/历史身份，复用 G2 概念/free_wiki 与原始质量记录。G3 PASS 只由全卡真实批次、11 包注册、对应独立字段页与来源/搜索、具名结构确认和独立复核共同产生；QUALITY=DEFERRED_TO_Q0。

#### Scenario: 完整结果门
- WHEN 只通过本地 Catalog 测试或只生成 Profile Candidate
- THEN G3 仍 WIP；真实批次、具名确认、平台/隔离 Release 未执行项明确 NOT RUN。

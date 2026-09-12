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
- THEN 反序列化请求必须逐一绑定 exact C child 的身份 anchors、entity/version key公式和所选证据；确认回执同时锁定真实文件及语义hash；C/base同 SourceBlock identity 不同完整内容必须拒绝，即使调用方重算全部外层hash（集中修复合同 `lane-d-python-repair-1.md`）。
- THEN D source集合严格为全部已选C材料blocks与actual base carry证据blocks的canonical并集；owner字段校验允许其所选材料、其自身carry及实际关联concept的证据来源，拒绝跨owner借用。按 `lane-d-source-coverage-design-2.md`（SHA-256 `ec64c6b90d2504b481686fc071ce1f6ed2bcf218339efafff8119aa6f7e21716`）同时校验请求与delta，主342样例包含身份块外的保障正文块及对应字段Evidence。
- THEN 所有既有实体必须有实际 C 自动 MATCH；新实体必须有实际 C 自动 CREATE，不增加主数据注册前置；缺失资格在编译及 Draft 前拒绝。
- THEN 首切片正向和容量 fixture 使用 actual G2 base 两医疗实体与重疾、两全、意外三新实体，合计 342 个标准字段页；完整 POST 使用真实 serializer 测量且不得超过现有 8 MiB，容量闭合前不得实施 handler/service/UI。
- THEN 旧 134 行 existing input 原样进入 request；132 行事实逐字继承，仅按修订6冻结的两行 exact unknown-only lineage 对齐旧单数 key 到新 Profile key，旧 Release 不变；每医疗仍恰好 67 页，禁止额外 legacy 页或删 base 压缩容量。
- THEN Active概念页复用现有concept-page-read.830.g2.v1 envelope；G3 overview related从sections字段引用严格构造同版同owner集合，G3服务端拒绝冲突查询。按 `d-active-page-transport-clarification-1.md`（SHA-256 `26189ef0159da209926d24d14b59939b0688924febd55c221b2e6b9b1536ed26`）分派，旧G2行为不变，Preparation仍用独立冻结响应。
- THEN 按独立复核的 `lane-d-downstream-execution-plan-1.md`（SHA-256 `a5cbf39c74f2bd26d52590580b7d2a059858d2951577614ad1cae3ed8727f3ab`），G3在落Draft前调用同一source verifier；仅G3允许create-draft operation且此时PreparationDigest为空/非存储权威；Review/Activate使用真实存储digest，G2 operation集合不变。
- THEN 按 `d-preparation-alignment-display-clarification-1.md`（SHA-256 `5e12a1e0f81677986aa8483c79e6376f9266b410655564be8ee96ec858b0daab`），前端不内联租户entity/release/member标识；在鉴权preparation后从expected base pin经现有双KB ACL historical search派生旧成员，并与当前manifest验证两行展示绑定。完整14字段lineage仍由服务端重验，不扩响应DTO，不以当前Head替代历史pin。
- THEN 使用既有 Draft/Ready/Review/Activate 和唯一 Head CAS；preparation 与 active 读取分开，真实 source authority 在 Draft/Review/Activate 按原 G1/C5 链重开；fixture 不替代实际模型、来源或业务验收。

### Requirement: G3-R4 批量身份与材料采信
系统 MUST 在后续同 G3 切片冻结 10–15 真实材料/revisions 和 Seed 标签来源，分别冻结 identity/classification 阈值，证明 MATCH/CREATE/MULTI/NEEDS_CONFIRM/QUARANTINE 真实场景。明确高置信自动 Candidate，歧义/版本冲突隔离；配置式 TrustPolicy 按来源、字段、版本、作用域、有效期求值，不以上传次序或模型自信提权。

#### Scenario: 自动与隔离
- WHEN exact 身份及依据满足独立阈值
- THEN 幂等 Candidate 沿唯一链形成；多实体有独立 Evidence，低置信/冲突不静默 MATCH。

#### Scenario: 真实多行正文与结构化身份分离
- WHEN C Corpus/Evidence 或 D 内联旧 G2 正文含 TAB、LF、CR
- THEN 按 `cd-multiline-canonical-amendment-7-v2.md`（SHA-256 `975ae956c2c851b8f8fffffbffd5bbbebb6b4051fa031237db3c0afb224f9380`）复用既有 G2 正文 canonical，保持 G3 domain/prefix 与合法旧向量 hash；不清洗原文、不改变 Catalog/G2 shared helper。
- THEN C 构造/重验在 typed 对象转字典前递归拒绝全部嵌套结构化字符串的控制字符，唯 exact SourceBlock.text/Evidence.quote 为正文豁免；D 沿该修订的 G2 正文与 control-free 身份边界，Python/Go 同时拒绝非 ASCII 域。

#### Scenario: 直接消费当前来源登记回执
- WHEN 真实来源已通过现有 knowledge-revision-source.v1 HTTP 登记
- THEN 按 `c-source-registration-amendment-8.md`（SHA-256 `0b2e924174e4ea31143f369dcf9ec2479a1f01e003b29e0f84cf188ddaf7dc66`）接入 exact 14-key 镜像，与原 LiveReceipt 组成严格 contract discriminated union；不伪造 admission/resource/self-hash 字段，不新增历史 admission 前置。
- THEN Registered scope 由实际 authenticated acquisition 与 BatchCorpus 绑定；来源校验、信任规则、候选 key 与重复来源 key 同步使用明确分支；Legacy 校验不变，D 继续重开服务端完整 source authority 与旧 G1/C5 carryover 链。

### Requirement: G3-R5 分类稳定与真实隔离验收
系统 MUST 保持重分类前后实体/字段/Evidence/历史身份，复用 G2 概念/free_wiki 与原始质量记录。G3 PASS 只由全卡真实批次、11 包注册、对应独立字段页与来源/搜索、具名结构确认和独立复核共同产生；QUALITY=DEFERRED_TO_Q0。

#### Scenario: 完整结果门
- WHEN 只通过本地 Catalog 测试或只生成 Profile Candidate
- THEN G3 仍 WIP；真实批次、具名确认、平台/隔离 Release 未执行项明确 NOT RUN。

## 2026-09-12 用户批准的有限修复

G3-P1：已发布读取复用既有不可变成员与固定来源定位，正常GET不重验整批候选、不调用DocReader；完整校验留在准入/发布及一次历史补建。缓存/投影绑定发布及来源版本，当前权限与目标身份逐请求检查。旧第6版保持不变。验证同字段/引用首读、重复读、进程重启复用及拒绝越权/版本漂移。root独占release/schema读取与repository/types必要小适配，g3_source_reuse独占concept_source_authority与来源复用小文件。

G3-P2：已有代码+备案号版本不因version_label缺项误挡，m07/08分别保留；m02/04/18利用现有证据关联，m09不同公司隔离，m19不确定适用性保留待办；m21完整多实体识别。只重跑受影响任务。

G3-P3：复用现有状态/检查点/幂等机制实跑小批与一次中断恢复，已完成任务不重复模型调用、不损坏第6版，结果不明调用先对账。Q0质量、大规模长稳和G4不在本轮范围。

用户已批准上述顺序和本机修复/部署，不另建Mission、冻结包或再次申请授权。测试与必要独立审查后推进实际验证，状态随实际结果填写。

### 2026-09-12 收尾接续授权

用户确认执行容量、恢复、读取、启动、歧义处置及修订发布六项遗留处理。既有第6版作为不可变历史保留，允许通过现有 Candidate/Review/Activate 形成新的隔离版；此前“第6版保持不变”不再解释为禁止新的授权发布。具体写域、验证与原卡完成边界见 `docs/superpowers/plans/2026-09-12-g3-final-closeout.md`。继续复用原 P1—P3 与 R1—R5，不新增产品 Goal 或生产验收门槛。

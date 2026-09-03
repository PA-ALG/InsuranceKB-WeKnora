# 830 G1 Entity FieldAssertion Pages Specification

## ADDED Requirements

### Requirement: G1-R1 stable real entity identity and routes

系统 SHALL 从 815 正式 Candidate/Release 读取并冻结实体
`ping-an-e-sheng-bao`，且 overview、section、field、free-wiki 的 page identity/route
只由稳定 entity/page key 形成。修改短标题、分类显示名或导航归属不得改变这些 identity、
Claim/Evidence 历史或旧 Release 路由。

#### Scenario: title and classification change

- **WHEN** 同一实体的显示标题与分类导航改变
- **THEN** 其 overview、section、67 个 field 与 free-wiki 的 page ID/route 全部不变

### Requirement: G1-R2 exact unique 76-member page graph

同一实体 Release SHALL 恰好包含 1 overview、7 个医疗险 Profile section、67 个独立
FieldAssertion 和 1 个空 free-wiki，共 76 个唯一 page ID。每个 FieldDefinition 恰好
对应一个 FieldAssertion；不得以表格、锚点或缺页替代。

#### Scenario: duplicate, missing or extra page

- **WHEN** manifest 出现重复 ID、缺少任一 ordered67 field、free-wiki 非空或总数不为 76
- **THEN** Candidate/Release 校验失败且不会进入 preparation

### Requirement: G1-R3 complete tri-state FieldAssertions

67 个 FieldAssertion SHALL 分别且仅为 `present`、`absent_explicitly` 或 `unknown`。
unknown 页面 SHALL 存在、值为空并带合法 typed reason，且不得显示为“无”。

#### Scenario: unknown field is omitted or collapsed to absent

- **WHEN** unknown 字段无独立页面、携带值/Evidence、无 typed reason 或显示为明确否定
- **THEN** manifest 或 UI contract 校验失败

### Requirement: G1-R4 known fields share exact Claim and Evidence

known FieldAssertion、所属 Section 与 Overview 聚合 SHALL 引用同一 release-bound Claim/
Evidence identity。来源点击 SHALL 使用 exact source revision、PDF、1-based page、quote
和 locator；任一不匹配时 typed fail closed，不得打开 current revision、相似 quote 或
第 1 页。

#### Scenario: one source authority component drifts

- **WHEN** revision/page/quote/locator/content hash 任一漂移
- **THEN** 来源读取失败且返回固定 typed error，页面不产生 fallback

### Requirement: G1-R5 short titles are separate from canonical namespace

页面 MUST 默认显示中文短标题，例如“投保年龄”“犹豫期”“保证续保期”。payload、
manifest 和索引 MUST 同时保留完整稳定 namespace/page ID，不得把长 namespace 当默认标题。

#### Scenario: open a field page

- **WHEN** 用户从 Section 点击 `cooling_off_period`
- **THEN** URL 指向该实体自己的 field route，标题显示“犹豫期”，payload 保留完整 namespace

### Requirement: G1-R6 whole graph is one atomic Release

全部 76 个页面 SHALL 作为同一 Candidate/Review/Release bundle 原子准备和激活，绑定同一
release_id。系统 SHALL 禁止按页发布或激活。

#### Scenario: activation before or after CAS

- **WHEN** 并发读取发生在激活 CAS 前后
- **THEN** 每次读取只看到完整旧 Release 或完整 76-page 新 Release，不出现混版

### Requirement: G1-R7 current and pinned reads never fall back

current read SHALL 在请求开始固定唯一 Head 的 release/epoch；显式 pinned read SHALL 只读
请求的 exact release。不存在、无权或 payload 不匹配时失败关闭，不得回落 current/latest。

#### Scenario: invalid pinned release

- **WHEN** 调用者请求不存在、foreign 或不完整的 release_id
- **THEN** 返回 typed not-found/forbidden/integrity error，且不会读取 current

### Requirement: G1-R8 no second authority

Harness SHALL 只编译结构化页面图和 Candidate bundle；WeKnora SHALL 继续承担唯一 Wiki、
审核、Release、Head、ACL 与来源读取。G1 不得新增数据库表、在线 Harness reader、第二
publisher、第二事实库或可独立编辑的 Markdown 正文。

#### Scenario: rendered page is deleted

- **WHEN** 非权威 rendered content 被删除
- **THEN** 页面可由同 Release 的 Claim/Evidence/PageManifest 确定性重建

### Requirement: G1-R9 renderer is profile-driven, not seven-hardcoded

公共 validator、API renderer 和前端 renderer SHALL 遍历 PresentationProfile 的有序
section 集合与 field mapping，不得将 section 数量 7 或医疗险 section 名写成全局规则。
G1 只注册医疗险 Profile。

#### Scenario: minimal non-seven profile unit test

- **WHEN** 单元测试提供一个合法的 2-section Profile 与完整 field partition
- **THEN** 公共 validator/renderer 接受并按给定顺序输出，不新增第二产品 Profile

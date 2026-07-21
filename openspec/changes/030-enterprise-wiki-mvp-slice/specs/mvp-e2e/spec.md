# 030 Real MVP Slice 验收规格

## ADDED Requirements

### Requirement: MVP1 冻结 23-entry manifest

manifest SHALL 精确列出 23 个受控输入条目、内容 hash、产品/版本预期、输入类型、来源权利、是否结构化、是否受控 fixture 与 `claim_evidence_eligible`；其中 5 个 `product_meta.json` SHALL 标记为 registration-only/false。输入字节变化必须产生新 run revision。SHALL NOT 修改或冒用 020 canonical admission。

030 SHALL 提供最小、按 `purpose + run_schema_version` 参数化的 run-admission builder/evaluator core；允许的 profile/角色集合来自代码所有的固定 registry，MVP 只登记 `enterprise-wiki-mvp` profile，CLI/YAML 不得注入任意 schema/profile/role。它实现 027 `AdmissionVerifier`，不得另定义 Admission port/DTO。028 strict request SHALL 使用 027 DTO 独立提供 expected purpose/schema；core 必须先以该 pair 从代码 registry 选择 verifier，再解析 artifact，未知 pair 或 artifact 自报不同 pair/domain 均 fail closed。verifier SHALL 验证 approval/trust/current content，逐字段比较 request 与 actual values，最后通过 027 受控 factory 签发 opaque `VerifiedAdmission`；其 binding view 保留 purpose/schema 及全部签名字段。公开 DTO、artifact 自报 READY 或 caller-injected verifier 不得产生 capability。它不得调用 020 中硬编码 `wip-gs-v0.1`、13 产品或 `annotator/weak_extractor/judge` 角色的 evaluator。

MVP approval envelope SHALL 使用独立 versioned signature domain，并绑定 purpose/schema version、exact run identity/revision、Space、23-entry manifest/eligibility、Golden Slice、routing-policy identity/hash、schema/template lock、structured-dispatch lock、model plan/deployment roles、资源上限、rights/provenance、clean integration commit SHA 与 expiry。`structured-dispatch lock` SHALL 以 canonical hash 冻结 exact registration meta path/hash set、structured source-registry identity/authority/record-schema refs、known-schema adapter/canonicalizer versions、source-profile fingerprints、mapping manifests 与 effective mapping versions；替换其中任一项必须重新 admission。production trust policy SHALL 来自不可由 artifact/request/CLI 覆盖的 root-protected deployment source，并以 `key_id + public-key fingerprint` 固定映射到具名 human identity、`mvp-run-admission-approver` role、approval domain、允许 purpose/schema 与 Space scope；envelope 自报 identity/role 不得提权。READY SHALL 由该 policy、真人签名和当前内容重新推导，不得信任 YAML 自报状态或 self-enrollment。

签名 approval envelope 与最终 strict run request SHALL 位于仓库外的受控、内容寻址 artifact store；Git 只保存 unsigned schema/plan template 与运行后的 sanitized digest/index/report。人类在 clean integration SHA X 上签名，外部 request 绑定 X 与 envelope digest，运行仍在 clean X 上执行；不得把 envelope/request 提交后再用新 SHA 冒充被批准代码。可复用经审计的 canonicalization/signature 原语，但不得修改或生成 020 canonical 工件；020 是否迁入该通用 core 留 M2 单独变更。

#### Scenario: 输入漂移阻断运行

- **WHEN** 任一 PDF/product_meta/JSON/fixture 内容在 admission 后改变
- **THEN** run 在模型调用前 BLOCKED，模型调用数为 0

#### Scenario: 030 不借用 020 硬编码 evaluator

- **WHEN** 用 020 canonical artifact/evaluator、未登记 purpose/schema/role，或缺少 030 domain-separated 真人 approval 尝试获得 030 `VerifiedAdmission`
- **THEN** profile adapter 按实际失败返回 typed BLOCKED（包括 profile/role 未登记、签名/authority 缺失或 expected/actual identity mismatch），不签发 opaque capability，模型调用数为 0

#### Scenario: 受信 key 不得跨 Space 或 profile 提权

- **WHEN** envelope 自报其他 human/role，或已登记 key 被用于 policy 未允许的 Space、purpose/schema 或 signature domain
- **THEN** evaluator 在 job/provider 前 typed BLOCKED，且 artifact/request 不能注册或覆盖 trust policy

#### Scenario: approval 工件不改变被批准代码身份

- **WHEN** clean integration SHA X 已冻结并由人类批准
- **THEN** envelope 与 strict request 在仓外内容寻址存储，运行仍验证 clean X；把它们加入 Git 后产生的 SHA Y 不得替代 X 或被隐式批准

### Requirement: MVP2 产品归属与模板

5 个产品的文档级分类和事实级归属 SHALL 达 100% controlled acceptance；跨产品污染为 0。每个 knowledge-eligible 文档 SourceRevision 先形成绑定 routing policy/template lock 的父 intake job；混合文档对每个明确产品路由确定性扇出绑定批准 TemplateVersion/hash 的子 compilation job。歧义项进入 unassigned/Alert/ReviewItem，不强行归属且不创建伪产品子 job。registration-only `product_meta` 和 010 通道二结构化事实不伪造文档编译 job。

#### Scenario: 普通与分红型不串知识

- **WHEN** 两个相似名称产品同时运行
- **THEN** 事实、Evidence、ChangeSet 和页面分别绑定正确 product_version_id

#### Scenario: 混合文档按产品扇出

- **WHEN** 同一文档同时包含两个明确产品知识点与一个无法消歧的知识点
- **THEN** 父 intake job 复用两个产品子 compilation job，明确知识点分别进入正确产品，歧义知识点只进入 unassigned + Alert/ReviewItem，重放零重复

### Requirement: MVP3 抽取质量与证据

在冻结 MVP Golden Slice 上，候选字段级 precision SHALL ≥0.90、recall SHALL ≥0.85；所有进入批准 snapshot 的 Claim 必须人工确认且 Evidence 回验率=1.00。`unknown` 不得转为 `absent_explicitly`。

#### Scenario: 无证据候选不能发布

- **WHEN** 候选值无法在冻结来源回验
- **THEN** 候选进入 gap/review/alert，批准 snapshot 中不存在该无证据 Claim

### Requirement: MVP4 结构化直入

已知 schema 的 `product_meta.json` SHALL 走 010 通道一，只写 003 产品/版本注册及可审计导入回执，产生零 Claim、零 ClaimEvidence，不得被包装为业务事实来源。FAQ 原始 question/answer 只能暂存；只有来自已登记通道二来源、携带显式 `fact_assertions` 的 FAQ 记录可以跳过 PDF 解析，并 SHALL 形成 SourceRevision、结构化 Evidence/record locator、ChangeSet/Review。任何结构化输入不得借直入绕过产品对齐和来源 authority。

#### Scenario: FAQ JSON 有治理链

- **WHEN** 导入来自已登记来源、同时包含 raw question/answer 与显式 fact_assertions 的受控 FAQ JSON
- **THEN** raw FAQ 只暂存，fact assertions 可从最终 snapshot/读模型追溯 source system、record id/revision/hash/mapping version，无伪 page/chunk

#### Scenario: 产品元数据不冒充 Claim 来源

- **WHEN** 导入 MVP 中 5 份 `product_meta.json`
- **THEN** 产品/版本注册幂等完成，Claim 与 ClaimEvidence 增量均为 0

### Requirement: MVP5 更新、冲突与告警

后续 SourceRevision SHALL 产生 add/enrich/supersede/conflict 中正确动作；受控冲突发现率=1.00，不静默覆盖。模板失配、无共识、Evidence 失败、attempt 上限 SHALL 产生持久 Alert 且停止不安全候选推进。

#### Scenario: 新资料不静默覆盖

- **WHEN** 后续修订给出与当前 Claim 不同的同字段值
- **THEN** 产生 Conflict/ReviewItem，授权人裁决前 CurrentRelease 不变

### Requirement: MVP6 人审、同快照与回滚

授权人批准完整 ReleaseManifest hash 后才能 promote。真实 run SHALL 先由具名真人对 exact compilation manifest 中的 ChangeSet/ReviewItem 作显式裁决，再构建 candidate；另一具名授权人查看 candidate manifest 后 SHALL 人工填写 exact manifest hash、snapshot、expected current、授权 receipt 与理由。CLI 不得推断或默认这些输入。Harness Reader 与 MCP SHALL 返回相同 snapshot/hash；回滚到旧批准 snapshot 时零模型调用且两边同时切换。

#### Scenario: 端到端更新与回滚

- **WHEN** release A 发布、后续 release B 经冲突审核发布，再回滚 A
- **THEN** change log 保留 A→B→A 事件，Reader/MCP 各阶段同 snapshot，provider 在回滚阶段零调用

### Requirement: MVP7 可恢复与效率证据

同 run 重放不得重复写事实；中间故障从最近 checkpoint 恢复。validation report SHALL 记录每个 PR 的七段时间、focused/full/live 测试证据和所有 NOT RUN，不把等待时间或软件 PASS 冒充业务效果。

#### Scenario: 崩溃恢复不重做成功阶段

- **WHEN** run 在 verify 后崩溃并重启
- **THEN** 已成功 stage attempt 数不增加，只重试失败/未完成阶段

#### Scenario: 真实运行可复现且不伪绿

- **WHEN** admission READY 后对冻结 23-entry request 执行唯一 028 `run-manifest` 命令
- **THEN** validation report 记录 literal argv、request hash 与 exit status；exit 0 只代表 knowledge sink 完成且 sealed compilation manifest 最后写入，CurrentRelease 仍不变
- **AND** 之后只用 029 治理命令消费该 bundle，依次验证真人 review decisions、构建 candidate、真人 exact-hash approval、expected-current CAS promote 与 Human/MCP 同 snapshot serving proof；不得调用第二个编译 runner或模型
- **AND** final artifact manifest 在 release proof/serving proof 后最后写入并绑定全部 compilation/human/governance/candidate/release/serving 制品；external preflight blocked 使用 exit 2，启动后 blocked/failed 使用 exit 3

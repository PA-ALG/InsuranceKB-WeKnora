# 030 Real MVP Slice 验收规格

## ADDED Requirements

### Requirement: MVP1 冻结 23-source manifest

manifest SHALL 精确列出 23 个 source、内容 hash、产品/版本预期、文档类型、来源权利、是否结构化、是否受控 fixture；输入字节变化必须产生新 run revision。SHALL NOT 修改或冒用 020 canonical admission。

#### Scenario: 输入漂移阻断运行

- **WHEN** 任一 PDF/JSON/fixture 内容在 admission 后改变
- **THEN** run 在模型调用前 BLOCKED，模型调用数为 0

### Requirement: MVP2 产品归属与模板

5 个产品的文档级分类和事实级归属 SHALL 达 100% controlled acceptance；跨产品污染为 0。混合文档歧义项进入 unassigned/Alert，不强行归属。每个 job 钉住批准 TemplateVersion/hash。

#### Scenario: 普通与分红型不串知识

- **WHEN** 两个相似名称产品同时运行
- **THEN** 事实、Evidence、ChangeSet 和页面分别绑定正确 product_version_id

### Requirement: MVP3 抽取质量与证据

在冻结 MVP Golden Slice 上，候选字段级 precision SHALL ≥0.90、recall SHALL ≥0.85；所有进入批准 snapshot 的 Claim 必须人工确认且 Evidence 回验率=1.00。`unknown` 不得转为 `absent_explicitly`。

#### Scenario: 无证据候选不能发布

- **WHEN** 候选值无法在冻结来源回验
- **THEN** 候选进入 gap/review/alert，批准 snapshot 中不存在该无证据 Claim

### Requirement: MVP4 结构化直入

已知 schema product metadata/FAQ JSON SHALL 跳过 PDF 解析，但仍形成 SourceRevision、结构化 Evidence/record locator、ChangeSet/Review；FAQ 或元数据不得借直入绕过产品对齐和来源 authority。

#### Scenario: FAQ JSON 有治理链

- **WHEN** 导入受控 FAQ JSON
- **THEN** 可从最终 snapshot/读模型追溯 source system、record id/revision/hash/mapping version，无伪 page/chunk

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

- **WHEN** admission READY 后执行唯一 028 `run-manifest` 命令
- **THEN** validation report 记录 literal argv、request hash 与 exit status；exit 0 只代表 knowledge sink 完成且 sealed compilation manifest 最后写入，CurrentRelease 仍不变
- **AND** 之后只用 029 治理命令消费该 bundle，依次验证真人 review decisions、构建 candidate、真人 exact-hash approval、expected-current CAS promote 与 Human/MCP 同 snapshot serving proof；不得调用第二个编译 runner或模型
- **AND** final artifact manifest 在 release proof/serving proof 后最后写入并绑定全部 compilation/human/governance/candidate/release/serving 制品；external preflight blocked 使用 exit 2，启动后 blocked/failed 使用 exit 3

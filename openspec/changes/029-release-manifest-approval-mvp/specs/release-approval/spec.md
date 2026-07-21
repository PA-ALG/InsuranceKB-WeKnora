# 029 Release Approval MVP 验收规格

## ADDED Requirements

### Requirement: RA1 完整且确定性的 ReleaseManifest

manifest SHALL 绑定 space、snapshot、schema/template/model-plan identity，以及全部 SnapshotFact、rendered pages、产品目录 entries 和页面 relationships 四类 MVP serving 制品；每类同时保存 canonical items、count 与分项 SHA-256，外层 manifest 再对完整 canonical payload 计算 SHA-256。顺序或 JSON 格式差异不得改变语义 hash；任一制品内容、count 或分项 hash 变化都必须使验证失败并使外层 hash 改变。

#### Scenario: 任一 serving 制品改动改变 hash

- **WHEN** 分别只修改一个冻结事实/Evidence、rendered page、directory entry 或 relationship，或伪造任一分项 count/hash
- **THEN** manifest hash 改变，旧 approval 不再匹配

### Requirement: RA2 真人授权人批准完整 hash

ReleaseApproval SHALL 记录 space、snapshot、manifest hash、actor、角色/授权 receipt、时间和理由；模型、service account 或未授权 actor 不得创建有效 approval。approval append-only，不能原地改 hash。

#### Scenario: 模型不能批准

- **WHEN** actor 类型为 model/service 或不属于 Space 授权人
- **THEN** approval 创建失败，CurrentRelease 不变

### Requirement: RA3 CAS CurrentRelease

promote SHALL 在同一事务内重算/核对 manifest、approval 有效性和 expected current；任一不匹配 fail closed。并发 promote 只有一个成功。

#### Scenario: 批准后篡改

- **WHEN** approval 后 snapshot manifest 内容被改变
- **THEN** promote 拒绝并产生 Alert，CurrentRelease 保持旧 snapshot

### Requirement: RA4 同一 SnapshotReader

029 SHALL 公开唯一 `ApprovedSnapshotReader.read_current(scope, *, product_id=None, product_version_id=None, predicates=None, effective_on=None, claim_id=None)` 合同。它返回严格 `ApprovedSnapshotResult | ServingFailure`：成功结果包含 approval identity、`snapshot_id + manifest_hash` 与 canonical facts；facts 以 `(product_id, product_version_id, predicate, effective_from, effective_to, claim_id, revision_no)` 排序，Evidence 使用 document/structured 严格判别联合并按稳定来源 identity + evidence id 排序。产品/版本/claim 为精确过滤，日期为闭区间过滤，`predicates=None` 表示全部且空/重复 predicates 被拒绝。Coverage gap、approval/manifest 不可用和 scope mismatch 使用固定枚举失败 envelope，不以空数组代替。`value_state=unknown` 若存在于批准快照仍是成功 fact；只有真实 CoverageGap 才映射 not-found。Harness 人类 Reader 与 013 MCP SHALL 导入并消费该公共 DTO/方法，回显同一 `snapshot_id + manifest_hash`；不得自建 canonical fact/evidence 模型或回查 mutable Claim 补正文。

#### Scenario: 人与 Agent 同 hash

- **WHEN** 同一 Space/产品同时从 Harness Reader 与 MCP 查询
- **THEN** 两边 snapshot_id、manifest_hash、事实集合一致

### Requirement: RA5 逻辑回滚

rollback SHALL 只允许仍有有效 approval、manifest 可重算匹配的旧 snapshot，并以 expected current CAS 切换；不得重新生成事实或调用模型。

#### Scenario: 回滚零模型

- **WHEN** 从 release B 回滚到批准的 release A
- **THEN** CurrentRelease 指向 A，provider fake 零调用，人/MCP 同时读 A

### Requirement: RA6 P-1 前生产 Wiki UI fail closed

029 SHALL 不把逐页 publisher 成功当作 production release；ACL 隔离 staging 只作预览，普通 UI/RAG 可见写入被拒绝。

#### Scenario: 生产 UI 写入被拒

- **WHEN** 在 P-1 capability 不存在时请求 production Wiki publish
- **THEN** 返回类型化 blocked，Harness CurrentRelease/Reader 仍可服务已批准 snapshot

### Requirement: RA7 真人控制的治理命令与最终封存

029 SHALL 提供治理专用而非编译用的命令序列：`apply-review-decisions → build-candidate → approve-manifest → promote-approved → seal-run-artifacts`。它只消费 028 sealed compilation manifest 和既有 review/release 服务，不得导入 runtime stage、调用模型或执行 Node/TS。review decisions 与 release approval request SHALL 分别由具名真人在查看 ChangeSet/ReviewItem 和完整 release manifest 后填写；命令不得推断 decision、actor、manifest hash 或 expected current。`approve-manifest` 只追加 approval，`promote-approved` 才执行 RA3 CAS。最终 `artifact-manifest.json` SHALL 在 release proof 与 Human/MCP 同 snapshot/hash serving proof 都验证后最后写入，并绑定此前全部编译、人工输入、review、candidate、approval、release 与 serving 制品。

#### Scenario: 编译成功不能自动发布

- **WHEN** 028 run-manifest exit 0，但缺少真人 review decisions 或缺少真人填写的完整 manifest hash/授权 receipt
- **THEN** candidate/approval/promote/final seal 按对应阶段 fail closed，CurrentRelease 不变；系统不得生成默认批准输入

#### Scenario: 真人批准后才封存发布证据

- **WHEN** review receipt 绑定 exact compilation manifest、授权人批准 exact release manifest 且 expected current CAS 成功，Human/MCP serving proof 也绑定同 snapshot/hash
- **THEN** release proof 有效，并以 exclusive create 最后生成 final artifact manifest；该治理流程模型调用数为零

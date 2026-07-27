# 043 P2d Space Security Boundary 验收规格

> 本 change 为 spec-only。所有 requirement 冻结未来 P2d 实现合同，不表示
> P3 前置已满足，也不授权创建生产代码或 migration。

## ADDED Requirements

### Requirement: P2D.1 P3 是 principal 与角色的唯一 Owner

P2d SHALL 只消费 P3 public contract 中的五个人类角色
`viewer | editor | reviewer | space_admin | super_admin`、两个 scoped
service principals `source_reader | wiki_projector`、唯一 principal 铸造/
校验入口与其 derived Space scope。P2d SHALL NOT 复制角色/principal 枚举、
建立 principal/credential 表、实现第二 auth provider，或采信 caller 在
path/header/body 中自报的 `space_id/user_id/role`。

`source_reader` SHALL 只可读取其 P3 scope 绑定的 RAW KB；
`wiki_projector` SHALL 只可投影其 P3 scope 绑定的 managed Wiki KB。两者
SHALL NOT 互换能力、持有人类角色或 superadmin 能力，亦 SHALL NOT 因
provider call 被放大为模型调用 authority。provider gate SHALL 把 caller
提供的 job/stage/attempt/generation/Space 只当 expected facts，并经 P1-owned
**read-only** active-fence verifier 从 PostgreSQL current job row + DB clock 重验
Space/job/current generation/`running` state/exact attempt/unexpired lease；
constructible `ClaimedJob` snapshot 本身不授予权限，也不被定义成 principal。
当前 P1 `JobStore.heartbeat` 会续租并写库，不能满足授权失败零写合同。
P2d 实现 SHALL 保持 blocked，直到 P1 public contract 提供上述只读
verifier；P2d SHALL NOT 自行读取/修改 `wiki_jobs`，也不得以 heartbeat、
start 或其他状态推进替代授权验证。`super_admin` 可执行显式管理动作，但
SHALL NOT 绕过当前 RAW ACL、binding active、profile gate、integrity 或
provenance 检查。

当前 OpenSpec 039 没有可读取 RAW+Wiki 两端 ACL 的 authority：
`source_reader` 只读 RAW Source/chunk/artifact，`wiki_projector` 只写
managed Wiki。P2d SHALL NOT 发明第三个 service principal/capability。
实现 SHALL 保持 blocked，直到单独的 P3 amendment 冻结并实现 P3-owned、
least-privilege ACL-inspection authority（或等价 authenticated human
delegation），且 P3 implementation 合入 main。spec 文档或手工 fake
principal/credential SHALL NOT 被解释为依赖已满足。

#### Scenario: caller 自报身份不产生权限

- **WHEN** caller 在请求中声明另一个 Space/user/role，但 P3 principal scope
  不含该 Space
- **THEN** P2d 在读取 binding/profile 或外部 ACL 前 typed 拒绝，零数据、
  零 transport

#### Scenario: P3 contract 或实现未满足不允许提前接线

- **WHEN** implementation lane 的 main 仍无 P3 principal/service shell
  implementation，或仍无经独立 P3 amendment 冻结的 ACL-inspection
  authority
- **THEN** P2d 实现任务保持 `BLOCKED`，不得用本地 DTO 或 spec fake 代替 P3

#### Scenario: provider job context 不是第三 principal

- **WHEN** Worker 为已被 P1 fencing 的 job 请求 provider gate
- **THEN** gate 把 job/stage/attempt/generation/Space 作为 expected facts，
  再由 P1 current row/DB clock 证明 active fence；不得给
  `source_reader/wiki_projector` 增加 provider capability，也不创建第三个
  principal

#### Scenario: stale ClaimedJob snapshot 不构成 authority

- **WHEN** caller 保留旧 `ClaimedJob` snapshot，但其 lease 已过期、job 已
  被更高 generation 回收或不再 `running`
- **THEN** P1-owned read-only active-fence verifier typed 拒绝，P2d gate
  transport=0

### Requirement: P2D.2 KnowledgeSpaceBinding 为 append-only 版本权威

系统 SHALL 为每次有效的 admit/reconcile/rebind/disable 结果写一个
Space-scoped、append-only `KnowledgeSpaceBinding` version。version SHALL
至少冻结：

- `id/space_id/tenant_id/raw_kb_id/wiki_kb_id`；
- 封闭 `state`：
  `active | acl_mismatch | acl_scope_unsupported |
  verification_unavailable | disabled`；
- 与 state 绑定的封闭 `state_reason`：
  `active→acl_equivalent`；
  `acl_mismatch→principal_set_mismatch | role_mapping_mismatch |
  capability_mismatch | tenant_or_kb_mismatch`；
  `acl_scope_unsupported→source_acl_narrower_than_kb |
  file_acl_narrower_than_kb`；
  `verification_unavailable→acl_api_unavailable |
  acl_snapshot_unstable | acl_contract_unknown | acl_role_unknown |
  acl_mapping_unknown | acl_inspection_authority_unavailable`；
  `disabled→administrator_disabled`；
- `acl_contract_version`、`acl_role_mapping_version/hash`；
- `raw_acl_digest/wiki_acl_digest/acl_equivalence_digest`；
- C0 `content_hash`、`supersedes_id`、`created_at` 与 P3 admin principal
  或 P1 reconciliation job authority 的非秘密 tagged 稳定引用。

version 一经 INSERT SHALL 在 DB 层拒绝 UPDATE/DELETE；枚举外 state/reason
或不匹配组合 SHALL 拒绝。时间戳/actor metadata SHALL NOT 进入 security
`content_hash`，同一安全内容跨重试仍得同一 hash。旧 version 保留审计，
是否 current 只由 Space pointer 决定；durable idempotency 归 P2D.10 的
mutation receipt，不由 version 是否插入决定。

`knowledge_spaces` SHALL 保存
`current_binding_id + binding_epoch`。current pointer SHALL 只能指向同
Space version；`binding_epoch` SHALL 单调。只有 current version
`state=active` 才可铸造 online `KnowledgeScope`/security snapshot。legacy
`binding_status=bound`、tenant/raw/wiki mirror 或历史 active version 单独
均不构成 active authority。

#### Scenario: legacy bound 不自动获得 active

- **WHEN** migration 前存在 `binding_status=bound` 的 Space，升级后没有
  current binding pointer
- **THEN** 新生产 loader 返回 typed unavailable，provider/Candidate/
  promotion authority 均为空；migration 不猜 ACL digest 或自动建 active
  version

#### Scenario: 历史 version 不可改写

- **WHEN** 管理员 rotation 后尝试通过 service API 或 direct SQL UPDATE/
  DELETE 改写旧 binding version
- **THEN** DB/service fail closed，旧 content_hash 与字段逐字节不变

### Requirement: P2D.3 ACL canonical digest 与等价 admission

P2d SHALL 只经 P3-owned ACL-inspection authority（或经 P3 amendment
认可的 authenticated human delegation）从当前 WeKnora KB ACL 读取面获得
RAW/Wiki ACL snapshot，并经 code-owned、版本化 `AclRoleMapping` 规范化为
`AclSnapshotV1`。P2d SHALL NOT 持有自建 admin credential 或把
`source_reader/wiki_projector` 扩权。缺该 authority SHALL 产生
`verification_unavailable/acl_inspection_authority_unavailable`，不得
admit active。

snapshot SHALL 至少把 tenant、KB、ACL contract version、每个 P3 稳定
principal reference 的 kind/effective role/capability 集合纳入 C0
canonical hash；集合 SHALL 按 C0 set 语义去序去重。raw credential、
token、secret 与显示名 SHALL NOT 持久化进 binding 或日志。

`raw_acl_digest` 与 `wiki_acl_digest` SHALL 分别使用 C0 domain-separated
object type；`acl_equivalence_digest` SHALL 覆盖两个 digest、role-mapping
version/hash 与等价 verdict。只有在同 tenant、exact RAW/Wiki KB、两轮
连续读取逐字节稳定、且受支持 role mapping 下等价时，admission 才可产生
`active`。系统 SHALL NOT 用 caller ACL、旧 digest、时间戳或单次不稳定列表
补证。

ACL 不等价 SHALL 产生 `acl_mismatch`。成功认证的 inspection response 若
明确给出未知 role/响应形状/contract、API unavailable verdict，或两轮成功
读取不稳定，可在一个已授权 mutation 中产生 `verification_unavailable`。
adapter exception、timeout、未认证响应或普通 DB/API 运行时失败 SHALL typed
失败且按 P2D.13 零写，不得自动提交 current state。两种已提交的 non-active
state 都 SHALL 阻断 current online guard。

#### Scenario: 等价且稳定才 active

- **WHEN** RAW/Wiki 两轮 ACL 读取分别逐字节稳定，tenant/KB 与 P3 scope
  exact 相等，role mapping verdict 等价
- **THEN** 写入 current `active` version，三个 digest 与 mapping hash 均
  可由相同 snapshot 复算

#### Scenario: 读取间发生变化不沿用旧 digest

- **WHEN** RAW 或 Wiki ACL 在两轮 admission 读取之间变化
- **THEN** current state 为 `verification_unavailable` 或 admission
  typed 失败；不得沿用上一轮 active digest

#### Scenario: RAW/Wiki 不等价

- **WHEN** Wiki ACL 在映射后允许一个 RAW ACL 不允许的 principal/role，或
  反向不满足冻结等价规则
- **THEN** current state 为 `acl_mismatch`，online read/provider/
  Candidate/promotion 全部 fail closed

#### Scenario: 当前 P3 无 ACL inspection authority

- **WHEN** P3 public contract 仍只有 039 的 `source_reader/wiki_projector`
  能力
- **THEN** P2d admission 返回
  `verification_unavailable/acl_inspection_authority_unavailable`，不得
  创建 active binding 或用 P2d credential 补位

### Requirement: P2D.4 当前 ACL 是持续授权且窄粒度 fail closed

binding admission digest SHALL 是一致性/审计证据，不是持续用户授权。
P2d SHALL 导出唯一 `CurrentRawAclGuard`/verifier；它对每次调用同时要求：

1. P3 当前 human principal 对目标 Space 的角色允许该动作；
2. P2d current binding `active` 且 current digest reconciliation 可用；
3. 当前 WeKnora RAW KB ACL 仍允许该 principal。

P11/P9a/P9b/P13 等后续 consumer SHALL 把同一 guard 接到 managed
Wiki/API/MCP/search/cache 与 evidence original access；仅拥有更宽 Wiki KB
权限 SHALL NOT 返回标题、摘要、正文、search hit、cache 命中或历史
Release 内容。RAW 权限撤销 SHALL 使 Active 与历史 Release 立即不可读。
P2d 本身只交付 guard/verifier 与 fake-consumer contract test，SHALL NOT
实现或宣称这些 endpoint/Release read 已接线；端到端零泄漏验收归各 surface
Owner。

若 WeKnora 出现比 KB 更窄的 Source/File ACL，相关 Space binding SHALL
进入 `acl_scope_unsupported` quarantine；P2d SHALL NOT 推断逐
Claim/Evidence/Page ACL、求交集或继续发布。tenant/KB move、rebind、
当前 ACL 无法证明一致时亦 SHALL fail closed。

#### Scenario: Wiki 较宽不能绕过 RAW ACL

- **WHEN** principal 仍有 Wiki viewer 但当前 RAW KB ACL 已撤销
- **THEN** P2d `CurrentRawAclGuard` 返回 typed DENY，P2d fake consumer
  返回零 payload
- **AND** managed Wiki/API/MCP/search/cache 与历史 Release 的真实零泄漏
  场景保留给 P11/P9a/P9b/P13 各 owner 接线验收，P2d 不虚报完成

#### Scenario: Source 级 ACL 触发 quarantine

- **WHEN** ACL capability probe 发现某 Source/File visibility 窄于父 RAW
  KB
- **THEN** current binding 进入 `acl_scope_unsupported`，不得按 Space ACL
  编译/发布，也不得临场创建 per-Claim visibility label

### Requirement: P2D.5 binding 状态转换、rebind 与 epoch

binding mutation SHALL 采用 append-only transition：

```text
none → active
active/non-active → active | acl_mismatch | acl_scope_unsupported |
                    verification_unavailable | disabled
```

每个不同 canonical state/content transition SHALL 插入新 version、指向
`supersedes_id`、CAS Space current pointer 并使 `binding_epoch +1`。
current version 与新观察 content/state 完全相同时 reconciliation SHALL
no-op 且 epoch 不变。rebind 到新 tenant/RAW/Wiki SHALL 产生新 version 并
在同一事务同步 legacy mapping mirror；旧 mapping 不得继续 current。

A→B→A SHALL 产生比原 A 更大的 epoch，旧 security snapshot/Candidate
不得因 id/hash 回到相同值而复活。disable SHALL 产生 current `disabled`
version，而不是删除历史。

#### Scenario: 完全相同 reconciliation 不制造漂移

- **WHEN** current active version 与新稳定 ACL/mapping/content 逐字段相同
- **THEN** 返回 no-op，current id/hash/epoch 均不变

#### Scenario: A→B→A 关闭 ABA

- **WHEN** binding 从 A rebind 到 B 后又回到与 A 相同的 tuple/digest
- **THEN** current epoch 严格大于初始 A；冻结初始 epoch 的 Candidate exact
  recheck 失败

### Requirement: P2D.6 CompilationSecurityProfileVersion 不可变且完整

系统 SHALL 建立 Space-scoped、append-only
`CompilationSecurityProfileVersion` registry。每个 version 的 C0
canonical content 至少包含：

1. profile schema/version 与资料分类上限；
2. exact allowed `provider + model/deployment immutable identity +
   capability role + policy version` 集合，以及显式 fallback 顺序/禁用；
3. redaction/tokenization policy version/hash、所需 DLP/KMS/sanitizer/
   renderer adapter contract version/hash，以及 code-owned trusted adapter
   registry/verifier identity/hash；
4. retention、provider no-training、region/data-residency 约束；
5. allowed tools、network destinations/capabilities（默认 deny）；
6. prompt template/instruction boundary 与文档指令隔离 policy hash；
7. input/output sanitizer 与 malicious content verdict contract；
8. Markdown/HTML/URL renderer policy version/hash；
9. logging/observability policy（raw source/prompt/output/credential 默认
   禁止）；
10. secret/KMS reference contract version/hash（只存引用，不存 secret）。

version SHALL 包含 `id/space_id/content_hash/supersedes_id/created_at/
actor_principal_ref`，并在 DB 层拒绝 UPDATE/DELETE。Space SHALL 保存
`current_security_profile_id + security_profile_epoch`；pointer 只能指向
同 Space version。register+activate、rotate、deactivate 只通过 Space row
CAS 事务；deactivate 把 pointer 置 NULL 并使 epoch +1。

缺 current profile SHALL 是 absolute blocker。profile 不得用 env/default
静默补字段；外部 DLP/KMS 只通过 versioned adapter contract 复用，P2d
SHALL NOT 建设平台。安全 adapter 的可序列化 receipt/view 不构成权威；
只有 current profile 指定的 code-owned registry/verifier 验证后签发的
opaque `VerifiedSecurityAttestation` 可供 gate 使用。attestation SHALL
绑定 adapter identity/build、contract/policy version/hash、input/output
digest、Space/job/stage/attempt/generation/call-scope、issued/expiry，并
携带不可伪造的进程内 seal 或等价 cryptographic verification。caller
复制/构造/反序列化字段相同的 DTO SHALL 被拒绝。

#### Scenario: profile rotation 不改历史

- **WHEN** current profile A 旋转到 B
- **THEN** A 字段/hash 逐字节不变，current pointer=B，epoch +1；直接改写
  A 被 DB 拒绝

#### Scenario: 缺安全字段不允许激活

- **WHEN** profile 缺 allowed identity、redaction、residency、tool/network、
  renderer 或 logging 中任一必需字段
- **THEN** registry typed 拒绝，current pointer/epoch 不变

### Requirement: P2D.7 provider pre-call gate 必须重读 current authority

每次外部 provider transport dispatch 前 SHALL 经过 P2d canonical gate。
gate SHALL 自数据库读取同一 Space current active binding 与 current
profile，并经 P3-owned ACL-inspection authority 重新读取当前 RAW/Wiki ACL
与 capability freshness、重算 digest 并与 current binding exact 比较。
gate SHALL NOT 接受 caller 传入的 ACL、policy/current pointer/ALLOW receipt
作为 authority。gate input SHALL 绑定 exact：

- P3 derived Space；
- P1/P5b1 expected job facts（不是 principal），含 job id、stage、attempt、
  generation；其 authority 只来自 final P1 current active-fence verification；
- binding/profile id/hash/epoch；
- current RAW/Wiki ACL digest/freshness 与 input/content/prompt digest；
- exact provider/model/deployment/role 与 fallback position；
- data classification；
- redaction/tokenization/DLP/KMS/sanitizer/renderer 的 opaque
  `VerifiedSecurityAttestation`；
- requested tool/network/residency/retention/no-training/logging facts。

gate SHALL 先做 profile exact evaluation，再在 transport dispatch 前完成
bounded final verification bundle：

1. re-read/recheck current binding/profile；
2. re-read current WeKnora RAW/Wiki ACL digest/freshness；
3. 验证每个 opaque attestation 与 current profile/call scope exact；
4. 最后调用 P1-owned read-only active-fence verifier，以 current
   PostgreSQL row 与 DB clock 复核 Space/job/generation、`state=running`、
   exact attempt、unexpired lease；该 verifier 不得续租、推进状态、写
   Outbox 或产生其他持久副作用。

DENY、DB/ACL/P1 verifier 读取失败、non-active binding、NULL/changed
profile、current ACL digest 不等/不稳定、attestation 缺失/不匹配、
stale generation、non-running、attempt mismatch、lease expired/reclaimed
时 transport SHALL 为 0。ALLOW 只签发 package-owned、不透明、不可序列化、
短期、exact call-scope、单次消费的 authorization；可序列化 decision
receipt 只作审计，不得授予调用。receipt SHALL 记录 P1 verified
job/generation/attempt/lease-expiry 与实际 binding/profile/ACL digest，不含
payload/secret。DENY 可向调用方返回 secret-free typed decision value，但
P2d SHALL NOT 在失败路径持久化 success/deny receipt；任何持久审计投影须由
后续独立 owner 在不授予 authority 的事务中设计，不能成为本 gate 的副作用。

pre-call authorization 只有在上述四项 final bundle 全部通过后成立；P1
fence 的线性化点是最后一次 P1 DB-time verifier，profile/ACL 的线性化点是
各自最后一次 current recheck。profile rotation、ACL 撤销、lease expiry/
reclaim 若在对应线性化点前发生 SHALL 被观察并阻断；若 profile/ACL 在其
线性化点后发生，已 dispatch call 可完成，但 receipt SHALL 记录实际旧
snapshot/ACL digest，后续 Candidate/promotion exact recheck SHALL stale。
实现 SHALL NOT 为跨 provider 网络调用持有 PostgreSQL 长事务锁。

#### Scenario: 禁用 provider/fallback 零 transport

- **WHEN** call identity 或 fallback position 不在 current profile exact
  allowset
- **THEN** gate 返回带 secret-free reason 的 typed DENY decision value，
  不持久化 receipt，provider fake 调用数为 0

#### Scenario: caller 声称已脱敏或伪造 receipt 不构成 attestation

- **WHEN** caller 只提交 `redacted=true`，但没有 current profile 要求的
  adapter verifier 签发且 exact input/output/policy/call-scope 的 opaque
  attestation，或手工构造同字段 receipt/view
- **THEN** gate fail closed，transport=0

#### Scenario: rotation/ACL 撤销与 dispatch 确定性交错

- **WHEN** profile rotation 或当前 ACL 撤销在 gate final DB+WeKnora
  recheck 前发生
- **THEN** old authority 被拒且 transport=0
- **AND WHEN** 变化在 dispatch linearization 后发生
- **THEN** receipt 精确记录 old profile id/hash/epoch 与 old ACL digest，
  之后 exact Candidate verifier 拒绝该旧 snapshot

#### Scenario: lease expiry/reclaim/stale generation 零 transport

- **WHEN** gate 持有 expected generation N，但 final P1 verifier 观察到
  lease 已按 DB clock 过期、job 已被回收到 generation N+1、state 不再
  `running` 或 attempt 不等
- **THEN** gate typed DENY，ALLOW authorization/receipt 与 transport 均为
  0；caller 的旧 `ClaimedJob` snapshot 不改变结果

### Requirement: P2D.8 027 过渡 gate 无双 authority

P2d 实现 SHALL 按
`docs/insurance-kb/24-legacy-asset-disposition.md` 记录 change 027
`model_policy` source commit/path 与接受/拒绝行为：

- 接受并移植 deny-only 的 canonical identity/rolling/强模型/family/
  deployment grammar 与 sealed gate 思想；
- 拒绝硬编码 provider allowlist、进程内 policy snapshot 作为 Space current
  authority、旧 receipt/permit 作为调用授权。

P2d current CompilationSecurityProfile SHALL 成为唯一 allow authority。
基础 deny-only 规则可比 profile 更窄，profile SHALL NOT 放宽其拒绝；旧
composition root/entrypoint SHALL NOT 在 P2d cutover 后独立签发 ALLOW。
本 change SHALL NOT 物理删除 027 模块或清理历史 receipt。

#### Scenario: 旧 permit 不能绕过 current profile

- **WHEN** caller 持有 change 027 的旧 ALLOW receipt/permit view，但 Space
  current profile 已旋转或为空
- **THEN** P2d gate 拒绝，transport=0；旧值只保留审计意义

### Requirement: P2D.9 SecurityAuthoritySnapshot 与 exact consumer contract

P2d SHALL 提供只读、immutable `SecurityAuthoritySnapshot`：

```text
space_id
binding_id + binding_content_hash + binding_epoch + binding_state
security_profile_id + profile_content_hash + security_profile_epoch
snapshot_hash
```

`snapshot_hash` SHALL 用 C0 覆盖上述所有字段。snapshot 只能从当前 DB
authority 读取，且签发前 SHALL 经 P2D.3 的 P3-owned ACL-inspection
authority 重读当前 RAW/Wiki ACL/freshness，重算值必须与 current active
binding digest exact 相等；ACL 读取失败/变化/不等 SHALL 不签发 snapshot。
caller 复制/改写 DTO、legacy tuple 或独立 id/hash SHALL NOT 构成 authority。

P6b Candidate consumer contract SHALL 在 Candidate 形成事务中要求 binding
active、profile 非空、current ACL/freshness exact，并把 exact snapshot
全字段纳入 Candidate content/digest。P8 promotion consumer contract SHALL
在其 Space 串行事务内重读 current DB authority、重新验证当前 RAW/Wiki ACL/
freshness，再与 Candidate/Decision 冻结值逐字段 exact 比较。任何 ACL
不可证明/不等、binding state/id/hash/epoch 或 profile id/hash/epoch 不等
SHALL：

- 不形成 Candidate，或把已有 Candidate 标记 `stale/superseded`；
- 保留 Decision 审计但不得发布；
- 原 input batches 按 P6b/P8 owner 合同 requeue；
- 零 WikiRelease/active pointer/Outbox side effect。

P2d SHALL 只交付 snapshot/verifier contract，SHALL NOT 创建或修改
Candidate、Decision、Release、input batch 或 promotion 生产表/状态机。

#### Scenario: exact snapshot 可形成 Candidate

- **WHEN** P6b-style consumer 在同一事务读取 active binding + current
  profile，形成前 current RAW/Wiki ACL/freshness 与 binding exact 且 verifier
  仍相等
- **THEN** Candidate payload/digest 含 snapshot 所有 id/hash/epoch/state

#### Scenario: profile A→B→A 旧 Decision 不复活

- **WHEN** Candidate/Decision 冻结 profile A epoch 10，current 依次变 B
  epoch 11、A epoch 12
- **THEN** promotion exact recheck 因 epoch 不等 stale/requeue，零发布

### Requirement: P2D.10 mutation 事务、幂等与 Space 行锁

系统 SHALL 为所有成功/no-op/deactivate binding/profile mutation 写
append-only `SecurityBoundaryMutationReceipt`。receipt SHALL 至少包含：

- `space_id`；
- 封闭 `operation_kind`：
  `binding_admit | binding_reconcile | binding_rebind |
  binding_disable | profile_register_activate | profile_rotate |
  profile_deactivate`；
- `idempotency_key + C0 request_hash`；
- `authority_snapshot_hash`：admin mutation 覆盖 P3 actor stable ref、derived
  Space 与授权 action；scheduled reconciliation 覆盖 P1 verified
  Space/job/generation/attempt/operation kind。raw credential/secret 不进入
  snapshot；
- 封闭 `result_kind`：`created | changed | noop | deactivated`；
- nullable `result_current_id`、`result_epoch`、`result_snapshot_hash`、
  C0 `receipt_hash` 与 `created_at`。

`(space_id, operation_kind, idempotency_key)` SHALL 唯一，receipt SHALL 在
DB 层拒绝 UPDATE/DELETE。所有 mutation SHALL：

1. 对 admin mutation 验证 P3 actor + derived Space scope；对 scheduled
   reconciliation 经同一 P1-owned read-only active-fence verifier 验证 current
   generation/`running`/attempt/unexpired lease，且只允许 reconcile 当前
   tuple/ACL state，不得借 job 改 tuple/profile；
2. 先形成上述 secret-free C0 `authority_snapshot_hash`；再计算包含它、
   expected pointer/epoch 与完整 payload 的 C0 `request_hash`，使用数据库
   committed 值而非 ORM identity-map pending 值；
3. `SELECT ... FOR UPDATE` 同一 `knowledge_spaces` 行；
4. 若唯一 receipt 已存在：同 request hash 和同 authority snapshot 返回其
   原结果（即使 current 后来已变化），不同 request 或不同 authority
   snapshot 均 typed `idempotency_conflict`；
5. 无 receipt 时比较 caller 的 `expected_current_id + expected_epoch`；
6. INSERT immutable version（若该结果需要；no-op/profile deactivate
   可以不插 version）；
7. CAS pointer、同步 mapping mirror（仅 binding tuple 变化时）、按结果
   需要 epoch +1；
8. **总是** INSERT 成功/no-op/deactivate receipt，与 version/pointer 同一
   事务 commit/rollback。

相同 idempotency key + 相同 canonical request SHALL 从 durable receipt
返回原结果且不重复增 epoch；相同 key + 不同 request SHALL typed
`idempotency_conflict` 且零写。stale expected pointer/epoch SHALL typed
`stale_authority` 且零写；未提交失败不伪造成功 receipt。

binding 与 profile mutation 共享同一 Space row serialization boundary，
避免 lost update；不同 Space SHALL 不需要全局锁。实现 SHALL NOT 依赖
进程锁、leader 或 SQLite 锁语义。

#### Scenario: 并发双 mutation 无 lost update

- **WHEN** 一个事务 reconcile binding、另一个同时 rotate profile，二者
  针对同一 expected Space authority
- **THEN** PostgreSQL 行锁串行；两个变更要么按更新后的 expected 值显式
  重试后都保留，要么一个 typed stale，绝不互相覆盖

#### Scenario: 相同幂等键异 payload 拒绝

- **WHEN** 同一 Space/operation/idempotency_key 先后提交不同 ACL/profile
  canonical payload
- **THEN** 第二次 `idempotency_conflict`，current pointer/epoch/历史 rows
  均无额外变化

#### Scenario: no-op 与 deactivate 也可持久重放

- **WHEN** reconciliation 得到 no-op，或 profile deactivate 把 current
  pointer 置 NULL，随后以相同 key/request 重试
- **THEN** 从 immutable mutation receipt 返回原
  result_kind/current_id/epoch/snapshot，不插重复 version、不重复增 epoch

#### Scenario: 跨 actor 或 Worker 不复用幂等结果

- **WHEN** actor/Worker A 已以某 idempotency key 提交 no-op 或 deactivate，
  actor/Worker B 以相同 key 与相同业务 payload 重试
- **THEN** 因 `authority_snapshot_hash` 不同而 typed
  `idempotency_conflict`，不返回 A 的结果细节且零写

### Requirement: P2D.11 数据库强制 Space 隔离与唯一 mapping

数据库 SHALL 以 composite FK/check/unique 证明：

- current binding/profile pointer 只能指向同 `space_id` version；
- active/current mapping 的 `(tenant_id, raw_kb_id)` 与
  `(tenant_id, wiki_kb_id)` 不得被两个 Space 同时占用；
- pointer NULL/epoch shape 合法、epoch 非负；
- `supersedes_id` 只能引用同 Space 同 kind version；
- binding state/reason 组合满足 P2D.2 的封闭映射；
- immutable version 与 mutation receipt UPDATE/DELETE 被数据库拒绝。

服务层 SHALL 在任何外部 ACL/provider 调用前复核 attested Space 与 current
binding tuple exact 相等。跨 Space 请求 SHALL 返回统一 typed refusal/not
found，SHALL NOT 泄漏另一 Space 的 binding/profile/digest/state 存在性。

#### Scenario: cross-Space pointer direct SQL 也失败

- **WHEN** 尝试把 Space A current profile/binding pointer 指向 Space B
  version
- **THEN** PostgreSQL composite FK/check 拒绝，两个 Space 均保持原状态

#### Scenario: 同一 RAW/Wiki KB 不可当前复用

- **WHEN** Space B admission 试图占用 Space A 当前 mapping 的 RAW 或 Wiki
  KB
- **THEN** DB/service fail closed；不得靠不同 binding history id 绕过

### Requirement: P2D.12 唯一 migration、legacy cutover 与范围预算

P2d implementation SHALL 独占 Alembic id `0016`，恰好一个 migration
文件；在实现时从最新 main 真实 single head 接续，SHALL NOT 假设数字顺序
等于拓扑、产生 multi-head、修改历史 migration 或拆第二 migration。

migration SHALL 保留 `knowledge_spaces` 现有 tuple/unique 作为 current
mapping 兼容镜像，新增 binding/profile immutable registry、
`SecurityBoundaryMutationReceipt`、current pointers/epochs 与所需 DB
constraints/append-only guards。它 SHALL NOT
把存量 `bound` 自动 backfill 为 active，也 SHALL NOT drop 旧表/旧列或清理
历史数据。P2d service cutover 后，legacy mirror 只能在 pointer CAS 事务中
同步；所有新生产 read 使用 current binding/profile authority。

未来实现 diff SHALL ≤15 logical files，生产代码目标 500–800 行；超过约
900 行、需要第二 migration、provider SDK、principal 表、Candidate/Release
表或逐 Claim ACL 时 SHALL 停止并拆新 change。P2d 验收 SHALL 在 PostgreSQL
16 跑 migration、并发、cross-Space、immutability 与 gate/rotation 交错，
JUnit `skipped=0`；SQLite 不替代 PG16。

#### Scenario: 0016 是唯一 migration

- **WHEN** 审查未来 P2d implementation diff 与 Alembic heads
- **THEN** 只新增一个 `0016_*` 文件、历史 migration 零改、single head，
  down_revision 等于该实现分支 base 的真实 main head

#### Scenario: 超预算停止而非夹带

- **WHEN** 实现需要 >15 logical files、>~900 生产行、第二 migration 或
  任一非目标领域
- **THEN** 当前实现停止并回到边界设计/新 change，不在 P2d 临场扩面

### Requirement: P2D.13 API、principal 与 Worker 权限矩阵及失败零写

P2d public service contract SHALL 使用下列封闭操作，不得由 endpoint、
Worker 或调用方另立同义入口：

| 操作 | 唯一可接受 authority | 明确拒绝 |
|---|---|---|
| `verify_current_read_authority` | P3 `viewer | editor | reviewer | space_admin | super_admin` human principal；目标 Space 必须来自其 current derived scope，且 P2D.4 current RAW ACL guard 通过；只返回 authority verdict，不返回知识 payload | caller 自报 Space/user、任一 service principal、无当前 RAW ACL |
| `administer_binding` / `administer_security_profile` | 目标 Space 的 P3 `space_admin`，或对 exact target Space 执行显式动作的 `super_admin`；仍须 operation-specific integrity；binding 只有通过 proposed/current tuple 的 P3-owned ACL inspection 才可 active | viewer/editor/reviewer、service principal、全局/隐式 superadmin |
| `reconcile_binding` | P1 read-only fence 证明 exact Space/job 的专用 Worker operation；ACL 读取另经 P3-owned inspection authority；只可观察/记录 current tuple 与 ACL state | human request 伪装 job、任一 service principal、跨 Space job |
| `authorize_provider_call` | P1 read-only active-fence verifier 证明的 exact Worker job/call scope | human principal 直接调用、`source_reader`、`wiki_projector`、旧 receipt/permit |
| `inspect_raw_wiki_acl` | 独立 P3 amendment 定义的 least-privilege ACL-inspection authority 或等价 authenticated human delegation | P2d credential、扩权后的现有 service principal、caller ACL |

P3 可在 API adapter 中把已认证 principal 与 derived target Space 传入 P2d，
但 SHALL 在业务 handler、P2d mutation 或任何外部 ACL/provider I/O 前完成
身份与目标 Space 校验。request path/header/body 中的 Space/user/role 只可作
expected target，不可成为 authority。Worker 的 job facts 不是 principal；
P2d SHALL NOT 因 job 存在而授予 `source_reader/wiki_projector` 新能力。
初始 binding 尚不存在或 current binding 为 non-active 时，获授权管理员仍可
执行 admit/rebind/disable/profile mutation；这不放宽 online authority：
只有 P2D.3 admission 成功得到 current active binding 且 current profile
非空，read/provider/Candidate/promotion verifier 才可通过。

所有 typed 拒绝和运行时失败——包括未认证/权限不足、cross-Space、stale
pointer/epoch、idempotency conflict、ACL/profile unavailable、P1 fence
stale/expired/reclaimed、attestation 不匹配以及普通 DB/adapter error——
SHALL 在该操作上保持：

- 零 binding/profile/current pointer/epoch/mutation-receipt 写；
- 零 job/lease/outbox/domain write；
- 零 Candidate/Decision/Release/requeue side effect；
- 零 provider transport；
- 零可重放 ALLOW capability 或持久成功/拒绝 receipt。

`acl_mismatch | acl_scope_unsupported | verification_unavailable | disabled`
version 只有在一个**成功授权、显式提交**的 admit/reconcile/disable mutation
中才是可审计结果，不得把未授权请求或 adapter 异常自动提交成状态变更。
成功提交的 non-active state 不是“失败旁路”，仍须遵守 P2D.10 的 Space row
锁、expected pointer/epoch、幂等 receipt 与原子事务。

#### Scenario: API 越权在 handler 前零写

- **WHEN** caller 自报目标 Space 或角色，但 P3 current principal 不具备该
  Space 的对应操作权限
- **THEN** API adapter/P2d typed 拒绝，handler、ACL/provider adapter 未被
  调用，P2d/P1/domain/Outbox 表逐行不变

#### Scenario: Worker 授权检查不得以 heartbeat 制造写副作用

- **WHEN** Worker 请求 provider authorization，而 P1 current fence 已过期、
  被回收、generation/attempt/state 不匹配，或后续 P2d gate 拒绝
- **THEN** 只读 verifier/P2d typed 拒绝；lease expiry、job state、Outbox、
  security receipt 与 transport 均不变；不得调用 `heartbeat` 延长 lease

#### Scenario: 明确 non-active observation 与失败分离

- **WHEN** 已授权 reconciliation 对稳定 ACL snapshot 得出
  `acl_mismatch`，并以 fresh expected pointer/epoch 与 idempotency key 提交
- **THEN** 可按 P2D.10 原子写 non-active version/current pointer/receipt
- **AND WHEN** ACL adapter 抛错、权限失效或事务前置校验失败
- **THEN** 整个操作 typed 失败且零写，不把错误冒充已提交 observation

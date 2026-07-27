# 043 · Tasks（P2d Space Security Boundary）

> 当前阶段：`SPEC-ONLY / IMPLEMENTATION BLOCKED ON P3 CONTRACT +
> IMPLEMENTATION + P1 READ-ONLY FENCE`。下列 Contract Card 为冻结合同；
> “未来实施清单”不是本窗口的实现授权。

## Contract Card

### 单一职责与非目标

单一领域不变量：

> 任一在线读取、provider 调用、Candidate 形成或 promotion 只能消费同一
> Space 当前、ACL 可证明等价的 KnowledgeSpaceBinding 与当前不可变
> CompilationSecurityProfile；caller、历史快照、旧 `bound` 行或旧 profile
> 都不能放大权限。

单一交付面为 binding admission/ACL digest 状态、profile immutable
registry/current pointer、provider pre-call gate 与 exact snapshot verifier。
proposal「明确非目标」全文有效，尤其不实现 provider、逐 Claim ACL、
DLP/KMS 平台、P11、Candidate/promotion、历史清理或 Tencent 上游债务。

### 读写权威

| 概念 | 唯一权威 | 明确非权威 |
|---|---|---|
| principal/角色/服务身份 | P3 唯一铸造和 scope/capability 检查入口 | caller body/header、自报 user/space、P2d 自建 DTO/表 |
| RAW/Wiki ACL 当前事实 | WeKnora 当前 KB ACL 读取面，经 P3-owned ACL-inspection authority（待独立 amendment）认证、P2d adapter 规范化 | 发布时 ACL 快照、旧 digest、caller 列表、P2d 自建第三 service principal |
| binding 历史与当前值 | append-only `KnowledgeSpaceBinding` + `knowledge_spaces.current_binding_id/binding_epoch` | 单独的 legacy `binding_status=bound` 或 ORM identity-map pending 值 |
| security profile 历史与当前值 | append-only `CompilationSecurityProfileVersion` + Space current pointer/epoch | env allowlist、caller policy、旧 027 permit/view |
| provider allow/deny | P2d gate 对 DB current snapshot + WeKnora current ACL/freshness + P1-owned read-only active-fence verifier 的 current job/generation/running/attempt/unexpired lease + exact call facts 的决策 | constructible ClaimedJob snapshot、会续租的 heartbeat、服务 principal 权限放大、可序列化 receipt、复制 permit、缓存 ALLOW |
| Candidate/promotion 判定 | P6b/P8 各自事务消费 P2d exact verifier | P2d 写 Candidate/Release 或替消费方推进状态 |

操作权限严格采用 P2D.13 的封闭矩阵：人类读只接受 P3 current derived
Space + 对应角色 + current RAW ACL；binding/profile 管理只接受目标 Space
`space_admin` 或 exact-target 显式 `super_admin`；reconciliation/provider
authorization 只接受 P1 fenced Worker job；现有两个 service principal
不得互换能力或获得 provider/admin authority。任何拒绝/运行时失败均零
P2d/P1/domain/Outbox 写、零 transport、零可重放 authority。

### 数据与内容身份

- `KnowledgeSpaceBinding` 是 immutable version，至少冻结：
  `id/space_id/tenant_id/raw_kb_id/wiki_kb_id/state/state_reason/
  acl_contract_version/acl_role_mapping_version/acl_role_mapping_hash/
  raw_acl_digest/wiki_acl_digest/acl_equivalence_digest/content_hash/
  supersedes_id/created_at/actor_principal_ref`。
- binding state 封闭为：
  `active | acl_mismatch | acl_scope_unsupported |
  verification_unavailable | disabled`。只有 `active` 可被在线 guard 使用。
- `state_reason` 按 state 封闭为：
  `active→acl_equivalent`；
  `acl_mismatch→principal_set_mismatch | role_mapping_mismatch |
  capability_mismatch | tenant_or_kb_mismatch`；
  `acl_scope_unsupported→source_acl_narrower_than_kb |
  file_acl_narrower_than_kb`；
  `verification_unavailable→acl_api_unavailable |
  acl_snapshot_unstable | acl_contract_unknown | acl_role_unknown |
  acl_mapping_unknown | acl_inspection_authority_unavailable`；
  `disabled→administrator_disabled`。枚举外值一律拒绝。
- `CompilationSecurityProfileVersion` 是 immutable Space-scoped version，
  至少冻结 proposal/spec P2D.6 的完整安全字段、`content_hash`、
  `supersedes_id/created_at/actor_principal_ref`。
- `SecurityBoundaryMutationReceipt` 是所有成功/no-op/deactivate mutation
  的 append-only 幂等账本，至少冻结
  `space_id/operation_kind/idempotency_key/request_hash/
  authority_snapshot_hash/result_kind/result_current_id/result_epoch/
  result_snapshot_hash/receipt_hash/created_at`；
  `(space_id, operation_kind, idempotency_key)` 唯一。
- `SecurityAuthoritySnapshot` 冻结：
  `space_id + binding_id/hash/epoch/state +
  security_profile_id/hash/epoch + snapshot_hash`；hash 全部走 C0。
- ACL digest 不保存 raw secret/credential；principal 标识只使用 P3
  提供的稳定非秘密引用。未知角色、未知 ACL 形状或读不稳定一律
  `verification_unavailable`。

### 事务、幂等与并发

1. binding admit/reconcile/rebind/disable 与 profile register/rotate/
   deactivate 都在 caller-owned PostgreSQL 事务中锁同一
   `knowledge_spaces` 行。
2. mutation 接收 `expected_current_id + expected_epoch + idempotency_key`，
   先由 P3 human actor 或 P1 Worker fence 形成 secret-free
   `authority_snapshot_hash`，再把它与完整请求一起计算 C0 `request_hash`
   并读取/竞争唯一 mutation receipt。相同键+
   相同 hash 返回 receipt 冻结结果；相同键+不同 hash typed
   `idempotency_conflict`，零写。
3. 可选插入 immutable version、可选更新 current pointer、同步 legacy
   mapping mirror（若 mapping 改变）、可选 epoch `+1`，并**总是**写成功/
   no-op/deactivate mutation receipt；全部同一事务提交，失败全回滚。
4. 当前 canonical 内容与 state 完全相同时 reconciliation 为 no-op，不
   增 epoch；不同内容即使最后回到旧 id/hash，也必须新 epoch，关闭 ABA。
5. binding 与 profile 并发变更由同一 Space row lock 串行；不同 Space 可
   并行。composite FK/unique/check 在 DB 层拒绝跨 Space pointer、重复当前
   KB mapping、负 epoch 与 pointer/epoch 非法形状。
6. provider ALLOW receipt 是审计值不是幂等调用权威；每个外部 attempt
   绑定 P1/P5b1 expected
   `job/stage/attempt/generation/call-scope`，并在 dispatch 前经 P1-owned
   **read-only** active-fence verifier 用数据库时钟重验 current generation、
   `running` state、attempt 与未过期 lease。当前会续租的
   `JobStore.heartbeat` 不满足该授权合同；P1 public read-only verifier
   合入前 P2d implementation 保持 blocked。authorization 单次消费；
   constructible `ClaimedJob` 不授予权限。`source_reader/wiki_projector`
   不因 provider call 获得新能力；P2d 不承诺外部网络 exactly-once。

### 状态机

```text
无 current binding
  └─ admit（ACL 两次稳定读取且等价、KB 粒度受支持）→ active
     ├─ ACL 不等价/收窄/无法证明/disable
     │    → 新 immutable version（acl_mismatch /
     │       acl_scope_unsupported / verification_unavailable / disabled）
     ├─ rebind 成功 → 新 active version
     └─ reconcile 完全相同 → no-op（epoch 不变）

无 current profile
  └─ register + activate → profile A, epoch N
       ├─ rotate → profile B, epoch N+1
       ├─ deactivate → NULL, epoch N+1
       └─ A→B→A → epoch N+2（旧 Candidate 仍 stale）
```

任一 non-active binding 或 NULL profile 对 provider/Candidate/promotion/
在线 guard 都是 absolute blocker；不得回落 `human_batch` 后继续执行安全
敏感动作，`human_batch` 也不能绕过 ACL/security。

### 威胁矩阵

| 威胁 | 冻结处理 |
|---|---|
| RAW/Wiki ACL 不等价 | admission 拒 active，current state=`acl_mismatch`；在线 guard/provider/Candidate/promotion 全拒 |
| 权限撤销或 ACL 漂移 | current guard 使用当前 ACL；reconciliation 产生新 version/epoch；旧 Candidate exact recheck stale/requeue |
| reconciliation 前已发生 ACL 撤销 | provider final gate 重新读取 RAW/Wiki current ACL/freshness 并与 binding digest exact 比较；不等/不可读则 transport=0 |
| Source/File 出现窄于 KB 的 ACL | `acl_scope_unsupported` quarantine；不猜交集、不发布 |
| ACL API 不可达、列表不稳定、未知角色 | `verification_unavailable`；不沿用旧 digest |
| caller 自报 Space/user/角色或伪造 principal | 只接受 P3 opaque/typed principal 与 derived scope；进入 handler 前拒绝 |
| API/Worker 拒绝路径产生副作用 | P2D.13 要求在 handler/adapter I/O 前校验；失败零 P2d/P1/domain/Outbox 写、零 transport、零持久 receipt/capability |
| 服务 principal 权限互换 | `source_reader` 只读绑定 RAW，`wiki_projector` 只投影绑定 Wiki；不得获得人类/superadmin 能力 |
| 当前 P3 无两端 ACL inspection authority | P2d implementation 保持 blocked；单独 amendment 归 P3，P2d 不新增第三 principal/capability |
| 当前 P1 只有会续租的 heartbeat | P2d implementation 保持 blocked；先由 P1 提供 read-only DB-clock active-fence verifier，P2d 不直读/改写 jobs |
| 跨 Space pointer/KB/call replay | composite FK + current mapping unique + attested scope + snapshot/call-scope hash；零数据/零 transport |
| profile 原地改写/删除 | append-only table DB guard 拒 UPDATE/DELETE；rotation 只 CAS pointer/epoch |
| A→B→A ABA | binding/profile epoch 单调进入 snapshot/Candidate digest/promotion recheck |
| 禁用 provider/fallback 或 rolling/未知 identity | exact profile allowset + deny-only identity grammar；未列 fallback 默认拒绝，transport=0 |
| PII 未脱敏、DLP/KMS adapter 无可信 attestation/不可用 | gate 只接受 code-owned registry/verifier 签发、绑定 input/output/policy/call-scope 的 opaque `VerifiedSecurityAttestation`；caller DTO/view 无权威 |
| residency/retention/no-training/tools/network 不满足 | gate typed DENY；不以环境默认或 provider 宣称补齐 |
| prompt injection/恶意 HTML/Markdown/URL/日志原文或 credential | profile 冻结隔离、sanitizer/renderer/log policy version/hash；缺失或不匹配零 transport |
| gate 后 profile/ACL 并发变化 | transport dispatch 前最后 DB+WeKnora ACL/freshness recheck 为线性化点；先发生变化必须拒绝，后发生则 receipt 记录旧 authority 且后续 Candidate stale |
| 旧 worker lease 过期/被回收/代际落后仍尝试 provider | final gate 调 P1-owned read-only active-fence verifier；stale generation、非 running、attempt 不等、DB-clock lease expired/unavailable 一律 transport=0 |
| 重复 mutation/重复 ALLOW | durable mutation receipt 对 no-op/deactivate 也冻结 request/result；ALLOW capability 单次、短期、不可序列化，receipt 不授予调用权 |
| legacy `binding_status=bound` 自动升级 | migration/current loader 均拒；必须显式 live admission，零猜测 backfill |

### exact 验收测试清单

1. C0 vectors：binding/profile/snapshot/gate decision 同输入同 hash，任一
   Space/KB/ACL/mapping/profile/call-scope 字节变化改变 hash；
2. migration `0016` fresh upgrade/downgrade、单 head、两 immutable
   registry + 一 immutable mutation-receipt 表、两 current
   pointer/epoch、composite FK/check/unique/append-only DB guard 精确；
   历史 migration 零修改；
3. pre-existing `bound` 行升级后 current binding/profile 均空，新生产
   loader/provider 全 fail closed，不伪造 active/profile；
4. admission 两轮 RAW/Wiki ACL 快照相同且等价 → active；digest 不等价、
   第二轮变化、未知 role/API failure 分别进入 exact typed state；
5. 更窄 Source/File ACL → `acl_scope_unsupported`，零 provider/Candidate
   authority；
6. current ACL 撤销：P2d exported `CurrentRawAclGuard` 立即返回 typed
   DENY，fake consumer 零 payload；reconciliation 后 pointer/epoch 更新，
   旧 snapshot exact verifier 拒绝。P11/P9a/P9b/P13 的真实 managed
   GET/search/cache/API/MCP/历史 Release 接线与端到端零泄漏由各 owner
   后续验收，P2d 不宣称已完成；
7. profile register/rotate/deactivate、direct UPDATE/DELETE 拒绝、
   A→B→A epoch 前进、旧 profile 可审计不可再成为 current authority；
8. provider gate fake transport：每项 profile 字段 exact allow；P1 current
   fence 的 Space/job/generation/running/attempt/lease exact；未知/
   disabled provider/model/deployment/fallback、未脱敏 PII、缺可信
   DLP/KMS attestation、residency/retention/tool/network/log/renderer
   不满足，current RAW/Wiki ACL/freshness 与 binding 不等，或 P1 fence
   unavailable/stale/expired/reclaimed，均 typed DENY 且 transport 0；
9. gate 不能接受 caller policy/permit/view/`redacted=true` 或伪造
   attestation DTO；只有 code-owned verifier 签发且 exact
   input/output/policy/call-scope 的 opaque attestation 可用；receipt
   secret-free，复制/反序列化不能调用 transport；
10. Candidate snapshot 合同：P6b-style consumer 只有 exact
    id/hash/epoch/state/current profile 才可形成；任一变化拒绝形成或
    stale/requeue；
11. promotion snapshot 合同：P8-style consumer 在 Space 串行事务内 exact
    recheck；ACL/profile/binding/epoch 任一不等，零 Release/pointer/Outbox；
12. PostgreSQL 16 并发：包括 no-op/deactivate 在内的同键同 payload 从
    durable receipt 重放单结果；同键异 payload 冲突；双 admission、
    admit-vs-rebind、binding-vs-profile rotation 受同 Space 行锁/CAS
    收敛，无 lost update；
13. PostgreSQL 16 双 Space：各自并行成功；cross-Space binding/profile
    pointer、RAW/Wiki KB 重用、principal scope replay 由 DB/服务双层拒绝；
14. provider gate/rotation/ACL/P1 fence 确定性交错：rotation、ACL 撤销、
    lease expiry、generation reclaim 或 state/attempt 变化先于对应 final
    recheck → transport 0；profile/ACL 变化后于 dispatch linearization →
    receipt 精确记录旧 snapshot/ACL digest，随后 Candidate exact verifier
    stale；
15. P3 ownership guard：P2d diff 无 role/principal enum、principal table、
    auth provider；只 import/consume P3 public contract。
16. API/principal/Worker 权限矩阵：五类操作逐项覆盖 allow/deny；越权、
    cross-Space、stale/expired/reclaimed、ACL/profile/adapter/DB failure
    均断言 P2d/P1/domain/Outbox 全表零写、transport=0、零持久 receipt/
    capability；成功授权的 non-active reconciliation 单独证明原子提交；
    no-op/deactivate receipt 绑定 exact actor/Worker authority，跨 authority
    相同 idempotency key typed conflict。

验收 2/12/13/14 必须走 PostgreSQL 16，JUnit `skipped=0`；SQLite 不得替代。
本 spec-only 窗口不运行 PG、feature/full/provider/live lane。

### 路径与 migration 预算

- future implementation logical files ≤15（含 migration、测试与实现期文档
  回写）；
- 生产代码目标 500–800 行，约 900 行为硬警报线；超过即停止并拆 change；
- migration id `0016` 只归 P2d，恰好一个文件；实现时从 main 真实 single
  head 接续，禁止 multi-head、第二 migration 与历史 migration 修改；
- 允许面：`harness/src/insurance_harness/db/{models,scope}.py`、新小型
  `security_boundary/`、`harness/migrations/versions/0016_*`、≤4 个 focused
  tests、OpenSpec 043/必要 HANDOFF 回写；
- 禁止面：provider SDK、WeKnora Go/Vue、Candidate/Release/Review 表、
  principal/auth 实现、DLP/KMS 平台、历史 cleanup。

## 当前 spec-only 清单

- [x] S1 从 exact `origin/main=40f3ae9e4b41fab51566c438da08c57d80e3089b`
  建独立 worktree，先占 OpenSpec 043，再开目录；
- [x] S2 占 migration id 0016（只占号，零 migration 文件）；
- [x] S3 冻结 proposal、Contract Card、验收 spec 与未来实施 plan；
- [x] S4 双独立 Spec/Plan review，C/I/M findings 闭环；
- [x] S5 strict OpenSpec + diff/scope/private/secret/UTF-8/LF 门禁；
- [x] S6 冻结 local candidate tree，validation report 与交接证据。

## 未来实施清单（全部 BLOCKED ON P3 + P1 READ-ONLY FENCE）

- [ ] I0 P3 ACL-inspection authority amendment、P3 实现及 P1-owned
  read-only active-fence verifier 均已合入 main，且新 Mission Card 明确
  放行；否则立即停止；
- [ ] I1 按 TDD 先落 migration/schema/legacy fail-closed RED，再实现唯一
  migration 0016；
- [ ] I2 先落 binding admission/reconciliation/ACL state/并发 RED，再实现
  append-only registry 与 current pointer；
- [ ] I3 先落 profile immutability/rotation/ABA RED，再实现 registry/current
  pointer；
- [ ] I4 先落 provider pre-call gate 零 transport RED，再按 provenance
  移植 027 deny-only 内核并关闭旧独立 allow path；
- [ ] I5 先落 SecurityAuthoritySnapshot 与 P6b/P8 consumer-contract RED，
  只实现 verifier，不实现 Candidate/promotion；
- [ ] I6 focused/Ruff/mypy/strict OpenSpec + PG16 acceptance（skipped=0）；
- [ ] I7 按高风险 P2d 执行双独立 Spec/Quality/Security 复审；超过预算或
  出现第二领域不变量即停止重切。

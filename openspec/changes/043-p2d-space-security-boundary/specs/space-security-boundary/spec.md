# 043 P2d Space Boundary Foundation

> 本 change 为 spec-only。它只冻结 Space、RAW/Wiki ACL 与 current binding 的
> 基础边界，不表示实现依赖已满足。

## ADDED Requirements

### Requirement: P2D.1 P3 是 principal 与 Space scope 的唯一 Owner

P2d SHALL 只消费 P3 public contract 中铸造的 human principal、五个人类角色
`viewer | editor | reviewer | space_admin | super_admin` 和 derived target
Space。P2d SHALL NOT 复制 principal/角色枚举、建立 credential 表，或采信
caller 在 path/header/body 中自报的 `space_id/user_id/role`。

对 binding 执行 admit/reconcile/rebind/disable 的 human authority SHALL 是
目标 Space 的 `space_admin`，或对 exact target Space 执行显式动作的
`super_admin`。`super_admin` 仍不能绕过 ACL、tenant/KB identity、integrity
或 CAS。

P2d 需要读取 RAW/Wiki 两端 ACL 时，SHALL 只使用经独立 P3 amendment 批准并
合入的 least-privilege ACL inspection authority，或 amendment 明确允许的
authenticated human delegation。P2d SHALL NOT 扩权 `source_reader` /
`wiki_projector`、发明第三个 service principal，或持有自建 admin credential。
该 P3 authority 未合入时，P2d implementation SHALL 保持 blocked。

#### Scenario: caller 自报身份不产生权限

- **WHEN** caller 声明另一个 Space/user/role，而 P3 principal 的 current
  derived scope 不允许该操作
- **THEN** P2d 在读取 binding 或外部 ACL 前 typed 拒绝，零写、零 transport

#### Scenario: ACL inspection 依赖未满足

- **WHEN** main 中仍没有经批准的 P3-owned ACL inspection authority
- **THEN** P2d implementation 保持 blocked，不用 fake principal、P2d
  credential 或扩权后的既有 service principal 补位

### Requirement: P2D.2 binding version 与 current epoch 是 Space 权威

每次有效 admit/reconcile/rebind/disable SHALL 产生一个 Space-scoped、
append-only `KnowledgeSpaceBindingVersion`。version 至少冻结：

- `id/space_id/tenant_id/raw_kb_id/wiki_kb_id`；
- 封闭 `state`：
  `active | acl_mismatch | acl_scope_unsupported |
  verification_unavailable | disabled`；
- 与 state 匹配的封闭 reason；
- `acl_contract_version` 与 role-mapping version/hash；
- RAW/Wiki ACL digest 与 equivalence digest；
- C0 `content_hash`、`supersedes_id`、actor reference 和 created timestamp。

version 一经 INSERT SHALL 在数据库拒绝 UPDATE/DELETE。timestamp 与显示用途的
actor metadata SHALL NOT 进入 security `content_hash`。同一 canonical 内容
重试必须得到同一 hash。

Space SHALL 只以 `current_binding_id + binding_epoch` 表示 current binding。
pointer 只能指向同 Space version；每次不同内容的成功切换使 epoch 单调递增。
只有 current version `state=active` 才可授予 online authority。legacy
`binding_status=bound`、tenant/raw/wiki mirror 或历史 active version 单独均不
构成 current authority。

#### Scenario: legacy bound 不自动 active

- **WHEN** migration 前 Space 只有 `binding_status=bound`，没有可证明的 ACL
  equivalence
- **THEN** migration 不猜 digest、不自动创建 active version，current loader
  返回 typed unavailable

#### Scenario: 历史 version 不可改写

- **WHEN** service 或 direct SQL 尝试 UPDATE/DELETE 一个既有 binding version
- **THEN** 数据库 fail closed，历史字段与 content hash 保持不变

#### Scenario: A→B→A 关闭 ABA

- **WHEN** current binding 从 A 切到 B 后又回到与 A 相同的 canonical 内容
- **THEN** 新 current epoch 严格大于初始 A，冻结旧 epoch 的 authority 失效

### Requirement: P2D.3 ACL 等价 admission 与 reconciliation

P2d SHALL 通过 P3-owned inspection authority 对 exact tenant、RAW KB、Wiki
KB 读取 ACL snapshot。snapshot SHALL 使用版本化 role mapping，包含稳定
principal reference、effective role/capability 与 ACL contract identity，并按
C0 canonical set 语义生成 domain-separated SHA-256 digest；credential、
token、secret 和显示名不得进入 snapshot、binding 或日志。

一次 active admission/reconciliation SHALL 要求：

1. P3 derived Space 与 proposed/current binding 的 Space exact 相同；
2. tenant、RAW KB、Wiki KB identity exact 相同且属于该 binding；
3. RAW/Wiki ACL 各自两次读取稳定；
4. role mapping 支持全部返回值；
5. mapping 后 RAW/Wiki effective principal set 与 capability 等价。

ACL 不等价 SHALL 形成 `acl_mismatch`。Source/File ACL 比 KB 更窄 SHALL 形成
`acl_scope_unsupported`。已认证且形状受支持的 observation 明确显示 contract
未知、role 未知或两次读取不稳定时，可由已授权 mutation 形成
`verification_unavailable`。adapter exception、timeout、未认证响应或普通
DB/API 失败不是可提交 observation，必须按 P2D.6 零写失败。

current binding digest 是 admission 证据，不是永久授权。P2d SHALL 导出一个
read-only current guard：每次读 authority 判断同时要求 P3 current human
principal 对 exact Space 有允许角色、current binding active、当前 RAW ACL
仍允许该 principal。P2d 只交付 guard 与 fake-consumer contract tests；真实
Query/Wiki/MCP/search/cache 接线归各 surface Owner。

#### Scenario: 等价且稳定才 active

- **WHEN** exact RAW/Wiki ACL 两轮读取稳定、identity 相符且 mapping 后等价
- **THEN** admit/reconcile 可提交 current active version，digest 可由相同
  snapshot 复算

#### Scenario: ACL 不等价或读取不稳定

- **WHEN** RAW/Wiki principal/role/capability 不等价，或两次读取不同
- **THEN** 不得形成 active；只在已授权、显式 mutation 中提交对应 non-active
  observation，否则 typed 失败且零写

#### Scenario: 当前 RAW 权限撤销

- **WHEN** binding 仍 active，但 principal 已从当前 RAW ACL 撤销
- **THEN** current guard typed DENY，fake consumer 返回零 payload；历史
  admission digest 不可替代当前 ACL

### Requirement: P2D.4 mutation 原子且 Space 隔离

每个 binding mutation SHALL 绑定 exact：

`operation + space_id + actor_principal_ref +
expected_current_binding_id + expected_binding_epoch`。

mutation SHALL 在同一 PostgreSQL 事务内：

1. 锁定 exact Space row；
2. 重验 P3 principal 对该 Space 的 current authority；
3. 重验 expected pointer/epoch；
4. 取得并验证稳定 ACL observation；
5. 必要时插入 immutable version；
6. CAS 更新 current pointer 与 epoch。

不同 actor、stale pointer/epoch 或 cross-Space object SHALL typed 拒绝。相同
canonical current state 的 reconciliation SHALL no-op，pointer/hash/epoch
不变。

数据库 SHALL 以 composite key/FK/unique constraint 保证：

- current pointer 与 version 同 Space；
- RAW/Wiki current mapping 不被两个 Space 复用；
- supersedes chain 不跨 Space。

#### Scenario: 并发 mutation 无 lost update

- **WHEN** 两个事务以同一 expected pointer/epoch 对同一 Space 提交不同 ACL
  observation
- **THEN** 至多一个推进 current pointer/epoch；loser fresh 读取后 typed stale，
  不覆盖 winner

#### Scenario: cross-Space reference fail closed

- **WHEN** request、ACL observation、supersedes id 或 current pointer 任一属于
 另一个 Space
- **THEN** service 与数据库均拒绝，两个 Space 的 version/pointer/epoch 不变

#### Scenario: 相同 observation 不制造版本

- **WHEN** reconciliation 观察到与 current 完全相同的 canonical state
- **THEN** 返回 no-op，version 数与 epoch 不增加

### Requirement: P2D.5 binding 状态转换受限

binding current state SHALL 只允许：

```text
none → active | acl_mismatch | acl_scope_unsupported |
       verification_unavailable | disabled
current → active | acl_mismatch | acl_scope_unsupported |
          verification_unavailable | disabled
```

每个不同 canonical state/content transition 插入新 version 并指向
`supersedes_id`。rebind 到新 tenant/RAW/Wiki 必须形成新 version；旧 mapping
不得继续 current。disable 产生 current `disabled` version，不删除历史。

只有成功授权且 observation 可证明的 mutation 可提交 non-active state。
未认证请求、ACL adapter 异常或事务前置失败不得被伪装成
`verification_unavailable`。

#### Scenario: disable 保留历史

- **WHEN** 授权管理员 disable current binding
- **THEN** 新增 disabled version 并推进 epoch；旧 version 不变，online guard
  fail closed

#### Scenario: adapter 错误不是状态转换

- **WHEN** ACL adapter 抛出 timeout、认证或普通运行时错误
- **THEN** operation typed 失败，current pointer/epoch 与 version 数不变

### Requirement: P2D.6 所有失败路径零写

系统 SHALL 确保未认证、权限不足、cross-Space、stale pointer/epoch、
ACL authority unavailable、ACL response 未认证、adapter/DB error、约束失败和
未知状态 SHALL 在该操作上保持：

- 零 binding version、current pointer、epoch 写；
- 零 P1 job/lease/outbox/domain write；
- 零 Candidate/Decision/Release/requeue side effect；
- 零 provider/model/WeKnora mutation transport；
- 零可重放 ALLOW capability。

API adapter SHALL 在业务 handler、binding mutation 与外部 ACL I/O 前先完成
principal/target Space 校验。实现 SHALL 不捕获或改写
`KeyboardInterrupt/SystemExit/MemoryError`。

#### Scenario: API 越权在 handler 前零写

- **WHEN** caller 不具备目标 Space 的管理权限
- **THEN** API/P2d typed 拒绝，ACL adapter 未调用，P2d/P1/domain/Outbox 表
  逐行不变

#### Scenario: ACL 读取后 DB 失败整笔回滚

- **WHEN** 已授权 mutation 完成稳定 ACL observation，但 version/pointer
  事务任一步失败
- **THEN** 整个事务回滚，旧 current 保持，外部 mutation transport 为零

### Requirement: P2D.7 范围与依赖保持最小

本 change 的未来实现 SHALL 最多新增一个 migration，并 SHALL NOT 实现：

- CompilationSecurityProfile、provider gate、P1 active-fence verifier；
- DLP/KMS/residency/renderer/logging/attestation；
- Candidate/Decision/promotion snapshot、Release 或 Query；
- 通用 ACL 平台、逐 Claim ACL、P3/P1 实现或真实 WeKnora patch。

实现前 SHALL 从当时 main 读取实际 Alembic head；不得假设 `0016` 的
`down_revision`。未来实现目标不超过 12 logical paths；需要第二 migration、
第 13 路径或上述后续领域时 SHALL 停止并另立 Mission Card。

#### Scenario: 依赖满足后仍不夹带后续领域

- **WHEN** P3 principal implementation 与 ACL inspection authority 已合入
- **THEN** 只解除 Space binding foundation 的实现阻断，不授权 provider、
  security profile、Candidate/promotion 或 P1 fence 工作

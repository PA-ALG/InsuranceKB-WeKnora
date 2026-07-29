# WeKnora Release capability falsification Specification

## ADDED Requirements

### Requirement: R0.1 能力矩阵必须基于当前 adopted fork

系统 SHALL 以当前 project identity、`80a5003` ancestry、exact source/API/
migration/test 证据将 Release 能力分类为
`PRESENT|PATCHABLE|ABSENT|UNKNOWN`。单页 revision/history/revert 或单页
optimistic version SHALL NOT 被分类为整版 manifest、Active Head/CAS 或 pinned
read。

#### Scenario: 单页能力被误写为整版能力

- **WHEN** 证据只证明一个 `wiki_pages` row 的 version、history 或 revert
- **THEN** 整版 manifest、集合级原子激活与 release-aware read 仍不得标为
  `PRESENT`

### Requirement: R0.2 S0-R 必须是两工作日二元证伪

S0-R SHALL 从输入身份、专用环境与用户批准 Mission Card 全部就绪后计时，最多
两个工作日。终态只能是 `RELEASE_PATH_FEASIBLE` 或
`RELEASE_PATH_NOT_FEASIBLE`。需要超出 exact path、表/索引、migration、read
surface、升级责任或命令预算时 SHALL 立即选择 NOT_FEASIBLE，不得扩面或延期。

#### Scenario: 第三条实现路线出现

- **WHEN** Owner 需要 Mission Card 之外的生产路径、第二个 migration 或通用
  index/recovery 平台
- **THEN** 本轮停止并输出 NOT_FEASIBLE，不把新路线追加进两日窗口

### Requirement: R0.3 唯一 fixture 必须证明集合级原子性

S0-R SHALL 使用 R0(A/B/C) 与 R1(A 更新/B 删除/C 不变/D 新增)，并从同一 R0
base 创建两个不同 Candidate。R1 SHALL 经过目标 preparation/index/CAS/receipt
路径；同 base 只有一个 Candidate 可激活。

#### Scenario: 读取不能混版

- **WHEN** current 或 pinned read 与 R1 激活并发
- **THEN** 一次请求的 page、payload 与 minimal search 只可全部属于 R0 或全部
  属于 R1，不得出现 A′+B、缺 C 或其他成员混合

#### Scenario: 同 base 双 Candidate

- **WHEN** 两个不同 Candidate 使用同一 expected release/epoch 并发 activate
- **THEN** 只有一个更新 Head，另一个 typed conflict 且 release/head/receipt
  零半写

### Requirement: R0.4 暂定授权必须闭合解析并绑定 exact scope

实验 `PublishAuthorizationV0` SHALL 只包含 Mission Card 冻结字段。签名字节
SHALL 是移除 signature 后的 canonical JSON：字段字典序、无多余空白、整数
十进制、字符串 NFC，并拒绝重复 key、浮点和未知字段。

Activate SHALL 依次执行：闭合解析/canonical digest；exact receipt 幂等查询；
验签；action/scope/expiry；Ready preparation/digests；当前 Space、单值 RAW/Wiki
binding 与双 KB ACL；expected release/epoch；最后在一个事务中写 immutable
release/members、CAS Head、消费 nonce 与 receipt。

#### Scenario: 成功响应丢失后授权已过期

- **WHEN** exact 请求已经提交成功但响应丢失，调用者在 expiry 后重试
- **THEN** 系统先按 exact digest 返回原 receipt，不把已成功动作改报为过期

#### Scenario: 任一绑定漂移

- **WHEN** candidate、manifest、ready receipt、review、policy、Space、RAW/Wiki
  KB、head/epoch、nonce 或 signer 任一不匹配
- **THEN** activate typed fail closed，且所有 Release 表与普通 Wiki 页面零写

### Requirement: R0.5 managed write 与当前 ACL 必须 fail closed

release-managed Wiki KB 的普通 Wiki PUT/DELETE SHALL 被拒绝。current、pinned
与 minimal search 每次 SHALL 校验当前 Space、RAW KB 与 Wiki KB ACL，不得把
发布时权限永久化。

#### Scenario: 两 principal ACL shrink

- **WHEN** 两个 principal 起初可读取同一 pinned release，随后从当前 RAW/Wiki
  ACL 移除其中一个
- **THEN** 被移除 principal 的 current、pinned page/payload 与 minimal search
  全部拒绝且零写；保留 principal 继续读取完整同一 release

### Requirement: R0.6 四个故障点不得产生半激活

S0-R SHALL 仅在 preparation、index、CAS、receipt 边界各注入一次有界失败。
激活前失败不得改变 current Head；CAS 后的 nonce、receipt 与 Head SHALL 同事务，
不存在 Head 已切换但 receipt/nonce 未提交的可见状态。

#### Scenario: 四类失败恢复

- **WHEN** 任一规定故障点触发
- **THEN** 读取仍完整看到原 release，或在事务已成功时通过 exact retry 得到同一
  receipt；不得要求人工修数据库或运行通用 reconciliation 平台

### Requirement: R0.7 S0-R 不得形成第二个 serving Head

S0-R SHALL 允许 Harness 只提供 Candidate、ReviewDecision 与
PublishAuthorization fixture。Harness SHALL NOT 保存可独立决定 serving 版本的
Active Head；正式实验 read 的 current identity SHALL 只来自 WeKnora scope
Head。

#### Scenario: Harness 有命令记录但 WeKnora CAS 未成功

- **WHEN** Harness 已记录发送命令而 WeKnora Head 未 CAS
- **THEN** current read 保持旧 release，Harness 记录没有 serving authority

### Requirement: R0.8 跟版责任必须有界

S0-R 的 project patch SHALL 登记到现有 patch inventory，使用 enterprise
migration source/ledger，并继续以 target manifest、standard Git merge 与
targeted gates升级。official migration SHALL 保持 byte-exact。

#### Scenario: 新 upstream 触碰 patch surface

- **WHEN** 后续 approved target 修改任一登记路径
- **THEN** thin check 产生人工 review 输入并重跑 S0-R targeted vectors；不得
  自动 keep-ours/theirs，也不得建立 patch DSL

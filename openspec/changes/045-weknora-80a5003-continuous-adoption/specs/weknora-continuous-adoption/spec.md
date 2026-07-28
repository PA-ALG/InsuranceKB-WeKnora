# 045 WeKnora Immutable Upstream Thin Adoption Specification

## ADDED Requirements

### Requirement: U1.1 Manifest 是 upstream identity 的唯一批准输入

系统 SHALL 从 tracked target manifest 读取 repository、commit、tree、release
ancestor、required capability ancestors 与 official migration head。当前
manifest 的数据是 commit
`80a5003cc99a427098afe184eee6601916d3d156`、tree
`18fcf68e7a008ce69929e32233f0b6914040c223` 和 release ancestor
`v0.7.1@c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`；通用检查、merge 与 workflow
SHALL NOT 硬编码这些值。

`discover latest-stable` 与 `discover mainline-head` SHALL 只输出 resolved
immutable proposal，SHALL NOT 修改 manifest、checkout、runtime lock 或
workflow。未来 target SHALL 通过批准的新 manifest 进入相同轨道。

#### Scenario: mutable main 已前进

- **WHEN** Tencent `main` 越过当前 manifest commit
- **THEN** 当前采用仍使用 manifest 的 exact commit/tree，discover 只能提出
  新 immutable proposal，不静默改变 target

#### Scenario: 后续升级

- **WHEN** 用户批准新的 stable 或 mainline snapshot manifest
- **THEN** 同一 check/merge/migration/gate 流程读取新数据运行，不需要修改
  通用代码中的 target 常量

### Requirement: U1.2 Harness plugin contract 保持公开且不提权

系统 SHALL 保留 machine-readable Harness plugin contract，冻结 versioned
public REST、principal、authoritative Space binding、tenant/RAW-KB ACL、allowed
reads、denied mutations、zero-write、response/error envelope、retry、timeout、
idempotency、readiness 与 validation nodes。shared DB、Redis、Asynq、internal
queue 或私有 Go symbol SHALL NOT 成为 Harness compatibility authority。

Task 1B 中 W1 runtime、consumer adapted、source-reader authority 与 Artifact
states SHALL 全部为 false。`source_reader` authority SHALL 保持 blocked；
planned code/Artifact node SHALL 如实保持 planned，直到后续真实测试或 Artifact
证据落地。P4a/P4c SHALL NOT 因 upstream adoption 被声明 ready。

普通 Wiki 单页 history、diff、manual edit、optimistic locking 与 revert SHALL
作为产品验收，不得加入 Harness W1 endpoint/authority 合同。

#### Scenario: W1 runtime 可运行但 Harness 未适配

- **WHEN** W1 route tests 通过，但 consumer、source-reader authority 或 P4a/P4c
  尚未交付
- **THEN** 对应 contract state 保持 false，系统不得扩大 `source_reader` 权限

#### Scenario: upstream 产品功能通过

- **WHEN** Wiki history/diff/edit/revert 产品验收通过
- **THEN** 该证据只闭合产品 gate，不新增 Harness W1 endpoint 或 mutation 权限

### Requirement: U1.3 有限 check 必须在所有解析成功后给出封闭 verdict

系统 SHALL 提供有限 `check`（可作为 prepare CLI 子命令）。它 SHALL 在当前
project、manifest target checkout、runtime lock、W1 path inventory、official
migrations 与 plugin contract 范围内运行，SHALL NOT 支持 arbitrary repository
或 arbitrary patch。

target checkout SHALL clean，且 HEAD、tree、origin、release ancestor 与 required
capability ancestors 均与 manifest 一致。runtime lock SHALL 只作为 deployed
baseline 读取，SHALL NOT 作为 project↔target merge-base。

check SHALL 在所有 closed schema/type/ACL/path::node 解析成功后输出 deterministic
JSON。verdict SHALL 只有 `pass`、`manual_review_required`、`block`。

#### Scenario: target identity 不可证明

- **WHEN** checkout dirty、HEAD/tree/origin 漂移或任一 ancestor 不是 target
  ancestor
- **THEN** verdict 为 `block`，且不继续 merge、migration 或 Artifact

#### Scenario: runtime lock 与 project merge-base 不同

- **WHEN** runtime baseline 落后于 project source
- **THEN** check 分别使用真实 project merge-base 与 runtime lock，不能用
  runtime lock 替代 source merge-base

### Requirement: U1.4 Check 必须输出两组 registered W1 path overlap

check SHALL 使用标准 Git 计算并排序：

1. true project merge-base→target 的 changed paths；
2. runtime→target 的 changed paths。

两组 changed paths SHALL 分别与 registered W1 path inventory 求交集。任一
registered overlap SHALL 产生 `manual_review_required`，而不是自动 conflict
resolution。identity、migration 或 plugin hard failure SHALL 始终产生 `block`。

check SHALL NOT 解析 Go/SQL 业务语义、生成 patch、给出自动 keep-ours/theirs
裁决或演化成通用 collision engine。

#### Scenario: project delta 命中 W1 路径

- **WHEN** merge-base→target changed paths 命中一个 registered W1 path，且所有
  hard checks 通过
- **THEN** deterministic JSON 列出该 path，verdict 为
  `manual_review_required`

#### Scenario: 两组 delta 都无 overlap

- **WHEN** hard checks 通过，且 project 与 runtime 两组 registered overlap 都为空
- **THEN** verdict 为 `pass`

### Requirement: U1.5 Check 输出必须简短、确定且不含敏感数据

check JSON SHALL 使用固定 schema/key/list order、UTF-8、无时间戳输出，并只记录
target identity、hard-check 状态、两组 overlap、official migration
filename/head/SHA256、plugin digest 与 node counts。相同 semantic input SHALL
产生 byte-identical output。

输出 SHALL NOT 包含绝对路径、文件内容、环境变量、token、DSN、cookie 或
credential。check SHALL NOT 创建 tracked
`deploy/upstream/weknora-adoption-report.json` 或 receipt。

#### Scenario: mapping 格式变化

- **WHEN** 输入 YAML 只改变 comment、空白或 mapping 顺序
- **THEN** check 输出与 verdict 不变

#### Scenario: 输出可能包含 secret

- **WHEN**底层 Git、YAML 或 checksum 操作失败
- **THEN**错误使用封闭代码/摘要表达，不回显输入值、绝对路径或环境内容

### Requirement: U1.6 Official migrations 必须 byte-exact，enterprise 必须独立

official `migrations/versioned` SHALL 以 target Git tree 为 byte authority。
check SHALL 验证规范 filename、唯一连续版本、manifest official head 与每个文件
SHA256。target 尚不是 project HEAD ancestor 的合流前 check 只验证 target
official chain，并明确报告 `pre_merge`；target 成为 project HEAD ancestor 后，
check SHALL 要求 project official files 与 target byte-exact。项目 SHALL NOT
修改 official SQL 或添加 project-owned official-chain migration。

enterprise migrations SHALL 位于独立 source，并使用
`enterprise_schema_migrations` ledger，在 official
`schema_migrations` 完成后运行。045 SHALL NOT 生成 enterprise schema object
inventory，SHALL NOT 使用 generic SQL DDL parser 或 schema semantic collision
engine。

#### Scenario: official checksum 漂移

- **WHEN** filename/head 正确但任一 project official migration bytes 与 target
  不同
- **THEN** check verdict 为 `block`

#### Scenario: upstream head 增长

- **WHEN** 后续 manifest 指向更高 official migration head
- **THEN** official chain 按新 target byte-exact 更新，enterprise source/ledger
  保持独立，不复用 official version

### Requirement: U1.7 Legacy W1 000066 必须无损桥接

系统 SHALL 在普通 PostgreSQL migration 前用 raw SQL 只读分类
`schema_migrations` version/dirty、legacy W1 `000066` byte/checksum fixture、W1
fingerprint、official `000066` span expansion 与 enterprise ledger。已知 legacy
状态 SHALL 在 transaction/advisory lock 下重验并幂等收敛到 official+
enterprise 双 ledger。

unknown、dirty、partial、checksum mismatch 或 lock 前后漂移 SHALL 在普通
migration 前零写 `block`。legacy fixture SHALL 只用于 compatibility bridge，
不得成为 patch bundle、receipt 或通用 schema inventory。

#### Scenario: legacy W1 66

- **WHEN** official ledger clean at 66、legacy W1 bytes/checksum 完整且 official
  span expansion 缺失
- **THEN** bridge 在锁内重验后保留 W1 data、补齐 official 66 语义并登记
  enterprise baseline，再继续 official→enterprise migrations

#### Scenario: partial legacy state

- **WHEN**只有部分 W1 object/data 或 checksum 不匹配
- **THEN** bridge 零写失败，不 force version、不猜测修复

### Requirement: U1.8 Upstream 与 project replay 只能由标准 Git 历史承载

系统 SHALL 从 official remote 的 manifest exact SHA 创建标准 Git merge，并
保留可证明的 official ancestry。W1 与现有 logger redaction SHALL 通过普通、
可审查 replay commits 恢复；每个 project-owned path SHALL 在 W1 inventory
登记并通过定向测试。

045 SHALL NOT 生成或维护 W1 patch file、patch bundle、`verify-bundle`、receipt、
patch DSL 或 arbitrary patch engine。Git merge/replay history SHALL 是唯一
patch carrier。

#### Scenario: registered overlap 需要 replay

- **WHEN** 人工 review 决定 target change 与 W1 都必须保留
- **THEN** 实现者用普通 Git replay commit 解决并运行 focused tests，不生成
  bundle 或 apply DSL

#### Scenario: 出现 inventory 外 project patch

- **WHEN** merge 需要新的 project-owned production path 或新 patch identity
- **THEN** 045 `block` 并要求单独批准，不顺手扩大 replay

### Requirement: U1.9 定向 Code 与 Artifact gates 必须分离

Code gate SHALL 包含 thin-check mutation tests、official migration
head/checksum、W1/plugin compatibility、disposable PostgreSQL bridge/restart
matrix、Wiki history/diff/edit/revert 产品验收、focused frontend、OpenSpec 与
diff/scope checks。

trusted workflow SHALL 从已合入 main 的 exact source 构建 server、worker、
frontend 等多 images，并证明它们共享同一 commit/tree/lock。workflow SHALL
发布 digest、provenance 与 SBOM，SHALL NOT 下载或应用 project patch bundle。

Artifact gate SHALL 在 Code 合入后验证 image identity、multi-image 一致性、
backup/disposable PostgreSQL migration、plugin/readiness/zero-write probes 与
产品 smoke。Code 通过 SHALL NOT 被当成 Artifact ready。

#### Scenario: Code 通过但没有 trusted images

- **WHEN** merge/replay/migration/compatibility tests 通过，但 trusted workflow
  尚未从 main 构建 images
- **THEN** adoption 仍未完成，Artifact state 保持 false

#### Scenario: 多 image identity 不一致

- **WHEN** server、worker 或 frontend image 中任一个不是同一 approved
  commit/tree/lock
- **THEN** Artifact gate 失败，不发布 adopted verdict

### Requirement: U1.10 045 必须拒绝平台化扩张

045 SHALL NOT 创建或维护：

- `deploy/upstream/weknora-enterprise-schema-objects.yaml`；
- `deploy/upstream/weknora-adoption-report.json`；
- generic DDL/schema-object/collision report engine；
- W1 patch/bundle/receipt；
- `bundle`、`verify-bundle` 或任意仓库 patch DSL。

necessary official checksum 与 registered W1 overlap evidence SHALL 来自有限
check 的 deterministic stdout/CI log。045 SHALL NOT 实现 P2d、P3 ACL
inspection、P11/P13/P14、provider、full、P4a/P4c，也不得解除 source-reader
authority block。

#### Scenario: 提议新增通用 collision report

- **WHEN** 实现要求解析任意 SQL schema object 或生成 tracked adoption report
- **THEN** 该实现超出 045，必须删除或进入独立获批 Mission

#### Scenario: 提议用 bundle 简化 replay

- **WHEN** 实现要求生成 W1 patch/receipt 后由 workflow apply
- **THEN** 该实现被拒绝，改用标准 Git merge/replay history

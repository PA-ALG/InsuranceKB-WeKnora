# 045 · WeKnora `80a5003` Mainline Snapshot Continuous Adoption Design

> 状态：`SPEC-ONLY / IMPLEMENTATION NOT STARTED`
>
> 目标不是制造一个长期私有 fork，而是建立「持续跟随批准的官方不可变
> identity + Harness 插件化 + 企业迁移独立记账」的可重复升级路径。本设计
> 首先采用 Tencent WeKnora mainline snapshot
> `80a5003cc99a427098afe184eee6601916d3d156`；同一机制 SHALL 可用于后续
> stable release 或经用户明确批准的 mainline snapshot。

## 1. 已冻结事实

- 当前 deployed runtime source lock：
  `v0.6.3@5eefa70e6fc8f9ec27958779f91ece6cf685598c`；
- 当前 project main 与 target 的真实 Git merge-base 是
  `b4b63a0c1f60718aa496df5ecf3a61a347da3d06`；runtime lock `5eefa70e...`
  是 target ancestor，但不是 project main ancestor，因此 runtime upgrade
  baseline 与 source merge baseline 必须分开建模；
- release ancestor：
  `v0.7.1@c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`；
- 目标官方 mainline snapshot：
  commit `80a5003cc99a427098afe184eee6601916d3d156`，
  tree `18fcf68e7a008ce69929e32233f0b6914040c223`；
- 目标比 v0.7.1 前进 17 commits / 122 changed paths；提交
  `80a5003` 新增 Wiki 单页 revision history、line diff、manual editing、
  revert、optimistic locking 与官方 `000075_wiki_page_revisions`；
- 当前 trusted local-live app digest：
  `sha256:e2dd00b37dbcfebf87fab9d1e2338ad43e6ea9939a5ba9fcab9d412d866521f5`；
- 目标 snapshot 继承的官方 chain 使用
  `migrations/versioned/000066_expand_knowledge_span_name.{up,down}.sql`，
  up 将 `knowledge_processing_spans.name` 扩展到 `VARCHAR(255)`；
- 已合入 W1 使用
  `migrations/versioned/000066_knowledge_revision_manifest.{up,down}.sql`，
  创建 revision manifest 合同。两者编号相同、效果不同；
- 当前 local-live workflow 从官方 `5eefa70e` checkout，只重放
  model-debug access-log redaction patch；当前运行制品不含已合入仓库的 W1。

用户已明确：任何现有数据库都必须保留数据；不得用清空、重建、force
version 或伪造迁移历史绕过 `000066`。

## 2. 核心决策

### D1 · 官方源码持续跟随批准的不可变 identity

每次升级 SHALL 锁定官方 commit、tree 与 source archive digest；stable
release 还 SHALL 记录 tag，post-release mainline snapshot 还 SHALL 记录其
release ancestor 与相对增量。本次只允许 exact `80a5003...`，不得跟随会继续
移动的 `main`。官方源码与官方 migration 作为一组同步；不得只改
`VERSION`、镜像 tag 或 source lock。

官方大规模 vendor delta 不逐路径伪装成项目新功能。评审聚焦：

1. 官方 target identity 与来源是否可证明；
2. 企业 patch 的重放 delta；
3. 官方变更与企业 owner 的碰撞；
4. 数据迁移、API 合同和受信制品是否通过。

adoption report SHALL 同时生成真实 project-head/target 三方合流清单与
source-lock/target runtime delta。前者决定 merge conflicts，后者决定当前
部署到候选制品的实际升级范围；任一方不得替代另一方。

### D2 · Harness 继续是插件/外部服务

保险领域 authority、Space、安全、编译、Release、Query 与 worker 编排继续
归 Harness。集成优先使用 WeKnora public API、worker contract 或 sidecar；
不得借升级把领域逻辑搬入 Go fork。

持续升级的核心证据不是 vendor 文件能否合并，而是 machine-readable Harness
plugin contract 在新 target 上仍成立。该 inventory SHALL 固定 versioned
REST/lifecycle poll、完整 response envelope、typed error、principal、
authoritative Space binding、current tenant/RAW-KB ACL、allowed read/denied
mutation/zero-write、retry/idempotency/timeout、禁止共享内部基础设施及三阶段
validation nodes。兼容权威是公共 method/path/grammar/semantics，不是私有 Go
symbol。045 只建立 inventory 与 adoption compatibility gate；现有 Harness
consumer 仍为 pre-W1，P4a/P4c 适配和 source-reader ACL authority 保持独立
Mission/blocker，不在升级中顺手实现。

WeKnora 内部 patch 仍只允许 patch inventory 已批准的 W1/P11/P13/P14。
本 change 只重放已实现 W1 与现有 supply-chain redaction patch，不授权
P11/P13/P14 或新 patch。

045 显式修改 038 W1.6：W1 的 patch identity 与领域合同不扩大，但为解决
官方/项目 `000066` 冲突，allowed surface 增加独立 migrator、legacy
classifier/bridge、startup fail-closed readiness、双-ledger observability
与 collision tooling。这些路径必须归入 W1 adoption inventory，不能伪装成
上游文件，也不构成第五 patch。

### D2a · 用户要求的 upstream Wiki revision 功能必须真实可用

采用 `80a5003` 的直接用户价值不是 commit 数，而是普通 Wiki 单页的：

- revision history；
- 两版 line diff；
- manual editing + optimistic locking；
- revert 生成新 revision、保留旧历史；
- edit source attribution（user/agent/pipeline/revert）。

Code/Artifact gate SHALL 以 bounded upstream feature tests/probe 验证这些
能力和既有 ACL。该验证不把普通 Wiki revision 解释成 W1 Source parse
revision，也不接入 Harness managed-page fencing、ChangeProposal 或 Release
rollback。

### D3 · 迁移所有权永久独立记账

「分轨」只指 migration source 与 state ledger，不指产品版本分叉：

| owner | migration source | state ledger | 执行顺序 |
|---|---|---|---|
| Tencent upstream | `migrations/versioned` | `schema_migrations` | 先 |
| Enterprise W1+ | `migrations/enterprise/versioned` | `enterprise_schema_migrations` | 后 |

官方 migration 文件 SHALL 与目标 identity 一致。项目 migration SHALL NOT
再使用官方数字序列；企业序列从 `000001` 独立开始。两条链可修改同一
PostgreSQL database，但 enterprise migrator 使用独立 migration source、
独立 state table 与独立 advisory-lock identity。

### D4 · legacy W1 `000066` 只经一次兼容桥收敛

兼容桥在任何普通 migration 前运行只读 preflight。它 SHALL 读取：

- `schema_migrations` version/dirty；
- 官方 span column 的精确 type；
- W1 三列、revision table、约束和索引的结构指纹；
- 任何 enterprise ledger/baseline；
- 未知或部分应用形态。

升级矩阵 SHALL 独立覆盖下列四个来源画像。运行时 classifier 依据 ledger 与
schema 指纹选择安全动作；`fresh_target` 与既有 `upstream_66_plus` 即使最终
schema 相同，也必须作为不同 fixture 验证，但不要求生产代码靠业务行数量
猜测二者来源：

| 状态 | 官方 000066 效果 | W1 效果 | 收敛动作 |
|---|---|---|---|
| `pre_66` | 无（official ledger <66） | 无 | 官方链 66→75；企业链应用 W1 |
| `upstream_66_plus` | 有（existing DB） | 无 | 官方链续跑；企业链应用 W1 |
| `legacy_w1_66` | 无 | 有 | 事务内补齐官方 66；官方链续跑；结构证明后登记企业 W1 baseline |
| `fresh_target` | 有（fresh fixture at official head 75） | 无 | 企业链应用 W1 |

`legacy_w1_66` bridge SHALL：

1. 在 PostgreSQL advisory lock 和单事务内重新验证状态；
2. 执行与官方 up migration 等价的 span type 扩展；
3. 逐项证明 W1 schema 等于批准的 legacy 指纹；
4. 保持 `schema_migrations=66` 的语义从「仅 W1」收敛为「官方 66 + W1」；
5. 建立/登记 `enterprise_schema_migrations` 的 W1 baseline；
6. 提交后再允许官方 67–75。

它 SHALL NOT 删除或重建 W1 表、列、索引、revision rows、knowledge/chunk
数据。legacy SQL 与 checksum SHALL 迁出 active official chain，作为
只读 compatibility fixture 保留；不得静默删除或冒充官方文件。

bridge 提交是一个明确的可恢复 checkpoint。classifier SHALL 识别
`bridged_legacy_w1_66`（official 66 效果 + 完整 W1 指纹 + clean enterprise
W1 baseline，official ledger 仍为 66）并直接从官方 67–75 继续；进程在 bridge
提交后崩溃或第二实例稍后获得锁时，不得重复写 bridge，也不得把该状态误判为
unknown。official 67–75 完成后但 application 尚未 ready 的
`adopted_w1_pending_probe` 也 SHALL 可重入，只需重验 ledgers/schema/W1
capability。

### D5 · 未知状态 fail closed

以下任一情况启动失败且零 schema/data 写：

- 任一 ledger dirty；
- version 与结构指纹不一致；
- 同时只出现部分官方/W1 效果；
- W1 对象存在但约束、索引或列类型不匹配；
- 已有 enterprise ledger 与结构不匹配；
- 目标 identity/官方 migration checksum 不符；
- compatibility bridge 重验与 preflight 结果不同。

已经精确匹配上述 bridge checkpoint 或 final adopted checkpoint 的状态不是
unknown；它们必须幂等恢复。

禁止自动 `force`、向前/向后猜 version、drop/recreate 或 best-effort
继续启动。

### D6 · 碰撞检查不仅比较编号

CI SHALL 对每个目标官方 identity 生成：

- official migration version/name/checksum inventory；
- enterprise migration version/name/checksum inventory；
- enterprise-touched schema object inventory；
- official delta touched-object inventory；
- registered patch replay path inventory。

独立 namespace 使数字碰撞不再成立；但若官方新 migration 触碰
enterprise-owned 表/列/索引，或官方源码改到 W1 patch surface，CI 仍 SHALL
阻断并要求显式 compatibility/replay review。不得把「编号没撞」等同于
「语义兼容」。

### D7 · 启动顺序与 readiness 说真话

PostgreSQL 生产 profile 的启动顺序固定：

```text
identity/checksum preflight
  → legacy compatibility bridge（仅命中时）
  → official migrations
  → enterprise migrations
  → W1 capability/schema probe
  → application ready
```

任一步失败，application readiness SHALL 为 false，W1 route/worker SHALL
不可服务。`migration version` 的观测 SHALL 分别显示 official 与 enterprise
ledger，不得压成一个误导数字。

本 Mission 只认证 PostgreSQL 生产 profile。官方 SQLite 行为须保持上游
兼容，但 W1-on-SQLite 不在本 change 中补做或宣称已认证。

### D8 · 制品和部署必须来自同一身份

trusted workflow SHALL 从固定官方 commit/tree 构建，按 machine-readable
inventory 重放批准 patch，输出：

- final source tree / replay delta；
- image subject digest；
- provenance / SBOM / attestation；
- official + enterprise migration inventory/checksum；
- W1 capability probe；
- 备份 clone 上四状态矩阵与 rollback/recovery evidence。

只有 exact candidate 通过后才能更新 source lock、image lock 和 local-live
Compose。不得在目标数据库上边迁移边试错；首次真实升级只在可恢复备份 clone
验证通过后进行。

## 3. 升级失败与恢复

- migration 前必须具备可验证备份与恢复点；
- preflight/bridge/official/enterprise 每阶段产生不含 secret 的 receipt；
- bridge 单事务失败自动回滚；
- official 67–75 或 enterprise migration 失败按标准 dirty fail-closed，
  不自动 force；
- 切换失败优先恢复数据库快照和旧 digest，不执行 destructive down；
- 官方 000066 down SQL 会截断 span name 到 64，生产回滚 SHALL NOT 默认调用
 该 down migration。

## 4. 交付切片

为避免大规模官方 vendor delta 与高风险 migration 混成不可审查大包，交付
拆为：

1. **045-Spec**：本设计、OpenSpec、状态机与测试矩阵；零生产代码；
2. **045-Code**：官方 `80a5003` source sync、W1 replay、分轨 migrator、
   compatibility bridge、collision CI、source-lock v2、main-only multi-image
   trusted workflow 和 focused tests；workflow 定义先随 Code 合入，但此时
   不产生 runtime digest 或 adopted 声明；
3. **045-Artifact**：从已合入 main 的 trusted workflow 生成 image、
   provenance/SBOM，执行四状态备份 clone 演练、image-lock/digest 更新和受控
   local-live cutover。

Code 与 Artifact 可属于同一 OpenSpec，但必须独立 PR/独立 exact identity
复审；未经 Code 合入不得提前制造 Artifact 通过结论。

## 5. 非目标

- 不实现 P2d、P3 ACL-inspection、P11/P13/P14、P4a/P4c 或 provider；
- 不把 target snapshot 的 scoped/platform API key 冒充 RAW/Wiki ACL 等价能力；
- 不清理历史 worktree、旧 PR 或迁移历史；
- 不升级到 mutable upstream main、pre-release 或未锁定镜像；
- 不认证 SQLite W1、HA、全量性能/模型质量或生产正式切流；
- 除用户明确要求的普通 Wiki 单页 history/diff/manual edit/revert 验收外，
  不顺手吸收 target snapshot 的其他新功能到 Harness 产品面；
- 不把 upstream page revert 冒充 Harness Release rollback、P11 fencing 或
  P14 ChangeProposal。

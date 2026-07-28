# 045 WeKnora Continuous Adoption 验收规格

## ADDED Requirements

### Requirement: U1.1 官方 target identity 必须精确且可重放

系统 SHALL 仅从固定的 Tencent WeKnora commit、tree 与 source checksum
构建；stable release 记录 tag，mainline snapshot 记录 release ancestor 与
相对增量。本次目标 SHALL 是 commit
`80a5003cc99a427098afe184eee6601916d3d156`、tree
`18fcf68e7a008ce69929e32233f0b6914040c223`，其 release ancestor SHALL 是
`v0.7.1@c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`。`VERSION` 只能作为显示
信息；source lock、patch inventory、build provenance、image lock 与运行时
commit SHALL 指向同一候选身份。任一漂移 SHALL 阻断发布。

后续 stable release 或经用户批准的 mainline snapshot SHALL 复用相同协议。
mutable branch、floating image tag、仅修改显示版本或从非官方 archive 构建
均不构成采用。

#### Scenario: 版本号变化但源码未变化

- **WHEN** `VERSION` 声明 0.7.1，但 source tree/lock 仍为 `5eefa70e`
- **THEN** identity gate 失败，不构建或发布受信制品

#### Scenario: mutable main 已越过目标

- **WHEN** Tencent `main` 已有 `80a5003` 之后的新提交
- **THEN** 构建仍 checkout exact `80a5003...`；不得因 main 前进而静默改变
  source tree，除非用户另批新 identity 并更新 045

#### Scenario: 下一批准 identity 复用同一入口

- **WHEN** 后续选择新的固定 stable tag 或 mainline snapshot
- **THEN** 工具从新 identity 重新生成 official migration、schema-object 与
  patch overlap inventory，不要求把企业 migration 重新塞回官方编号链

### Requirement: U1.2 Harness 插件边界与 patch identity 不扩大

升级 SHALL 保持 Harness 作为外部 API/worker/sidecar 消费者。只有 inventory
已批准且本 Mission 拥有的 W1 和现有 model-debug log redaction 可重放。
P11/P13/P14 保持 planned；任何第五 patch、保险领域 Go 规则或未经登记路径
SHALL 阻断。

W1 replay SHALL 以 `80a5003...` 为新 upstream baseline，更新 exact file list、
overlap verdict、compatibility tests 与 remove condition。官方功能若能替代
某个 patch，只有等价合同测试全绿后才可删除该 patch。

W1 为适配独立 migration ledger 所需的 classifier、bridge、startup
readiness、migration observability 与 collision tooling SHALL 作为 W1
adoption surface 在 inventory 中逐路径登记；它们改变 038 W1.6 的历史
allowed surface，但不创建新的 patch identity 或保险领域能力。

#### Scenario: 上游新功能看似接近 W1

- **WHEN** target snapshot 提供新的 API key、activity audit 或 source
  download 能力，
  但没有通过 W1 SourceLifecycle/RevisionManifest contract
- **THEN** W1 不得被删除或宣称由上游替代

#### Scenario: 出现未登记项目改动

- **WHEN** replay delta 含 inventory 外的生产路径或新 patch identity
- **THEN** upgrade gate 失败并要求新 Mission，不顺手扩大 045

### Requirement: U1.3 官方与企业 migration 独立记账

PostgreSQL SHALL 按以下顺序执行两条 migration chain：

1. 官方 `migrations/versioned` + `schema_migrations`；
2. 企业 `migrations/enterprise/versioned` +
   `enterprise_schema_migrations`。

企业 chain SHALL 使用独立 version namespace、state table 与 advisory-lock
identity。官方 migration 文件 SHALL 与 target commit/tree checksum 一致；
official head SHALL 包含 `000075_wiki_page_revisions`；active
官方目录中 SHALL 只有官方 `000066_expand_knowledge_span_name`，不得保留、
覆盖或改名伪装项目 W1 `000066`。

legacy W1 SQL/checksum SHALL 作为只读 compatibility fixture 保留。W1 的
active enterprise migration SHALL 从企业 `000001` 开始。

#### Scenario: 新官方 migration 继续增长

- **WHEN** 官方后续新增 `000075+`
- **THEN** 官方 ledger 正常推进，企业 ledger/version 不变且随后独立推进，
  不产生数字占号冲突

#### Scenario: 两个 migrator 并发启动

- **WHEN** 两个 application instance 同时启动
- **THEN** official/enterprise 各自通过稳定 lock identity 串行；任一
  compatibility bridge 也只允许一个 writer；后获得锁的实例识别已提交
  checkpoint 并幂等续跑，最终 ledger/schema 一致

### Requirement: U1.4 四种数据库状态必须无损收敛

升级器 SHALL 在写入前依据 ledger 与 schema 指纹选择支持的安全动作，并 SHALL
独立验证下列四个来源画像：

`pre_66 | upstream_66_plus | legacy_w1_66 | fresh_target`。

classifier SHALL 同时验证 ledger、官方 span column 与完整 W1 schema 指纹，
不能只读 migration version。`fresh_target` 与 existing
`upstream_66_plus` 可具有相同 schema/action；实现 SHALL NOT 读取业务行数
猜测来源，但验收必须以独立 fixtures 证明两条路径。四种画像都 SHALL 最终
满足：

- 官方 chain clean at target head 75；
- `knowledge_processing_spans.name` 为 `VARCHAR(255)`；
- enterprise chain clean at W1 head；
- W1 columns/table/constraints/indexes 与数据保持；
- W1 compatibility tests 通过。

系统 SHALL 额外识别由自身产生的两个可恢复 checkpoint：

- `bridged_legacy_w1_66`：official 66 效果、完整 W1 指纹和 clean enterprise
  W1 baseline 均存在，official ledger 仍为 66；
- `adopted_w1_pending_probe`：official/enterprise ledgers 与 schema 已完成，
  尚待 W1 capability/readiness probe。

两者不是新的输入来源画像；它们用于进程崩溃和多实例竞争后的幂等续跑。

#### Scenario: legacy W1 000066

- **WHEN** `schema_migrations=66 clean`、W1 完整指纹存在、官方 span 扩展不存在
- **THEN** bridge 在同一事务和 advisory lock 内补齐官方 66 效果、重验 W1
  指纹并登记 enterprise baseline；不删除、复制或改写 W1 业务数据，再允许
  官方 67–75 运行

#### Scenario: upstream 000066 已执行

- **WHEN** 官方 span 扩展存在、W1 指纹不存在且 official ledger clean
- **THEN** 官方 chain 续跑后 enterprise W1 migration 正常应用；不把官方 66
  误判为 legacy W1 baseline

#### Scenario: pre-66 与全新数据库

- **WHEN** 分别从 clean pre-66 数据库和 fresh target snapshot 数据库升级
- **THEN** 两者均先完成官方 chain、再完成企业 chain，最终合同等价且既有
  数据逐表计数/摘要不因 compatibility bridge 丢失

#### Scenario: bridge 提交后进程崩溃

- **WHEN** legacy W1 bridge 已原子提交，但进程在官方 67 开始前崩溃并重启
- **THEN** classifier 精确识别 `bridged_legacy_w1_66`，不重复写 bridge，
  从官方 67–75 继续，最终数据与一次不中断升级相同

#### Scenario: migration 完成后 probe 前崩溃

- **WHEN** 两条 ledger/schema 已完成但进程在 W1 capability probe 前崩溃
- **THEN** 重启识别 `adopted_w1_pending_probe`，重验后继续 readiness；
  不回退、force 或重复应用 enterprise W1

### Requirement: U1.5 模糊、dirty 与部分状态必须 fail closed

系统 SHALL 在任一 ledger dirty、version/结构不一致、部分 W1 schema、未知
index/constraint 差异、official checksum 漂移或 preflight 与 lock 内重验
不一致时，于普通 migration 前失败。失败 SHALL 保持 schema/data/ledger
零写。

系统 SHALL NOT 自动 force version、猜测前一版本、drop/recreate、执行
destructive down 或把未知状态登记为 baseline。
精确匹配 U1.4 两个 checkpoint 的状态 SHALL 幂等恢复，SHALL NOT 被当成
unknown。

#### Scenario: 只有一半 W1 对象

- **WHEN** W1 三列存在但 revision table/index/constraints 不完整
- **THEN** 状态为 unsupported，升级零写失败并输出不含数据/secret 的结构
  差异 receipt

#### Scenario: preflight 后状态被另一进程改变

- **WHEN** 首次只读分类后、bridge 获锁前数据库结构或 ledger 变化
- **THEN** lock 内重验失败，bridge 零写退出，不沿用过期分类

#### Scenario: dirty migration

- **WHEN** official 或 enterprise ledger 标记 dirty
- **THEN** application readiness=false，不自动 force 或继续另一条 chain

### Requirement: U1.6 编号、schema object 与 patch surface 三层碰撞门禁

CI SHALL 对固定且获批的 upstream identity（stable tag 或 exact snapshot
commit/tree）与 enterprise inventory 比较：

1. migration source/ledger namespace 与 checksum；
2. upstream migration touched schema object 与 enterprise-owned object；
3. upstream source delta 与 registered patch replay paths。

工具 SHALL 区分两个不可混淆的源码基线：

- 项目源码合流基线：由当前 project head 与 target 的真实 Git merge-base
  自动推导；
- 当前运行制品基线：由已验证 source lock 提供，用于证明 deployed
  runtime 到 target 的实际升级 delta。

本次 project main 与 target 的真实 merge-base 是
`b4b63a0c1f60718aa496df5ecf3a61a347da3d06`，而 current runtime source
`5eefa70e6fc8f9ec27958779f91ece6cf685598c` 不是 project main 的 ancestor。
collision report SHALL 同时记录两种 delta，且不得把 runtime baseline
冒充 Git merge-base。

任何语义 overlap SHALL 产出 exact object/path/old-new identity，并要求显式
compatibility verdict。collision gate SHALL 在新增任何 enterprise WeKnora
migration 和每次 upstream tag 更新时运行。

#### Scenario: 编号独立但 schema 对象重叠

- **WHEN** 新官方 migration 使用官方 `000080`，却修改 W1 拥有的
  `knowledge_revisions` 或相关列/index
- **THEN** schema-object gate 仍阻断；独立编号不得掩盖语义碰撞

#### Scenario: 上游修改 W1 patch surface

- **WHEN** 新 tag 修改 W1 replay 的 Go path
- **THEN** replay gate 要求该 path 的三方 delta 与 W1 contract tests，
  不把自动合并成功视为语义兼容

#### Scenario: runtime baseline 不是 project merge-base

- **WHEN** source lock commit 是 target ancestor，但不是当前 project head
  ancestor
- **THEN** report 分别输出真实三方 merge path/conflict 与 runtime-to-target
  delta；不得使用合成 `runtime..project` 结果代替 Git merge 语义

### Requirement: U1.7 readiness 与观测必须反映两条迁移链

PostgreSQL application readiness SHALL 仅在 identity preflight、必要 bridge、
official migration、enterprise migration 与 W1 capability probe 全部成功后
为 true。观测 SHALL 分别暴露 official/enterprise version、dirty/error 与
W1 capability，不得用单一 migration version 隐藏 enterprise 失败。

任一失败时 W1 route/worker SHALL 不可服务，且日志/receipt SHALL 不含 DSN、
credential、token 或业务内容。

#### Scenario: 官方成功但企业失败

- **WHEN** official target-head migration 完成、enterprise W1 migration 失败
- **THEN** readiness=false，状态明确显示 official clean / enterprise failed，
  W1 capability=false

#### Scenario: SQLite profile

- **WHEN** 使用官方 SQLite profile
- **THEN** 上游 SQLite 启动行为不因 PostgreSQL enterprise migrator 被破坏；
  本 change 不宣称 W1-on-SQLite 已认证

### Requirement: U1.8 受信制品与切换必须有恢复证据

trusted workflow SHALL 从 exact `80a5003...`/tree `18fcf68e...` 构建，重放
批准 patch，并产生
final source tree、image subject digest、provenance、SBOM、attestation、
migration inventories/checksums 与 W1 capability evidence。

真实数据库升级前 SHALL 在可恢复备份 clone 上执行四状态矩阵、数据
count/digest 不变量和 restore drill。source lock、image lock 与 Compose
只能在同一 exact candidate 全绿后更新；旧 digest SHALL 保留为恢复目标。

#### Scenario: Code 已合入但新镜像未验证

- **WHEN** source sync/bridge 已合入，而 trusted image 或四状态 clone gate
  尚未完成
- **THEN** 状态只能是 `CODE MERGED / RUNTIME NOT ADOPTED`，不得声明 target
  已运行

#### Scenario: 升级后需恢复

- **WHEN** cutover 后验收失败
- **THEN** 按已演练恢复点恢复数据库与旧 digest；不得默认运行会截断 span
  name 的官方 down migration或删除 W1 schema

### Requirement: U1.9 范围保持在持续升级主航道

045 SHALL 只拥有 upstream adoption、migration 分轨/compatibility、W1 replay、
collision gate 与 trusted artifact。P2d/P3 ACL、P11/P13/P14、provider、
完整性能/模型质量、生产正式切流与历史清理 SHALL 另立 Mission。

实现 SHALL 拆为 Code 与 Artifact 两个 exact-identity PR。官方 vendor delta
路径数不计作项目领域扩面，但 project-authored delta SHALL 有 machine-readable
inventory；出现未登记 patch 或需要改变 W1 领域合同即停止并回到规格审查。

#### Scenario: target snapshot 新特性诱发扩面

- **WHEN** reviewer 发现 scoped keys、activity audit、worker governance 等
  可用于未来能力
- **THEN** 只记录 BACKLOG/compatibility evidence，不在 045 实现新产品面

### Requirement: U1.10 目标 snapshot 的 Wiki revision 用户能力必须可用

adopted source SHALL 包含 `80a5003` 引入的官方
`000075_wiki_page_revisions`、Wiki revision API/service/repository 与
frontend revision drawer/diff/editor。Code/Artifact gate SHALL 对普通、
unmanaged Wiki page 验证：

1. manual edit 使用 optimistic locking，stale save 被拒绝；
2. history 稳定列出 superseded 与 current revisions，并保留 edit source；
3. 任意两版可产生与内容一致的 line diff；
4. revert SHALL 创建一个新的 current revision，历史版本保持不变；
5. 未授权 principal 不得读取 history/diff 或执行 edit/revert，失败零写。

这些 upstream page revisions SHALL NOT 被解释为 W1 knowledge parse
revision、Harness Release rollback、P11 managed-page fencing 或 P14
ChangeProposal。045 只证明官方普通 Wiki 功能在重放 W1 后仍可用。

#### Scenario: manual edit 与 stale save

- **WHEN** 用户读取 page version N，成功保存一次 manual edit 后又以旧 N
  提交不同内容
- **THEN** 第一次产生 N+1 revision 且 source=user/manual，第二次被
  optimistic-lock conflict 拒绝，current/history 不被覆盖

#### Scenario: diff 与 revert 保留历史

- **WHEN** page 有 N、N+1 两版，用户查看 diff 并 revert 到 N
- **THEN** diff 与两版内容一致；revert 产生新的 N+2 current revision，
  N/N+1 均仍可读且 source attribution 可区分

#### Scenario: upstream 功能不越过 ACL

- **WHEN** 无该 Wiki page 读取或编辑权限的 principal 请求
  history/diff/edit/revert
- **THEN** 沿用官方 ACL typed 拒绝、零 page/revision 写且不泄漏内容

## MODIFIED Requirements

### Requirement: W1.6 patch budget 与上游兼容义务

W1 SHALL 继续是 patch inventory
（`deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`）中
`patch_id: W1` 描述的唯一 revision-manifest fork 改动来源。每次 upstream
adoption SHALL 把 `upstream_sha`、`file_path`、compatibility verdict 与
remove condition 更新为 exact candidate；inventory 与 project-authored
replay delta 不一致 SHALL 验收失败。W1 的 API、attempt/revision、digest、
ACL 与非回归领域合同保持由 038 W1.1–W1.7 唯一定义，不得借 adoption 增加
保险领域逻辑。

自 045 起，038 对 migration path、历史 `000066` 与固定 allowed surface 的
旧限制由下列规则替代：

1. 官方 `migrations/versioned/` SHALL 与 adopted Tencent identity 的 official
   migration files/checksums 一致；
2. W1 active migration SHALL 位于
   `migrations/enterprise/versioned/000001_knowledge_revision_manifest.*`，
   状态只记入 `enterprise_schema_migrations`；
3. 项目历史
   `migrations/versioned/000066_knowledge_revision_manifest.*` SHALL 从 active
   official chain 移出，但其 up/down bytes、checksum、原始 path/identity
   metadata SHALL 作为只读 legacy compatibility fixture 保留；这是唯一获
   045 授权的历史 W1 migration relocation，SHALL NOT 静默删除、改写语义或
   冒充 upstream `000066`；
4. W1 adoption surface MAY 包含且仅限：
   - 038 已有 W1 types/repository/service/handler/router 与测试；
   - official/enterprise migrator、legacy classifier/bridge、startup
     fail-closed readiness、双-ledger observability 与对应测试；
   - migration/patch collision inventory tooling、legacy fixture、patch
     inventory；
   - exact source lock、ordered patch verifier 与 main-only multi-image trusted
     workflow（随 045 Code PR 合入，但不含 runtime digest/adopted 结论）；
   - trusted image lock、Compose digest 与 runtime validation evidence
     （只在 045 Artifact PR）；
5. implementation SHALL 在 inventory 中逐一列出 project-authored paths。
   upstream identity vendor delta 不冒充项目 patch，但 SHALL 以 exact
   commit/tree/checksum 和 replay delta 单独审查；
6. PostgreSQL 是 W1 migration/concurrency 的认证 profile；SQLite upstream
   行为保持非回归，但 W1-on-SQLite 不在 045 宣称已认证。

跟版 compatibility matrix SHALL 至少重放：exact completed-attempt
manifest/content binding、reparse-pagination-delete race rejects mixed
revisions、existing knowledge REST behavior remains compatible、no shared
database/Redis/Asynq dependency；并 SHALL 增加 045 的四来源升级矩阵、
crash-resume checkpoints、双 ledger readiness 与三层 collision gate。

#### Scenario: target adoption surface 与 inventory exact 一致

- **WHEN** 审查 045 Code/Artifact 的 project-authored replay delta
- **THEN** 每个路径都属于上述 allowed categories 并在 W1/redaction 或
  supply-chain inventory 中逐一登记；不存在第五 patch identity、保险领域
  Go 逻辑或未登记生产路径

#### Scenario: legacy 000066 可审计迁出 active chain

- **WHEN** target 的 official `000066_expand_knowledge_span_name` 进入 active
  official migration source
- **THEN** legacy W1 `000066` 的原始 bytes/checksum/path identity 仍可由
  compatibility fixture 验证，active W1 语义由 enterprise `000001` 承接，
  既没有双 000066，也没有静默改写历史

#### Scenario: migration 失败阻断服务

- **WHEN** official/enterprise migration、bridge 或 W1 capability probe
  任一步失败
- **THEN** startup/readiness fail closed，不沿用 038 实现中“记录 warning
  后继续服务”的旧行为；双 ledger error 可观测且不泄漏 secret

#### Scenario: 后续批准 identity 继续重放 W1

- **WHEN** adopted upstream baseline 从 `80a5003` 更新到后续固定 stable tag
  或批准的 mainline snapshot
- **THEN** 重新生成 commit/tree/checksum、release ancestry、
  migration/schema-object/patch-overlap inventory 并运行全部 compatibility
  matrix；无需把 W1 放回官方数字链

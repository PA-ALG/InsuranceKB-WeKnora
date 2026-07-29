# 033 Production Architecture Reset 验收规格

> [!WARNING]
> 2026-07-29 Amendment 2 已取代 D0.3/D0.4/D0.5 中的 PostgreSQL serving
> authority、Outbox Projector、P11 epoch-fenced projection 与封闭旧 patch
> 编号语义。相关旧 Requirement/Scenario 仅作历史验收证据，不授权实现。当前
> replacement contract 见本文件末尾 D0.12–D0.17。
>
## ADDED Requirements

### Requirement: D0.1 可配置审核策略

生产审核 SHALL 由不可变、版本化的 Space ReviewPolicy 选择
`machine_auto | human_batch | hybrid | trusted_import` 四种合法模式。系统
SHALL NOT 把人工逐页操作或真人最终审批硬编码为所有 Space 的共同前置。
`trusted_import` SHALL 只接受受控 connector 与不可变 attestation，不接受
调用者自报 trusted。`machine_auto` SHALL 精确绑定仍有效的
QualityProfileApproval id/hash、AutomationScope hash、完整 run fingerprint、
covered capabilities 与当前 CompilationSecurityProfile。QualityProfileApproval
SHALL 来自 P2c code-owned registry，绑定独立 reviewer receipt 与 append-only
revocation generation；AutomationScopeV1 SHALL 精确绑定 Schema、Space、
product/version、source/document profile、parser/chunker、
compiler/deployment build、model/model-plan、prompt、template、
canonicalizer/comparator、security profile、evaluator 与 QualityProfile；
run fingerprint SHALL 再绑定 semantic-input manifest 与全部 attempt receipts。
Candidate 的全部 required capabilities SHALL 是 approval
`covered_capabilities` 的子集。approval 缺失或撤销、任一字段/hash 不匹配、
unsupported/schema-gap、unresolved entity、Evidence/locator/digest、
恶意内容或 ACL/security blocker SHALL 确定性回落 `human_batch` 并使旧自动
Decision 不适用；调用者不能 override。

#### Scenario: 四种模式均为合法策略

- **WHEN** 四个 Space 分别 pin 四种审核模式及其 exact policy version
- **THEN** 每种模式都可按自己的冻结合同形成 ReviewDecision，系统不会仅因
  缺少逐页审批而拒绝 `machine_auto`、`hybrid` 或 `trusted_import`

#### Scenario: machine_auto 资格漂移回落人工批审

- **WHEN** Candidate 的 Space/product/version、Schema、source/parser/chunker、
  model-plan、prompt/template/compiler/deployment、canonicalizer/comparator、
  evaluator/QualityProfile、semantic inputs/attempts、covered capability、
  security profile 或 QualityProfileApproval/revocation generation 任一与权威
  registry 不同，approval 已撤销，或出现绝对 blocker
- **THEN** provider/发布 authority 不会由旧标签恢复，ReviewPolicy 确定性选择
  `human_batch` 并使旧自动 Decision 不适用

### Requirement: D0.2 human_batch 审 exact CandidateRelease

`human_batch` SHALL 让授权人对完整、不可变的 CandidateRelease digest
执行一次批量批准或拒绝。系统 SHALL NOT 提供 page/item approve API，也不得
在批准后偷偷移除成员而复用原 Decision。

#### Scenario: 一键批量决定绑定完整候选

- **WHEN** 授权人批准一个包含页面、Claim、Relation、Evidence 与 Conflict
  成员摘要的 CandidateRelease
- **THEN** ReviewDecision 精确绑定 Candidate digest；任一成员变化都会生成
  新 Candidate 并使旧 Decision 不适用

### Requirement: D0.3 PostgreSQL 是 Release serving authority

应用服务当前知识版本 SHALL 只由 PostgreSQL
`Space.active_release_id + activation_epoch` 决定。激活与回滚 SHALL 使用
expected-current CAS 并单调递增 epoch。filesystem、inode、hardlink、
rename、fd、fsync、WeKnora 页面状态或投影完成标记 SHALL NOT 成为 Release
提交权威。publication SHALL 在同一 PostgreSQL 事务中重验 base
release/activation epoch、policy id/epoch、binding/security 和 Decision，创建
不可变 WikiRelease 与成员，执行 active pointer/epoch CAS，并写 Outbox。
同一 Space 的最终 merge/review/promotion SHALL 串行，不同 Space 可以并行。
CAS loser 的 publication 事务 SHALL 整体回滚、零 Release/Outbox；随后 fresh 同 Space 串行事务 SHALL stale/requeue 且不得复用旧 Decision。

#### Scenario: 文件和投影成功不能提交 Release

- **WHEN** Candidate 文件制品或 WeKnora managed 页面全部写入成功，但
  PostgreSQL active pointer CAS 未成功
- **THEN** 应用继续服务旧 active release，写入结果不具发布权威

#### Scenario: CAS loser 确定性重排

- **WHEN** 两个多实例事务基于同一 base release/epoch 并发 promotion
- **THEN** 只有一个事务创建并激活其不可变 WikiRelease 与 Outbox；另一方先
  整体回滚，再由 fresh 串行事务标记 stale 并确定性 requeue，旧 Decision 不复用

#### Scenario: at-least-once 投影可恢复

- **WHEN** Outbox 或 Projector 在成功后丢失确认并重复执行
- **THEN** 稳定幂等键与 epoch fencing 使结果等价，reconciliation 补齐缺项；
  系统不宣称 exactly-once

### Requirement: D0.4 WeKnora 是隔离的 fenced 可重建投影

LLM Wiki SHALL 只通过版本化 WeKnora REST 与 Source lifecycle event 集成，
不共享 WeKnora 数据库、Redis、Asynq 或内部队列。MCP SHALL NOT 成为
WeKnora integration/control plane，只能在后续 P9b 作为 Active Query service
的消费者 thin adapter。managed Wiki SHALL 是 Active WikiRelease 的可重建
投影；P11 server-side activation-epoch fencing SHALL 拒绝迟到写和普通
PUT/DELETE 绕过，投影失败只影响 freshness，不反向修改 Release。

#### Scenario: 迟到投影不能覆盖当前版本

- **WHEN** activation epoch 12 已被接受后收到 epoch 11 的 managed-page 写入
- **THEN** WeKnora 服务端拒绝该写入，PostgreSQL active release 与当前投影
  high-watermark 均不回退

### Requirement: D0.5 WeKnora patch budget 封闭

D0 SHALL 维护 machine-readable patch inventory。只有 W1 revision manifest、
P11 managed-page fencing、P13 Evidence/Review UX 和 P14 Proposal Edit UX
可以在各自批准的 path/budget 内修改 WeKnora。任何其他 patch SHALL 先修改
033、说明直接生产闭环价值并取得独立批准。

#### Scenario: 未登记 patch fail closed

- **WHEN** 计划或 diff 声明一个不属于 W1/P11/P13/P14 的 WeKnora patch
- **THEN** inventory 校验失败，D0 和该 patch 均不可进入实现

### Requirement: D0.6 Wiki 是应用知识权威

Active WikiRelease SHALL 是人、API、MCP 和问答的应用知识权威，并保留
Evidence、Conflict、版本、不可变 Release 与回滚语义。原始资料 SHALL 是证据
真相，但未发布 chunk、Candidate 或编辑不得进入应用结论。

#### Scenario: 查询固定一个 Active Release

- **WHEN** 请求开始后 active release 在并发事务中切换
- **THEN** 该请求的页面、Claim、Relation、Evidence 和引用仍全部来自开始时
  固定的同一 Release

### Requirement: D0.7 raw 只用于证据、审核和补编

raw chunk、原始向量/BM25 检索和 raw RAG SHALL 只用于 Evidence 核查、人工
审核和触发补编。Active WikiRelease 无答案时，应用 SHALL 返回“已发布知识
不足”或请求补充条件；不得把原始检索结果静默包装成发布结论。

#### Scenario: 无发布知识时禁止 raw fallback

- **WHEN** Active Query 对一个问题没有已发布知识
- **THEN** 返回类型化 insufficient/needs-qualification，raw 搜索调用次数为零
  或仅以显式证据核查流程执行，响应不会把 raw 内容标成答案

### Requirement: D0.8 旧路线只作历史证据

旧 PR26/28/33、冻结 029/029a 与 031 runtime SHALL 只保留为审计、威胁场景和
可选择性重写的测试素材。D0 及后续实现 SHALL NOT 继续更新、rebase、
cherry-pick 或直接重放其 authority/runtime。

#### Scenario: 旧分支不能成为实现依赖

- **WHEN** 后续 PR 的 diff 或构建输入引用旧分支的未合并 runtime blob
- **THEN** scope gate 拒绝该 PR；只有在新 Contract Card 下重写且通过当前
  TDD 的独立代码才可进入主线

### Requirement: D0.9 弱模型与小 PR 门禁保留

生产 SHALL 只使用经版本化策略批准的 MiniMax/Qwen/Qwen-VL 级弱模型；
强模型不得成为生产 fallback、judge 或发布前置。每个实现 PR SHALL 有
OpenSpec、Contract Card、关键 RED→GREEN、独立复审和单一领域不变量，通常
不超过批准的 10–15 个逻辑文件。

#### Scenario: 新实现先审合同再写代码

- **WHEN** 一个后续任务准备实现生产领域行为
- **THEN** reviewer 先批准其 authority、事务、状态机、威胁矩阵、测试和路径
  预算；缺任一项时功能代码保持零变更

### Requirement: D0.10 doc-only Contract Card 与幂等 stale scan

pre-implementation S0 SHALL 只修改 proposal 所列 6 个治理路径；完整 D0
SHALL 最多修改该 6 路径加 S1 精确 16 路径，共 22 路径。只有旧 029/032
六文件允许 notice-only，031 OpenSpec 文件不得修改。固定 scanner SHALL 冻结
exact regex、scan roots、UTF-8/LF 与空白归一化、C locale 排序规则、完整
classified baseline manifest 和 SHA-256；同一树运行两次 SHALL 产生相同 hash，
未知或未分类命中 SHALL fail closed。功能测试、full、provider、live 与
PostgreSQL SHALL 记为 NOT RUN。

#### Scenario: 第七路径使候选失效

- **WHEN** temp-index 相对 base 出现 proposal 路径预算以外的第七条路径
- **THEN** pre-implementation candidate 不得冻结或提交，Owner 返回
  NEEDS_CONTEXT

#### Scenario: baseline 新命中未分类

- **WHEN** exact scanner 在冻结 roots 中发现 baseline manifest 之外的新命中
- **THEN** 即使 OpenSpec syntax valid，D0 仍 fail closed，直到该命中被明确
  归类并经 Spec review

### Requirement: D0.11 旧路线与 migration 计划不可复用

S1 SHALL 在 OpenSpec README、roadmap、parallel blueprint 与 control board
把旧 029/031/PR 路线标为 superseded/history-only。旧计划 migration
`0013/0014` SHALL 标为 `superseded / not reusable`，D0 SHALL NOT 预占替代
migration；后续 owner 必须从执行时真实 `origin/main` Alembic head 重新占号。
除旧 029/032 六个 notice-only 文件外，任何旧 OpenSpec 历史正文 SHALL 保持
不变。

#### Scenario: 031 OpenSpec 不得被 notice 扩域

- **WHEN** S1 scope 检查发现任意 `openspec/changes/031-*` 文件变化
- **THEN** D0 立即停止并返回 NEEDS_CONTEXT，不得以“统一 superseded notice”
  为理由扩大历史文件范围

### Requirement: D0.12 单一 serving Active Release authority

正式线上知识 SHALL 只有一个 serving Active Release authority。Harness 与
WeKnora SHALL NOT 同时保存可独立决定线上版本的 Active Head。Harness MAY
保存不可变 Candidate、ReviewDecision、PublishAuthorization、命令与回执，但
本地 `current_release` 或 receipt 镜像 SHALL NOT 成为 serving pointer。

#### Scenario: Harness receipt 不能形成第二个 Head

- **WHEN** Harness 已记录发布命令或 activation receipt，但 WeKnora Active Head
  未完成目标 CAS
- **THEN** 正式读取不切换到该 Candidate，Harness 记录不具 serving authority

### Requirement: D0.13 WeKnora 载体条件接受并可证伪

WeKnora 作为唯一 serving authority carrier SHALL 保持
`ACCEPTED_CONDITIONALLY`，直到 `80a5003` capability gap matrix 与 S0-R
证明整版 manifest、原子激活、幂等、并发单赢家、pinned/release-aware read 和
防旁路写可在有界 patch 内实现。S0-R SHALL 是输入就绪后的两工作日证伪窗口，
终态只能为 `RELEASE_PATH_FEASIBLE` 或
`RELEASE_PATH_NOT_FEASIBLE`；通过不等于生产 Kernel 或 MVP 完成。

#### Scenario: S0-R 不得无限延期或旁路通过

- **WHEN** 输入已冻结且两工作日窗口结束
- **THEN** 输出一个终态及 exact patch/migration/upgrade responsibility；不得
  以未完成继续延期，也不得用未经过目标 preparation/activation/read 路径的 Demo
  声明 feasible

### Requirement: D0.14 MVP cardinality 与 S0-Q 输入保持真实

MVP SHALL 使用 `1 Space = 1 RAW KB + 1 release-managed Wiki KB`，该限制
SHALL 是 MVP profile 而非永久企业不变量。S0-Q 输入 SHALL 来自当前
`80a5003` WeKnora/W1 冻结解析输出，或身份、digest、页码、表格结构和解析版本
完全冻结的等价制品；SHALL NOT 用人工清洗 Markdown 替代真实解析难度。

#### Scenario: 清洗文本不能通过 S0-Q

- **WHEN** 输入在 WeKnora/W1 冻结前被人工重排、去除表格结构或改写为干净
  Markdown
- **THEN** 该运行不得产生
  `KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`

### Requirement: D0.15 legacy 改接与清理按纵切需要执行

S0-R/S0-Q 通过后，首个 MVP PR SHALL 只改接其真实调用入口。旧 publisher、
SnapshotReader、`current_release`、旧表和 migration MAY 冻结留存；SHALL NOT
要求第一个纵切完成全量 legacy 删除。`wiki_projector` 只有在替代 principal
合同冻结后才可移除或改名，物理清理 SHALL 是 MVP 后独立任务。

#### Scenario: 冻结 legacy 不阻断首个纵切

- **WHEN** 首个纵切不导入、不注册也不调用旧 publisher/reader
- **THEN** 旧代码和 migration 的存在不阻断该纵切，且功能 PR 不夹带清理

### Requirement: D0.16 OpenSpec 043 不得按旧投影语义实现

OpenSpec 043 SHALL 保留 Space、principal fail-closed、binding epoch、ACL
等价、跨 Space 拒绝、ABA/concurrency 与失败零写合同；状态 SHALL 为
`SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`。当前 `wiki_projector` 和单
RAW/Wiki projection binding SHALL NOT 直接授权实现。S0-R 独立 OpenSpec
SHALL 先冻结暂定最小发布 principal、MVP binding 与 Release 协议，PASS 后才
形成 043 Amendment。

#### Scenario: 043 不能在 S0-R 前创建 migration

- **WHEN** 043 尚未吸收 S0-R 已验证的 principal/binding/Release 合同
- **THEN** P2d implementation 与预留 migration 0016 保持未开始

### Requirement: D0.17 045 identity 与 Artifact 状态不得合并

治理状态 SHALL 分开记录 upstream capability `80a5003...`、trusted image
build source `a8bf55ae...` 和 current main `529d72c...`。source adoption、
legacy `000066` bridge、trusted images 与 digest pin SHALL 记为 complete；
Full Artifact/W1 runtime probes 与 `source_reader` authority SHALL 保持 open/
blocked，直到各自节点提供真实证据。

#### Scenario: digest pin 不等于 Artifact closure

- **WHEN** app/frontend/docreader 已固定 digest，但 W1 runtime、ACL、zero-write、
  race 或 manifest probe 仍为 planned
- **THEN** 045 不得声明 Full Artifact complete 或 source-reader ready

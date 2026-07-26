# 033 · Production Architecture Reset

> 状态：D0 实施，pre-implementation spec candidate；用户于 2026-07-26
> 最终书面批准生产架构重置方向。本阶段只冻结 OpenSpec 与 planned patch
> inventory，等待独立 Spec Approved 后才进入治理文档改写。
>
> 权威设计源：
> `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
> （受控源 SHA-256
> `e1ef9f2276fbac714c3e5a7398aabab190b8e0dea9229ea35b897ff148c0ae9f`）。
> 本阶段按审查门不复制或修改该设计文件。

## 为什么做

旧路线把强制真人最终批准、filesystem/inode/hardlink 发布原子性、逐页补偿
和通用运行准入堆进知识发布主链，既没有提升知识质量，也让并发与恢复边界
不断扩大。用户已选择近期真实上线并承担并发，因此必须先把生产权威收敛到
共享 PostgreSQL，把 WeKnora 变成受 fencing 保护、可重建的 Wiki 投影，并用
小 PR 分别交付语义、审核、Release、投影和上线能力。

## 本 Change 做什么

- 冻结近期生产架构、权威分层、审核模式、发布事务和 WeKnora patch budget；
- 废弃下列实现路线：
  - 所有生产 Release 强制逐页审核或强制真人最终审批；
  - filesystem、inode、hardlink、rename、fd 或 fsync 作为发布权威；
  - raw RAG、raw chunk 或原始检索作为应用答案的静默 fallback；
  - “绝对零 WeKnora 修改”，改为仅允许 W1/P11/P13/P14 在批准 budget 内
    进行通用、可上游化的最小 patch；
  - 继续更新、rebase、cherry-pick 或重放旧 PR26/28/33、旧 029a 或 031
    runtime 路线；
- 保留并强化：
  - Wiki/Active WikiRelease 是应用知识权威；
  - Evidence、Conflict、版本、不可变 Release、回滚与同 Release 查询；
  - Harness 只通过 WeKnora 版本化 REST 与 Source lifecycle event 集成，不共享
    数据库、Redis 或队列；MCP 仅是后续 Active Query 消费者薄适配器；
  - 生产仅使用经准入的弱模型，强模型不成为生产 fallback；
  - OpenSpec、strict TDD、Contract Card、独立复审与小 PR。

## 明确不做

本 Change 不实现任何 Python/Go/Vue 功能代码，不创建迁移，不运行 provider、
live、PostgreSQL 或 full tests，不修改 WeKnora fork，也不接入旧 029/031
runtime。D0 不定义 Candidate/Release 的生产 DTO 或数据库表；这些分别归后续
小 PR。

## Contract Card

### 单一职责与权威

D0 只拥有治理文档和 planned patch inventory。它不铸造运行时 authority。
生产设计冻结的 serving authority 是 PostgreSQL
`Space.active_release_id + activation_epoch`；Candidate、Decision、投影或
文件制品都不能替代该权威。

### 幂等键与 stale scan

治理入口使用以下大小写不敏感的 exact Rust-regex（单行 UTF-8 输入）：

```text
最终批准|最终审批|人工终审|人工最终|真人批准|真人最终|逐页.{0,24}(审|批)|page/item approve|filesystem|文件系统|inode|hardlink|fsync|rename|逐页.{0,24}补偿|raw[- _]?rag|raw fallback|原始检索.{0,24}兜底|未编译.{0,24}兜底|RAW chunk|绝对零.{0,16}(WeKnora|fork|上游)|零(侵入|分岔|修改|改动|patch).{0,16}(WeKnora|fork|上游)|(禁止|不修改).{0,16}WeKnora|上游代码原则上不改|保险业务逻辑进 WeKnora.{0,8}= 0|fork.{0,16}(禁止|不改|改动)|PR ?#?(26|28|33)|旧 ?PR ?(26|28|33)|\b029a\b|\b031\b|release-manifest-approval|\b0013\b|\b0014\b
```

scanner roots 固定为以下 20 条、有序、repo-relative 路径：

1. `AGENTS.md`
2. `CLAUDE.md`
3. `HANDOFF.md`
4. `docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`
5. `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
6. `docs/insurance-kb/README.md`
7. `docs/insurance-kb/14-deployment-runbook.md`
8. `docs/insurance-kb/16-roadmap.md`
9. `docs/insurance-kb/22-parallel-execution-blueprint.md`
10. `docs/insurance-kb/23-mvp-control-board.md`
11. `openspec/changes/README.md`
12. `openspec/changes/033-production-architecture-reset/proposal.md`
13. `openspec/changes/033-production-architecture-reset/tasks.md`
14. `openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md`
15. `openspec/changes/029-release-manifest-approval-mvp/proposal.md`
16. `openspec/changes/029-release-manifest-approval-mvp/tasks.md`
17. `openspec/changes/029-release-manifest-approval-mvp/specs/release-approval/spec.md`
18. `openspec/changes/032-human-wiki-reader-mvp/proposal.md`
19. `openspec/changes/032-human-wiki-reader-mvp/tasks.md`
20. `openspec/changes/032-human-wiki-reader-mvp/specs/human-wiki-reader/spec.md`

第 5 条在 S0 尚未带入，manifest 必须写入唯一 `PENDING_ROOT` 记录；S1 只能在
Spec Approved 后以权威源内容替换该记录。validation report 是生成证据 sink，
patch inventory 是 machine allowlist，二者明确不作为 scanner roots，避免
self-reference；其内容仍受 path、schema、private/secret 和 absolute-path
门禁。

每个命中归一化为
`CLASS|repo/path:decimal-line|text`：仅接受 UTF-8/LF；行内连续 POSIX whitespace
折叠为一个 ASCII space 并去首尾空白；路径用 `/`；分类只能是大写
`REPLACE | HISTORY | EXPLICIT_NON_GOAL | PENDING_ROOT`；最后按
`LC_ALL=C` 对完整记录排序，以单个结尾 LF 序列化并计算 SHA-256。旧 029/032
六路径固定为 `HISTORY`，033 proposal/tasks/spec 固定为
`EXPLICIT_NON_GOAL`，其余现存 roots 固定为 `REPLACE`。validation report
必须保存全部记录与 hash；同一树运行两次必须逐字相同。任何未在 frozen
manifest 中出现的新记录、缺失记录、分类变化、root 增删或 hash 变化均 fail
closed；只有获批 S1 rewrite 可以生成下一份经独立 review 的 GREEN manifest。

### 威胁矩阵

| 威胁 | D0 冻结的处理 |
|---|---|
| 文档把 Candidate、投影或文件制品误写成 serving authority | 只有 PostgreSQL active pointer + epoch 可提交服务版本 |
| 调用者把 raw 检索包装成已发布答案 | raw 仅证据、审核、补编；应用返回已发布知识不足 |
| 调用者自报 trusted/machine approval | 审核模式由版本化 Space policy 与 exact Candidate/receipt 决定 |
| 旧 Decision 在 ABA 切版后复用 | Candidate/Decision 同时绑定 base release 与 activation epoch |
| 迟到 WeKnora 投影覆盖当前版本 | P11 server-side epoch fencing；投影不是 Release 权威 |
| 任意 fork 修改无限扩大 | 只允许 inventory 中 W1/P11/P13/P14，新增项必须先改 033 并独立批准 |
| 旧分支被当作可合并实现 | 只作历史证据/对抗测试素材，不更新、重放或授予 authority |

### 生产合同冻结

`machine_auto` 只有在 Candidate 精确绑定 P2c registry 中仍有效的
`QualityProfileApproval id/hash`、该 approval 的独立 reviewer receipt 与
append-only revocation generation、`AutomationScopeV1 hash`、完整 run
fingerprint、covered capabilities 和当前 CompilationSecurityProfile id/hash
时才可发布。`AutomationScopeV1` 精确覆盖 Schema、Space、product/version、
source/document profile、parser/chunker、compiler/deployment build、
model/model-plan、prompt、template、canonicalizer/comparator、security
profile、evaluator 与 QualityProfile；run fingerprint 还绑定本次语义输入
manifest 和全部 attempt receipts。Candidate 的每个 required capability 都
必须落在 approval 的 `covered_capabilities`，unsupported/schema-gap、
unresolved entity、Evidence/locator/digest 失败、恶意内容或 ACL/security
失败属于绝对 blocker。任一 approval 缺失/撤销、scope/fingerprint/profile
不匹配、capability 未覆盖或绝对 blocker 存在，ReviewPolicy 必须确定性回落
`human_batch` 并使旧自动 Decision 不适用；caller 的布尔值、标签、相似产品
或模型名称不能恢复自动发布。

Release publication 是一个 PostgreSQL 事务：在同一 Space 串行边界内重验
Candidate base release/activation epoch、policy id/epoch、binding/security 与
Decision，创建不可变 WikiRelease 和成员，以 expected-current CAS 切换
`active_release_id` 并递增 `activation_epoch`，同时写 Outbox。CAS loser 的
publication 事务整体回滚，零 WikiRelease/Outbox；随后用 fresh 同 Space 串行
事务标记 stale 并确定性 requeue，不能复用旧 Decision。不同 Space 可以并行；
Worker/Projector 是 at-least-once，以稳定幂等键、fencing 和 reconciliation 收敛，不宣称 exactly-once。

WeKnora 内部集成只允许版本化 REST 与 Source lifecycle event；Harness 不读取
其 DB、Redis/Asynq 或队列。MCP 不属于 WeKnora control plane，也不用于
Source/投影写入；它只可在后续 P9b 作为 Active Query service 的消费者薄适配器。

### 精确路径预算与 notice-only 规则

D0 总预算固定为 **22 个 logical files/paths**，不得使用目录通配或“相关治理
文档”等开放描述。

pre-implementation S0 只允许以下 **6 路径**：

1. `openspec/changes/README.md`
2. `openspec/changes/033-production-architecture-reset/proposal.md`
3. `openspec/changes/033-production-architecture-reset/tasks.md`
4. `openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md`
5. `openspec/changes/033-production-architecture-reset/validation-report.md`
6. `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`

只有 worktree2 Spec Approved 后，S1 才可**引入**以下 **16 个新路径**：

1. `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
2. `docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`
3. `AGENTS.md`
4. `CLAUDE.md`
5. `HANDOFF.md`
6. `docs/insurance-kb/README.md`
7. `docs/insurance-kb/14-deployment-runbook.md`
8. `docs/insurance-kb/16-roadmap.md`
9. `docs/insurance-kb/22-parallel-execution-blueprint.md`
10. `docs/insurance-kb/23-mvp-control-board.md`
11. `openspec/changes/029-release-manifest-approval-mvp/proposal.md`
12. `openspec/changes/029-release-manifest-approval-mvp/tasks.md`
13. `openspec/changes/029-release-manifest-approval-mvp/specs/release-approval/spec.md`
14. `openspec/changes/032-human-wiki-reader-mvp/proposal.md`
15. `openspec/changes/032-human-wiki-reader-mvp/tasks.md`
16. `openspec/changes/032-human-wiki-reader-mvp/specs/human-wiki-reader/spec.md`

S1 相对冻结 S0 candidate 的 incremental touched-path allowlist 严格为 **19
路径**：上述 16 个新路径，加以下 3 个已计入 S0、因此不增加 D0 unique path
总数的机械控制/证据路径：

1. `openspec/changes/README.md`：只允许 change 注册表及旧计划
   `0013/0014` 的退役状态更新；
2. `openspec/changes/033-production-architecture-reset/tasks.md`：只允许 S1
   checkbox 与 custody/门禁账本更新；
3. `openspec/changes/033-production-architecture-reset/validation-report.md`：
   只允许 GREEN manifest、验证门禁和 final identity 账本更新。

`proposal.md`、033 delta spec 和 patch inventory 在 S1 必须保持冻结 S0
candidate 中、由 validation identity 记录的 blob 不变，不得借 S1 重开合同。

其中只有第 11–16 路径是 notice-only：仅在文件顶部添加 prominent
`SUPERSEDED / HISTORY-ONLY` notice 与新设计指针，历史正文和 checkbox
逐字保持。不得新增或修改任何 031 OpenSpec 文件。`openspec/changes/README.md`
在 S1 还必须把旧计划 migration `0013/0014` 标为
`superseded / not reusable`；D0 不预占替代 migration，后续 owner 从执行时
真实 `origin/main` Alembic head 重新占号。

S0 出现第 7 路径、S1 引入第 17 个新路径、S1 incremental touched 出现第 20
个路径、D0 final unique 出现第 23 路径、上述 3 个 S0 控制/证据路径发生超出
机械账本用途的语义改写、冻结 blob 漂移或 notice-only 正文漂移时，Owner
必须停止并返回 `NEEDS_CONTEXT`。

### 非目标门禁

本阶段功能代码、migration、provider、live、PostgreSQL 和 full tests 均为
`NOT RUN / NOT IMPLEMENTED`。不得用跳过这些运行来宣称生产架构已经交付；本
candidate 只可获得 Spec Approved。

## 依赖与后续

033/D0 是 C0、W0 与 CAP0 的治理前置。独立 Spec Approved 后才允许把权威设计
带入本分支并执行治理文档 C；后续依赖顺序由批准设计的 D0/C0/W0/CAP0 及
Milestone A/B/C DAG 控制，不由旧 PR 状态反推。

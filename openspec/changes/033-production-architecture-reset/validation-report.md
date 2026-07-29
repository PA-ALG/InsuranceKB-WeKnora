# 033 D0 Validation Report

## 2026-07-29 Mission 0 · Authority Amendment 2

> 状态：`PR #67 CORRECTIVE CANDIDATE GREEN / INDEPENDENT SPEC + QUALITY APPROVED`
>
> 本节优先于下方历史 D0-S1 报告。下方旧 PostgreSQL serving authority、
> Projector 与 P11/P12 结论只保留审计价值。

### Identity 与范围

- Mission base / PR base：
  `529d72c994369750b26e352a70fd6284e8b0fd9d`
- PR #67 predecessor head：
  `d7d3c78363f7728abceda81e8f3a71bcc3cdf545`
- predecessor tree：
  `355af7375ac7fadacf8e3accc28f8c8429d029b8`
- branch：`codex/v3-governance-mission0`
- worktree：`.worktrees/v3-governance-mission0`
- corrective delta：13 个 Markdown/治理路径；累计 PR delta：34 个
  Markdown/治理路径
- 功能源码、migration、workflow、deployment lock、principal：零修改
- fresh pre-corrective GitHub readback：PR #67 `OPEN / Draft / MERGEABLE / CLEAN`，
  base/head 与上列一致；status checks 为 0
- corrective commit/push：`NOT YET`；新 exact head/tree 只能在提交后由 GitHub
  PR readback 记录，不能把提交 SHA 自引用进生成该提交的 tracked 文件

### 治理结论

1. 正式线上知识只有一个 serving Active Release authority；WeKnora carrier
   为 `ACCEPTED_CONDITIONALLY`，Harness 不保存第二个 serving Head。
2. 旧 PostgreSQL Active→Outbox→Projector 路线保留 history-only，不授权实现，
   legacy 按首个纵切真实调用改接，物理清理后置。
3. 043 保留 Space/principal/epoch/ACL/跨 Space/失败零写安全合同，但为
   `SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`；migration 0016 不创建。
4. 045 分离 upstream `80a5003...`、trusted build source `a8bf55ae...` 与
   current main `529d72c...`；source/bridge/images/digest pin complete，
   Full Artifact/W1 runtime probes open。
5. S0-R 是输入就绪后的两工作日二元证伪窗口；S0-Q 只接受 WeKnora/W1 冻结
   解析制品；MVP 单 RAW/Wiki cardinality 不是永久企业不变量。
6. 当前运行态是 `NO_PRODUCTION_ACTIVE_RELEASE`。目标 Release Kernel 未实现；
   旧 publisher/reader 虽有公开导出与测试覆盖，但 P3 生产 Worker 未注册发布
   Handler，不构成线上 authority。
7. S0-R 最小 fixture 使用 R0(A/B/C) → R1(A 更新/B 删除/C 不变/D 新增)、同
   base 双 Candidate、preparation/index/CAS/receipt 故障注入、并发
   current/pinned read 与两 principal 的 ACL shrink。单页成功不再能产生
   feasible 结论。
8. S0-R 编码前须由独立 OpenSpec/Mission Card 冻结暂定
   PublishAuthorization/read/ACL 合同与 exact patch/table/migration/upgrade
   预算；Mission 0 未实现或批准生产协议。

### 门禁

- `git diff --check`：PASS
- `openspec validate 033-production-architecture-reset --strict`：PASS
- `openspec validate 043-p2d-space-security-boundary --strict`：PASS
- `openspec validate 045-weknora-80a5003-continuous-adoption --strict`：PASS
- expanded authority scan：根 README、02/03/13、harness README 已加 prominent
  当前规范层级；旧 serving/Projector/publisher 正文只保留 history-only 价值
- cardinality/fixture scan：无未限定 `raw_kb_ids[]`、MVP 多 RAW 或单页
  feasible fixture；唯一“一个页面”命中是拒绝该 false positive 的 Scenario
- OpenSpec CLI PostHog telemetry：网络 flush 失败，不影响本地 validation PASS
- predecessor baseline `openspec validate --all --strict`：31 PASS / 12 个既存
  历史 change FAIL；corrective 只重跑 033/043/045 strict，不扩面修复历史 change
- full/provider/live/PostgreSQL/harness tests：`NOT RUN`（docs-only，按范围）
- predecessor 与 corrective semantic candidate 均由两条本地独立 agent lane
  完成 Spec/Quality review；corrective semantic diff SHA-256 为
  `dc2bed9d726e241d13b60dfd12609da1b4b767d2563242d28af0613a7c171cac`，
  两条 lane 均报告 BLOCKER 0、BACKLOG 0、MAINLINE DRIFT NO、DETAIL TRAP NO
  与 Approved YES。该本地只读复审不等于 GitHub formal Review；PR 当前没有
  GitHub formal review record。

---

> 阶段：D0-S1 governance rewrite whole-candidate
>
> 状态：CORRECTIVE GREEN / PENDING FRESH WHOLE-CANDIDATE INDEPENDENT REVIEW。
> pre-implementation exact tree
> `4d481d07b7cc6889053d0402d7b6023fb7fd8f98` 已获第三轮独立 Spec
> C0/I0/M0 Approved，是本轮唯一 S1 基线。
> 旧 whole-candidate tree
> `7fcc73c7c6a082310089af913b4d4bfcb8ea84c9` 的独立 Spec 结论为
> C0/I4/M0、Not Approved，只保留审计，不再是候选。

## 1. Identity 与 custody

- 执行基线：`origin/main =
  c3a833a482d0c1602f636b8e8df585fd64cb8765`
- 分支：`codex/033-production-architecture-reset`
- 隔离 worktree：`.worktrees/033-production-architecture-reset`
- S0 pre-tree：`4d481d07b7cc6889053d0402d7b6023fb7fd8f98`
- 权威设计源 SHA-256：
  `e1ef9f2276fbac714c3e5a7398aabab190b8e0dea9229ea35b897ff148c0ae9f`
- 用户最终书面批准：`2026-07-26`
- 当前阶段：`D0-S1`；只交付治理文档，不产生运行时 authority。

S1 冻结的 S0 blobs 保持不变：

- proposal：`edec4d7b129fcaa7e1a2ce54982090fe09a67374`
- spec：`e3fa25f7ee6bef6d23080012281ec20ff2382ac2`
- inventory：`e0a910c152cfc261bc316e1caafe1c6f41de745a`

## 2. S1 GREEN 语义账本

1. 批准设计完整带入；相对受控源只改一条状态元数据为“用户最终书面批准
   2026-07-26 / 当前阶段 D0 实施”，其余内容逐字一致。
2. 当前治理入口统一以 PostgreSQL
   `Space.active_release_id + activation_epoch` 为 serving authority；
   Candidate、Decision、文件与 WeKnora 投影均不是权威。
3. `machine_auto`、`human_batch`、`hybrid`、`trusted_import` 均为合法
   ReviewPolicy；自动策略任一 approval/scope/fingerprint/capability/security
   条件不满足时确定性回落 `human_batch`。新 Space 默认 `human_batch`；
   生产 `machine_auto` 只有在 G0b 批准后才能由显式版本化 policy binding
   在 exact scope 内启用。superadmin 只对 exact CandidateRelease 执行
   一次性动作，不能绕过 integrity/ACL/provenance/security。
4. Harness 与 WeKnora 只经版本化 REST + Source lifecycle event 集成；
   WeKnora managed Wiki 是带 epoch fencing、可重建投影；MCP 仅是后续 Active
   Query consumer thin adapter。
5. raw chunk/raw retrieval 只作 Evidence、审核与补编输入，不静默成为应用答案。
6. WeKnora patch budget 只允许 inventory 中 planned
   `W1/P11/P13/P14`；D0 未产生实际 patch。
7. 路线顺序固定为 `D0 → {C0, W0}`、`C0 → CAP0`，随后
   Milestone A/B/C；后续项均 planned/not implemented，文档数、样本数和 worker
   数均是配置或验收样本，不是产品硬上限。22 是 active execution plan，23
   是实时状态/决策板。
8. 旧 029/032 六文件只增加顶部 notice；031 OpenSpec 零修改；旧
   `0013/0014` 标为 `superseded / not reusable`，D0 不占新 migration。
9. change README 的旧并行基线是醒目的
   `SUPERSEDED / HISTORY-ONLY — NOT EXECUTABLE` 历史块；当前入口只指向
   033、批准设计、22、23。CLAUDE 的 AI commit/push 禁令不再含覆盖例外。

## 3. GREEN stale-scan manifest

scanner 的 exact regex、20 roots、UTF-8/LF、空白归一化、C-locale 排序和
fail-closed 规则保持 proposal Contract Card 不变。分类规则如下：

- 旧 029/032 六文件以及 HANDOFF 明确标注的旧正文：`HISTORY`；
- change registry 中显式 `superseded / history-only`、旧路线
  `NOT EXECUTABLE` 块或
  `superseded / not reusable` 的行：`HISTORY`；
- 033 proposal/tasks/spec 与批准设计中用于废弃旧约束、划定非目标、解释风险或
  限定可配置 policy 的命中：`EXPLICIT_NON_GOAL`；
- 其他 root 的任何命中：未分类并 fail closed。

GREEN manifest 共 78 条；不存在 `REPLACE` 或 `PENDING_ROOT`：

```text
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:1015|| D0 架构重置 | 提交本文，修订 AGENTS、CLAUDE.md、北极星和控制板，标记旧 029/031 路线 superseded，并把 WeKnora 改动例外严格限定为 W1/P11/P13/P14 + patch inventory | 功能代码、迁移、无预算 fork 改动 | 仓库不再把文件系统发布、强制人工终审或“绝对零上游改动”作为互相冲突的硬门禁 |
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:1016|| C0 Canonical Envelope | 唯一 RFC 8785/NFC/tagged scalar/domain-separated SHA-256 规范、语言中立 vectors 与 Python reference codec | Go/fork 改动、领域表、Candidate/Release 实现、第二套规范 | Python 与 expected bytes/hash 完全相等；非法 float/sentinel/Unicode 拒绝；W1/P11 后续用同 vectors 验 Go |
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:1042|| P9a Active Query API | 固定 Release 的页面/事实/比较/证据查询、SQL 条件下推和分页 | MCP transport、WeKnora 页面投影 | 不读 Candidate/raw fallback；切版中请求仍单版本；qualifier 缺失不乱选；容量 Profile 通过 |
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:1074|- `human_batch` 只提供 CandidateRelease 级命令，禁止 page/item approve API；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:1189|| 澄清自然语言 Query | **接受** | P9a 是结构化权威；WeKnora Agent/有界 Answer Service 只能消费 P9a 并固定 release，不新增 raw fallback。 |
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:123|- 不复制上传、解析/OCR/chunk 算法、面向用户的原文件系统或 ACL；只为发布证据冻结最小 normalized snapshot，并在 WeKnora 无不可变 pin 能力时保留内容寻址原文件副本；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:126|- 不建立通用 Workflow Engine、通用规则 DSL、部署控制器或文件系统发布事务；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:13|本轮不全面重写 Enterprise LLM Wiki，也不继续修补旧 029/031 的复杂发布与运行控制器。近期目标是：
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:23|- **审核策略可配置**：每个 Space 有版本化默认策略，并可按风险、来源可信度和冲突覆盖；机器高质量、可信结构化来源可自动发布，生产也可配置为必须人工终审；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:53|1. **单个 PR 同时解决过多问题。** 031 把运行准入、文件系统原子发布、进程/FD 生命周期、密钥、恢复和 CLI 放在一个安全边界中，任何新发现都会重开整棵树。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:54|2. **把部署级威胁引入领域请求路径。** inode、hardlink、fd、fsync、fork 等正确性本来不应成为 Wiki Release 的核心事务。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:56|4. **强制人工最终批准被写成硬编码真理。** 它与 MVP 的机器审核自动发布、可信结构化资料批量发布不兼容。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:620|- 成熟生产：强制 Release 级人工最终批准；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:683|文件系统 rename、inode、hardlink、fd、fsync 或跨服务分布式事务都不属于 Release 原子边界。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:693|- 投影失败暴露 freshness/health，不反向修改已提交 Release，也不执行逐页补偿 saga。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:724|P9a 是结构化 Active Knowledge Query：按 entity/predicate/applicability/as-of 查询事实、页面、比较和 Evidence，不负责把任意自然语言问题直接变成最终答案。自然语言体验由 WeKnora Agent 或后续有界 Answer Service 消费 P9a；它在一次请求开始时固定同一 `release_id`，把用户问题映射为已声明的 Schema predicate/qualifier，缺少必要 qualifier 时追问或返回 `needs_qualification`，再基于 P9a 结果组装带 citation 的答案。该消费层不得直接读取 Candidate、原始 chunk 或建立第二条 raw RAG fallback；文档 prompt injection 也不得改变工具集合、release pin 或安全策略。P9b 仍只是把相同结构化服务暴露为 MCP tool。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:766|- 031 式 SQLite budget ledger、PTU、密钥 ceremony、文件系统 operation store；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:869|holdout 的 manifest/hash 进入仓库，expected bundle 由独立质量 runner 以只读受控 artifact 提供，不出现在 feature branch 或 prompt context。一个 holdout version 只用于一次 acceptance decision；运行前不得泄露逐条 expected，报告先只暴露 aggregate 与失败类别。若验收失败并需要逐条反馈，该 holdout 随即退休为 validation 资产，下一次 G0b/G0v 必须使用新的独立 sealed holdout；禁止在同一已泄露 holdout 上反复调参直至通过。最终批准报告绑定 holdout bundle hash、evaluator hash、全部 attempt/run id 和独立 reviewer receipt。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:932|- 逐页人工审核作为默认流程；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:938|- cherry-pick 旧 PR26/28/33 或冻结 029/031 运行时。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:962|- 018 的逐页发布补偿 saga；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:963|- 029 的 filesystem sealing、CLI ceremony 和硬编码真人最终批准；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:964|- 031 的 SQLite/filesystem/PTU/Ed25519 部署控制器；
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:965|- 旧 PR26/28/33 的直接更新、rebase 或重放。
EXPLICIT_NON_GOAL|docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md:9|> 取代范围：本文取代旧北极星设计中关于强制人工终审、文件系统发布原子性、逐页补偿发布和过度运行准入的实现路线；未明确取代的知识语义、Evidence、Conflict、版本和 Release 原则继续有效。
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:15|旧路线把强制真人最终批准、filesystem/inode/hardlink 发布原子性、逐页补偿
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:172|11. `openspec/changes/029-release-manifest-approval-mvp/proposal.md`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:173|12. `openspec/changes/029-release-manifest-approval-mvp/tasks.md`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:174|13. `openspec/changes/029-release-manifest-approval-mvp/specs/release-approval/spec.md`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:184|`0013/0014` 的退役状态更新；
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:195|逐字保持。不得新增或修改任何 031 OpenSpec 文件。`openspec/changes/README.md`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:196|在 S1 还必须把旧计划 migration `0013/0014` 标为
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:25|- 所有生产 Release 强制逐页审核或强制真人最终审批；
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:26|- filesystem、inode、hardlink、rename、fd 或 fsync 作为发布权威；
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:27|- raw RAG、raw chunk 或原始检索作为应用答案的静默 fallback；
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:28|- “绝对零 WeKnora 修改”，改为仅允许 W1/P11/P13/P14 在批准 budget 内
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:30|- 继续更新、rebase、cherry-pick 或重放旧 PR26/28/33、旧 029a 或 031
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:43|live、PostgreSQL 或 full tests，不修改 WeKnora fork，也不接入旧 029/031
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:61|最终批准|最终审批|人工终审|人工最终|真人批准|真人最终|逐页.{0,24}(审|批)|page/item approve|filesystem|文件系统|inode|hardlink|fsync|rename|逐页.{0,24}补偿|raw[- _]?rag|raw fallback|原始检索.{0,24}兜底|未编译.{0,24}兜底|RAW chunk|绝对零.{0,16}(WeKnora|fork|上游)|零(侵入|分岔|修改|改动|patch).{0,16}(WeKnora|fork|上游)|(禁止|不修改).{0,16}WeKnora|上游代码原则上不改|保险业务逻辑进 WeKnora.{0,8}= 0|fork.{0,16}(禁止|不改|改动)|PR ?#?(26|28|33)|旧 ?PR ?(26|28|33)|\b029a\b|\b031\b|release-manifest-approval|\b0013\b|\b0014\b
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:80|15. `openspec/changes/029-release-manifest-approval-mvp/proposal.md`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:81|16. `openspec/changes/029-release-manifest-approval-mvp/tasks.md`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/proposal.md:82|17. `openspec/changes/029-release-manifest-approval-mvp/specs/release-approval/spec.md`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:126|raw chunk、原始向量/BM25 检索和 raw RAG SHALL 只用于 Evidence 核查、人工
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:130|#### Scenario: 无发布知识时禁止 raw fallback
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:138|旧 PR26/28/33、冻结 029/029a 与 031 runtime SHALL 只保留为审计、威胁场景和
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:165|六文件允许 notice-only，031 OpenSpec 文件不得修改。固定 scanner SHALL 冻结
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:186|把旧 029/031/PR 路线标为 superseded/history-only。旧计划 migration
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:187|`0013/0014` SHALL 标为 `superseded / not reusable`，D0 SHALL NOT 预占替代
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:192|#### Scenario: 031 OpenSpec 不得被 notice 扩域
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:194|- **WHEN** S1 scope 检查发现任意 `openspec/changes/031-*` 文件变化
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:30|缺少逐页审批而拒绝 `machine_auto`、`hybrid` 或 `trusted_import`
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:45|执行一次批量批准或拒绝。系统 SHALL NOT 提供 page/item approve API，也不得
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:59|expected-current CAS 并单调递增 epoch。filesystem、inode、hardlink、
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:60|rename、fd、fsync、WeKnora 页面状态或投影完成标记 SHALL NOT 成为 Release
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/specs/production-architecture-reset/spec.md:9|SHALL NOT 把人工逐页操作或真人最终审批硬编码为所有 Space 的共同前置。
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:10|fallback、绝对零 fork patch 和旧 PR/runtime 命中分类为
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:37|`029-release-manifest-approval-mvp/{proposal.md,tasks.md,
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:40|specs/human-wiki-reader/spec.md}`。历史正文与 checkbox 不改；031 OpenSpec
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:44|`0013/0014` 的状态为 `superseded / not reusable`；不预占替代 migration，
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:60|3. notice-only 仅限旧 029/032 六文件；不得新增或修改 031 OpenSpec 历史文件。
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:64|6. 旧 029a、031 和 PR26/28/33 只作历史证据，禁止从其未合并实现复制 authority。
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:6|被忽略；不触碰冻结 029a。
EXPLICIT_NON_GOAL|openspec/changes/033-production-architecture-reset/tasks.md:9|- [x] T2 运行治理入口 RED 扫描，把强制人工终审、filesystem 发布、raw
HISTORY|HANDOFF.md:125|| B3 | B2 产生的分歧/审核队列处理 | 并入 **020 D3**；生产只允许多弱模型证据建议 + 人工最终审核，既有 claude-session apply 路径 production-disabled；回写后重新出分，unresolved 不得静默丢弃 | 视队列量，单条很小 |
HISTORY|HANDOFF.md:154|为大型寿险企业建设 **Enterprise LLM Wiki**：以 WeKnora（本仓库，官方 v0.6.3 零分岔 fork）承载企业平台、权限、解析、检索和页面载体，以插件式 Python Harness 承载可恢复的知识编译与治理，把文档和结构化知识持续编译成原子化、有版本、可溯源、可关联、可进化的 Wiki。目标态 Wiki active release 与同快照 MCP 是人和 Agent 的默认消费权威；P-1 前由 Harness reader 安全承接人类读取，RAW 只作证据/兜底。这是一个**示范性项目**，文档与代码质量要求高于交付速度。
HISTORY|HANDOFF.md:182|1. **总体规划窗口（已完成基线，持续总控）**：027～032 已登记（031 为既有 operational admission），七个实施计划和独立复核已完成；继续只做范围、合同、PR review/merge 与 Roadmap，不写功能代码。
HISTORY|HANDOFF.md:183|2. **当前并行窗口**：S0 实施 027 NS-0；K0 实施 029；既有 031 按独立红队 finding 收口。三者均须原窗口修复、创建/更新 PR，再由总体规划窗口 review。
HISTORY|HANDOFF.md:34|| 当前 Wave | S0=027、K0=029 并发；既有 031 operational admission 单独收口；I0a=030 manifest/fixtures 等 031 窗口释放后接手，I0b admission profile 等 027 |
HISTORY|openspec/changes/029-release-manifest-approval-mvp/proposal.md:10|018 已有 ReleaseSnapshot/SnapshotFact/CurrentRelease 和可恢复 publish/rollback，但缺少完整制品 manifest、绑定完整 hash 的授权人批准和明确的 MVP serving contract。没有它，人和 Agent 同快照与“人工最终审核”无法成为可验证主链。
HISTORY|openspec/changes/029-release-manifest-approval-mvp/proposal.md:28|`knowledge/`、029 tests、唯一 migration 0013；MCP/workbench 只消费公开 service contract，不由本 change 修改。
HISTORY|openspec/changes/029-release-manifest-approval-mvp/specs/release-approval/spec.md:71|#### Scenario: 真人批准后才封存发布证据
HISTORY|openspec/changes/029-release-manifest-approval-mvp/tasks.md:11|- [ ] T6 迁移 0013；SQLite + PostgreSQL focused 验证，合入前重新指向实际 Alembic head
HISTORY|openspec/changes/README.md:38|| 028 | template-compilation-runtime-mvp | ⛔ superseded / history-only | 旧 PR28/runtime 路线不得继续实现、重放或作为生产 authority |
HISTORY|openspec/changes/README.md:39|| 029 | release-manifest-approval-mvp | ⛔ superseded / history-only | 历史规格仅供审计；由 033 后续 Release/Review 小 PR 重新交付 |
HISTORY|openspec/changes/README.md:41|| 031 | operational-run-admission | ⛔ superseded / history-only | 旧 runtime/PR 路线冻结，不更新、不重放、不授予生产 authority |
HISTORY|openspec/changes/README.md:65|| 0013 | 旧 029 计划 | superseded / not reusable；D0 不预占替代 migration |
HISTORY|openspec/changes/README.md:66|| 0014 | 旧 028 runtime 计划 | superseded / not reusable；D0 不预占替代 migration |
HISTORY|openspec/changes/README.md:85|> 分类：`superseded / history-only`；**NOT EXECUTABLE**。以下 027/028/029/030/031/032、NS-0、030 admission 与 HANDOFF MVP-0 路线仅作历史审计，
```

SHA-256：
`615da21de2b7690ab38ed24979d4b06b0d35ca3bb843aa49d604fa10a11aacf9`。
同一候选连续两次扫描必须生成相同的 78 条记录和 hash；任何未分类命中、
`REPLACE`、`PENDING_ROOT`、root 增删或 manifest 漂移均 fail closed。

## 4. 路径与 notice custody

- D0 final unique：严格 22 paths。
- S1 relative pre-tree incremental touched：严格 19 paths（16 new +
  README/tasks/validation）。
- S1 引入：严格 16 paths。
- 031 OpenSpec diff：0 paths。
- proposal/spec/inventory：冻结 blobs 不变。
- 旧 029/032 六文件：只增加完全相同的三行顶部 notice；移除 notice 后，
  blob 必须分别恢复为：
  `355eafc93ef3c0d2d49e6009ebf10355f3e42e6c`、
  `7b0c5c998399e7be7c2db2c1345158dfb8f31b17`、
  `bcd9e50b918fc65c799de43c157c808dc61b54c8`、
  `be1268315e60cc66350327d7efab612d28736821`、
  `331ed0aa394a8d649eca6cf925a6ab597809a8f9`、
  `89c7f02fb373f35eba91ee5cd0ff5cb0bc156c9e`。
- HANDOFF：只增加顶部当前状态块，既有历史正文不改。

## 5. 文档级门禁

- strict OpenSpec 033：PASS，exit 0
- `git diff --check`：PASS，exit 0
- exact22/final、exact19/incremental、16 new：PASS；031 diff = 0
- source-design semantic comparison：PASS；仅第 5 行状态元数据不同
- inventory schema/scope：PASS；仅 W1/P11/P13/P14，全部 `planned`
- stale scan run1/run2/embedded：PASS；78/78/78，SHA-256 均为
  `615da21de2b7690ab38ed24979d4b06b0d35ca3bb843aa49d604fa10a11aacf9`
- UTF-8/LF/private/secret/absolute-path：PASS，22 paths / 0 findings
- notice-only body restore：PASS，6/6 原始 blob 一致
- HANDOFF historical-body restore：PASS，原始 blob
  `e669e5bb96e42a440e5dcf4dba67e8534bf23fe6`
- relative rejected tree corrective scope：PASS，仅
  README、AGENTS、CLAUDE、HANDOFF、22、033 tasks/validation 共 7 路径
- internal Spec self-review：C0/I0/M0，Approved
- internal Quality self-review：C0/I0/M0，Approved
- real index empty / working=temp：PASS；最终 tree/modes/blobs 由独立 temp index
  冻结后作为外部 custody 事实回报，避免报告自引用
- 功能测试/full/provider/live/PostgreSQL：NOT RUN
- 功能代码/migration/实际 WeKnora patch：NOT IMPLEMENTED
- commit/push/PR/Ready/merge：NOT RUN

## 6. 下一阶段门

本 whole-candidate 只可交 worktree2 做独立 Spec review。未经总控后续明确授权，
Owner 不提交、不推送、不建 PR，也不启动功能实现。

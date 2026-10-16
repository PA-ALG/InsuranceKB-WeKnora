# S4c-2a · 候选发布：审核决定、激活为 Release、按 Release 读回

> 状态：已发布（2026-10-15；用户批准新开独立 Space、批准迁移 000006 仅在测试库运行） ｜ 作者：Claude Code
> 依据：蓝图 §4.1、§5.3、§5.4、§6.2、§6.3、§10.2；S3b Spec；2026-10-15 发布链路调研（子任务报告，结论摘入 §2）
> 分支：`slice/s4c2a` ｜ 工作目录：`.worktrees/s4c2a` ｜ 实现方：Claude ｜ 审核方：Codex（Go 平台、持久化、迁移、并发与发布合同）

## 1. 目标

Harness 已能编译出高质量的字段（S4d）。本片让 WeKnora 把一个通用 CandidateBundle 记录审核决定、激活为该 Space 唯一 Head 下的
新 Release，并按 Active 或指定 Release 读回成员——这是"编译 → 发布 → 读取"纵切的平台一半。不新建第二个 Head，不解释成员 payload。

## 2. 现状（调研结论）

- `internal/enterprise/release` 已有 `Receive`（校验、去重存储）与只读 `Preview`；`Store`、`EvidenceResolver` 只有测试实现，没有 decide/activate/read，
  也未接入生产路由（S4c-1 只挂了 source 路由）。
- 现有 Release 权威是 `wiki_release_*` 五张表（000002）：`(tenant_id, space_id)` 唯一 Head；`WikiReleaseRepository.Activate` 在一个事务内写
  preparation（可选）、release、members、Head（CAS 或首建）与 receipt。导出的 service 激活入口都要求 ed25519 签名并绑定 G2/G3 合同，不复用。
- JSONB 不保留原字节；成员行没有 evidence_refs / access_scope 列。
- 一个部署目前只有一个 scope，由 G3、frozen、product ingestion 共用。**用户决定：通用链路使用新的独立 Space，不碰 G3 的 Head。**

## 3. 设计

### 3.1 `internal/enterprise/release`（包内纯逻辑，不 import 旧 service/handler/types）

- 新端口 `Publisher`（与 `Store` 分开，S3b 的 `Store` 不变）：
  - `SaveDecision(ctx, Decision) (Decision, error)`：按 `(tenant, Space, Digest)` 幂等；
  - `DecisionByID(ctx, tenantID, spaceID, id) (Decision, error)`：找不到 → `DECISION_NOT_FOUND`；
  - `ReleaseByID(ctx, tenantID, spaceID, releaseID) (Release, error)`：`releaseID==""` 表示 Active；找不到 → `RELEASE_NOT_FOUND`；
  - `Activate(ctx, ActivationWrite) (Release, error)`：以 `Expected`（release ID + epoch）做 Head CAS；Head 已变 → `RELEASE_CONFLICT`；同一 `Nonce`
    重放返回同一 Release（幂等，不重复激活）。
- 构造：`NewService(store, evidence, schemas, release.WithPublisher(p))`（可选参数，S3b 调用不变）；未配置 Publisher 时新方法返回 `SERVICE_UNAVAILABLE`。
- `Decide(ctx, p, spaceID, candidateID, DecisionInput) (Decision, error)`：
  - 输入 `outcome ∈ {approve, reject, manual}`、`mode ∈ {machine, human}`；`mode=machine` 必须带 `policy_ref`（Harness 的版本化门槛策略标识）；
    可选 `score`（字符串数字）与 `reason`。不合法 → `DECISION_INVALID`。
  - 候选必须存在且属于本 Space；`Digest = sha256(规范 JSON{candidate_id, bundle_digest, outcome, mode, policy_ref, score, reason, subject})`。
- `Activate(ctx, p, spaceID, candidateID, decisionID) (Release, error)`：
  - 决定必须属于该候选且 `outcome=approve`，否则 `CANDIDATE_NOT_APPROVED`；
  - 读当前 Head：候选的 `base_release_id` 必须等于 Head（首次发布时二者都为空）；若候选给了 `base_epoch` 也必须相等；否则 `NEEDS_REBASE`，不写任何东西；
  - 物化：Head 成员 − removals ∪ 候选成员（同 slug 以候选为准）；removal 指向 Head 中不存在的成员 → `CANDIDATE_INVALID`；
  - `Nonce = sha256(candidate_id + ":" + decision_digest)`；调用 `Publisher.Activate`，`Expected` 为本次读到的 Head。
- `Release(ctx, p, spaceID, releaseID) (Release, error)`：按 Active 或指定 ID 读回完整成员（kind、slug、payload 原字节、digest、evidence_refs、access_scope）。
- `Release` 结构：`ID`、`Epoch`、`BaseReleaseID`、`CandidateID`、`DecisionDigest`、`Members []Member`。

### 3.2 平台适配器（新包 `internal/enterprise/releasestore/`）

- 迁移 `migrations/enterprise/versioned/000006_candidates.{up,down}.sql`：
  - `enterprise_candidates`：`id`、`tenant_id`、`space_id`、`bundle_digest`、`contract_version`、`base_release_id`、`raw_bundle`（**BYTEA**，原字节）、
    `created_by`、`created_at`，`UNIQUE(tenant_id, space_id, bundle_digest)`；并发提交用 `ON CONFLICT DO NOTHING` 后读回；
  - `enterprise_decisions`：`id`、`tenant_id`、`space_id`、`candidate_id`、`digest`、`outcome`、`mode`、`policy_ref`、`score`、`reason`、`subject`、`created_at`，
    `UNIQUE(tenant_id, space_id, digest)`；
  - down 迁移删除两表；`packagedEnterpriseMigrationHead` 加 1。
- `Store` 实现读写 `enterprise_candidates`；`Head`/`MembersOf` 读 `wiki_release_heads`/`wiki_release_members`。
- `Publisher.Activate` 调用现有 `WikiReleaseRepository.Activate`，在同一事务插入 Ready preparation（`CandidateDigest=bundle_digest`、
  `ReviewDecisionDigest=decision digest`、ID 与 receipt nonce 由 Nonce 确定）；成员 payload 原字节存 `content`（TEXT），`payload`（JSONB）只作检索；
  读回时用原字节核对 member_digest。evidence_refs 与 access_scope 随成员存入 payload 外层包装字段（不加列）。**不调用 `service/wiki_release.go`、不走签名路径。**
- Space 绑定：新配置 `ENTERPRISE_SPACES`（tenant、space、raw KB、wiki KB 列表），启动时校验与 G3 scope 的 Space 和 wiki KB 都不同；首次激活后用
  `GetHeadForSpace` 交叉核对。请求的 Space 不在配置中 → `RELEASE_ACCESS_DENIED`。
- `EvidenceResolver`：本片冻结引用格式 `source:v1:<knowledge_id>:<parse_attempt>:<file_sha256>`；校验 knowledge 属于该 Space 的 raw KB、修订存在且
  `file_sha256` 一致；逐字回验与字符框定位在 S4c-2b。未知前缀一律 false。同一请求内按 (knowledge, attempt) 缓存。

### 3.3 路由（`internal/enterprise/mount.go`）

在 `/api/v1/enterprise/spaces/:space_id` 下新增：`POST /candidates/:candidate_id/decisions`、`POST /candidates/:candidate_id/activations`
（body `{decision_id}`）、`GET /releases/active`、`GET /releases/:release_id`；策略同 candidates（全权限服务密钥）。生产装配在 router/container 的
现有 enterprise 接缝中注入 Store、Publisher、EvidenceResolver，并在 `docs/design/upstream-patches.md` 追加登记。

### 3.4 不在本片

人工审核队列与界面、自动 rebase、Revert、证据逐字回验与回跳（S4c-2b）、受管范围解析产物必存与来源事件（S4c-2c）、Harness 端提交与读回客户端（单独切片）。

## 4. 验收

- 受保护验收（RED 单独提交）：`internal/enterprise/release/publish_acceptance_test.go`（包内服务，内存 fake）。
- 实现方补：适配器 Postgres 集成测试（`integration_postgres` 标签/现有方式：并发去重、CAS 冲突、幂等重放、原字节读回、跨 tenant/Space 隔离、迁移升降）、
  Mount 级测试（鉴权、错误映射）、Space 配置校验测试。
- Go 受影响包测试相对 S0 失败清单不新增；守卫通过（不往 `service/wiki_release.go` 加代码）；CI 全绿。

## 5. 改动范围

- 允许：`internal/enterprise/release/`、`internal/enterprise/releasestore/`（新）、`internal/enterprise/mount.go` 与其测试、`migrations/enterprise/versioned/000006_*`、
  `internal/database/enterprise_migration.go`（迁移计数）、config 中新增 enterprise Space 配置、router/container 的 enterprise 装配点、`docs/design/upstream-patches.md`（追加）。
- 受保护：本片验收文件、S3b 验收、`docs/design/`、蓝图、`contracts/`。

## 6. 依赖与环境

- 依赖 S4c-1（#158）的 enterprise 路由注册；S4c-1 合并前先完成 §3.1 与 §3.2，路由装配在其合并后 merge main 再做。
- 迁移只在本地与 CI 测试库运行；部署到任何环境另开 Issue 由用户批准。无模型调用。

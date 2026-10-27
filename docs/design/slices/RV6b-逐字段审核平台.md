# RV6b · 逐字段审核（平台）：每个审核点单独决定，批准即上线

> 状态：Claude 2026-10-27 提出 ｜ 作者：Claude Code
> 依据：
> - 用户 2026-10-27 在线上审核页反馈"应该是一个审核点一个审核"，并选择"每个字段单独审"。页面效果按用户所选：按产品分组，每个字段一张卡，批准或拒绝的按钮就在字段旁边；
> - 调研（2026-10-27）：把候选拆成每个字段一份，Harness 要自己登记提交记录、处理重复候选、撤回再重提，9 个产品会拆出 600–750 份。因此**候选不拆，由平台支持按审核点决定**，页面效果相同；
> - RV5a：候选状态读时推导、批准前预检、同一指纹最多一个发布版本（`PublishedCandidate` 与候选锁）；
> - S8b：变基检查，即逐个 slug 比较基础版本与当前 Head。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 真实模型调用：0 ｜ 数据库迁移：**000011**（部署需用户批准）

## 1. 目标

候选进入人工队列后，管理员对其中每个**审核点**单独批准或拒绝。批准一个或几个审核点，立即发布一个只含这些变化的新版本；拒绝只记录决定。所有审核点都有决定后，候选离开待审列表。

机器路由（API Key 的 `Decide` + `Activate`）不变，仍然整份上线。RV5a 的整份审核接口保留，但候选一旦有了审核点决定，就不能再整份审核（§5.3）。

## 2. 审核点

审核点以候选与其**基础版本**（`base_release_id` 指向的版本，没有时为空）的差异为准，与当前 Head 无关，所以候选的审核点集合不会变化：

| 候选中的内容 | 是否审核点 | `kind` |
|---|---|---|
| 成员与基础版本中同 slug 成员的 `member_digest` 相同 | 不是，也不发布（没有变化） | — |
| `kind = "claim"` 的成员，有变化 | 是 | `claim` |
| 非 Claim 成员，基础版本已有这个 slug、内容不同 | 是 | `member` |
| 非 Claim 成员，基础版本没有这个 slug（如新产品的实体、展示配置、导航） | 不是，作为**随附成员**，随每次批准上线（见 §3） | — |
| `removals` 中的每个 slug | 是 | `removal` |

平台只认 `kind == "claim"` 这一个类别，与 RV5a 的 `reviewSummary` 一致，不区分其他类别。

## 3. 批准即上线

一次批准包含同一候选的一批审核点（1–500 个），处理顺序如下：

1. **检查**
   - 候选没有整份决定，也没有整份发布版本，否则返回 409 `CANDIDATE_DECIDED`；
   - 每个 slug 都是这个候选的审核点，否则返回 400 `DECISION_INVALID`；
   - 每个 slug 都还没有决定，否则返回 409 `MEMBER_DECIDED`。
2. **本次涉及的内容**由三部分组成：
   - 这批审核点中的成员；
   - 这批审核点中的移除项；
   - 随附成员中与当前 Head 同 slug 成员内容不同的（包括 Head 没有这个 slug 的）。已经随前一次批准上线、与 Head 相同的随附成员不再涉及。
3. **变基检查**（S8b 规则，范围只限本次涉及的 slug）：每个 slug 在基础版本与当前 Head 中的 `member_digest` 必须相同（两边都没有也算相同），否则返回 409 `NEEDS_REBASE`。移除项还要求 Head 中有这个 slug。不论基础版本是否等于 Head，都做这项检查。
4. **新版本的成员** = 当前 Head 的成员 − 本次的移除项 + 本次涉及的成员（同 slug 替换），使用现有的 `materialize`。
5. **激活**：调用 `Publisher.Activate`，`ActivationWrite` 的各项为：
   - `Expected` = 当前 Head；
   - `CandidateID` = 候选 ID；
   - `BundleDigest` = **批次指纹** = sha256(JSON `[候选 bundle_digest, 排序后的 slug 数组]`)；
   - `Nonce` = sha256(候选 ID + ":" + 批次指纹)；
   - `DecisionID` 与 `DecisionDigest` 由批次内容（候选、slug、结果、理由、决定人）确定，非空；
   - `Points` = 这批审核点的决定。

   Publisher 在**同一个激活事务**里写入这些决定，并把 `ReleaseID` 填为新版本。任一 slug 已有决定时，整个事务回滚，返回 409 `MEMBER_DECIDED`。Head 已被并发移动时，返回 409 `RELEASE_CONFLICT`，什么也不写，由管理员重试。
6. 因此**批准决定只与它的发布版本同时存在**，没有"已批准、未上线"的状态。同一批次重复提交时，按 nonce 或批次指纹返回已提交的版本（RV5a 的幂等规则）。

**拒绝**：调用 `PointStore.RejectPoints`，全部写入或全部不写；任一 slug 已有决定则返回 409 `MEMBER_DECIDED`。拒绝不发布版本。

**必须避开的现有捷径**：`precheckMembers` 与 `Service.Activate` 用 `active.CandidateID == c.ID` 判断"已上线"。按审核点发布的版本，`CandidateID` 也是这个候选，所以按审核点的路径**不能**使用这两个捷径，否则第二批会被当成已上线而直接返回。整份路径保持原样。

## 4. 状态（读时推导，不存储）

**审核点的状态**：
- 有 approve 决定：`released`，`release_id` 取决定上的版本；
- 有 reject 决定：`rejected`；
- 否则 `pending`。
- 候选有整份决定或整份发布版本时，审核点沿用候选的状态：`released`（`release_id` 为整份版本）、`rejected` 或 `approved`。

**候选的状态**：
- 有整份决定或整份发布版本时，沿用 RV5a 的状态，不变；
- 否则：有 `pending` 审核点时为 `pending`；所有审核点都已决定、且至少一个 `released` 时为 `released`；全部拒绝时为 `rejected`；
- 没有任何审核点的候选（例如内容与基础版本完全相同）按 RV5a 的规则处理。

**存储层的边界**：`QueueStore.Queue` 的含义不变，仍按 RV5a 推导：整份发布版本指 `candidate_digest = bundle_digest` 的版本，按审核点发布的版本不算。Service 在这个结果上叠加审核点规则：
- 所有审核点都已决定的候选，从 `pending` 列表移到 `decided` 列表；
- `decided` 列表按最后一次决定的时间倒序，最多 100 条。

**列表与详情**：
- `ReviewSummary` 增加 `point_count`（审核点总数）和 `pending_points`（仍待决定的个数）。不用 `points` 这个名字，因为详情里的 `points` 是审核点列表；
- `release_id` 取该候选最新的发布版本，可以是整份发布的版本，也可以是按审核点发布的版本；
- 一次列表请求中，同一个基础版本只读一次。

## 5. 接口与存储

### 5.1 Go 接口（冻结，验收测试依赖）

```go
// release/points.go
const ErrorMemberDecided = "MEMBER_DECIDED"

// PointDecision is a person's decision on one review point (RV6b). The store assigns ID and
// CreatedAt; ReleaseID is set for approvals, by the activation that wrote them.
type PointDecision struct {
	ID          string    `json:"id"`
	TenantID    uint64    `json:"tenant_id"`
	SpaceID     string    `json:"space_id"`
	CandidateID string    `json:"candidate_id"`
	Slug        string    `json:"slug"`
	Outcome     string    `json:"outcome"` // approve | reject
	Reason      string    `json:"reason"`
	Subject     string    `json:"subject"`
	ReleaseID   string    `json:"release_id"`
	CreatedAt   time.Time `json:"created_at"`
}

// PointStore keeps point decisions. A publisher that also implements it enables point review
// (detected like CandidateReleaseReader). RejectPoints writes all or none; an already decided
// point fails it with ErrorMemberDecided. Approvals are written only by Activate.
type PointStore interface {
	PointDecisions(ctx context.Context, tenantID uint64, spaceID, candidateID string) ([]PointDecision, error)
	RejectPoints(ctx context.Context, decisions []PointDecision) error
}

// ActivationWrite gains: Points []PointDecision — written in the activation transaction with
// ReleaseID set to the new release; an already decided point aborts the activation with
// ErrorMemberDecided. Empty for whole-candidate activations.
```

另外：
- `Service.ReviewPoints(ctx, p, spaceID, candidateID string, slugs []string, outcome, reason string) (PointResult, error)`，结果格式见 §5.2；
- 候选已有审核点决定时，`Service.Decide` 返回 409 `CANDIDATE_DECIDED`（机器路由与 RV5a 整份接口都走这里）。

### 5.2 会话接口（`MountSessionReviews`，只限管理员，规则同 RV5a）

1. `GET /view/candidates/:id` 的详情增加 `points`，按 slug 排序，每项为：
   ```json
   {"slug": "Q/waiting", "kind": "claim" | "member" | "removal",
    "status": "pending" | "released" | "rejected" | "approved",
    "decision": {"outcome", "reason", "subject", "created_at"} | null,
    "release_id": "…" | null, "blocker": ""}
   ```
   `blocker` 是这个审核点单独批准时、按当前 Head 做 §3 第 1–3 步检查的结果（例如 `NEEDS_REBASE`）。已决定的审核点 `blocker` 为空。一次详情请求中，Head 与基础版本各只读一次。
2. `POST /view/candidates/:id/points/decisions`：
   - 请求体严格为 `{"slugs": [...], "outcome": "approve" | "reject", "reason": "..."}`。未知字段、空 slug 数组、重复 slug、超过 500 个时返回 400 `DECISION_INVALID`，什么也不写；理由规则同 RV5a（去掉首尾空白后 1–2000 字）；
   - 返回 201：`{"status": 候选状态, "release_id": 新版本或 null, "epoch": 数字或 null, "points": [{"slug", "status"}]}`。
3. RV5a 的整份接口 `POST /view/candidates/:id/decisions` 保持原样。但候选已有审核点决定时，返回 409 `CANDIDATE_DECIDED`。

`writeError`：`MEMBER_DECIDED` → 409。

### 5.3 存储（迁移 000011）

新表 `enterprise_point_decisions`：

| 列 | 说明 |
|---|---|
| `id` | 主键 |
| `tenant_id`、`space_id` | |
| `candidate_id` | 引用 `enterprise_candidates(id)` |
| `slug` | |
| `outcome` | CHECK `approve` / `reject` |
| `reason`、`subject` | |
| `release_id` | approve 时必填，reject 时为 NULL（用 CHECK 约束） |
| `created_at` | |

唯一键为 `(tenant_id, space_id, candidate_id, slug)`。down 迁移删除这张表；`packagedEnterpriseMigrationHead` 改为 11。

## 6. 改动范围

- `migrations/enterprise/versioned/000011_enterprise_point_decisions.{up,down}.sql`；`internal/database/enterprise_migration.go` 的版本号；
- `internal/enterprise/release/`：新增 `points.go`（审核点、批准、拒绝、状态），以及 `reviews.go`、`publish.go`、`activation.go` 中必要的改动；
- `internal/enterprise/releasestore/`：新表的读写，`Activate` 在事务里写入 `Points`；
- `internal/enterprise/session_reviews.go`、`mount.go`；
- 实现方自己的测试。

不涉及的部分：
- 页面与首页拆分在 RV6c；
- 不改 Harness，不改 `contracts/`；
- 不改 RV5a 的验收测试。

## 7. 验收（RED，Claude 编写，受保护）

### 7.1 `internal/enterprise/session_points_test.go` 与 `session_points_world_test.go`

使用内存平台，在 RV5a 的 `reviewPlatform` 外加一层，实现 `PointStore`，并在 `Activate` 中写入 `Points`。测试场景如下：

- 种子版本：`P/waiting` 90日、`P/grace` 30日、`P/old`、实体 `entity/P`；
- 候选：
  - 改 `P/waiting` 为 180日；
  - `P/grace` 原样带上；
  - 新增 `Q/waiting`、`Q/grace`；
  - 新增 `entity/Q`、`presentation/Q`；
  - 修改 `entity/P`；
  - 移除 `P/old`。

需要覆盖的点：

1. 审核点恰为：
   - `P/waiting` claim、`Q/grace` claim、`Q/waiting` claim；
   - `entity/P` member；
   - `P/old` removal。

   `P/grace`、`entity/Q`、`presentation/Q` 不是审核点。
2. 批准 `Q/waiting`：
   - 新版本含 `Q/waiting`、`entity/Q`、`presentation/Q`，不含 `Q/grace`；
   - `P/waiting` 仍为 90日，`P/old` 仍在；
   - 候选仍在待审列表，`pending_points` 为 4。
3. 再批准 `Q/grace`：成功，不报 `NEEDS_REBASE`，`entity/Q` 没有变化。
4. 拒绝 `P/waiting`：Head 不动。再次决定返回 409 `MEMBER_DECIDED`。
5. 以下请求返回 400 `DECISION_INVALID`，且什么也不写：
   - 不是审核点的 slug；
   - 重复 slug、空数组；
   - 未知字段。
6. 一次批准 `entity/P` 与 `P/old`：
   - 候选离开待审列表，进入已处理列表，状态 `released`，`release_id` 为最新版本；
   - 新版本中 `P/old` 已移除，`entity/P` 为新内容。
7. 全部审核点都拒绝：候选状态为 `rejected`。
8. 另一份候选先把 `P/waiting` 改成 120日并上线：
   - 详情中 `P/waiting` 的 `blocker` 为 `NEEDS_REBASE`，批准它返回 409，并且没有写入决定；
   - `Q/waiting` 仍能批准。
9. 另一份候选先上线了内容不同的 `entity/Q`：批准 `Q/waiting` 返回 409 `NEEDS_REBASE`。
10. 有审核点决定之后：
    - 整份接口返回 409 `CANDIDATE_DECIDED`；
    - API Key 的 `Decide` 也返回 `CANDIDATE_DECIDED`。
11. 非管理员、服务密钥、其他租户的访问被拒绝，规则同 RV5a。

### 7.2 `internal/enterprise/releasestore/point_decisions_postgres_test.go`（PostgreSQL）

1. 带 `Points` 的激活：决定与版本同时写入，`release_id` 正确。
2. 第二次激活的 `Points` 含已决定的 slug：返回 `MEMBER_DECIDED`，Head 与版本数都不变。
3. `RejectPoints`：
   - 其中一个已有决定时，全部不写；
   - 并发拒绝同一个 slug，只留下一条。
4. 同一批次重复激活，只得到一个版本。

### 7.3 其他

以下改动都在 RED 提交内完成：
- `internal/database/enterprise_migration_head_test.go` 中的版本改为 11；
- `releasestore/store_postgres_test.go`：
  - `openSchema` 加上 000011，因为 `Decide` 要读审核点决定；
  - 000006 的回滚测试先回滚 000011，因为审核点决定引用候选。

**门禁**：
- `go build ./...`；
- `go test ./internal/enterprise/... ./internal/database/...`；
- PostgreSQL 测试由 CI 运行；
- 架构守卫。

## 8. 上线

与 RV6c（页面）和 S5b-3d-2（打开原文件，迁移 000012）一起部署，部署前请用户批准。

迁移回滚的顺序：
1. 先执行 down SQL，把迁移记录退回 10；
2. 再换回旧镜像。旧 App 不接受更高的迁移版本，见 #344。

线上现有的人工候选（594/596 与 S12 的 7 个）都没有整份决定，部署后可以直接逐点审核。

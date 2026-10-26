# RV5a · 人工审核队列（平台）：列出待审候选、查看内容、批准或拒绝

> 状态：Claude 2026-10-26 提出 ｜ 作者：Claude Code
> 依据：
> - 蓝图 §6.3："< 门槛 / 冲突 / 版本歧义 → 人工队列，暂不上线"；
> - RV1：路由为人工时，发布命令只提交候选，不做决定、不激活。所以队列里的一项，就是一个还没有决定、也没有发布的候选；
> - S8b：激活时自动变基，被别的版本改过的成员拒绝（`NEEDS_REBASE`）；
> - S9a：浏览器会话在进程内调用 Receive → Decide → Activate 发布（`expert/service.go`），本片沿用这种做法；
> - S5b-3a/3b：会话列表与会话写入的做法（`/view` 路由、管理员复核、严格请求体）。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 真实模型调用：0 ｜ 数据库迁移：无

## 1. 目标

今天，路由为人工的候选（例如 594、596 的两份补全）提交后，没有任何地方能看到或处理它们：平台没有列出候选的接口，前端也没有页面。本片补上平台一侧，下一片 RV5b 做页面：

1. 管理员能按状态列出 Space 的候选；
2. 能读出一个候选的全部内容（成员、移除项、当前能否上线）；
3. 能批准（记录人工决定并激活，生成新的发布版本）或拒绝（只记录决定）。

不改合同（`contracts/`）、不改 Harness、不加数据库迁移。

## 2. 候选的状态（读时推导，不存储）

对 Space 中的候选 C（同一 tenant、同一 Space）：

1. **`released`**：这个 Space 有一个发布版本的 `candidate_digest` 等于 C 的 `bundle_digest`；`release_id` 取该版本。
2. 否则看 C 最新的一条决定（按 `created_at`、再按 `id`）：
   - `approve` → **`approved`**：已批准但没有发布（激活被拒，例如 `NEEDS_REBASE`）；
   - `reject` → **`rejected`**；
   - `manual` → **`pending`**。
3. 没有决定 → **`pending`**。

机器自动上线的候选、专家修订生成的候选都已发布，状态是 `released`，出现在"已处理"一侧，不进待审列表。

列表分两种：
- `pending`：只含 `pending`，按 `created_at`、`id` 升序（先来先审），全部返回；
- `decided`：含 `approved`、`rejected`、`released`，按 `created_at`、`id` 降序，最多 100 条。

## 3. 存储接口

在 `internal/enterprise/release` 中新增（名称冻结，验收测试使用）：

```go
// QueueEntry is one candidate of a Space with its derived review status (RV5a §2).
type QueueEntry struct {
	Candidate Candidate // Status holds the derived status: pending, approved, rejected, released
	CreatedAt time.Time
	CreatedBy string
	Decision  *Decision // the latest decision, nil when none
	ReleaseID string    // the release this candidate became, "" unless released
}

// QueueStore lists the candidates of one Space by derived status. status is "pending" or
// "decided"; limit bounds the decided list (§2). Records of other tenants or Spaces never appear.
type QueueStore interface {
	Queue(ctx context.Context, tenantID uint64, spaceID, status string, limit int) ([]QueueEntry, error)
}
```

- `releasestore.Store` 实现 `QueueStore`：一次 SQL 取出候选、最新决定与对应发布版本，不逐条查询；
- `release.Service` 像 `ReferenceReader` 一样，在构造时检查 store 是否实现 `QueueStore`。没有实现时，下面的接口返回 `SERVICE_UNAVAILABLE`；
- `Decision` 需要带上 `CreatedAt`（存储已有该列）。

## 4. 会话接口

挂在 `/api/v1/enterprise/spaces/:space_id/view` 下，由新的 `enterprise.MountSessionReviews(r gin.IRouter, deps SessionDeps, guards ...gin.HandlerFunc)` 注册。

**访问规则（三个接口相同）**：
- 只接受浏览器会话（`checkSessionRead`）。带 API Key 的请求返回 403 `RELEASE_ACCESS_DENIED`；
- Space 检查同其他 `/view` 路由：未配置的 Space、其他租户的 Space 返回 404；
- 调用方提供管理员与 Wiki 编辑者的路由守卫（`router.go` 中与待确认材料的回答相同）。处理函数里再检查一次 `TenantRoleAdmin`，非管理员返回 403 `RELEASE_ACCESS_DENIED`，以防路由权限只记日志。读取也要管理员：候选是尚未发布的内容。

### 4.1 `GET /candidates?status=pending|decided`

- 不带 `status` 时按 `pending`；其他取值返回 400 `DECISION_INVALID`；
- 返回 200 `{"success": true, "data": {"items": [...]}}`，每一项：

```json
{
  "candidate_id": "cand_…", "created_at": "2026-10-26T08:00:00Z", "created_by": "svc-harness",
  "base_release_id": "rel_…", "status": "pending",
  "subjects": ["594"], "members": 3, "removals": 0,
  "decision": null, "release_id": null
}
```

- `subjects`：候选中 Claim 成员 `payload.subject_ref` 去重后排序；`members`、`removals` 是数量；
- `decision` 不为空时是 `{"decision_id", "outcome", "mode", "reason", "subject", "created_at"}`。

### 4.2 `GET /candidates/:candidate_id`

返回 200，`data` 在 4.1 那一项的基础上增加：
- `head_release_id`：当前 Head，没有时为 `null`；
- `blocker`：
  - `""`：现在批准可以上线；
  - 预检（见 4.3）失败时的错误码，例如 `"NEEDS_REBASE"`（当前 Head 改过了候选涉及的成员，按 S8b 的规则判断）、`"CANDIDATE_INVALID"`（候选移除的成员当前不存在等，成员合成失败）：批准也无法上线（审核 R2）；
  - `"CANDIDATE_DECIDED"`：状态是 `rejected` 或 `released`；
- `bundle_members`：候选中的成员，原样返回 `kind`、`logical_slug`、`payload`、`member_digest`、`evidence_refs`、`access_scope`；
- `bundle_removals`：移除的 slug 列表。

页面用这些成员与当前发布版本（已有的会话读取接口）对比，显示新旧取值与引文。

不存在、属于其他 Space 或其他租户的候选：404 `CANDIDATE_NOT_FOUND`，不暴露内容。

### 4.3 `POST /candidates/:candidate_id/decisions`

请求体严格为 `{"outcome": "approve" | "reject", "reason": "…"}`：
- 有未知键、重复键、类型错误，或 `outcome` 是其他值：400 `DECISION_INVALID`；
- `reason` 去掉首尾空白后为空，或超过 2000 个字符：400 `DECISION_INVALID`；
- 请求体上限 64 KiB。

| 当前状态 | `approve` | `reject` |
|---|---|---|
| `pending` | 预检通过后记录 `{approve, human, reason}`，再激活 → 201 | 记录 `{reject, human, reason}` → 201 |
| `approved` | 预检通过后用最新的那条 approve 决定再激活一次 → 201 | 409 `CANDIDATE_DECIDED` |
| `rejected`、`released` | 409 `CANDIDATE_DECIDED` | 409 `CANDIDATE_DECIDED` |

- 决定的 `subject` 是会话用户（`Principal.Subject`），`mode` 一律为 `human`；
- 201 返回 `{"decision_id", "status", "release_id", "epoch"}`。拒绝时 `release_id`、`epoch` 为 `null`，`status` 为 `rejected`；批准成功时 `status` 为 `released`；
- **预检**（审核 R2）：批准前按当前 Head 做一次激活前的全部检查，包括 S8b 变基检查和成员合成（移除项、成员冲突等），但不写入。
  - 预检失败：返回该错误码与原有的状态码（`NEEDS_REBASE` 409、`CANDIDATE_INVALID` 400 等），**不写决定**，状态保持不变。页面提示"内容已过期或无法合并，需要重新编译"，此时只能拒绝；
  - 预检通过后才记录决定并激活。之后的激活失败只可能来自并发（例如预检后 Head 又被移动），这时返回该错误码，已记录的决定保留，状态为 `approved`，可以再次批准重试；
- **同一候选最多生成一个发布版本**（审核 R1）：`Publisher.Activate` 在写入 Head 的同一事务里检查本 Space 是否已有由这个候选（同一 `bundle_digest`）生成的版本。有则不再生成，返回已有的那个版本，与 nonce 重放相同。
  - 这条规则在变基检查之前生效，对 API Key 的激活同样适用；
  - 内存实现也要遵守；
  - 两个管理员同时批准时，两条决定都会保留，只有一个版本。内容与当前版本相同的"空变化"候选也不会因为第二条决定再发布一次；
- 失败时（400 请求错误、403、404、`CANDIDATE_DECIDED`、预检失败）不写任何决定。

`writeError` 增加 `CANDIDATE_DECIDED` → 409。

## 5. 改动范围

- `internal/enterprise/release/`：`QueueEntry`、`QueueStore`，`Decision.CreatedAt`，`Service` 中列出、详情与决定的方法（名称由实现方定）；
- `internal/enterprise/releasestore/`：`Store.Queue`；`Activate` 在同一事务里检查同一候选是否已发布（审核 R1）；
- `internal/enterprise/release/publish.go`：`Publisher` 接口说明补上"同一候选最多一个版本"；批准前预检复用激活的检查（审核 R2）；
- `internal/enterprise/session_reviews.go`（新）：`MountSessionReviews` 与三个处理函数；`mount.go` 的 `writeError` 增加映射；
- `internal/router/router.go`：挂载 `MountSessionReviews`，守卫与待确认材料的回答相同。该文件已登记为上游补丁，不新增补丁文件；
- 实现方自己的测试。

## 6. 不在本片范围

- 页面（RV5b）；
- 编排命令报告中带出候选编号（并入 S5b-5，Harness 一侧）；
- 增量判定中的冲突项：它们只写在 Harness 本地，不在平台上（S8a）；
- 候选引文打开原文：引文接口按发布版本校验，候选还没有版本，本片只返回成员中自带的引文（`quote`、定位）。打开原文另开切片；
- 索引与分页：目前候选数量在几百以内，`decided` 列表限 100 条。数量增长后再加迁移。

## 7. 验收（RED，Claude 编写，受保护）

1. `internal/enterprise/releasestore/review_queue_postgres_test.go`（需要 `WEKNORA_TEST_POSTGRES_URL`，CI 的 enterprise-postgres 任务运行）：
   - 四种状态各自推导正确；有多条决定时取最新一条；
   - `pending` 升序全返回，`decided` 降序且受 `limit` 限制；
   - 其他租户、其他 Space 的候选不出现；
   - 同一候选用两条不同的批准决定激活两次，只有一个版本，第二次返回同一个版本（审核 R1）。
2. `internal/enterprise/session_reviews_test.go`（内存平台）：
   - 列表与详情的字段（含 `subjects`、`blocker`、`bundle_members`）；
   - 批准：生成新版本，待审列表变空，已处理列表中为 `released`；
   - 拒绝：不生成版本，状态 `rejected`；
   - 再次决定返回 409 `CANDIDATE_DECIDED`；
   - Head 改过同一成员：详情 `blocker` 为 `NEEDS_REBASE`；批准返回 409 `NEEDS_REBASE`，不写决定、状态仍为 `pending`，之后可以拒绝（审核 R2）；
   - API Key、非管理员、其他租户、未配置的 Space、不存在的候选、错误请求体：各自的状态码与错误码，且不写决定。

**门禁**：
- `go build ./...`；`go test ./internal/enterprise/...`（不新增失败）；PostgreSQL 测试由 CI 的 enterprise-postgres 任务运行；
- 架构守卫（`pytest -q tests/architecture`）；`router.go` 的挂载在审核时核对。

## 8. 上线

合并后随下一次 App 部署上线（部署需用户批准）；没有迁移。页面在 RV5b。

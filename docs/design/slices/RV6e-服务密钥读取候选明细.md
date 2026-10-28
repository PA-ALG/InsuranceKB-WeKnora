# RV6e · 服务密钥读取候选明细

> 状态：Claude 2026-10-28 提出 ｜ 作者：Claude Code
> 依据：
> - RV7（PR #413）审核意见 R3：`close` 只凭 slug 和调用者给的候选编号拒绝审核点，从不读取目标候选的内容。评委拒绝的是"90日"，同 slug 的遗留候选实际提议的却可能是"180日"，结论会被套到没审过的内容上。`close` 必须先读出目标候选每个 slug 的成员内容，与本批评审的版本核对。
> - 现有服务密钥接口读不到待审候选的成员：RV6d 的队列只给数量，预览只给 slug 分组。成员内容和审核点状态只有浏览器会话的 `GET /view/candidates/:candidate_id` 能读。
> - 依赖 RV6b（`Service.ReviewCandidate`、审核点视图）和 RV6d（服务密钥候选接口的授权方式）。
>
> 实现方：Claude ｜ 审核方：Codex ｜ 真实模型调用：0 ｜ 数据库迁移：无

## 1. 目标

给全权限服务密钥增加一个只读接口，读取一份候选的明细，内容与会话接口完全相同。这样机器通道在关闭审核点前，能核对候选里每个 slug 的实际内容。

## 2. 接口（`enterprise.Mount`，API Key，`RequireFullAccess`）

`GET /spaces/:space_id/candidates/:candidate_id`

- 调用 `Service.ReviewCandidate`，主体为服务密钥的主体；返回 200，`data` 与会话接口返回的 `ReviewDetail` 相同：
  - 候选摘要：`candidate_id`、`status`、`point_count`、`pending_points` 等；
  - `bundle_members`：每个成员带 `payload` 与 `member_digest`；
  - `bundle_removals`；
  - `points`：每个审核点的 `status`、`decision`、`blocker`；
  - `head_release_id` 与候选的 `blocker`。
- 只读：不写决定，不改 Head。
- 错误沿用 RV6d：
  - 其他 Space 的候选或不存在的候选返回 404 `CANDIDATE_NOT_FOUND`；
  - 没有密钥返回 401；
  - 只有检索能力的密钥、按知识库限定的密钥、浏览器会话都返回 403；
  - 服务未配置返回 503。

## 3. Harness：`PlatformClient.review_detail(space_id, candidate_id)`

- 返回 `CandidateDetail`。模型放在 `bundle/candidate_reviews.py`，因为 `client.py` 已接近 500 行。
- 解析规则：
  - 字段类型严格校验；
  - `bundle_members` 与 `bundle_removals` 为 `null` 时按空列表处理（平台对省略的列表输出 `null`）；
  - 以下情况返回 `INVALID_RESPONSE`：返回的 `candidate_id` 不是所请求的；成员 slug 重复；审核点 slug 重复。
- 失败码沿用 `_send`。

## 4. 改动范围

- `internal/enterprise/mount.go`：只增加一条授权登记和一条路由；
- `internal/enterprise/api_reviews.go`：一个处理函数；
- `harness/src/insurance_harness/bundle/candidate_reviews.py`（新文件）与 `bundle/client.py`：模型与方法；
- 实现方自己的测试。

不改 release 服务、存储、迁移、页面和 `contracts/`。

## 5. 验收（RED，受保护）

**Go**：`internal/enterprise/api_candidate_detail_test.go`。使用 RV6b 的内存审核点平台，经真实的 `middleware.Auth` 与 `APIKeyRouteAuthorizer` 访问：

1. 全权限密钥读取待审候选：
   - 返回内容与会话接口相同；
   - 成员的 `payload` 与 `member_digest` 与提交时一致；
   - 可以看到删除项、5 个待审审核点和 `head_release_id`；
   - 读取不写任何决定。
2. 机器拒绝一个点后再读取：该点为 `rejected`，带决定理由；候选的 `blocker` 为 `CANDIDATE_DECIDED`。
3. 其他 Space 的候选、不存在的候选返回 404 `CANDIDATE_NOT_FOUND`。
4. 访问控制：
   - 服务未配置返回 503；
   - 没有密钥返回 401；
   - 两种受限密钥返回 403；
   - 管理员浏览器会话返回 403 `RELEASE_ACCESS_DENIED`。

**Harness**：`harness/tests/bundle/test_candidate_detail.py`，用假 HTTP：

1. 请求路径与密钥头正确，解析出成员、删除项、审核点；
2. `null` 列表按空列表处理；
3. 以下情况返回 `INVALID_RESPONSE`：
   - 候选编号不符；
   - 成员 slug 重复；
   - 审核点 slug 重复；
   - 字段类型错误；
4. 平台的 404 映射为 `CANDIDATE_NOT_FOUND`；非法编号在发请求前返回 `INVALID_REQUEST`。

**门禁**：
- `go build ./...`；
- `go test ./internal/enterprise/...`；
- golangci-lint 只检查新代码；
- Harness `uv run pytest`、`ruff`、`mypy`；
- 守卫；
- `git diff --check`。

## 6. 上线

随下一次 App 部署上线。RV7 合入 main 后，`close` 改为先用 `review_detail` 核对内容（在 #413 中完成）。

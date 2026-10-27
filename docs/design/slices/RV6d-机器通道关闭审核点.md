# RV6d · 机器通道关闭审核点：服务密钥列出审核队列、拒绝审核点

> 状态：Claude 2026-10-27 提出 ｜ 作者：Claude Code
> 依据：
> - 用户 2026-10-27 的两条指示：
>   - "需要审核的太多了，这版你借助 gpt6.0 或者 opus5.5 直接判断吧"；
>   - "你全部决定吧，不要我来批准了，按照你的判断标准来，尽快推进"。
> - 模型评审（GPT-6 Astra，运维 Issue #384）批准的审核点已经走机器通道上线：做法是重新打上机器审核标签，生成新候选。但人工队列里还剩下几份候选无法收尾：
>   - 594：本地没有它的候选编号；
>   - 596、2647：这两份已经有逐点决定，RV6b 规定这种候选不能再整份决定（`CANDIDATE_DECIDED`）。
>   
>   目前逐点决定只有浏览器会话能做，而服务密钥没有会话。
> - 依赖 RV6b：审核点、`ReviewQueue`、`ReviewPoints`。
>
> 实现方：Claude ｜ 审核方：Codex ｜ 真实模型调用：0 ｜ 数据库迁移：无

## 1. 目标

给全权限服务密钥（与其他候选接口同一策略）增加两个接口，让机器通道也能清理人工队列：

1. 列出审核队列，用来找到候选编号以及剩余的审核点数。
2. 拒绝审核点，用来关闭被评委拒绝的点，以及已由机器候选取代的点。

**机器通道只能拒绝，不能批准审核点。** 机器批准的内容一律通过新的机器候选上线（RV1 的 `labelled`，claim 的 review 标签为 `mode=machine` 并带 `policy_ref`），已发布 claim 上的审核来源因此始终如实。如果直接批准原候选里的审核点，原候选按人工路由打的标签会原样上线，变成"机器批准却标着人工"。拒绝不发布任何内容，不存在这个问题。

## 2. 接口（`enterprise.Mount`，API Key，`RequireFullAccess`）

1. `GET /spaces/:space_id/candidates?status=pending|decided`
   - 与会话接口 `GET /view/candidates` 返回相同的列表（`Service.ReviewQueue`，包含 `point_count`、`pending_points`）；
   - 不带 `status` 时为 `pending`；`status` 其他取值返回 400 `DECISION_INVALID`。
2. `POST /spaces/:space_id/candidates/:candidate_id/points/decisions`
   - 请求体严格为 `{"slugs": [...], "outcome": "reject", "reason": "...", "policy_ref": "..."}`；
   - `outcome` 只能是 `reject`，其他值返回 400 `DECISION_INVALID`；
   - `policy_ref` 去掉首尾空白后为 1–200 个字符；
   - 理由的规则同 RV6b，但存储的理由是 `<reason>（policy_ref: <policy_ref>）`。拼接后总长度仍须在 2000 字以内，否则返回 400。本切片不加迁移，所以 policy 只能放进理由里保存；
   - 决定人为服务密钥的主体；
   - 其余规则（审核点范围、`MEMBER_DECIDED`、`CANDIDATE_DECIDED`、未知字段）完全沿用 `Service.ReviewPoints`；
   - 返回 201，格式同 RV6b 会话接口。

访问控制沿用 `Mount` 现有规则：
- 没有密钥返回 401；
- 只有检索能力或按知识库限定的密钥返回 403；
- 浏览器会话不经过这组路由。

## 3. 改动范围

- `internal/enterprise/mount.go`：只增加两条授权登记和两条路由；
- 新文件 `internal/enterprise/api_reviews.go`：两个处理函数；
- 实现方自己的测试。

不改 release 服务、存储、迁移、页面和 Harness。

## 4. 验收（RED，受保护）：`internal/enterprise/api_points_test.go`

使用 RV6b 的内存审核点平台，经真实的 `middleware.Auth` 与 `APIKeyRouteAuthorizer` 访问：

1. 全权限密钥能列出待审候选，`point_count`、`pending_points` 正确；`status=decided` 列出已处理的；非法 `status` 返回 400。
2. 拒绝一个审核点：返回 201；存储的理由带 `（policy_ref: …）`，决定人为服务密钥的主体；Head 不变。
3. 用 `approve` 返回 400 `DECISION_INVALID`，并且什么也不写。
4. 以下请求返回 400，并且什么也不写：缺少或为空的 `policy_ref`、超过 200 个字符的 `policy_ref`、未知字段、缺少理由。
5. 已决定的点返回 409 `MEMBER_DECIDED`；其他 Space 的候选返回 404。
6. 用机器拒绝全部剩余审核点后，候选离开待审列表，状态为 `rejected`。
7. 访问控制：没有密钥返回 401，受限密钥返回 403，服务未配置返回 503。

**门禁**：
- `go build ./...`；
- `go test ./internal/enterprise/...`；
- golangci-lint 只检查新代码；
- 守卫。

## 5. 上线

随下一次 App 部署上线（用户已授权 Claude 决定部署）。上线后，运维脚本用这两个接口关闭 594、596、2647 剩下的审核点，结果记录在 #384。

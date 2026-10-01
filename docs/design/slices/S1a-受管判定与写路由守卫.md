# S1a · 统一受管判定与全部写路由守卫

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §7.5、§8（G7）、§11（S1）
> 分支：`slice/s1a` ｜ 开工方式：写完计划即开工 ｜ 真实模型调用：不需要
> S1b（读入口按 Release 读取）另开一片，不在本片范围。

## 1. 目标

让"受管知识库的内容只能经发布链修改"成为运行时事实：受管判定只有一个实现，原生 `/wiki` 下
**所有**写路由（含 Agent 工具与 MCP 写工具）在受管库上一律被拒，且分类失败时失败关闭。

## 2. 现状问题

1. 判定有三套且结论可能不一致：
   - 配置判定 `NativeWikiWritesDisabled`（`internal/config/product_ingestion.go:29-36`），只看单个静态 scope，只被摄取链使用；
   - Head 判定 `RejectManagedWikiWrite`（`internal/handler/wiki_release.go:345`），只看 Wiki 侧且要求已激活；
   - custody 判定 `hasConceptReleaseCustody830G2`（`internal/application/service/concept_agent_830_g2.go:146-177`），覆盖 RAW 侧与激活前，但目前只有 Agent 用。
2. 原生 `/wiki` 下 5 条写路由未挂守卫：`POST /pages`、`POST /revert`、`POST /folders`、`POST /rebuild-links`、`POST /auto-fix`。
3. 已挂守卫的 6 条只在 `releaseHandler != nil` 时生效；旧包装 `RegisterWikiPageRoutes`（`routes_knowledge.go:396`）传 `nil`，走它注册就完全没有守卫。
4. 判定只覆盖 Wiki 侧；同时作为 RAW 的库可能在检索之外仍被视为可写。

## 3. 设计

### 3.1 新增 `internal/enterprise/managed`（Go）

```go
type Kind string    // KindNone | KindWiki | KindRaw
type State string   // StateUnmanaged | StatePending | StateActive

type Role struct {
    Kind  Kind
    State State
    Scope *types.WikiReleaseScope
}

type Classifier interface {
    Classify(ctx context.Context, tenantID uint64, kbID string) (Role, error)
}

func NewClassifier(heads HeadLookup, custody CustodyLookup) Classifier

// 错误码常量，验收测试按这些名字断言，命名不得更改：
const (
    ErrorCodeReleaseManaged             = "RELEASE_MANAGED_KB"
    ErrorCodeClassificationUnavailable  = "MANAGED_KB_CLASSIFICATION_UNAVAILABLE"
)
```

错误响应沿用现有信封 `{"success": false, "error": {"code": ..., "message": ...}}`（见
`internal/handler/wiki_release.go:402` 附近的 `writeWikiReleaseError`）。

- **判定规则**：一个 KB 只要属于某个 release scope（Wiki 侧或 RAW 侧任一），即受管。
  - `StateActive`：该 scope 已有 Active Head。
  - `StatePending`：scope 已存在（preparations/releases/receipts 任一有行）但尚无 Active Head。
  - `KindWiki` / `KindRaw` 表示它在该 scope 中的角色；同时属于两侧时 `KindWiki` 优先，判定结论不变。
- **裁决（2026-10-01 用户批准）**：受管自 scope 存在起生效，激活前同样拒绝普通写。理由：激活前写入的内容没有来源与审核记录，第一次发布时会被当成已有内容。
- **失败关闭**：查询出错或 tenant 缺失时返回 error，调用方返回 503，不放行。
- 数据来源：复用现有 `GetHeadForWikiKB`（`internal/application/repository/wiki_release.go:568`）与四表 custody 并集（`heads`、`preparations`、`releases`、`receipts`）。不新建表。

### 3.2 统一守卫中间件

```go
func (c Classifier) GuardWikiWrite() gin.HandlerFunc
```

- 取 `tenant_id`（缺失即 503）与路径参数 `kb_id`（缺失即 400）。
- `Classify` 出错 → 503，错误码 `MANAGED_KB_CLASSIFICATION_UNAVAILABLE`。
- 受管 → 409，错误码 `RELEASE_MANAGED_KB`，消息说明"该知识库内容由发布链管理，请经编译与审核流程修改"。
- 未受管 → 放行。
- **必须排在 RBAC 之前**：受管库的写请求不应先经过所有权校验（否则同一资源会出现两种拒绝语义），也让判定与调用者角色无关。

拒绝状态码统一为 **409**（2026-10-01 用户批准）：语义是"资源由发布链管理"，不是权限问题。

### 3.3 路由改造

- `registerWikiPageRoutes` 增加 `classifier managed.Classifier` 参数，移除 `releaseHandler == nil` 的放行分支。
- 原生 `/wiki` 下全部写路由（现 11 条，含 `PUT /move-page`、`PUT|DELETE /pages/*slug`、`PUT|DELETE /folders/:folder_id`、
  `PUT /issues/:issue_id/status`）统一先挂 `GuardWikiWrite()`，再挂原有 RBAC。
- 删除 `handler.WikiReleaseHandler.RejectManagedWikiWrite` 及其 `IsActiveManagedWikiKB` 调用链；删除
  `service.IsManagedWikiKB`。`container` 负责构造 `managed.NewClassifier(...)` 并注入。
- 旧包装 `RegisterWikiPageRoutes` 与新包装合并为一个必带 classifier 的入口；`router_wiki_test.go` 与
  `routes_knowledge.go` 的 nil 分支同步更新。

### 3.4 Agent 与 MCP 写工具

- Agent 的 wiki 写工具（`internal/agent/tools/`）与 MCP 的 document 写工具（`internal/mcpserver/tools_ingest.go`）在
  选定目标 KB 后调用同一个 `Classifier.Classify`；受管即拒绝并返回同样的错误码。
- Agent 现有的 custody 副本（`concept_agent_830_g2.go:146-177`）删除，改调 `managed.Classifier`；
  Agent 的 RAW 侧排除逻辑保留行为不变。
- 不改变非受管库的任何现有行为。

## 4. 验收

验收测试由 Claude 提供：`internal/router/native_wiki_guard_test.go`（本分支已有，当前 RED）。它要求：

| 测试 | 断言 |
|---|---|
| `TestNativeWikiRoutesIncludeKnownWriteAndReadPaths` | 原生 `/wiki` 下已知读写路由均已注册（防止注册被整体摘除） |
| `TestNativeWikiRoutesRejectReleaseManagedKB` | 受管 × {Pending, Active} × {Wiki, Raw} 的全部组合下，枚举出的每条路由都返回 409 且错误码为 `RELEASE_MANAGED_KB` |
| `TestNativeWikiGuardFailsClosedWhenClassificationFails` | 分类出错时每种路由均返回 503 且错误码为 `MANAGED_KB_CLASSIFICATION_UNAVAILABLE` |
| `TestNativeWikiGuardPassesUnmanagedKBToNormalGuards` | 非受管库放行到 RBAC（跨租户仍 403），且守卫在 RBAC 之前完成分类 |

Codex 另需补充（同目录、可自行命名）：

- `managed` 包单测：四种状态 × 两种角色 × 判定出错 × tenant 缺失；
- Agent 与 MCP 写工具在受管库上被拒、在非受管库上行为不变的测试；
- `container` 装配测试：classifier 被注入且非 nil。

其余门禁：仓库根 `python -m pytest -q tests/architecture` 必须通过（守卫基线 G10 会因新增上游补丁上升，
由 Claude 在同一 PR 中下调审核后更新基线，见 §6）。

## 5. 改动范围

- 允许新增：`internal/enterprise/managed/`（`classify.go`、`guard.go` 及测试）。
- 允许修改：`internal/router/routes_knowledge.go`、`internal/router/router.go`、`internal/router/router_wiki_test.go`、
  `internal/container/container.go`、`internal/handler/wiki_release.go`（仅删除写守卫与相关辅助）、
  `internal/application/service/wiki_release.go`（仅删除 `IsActiveManagedWikiKB`/`IsManagedWikiKB` 及其仓储调用）、
  `internal/application/repository/wiki_release.go`（仅删除被删函数独占的方法）、
  `internal/application/service/concept_agent_830_g2.go`（改用 `managed.Classifier`）、
  `internal/agent/tools/` 与 `internal/mcpserver/` 中写工具的受管检查点。
- 不得修改：`internal/router/native_wiki_guard_test.go`、蓝图、`docs/design/`、`tests/architecture/`、`contracts/`、`harness/`、`frontend/`。
- 不新增表、不新增服务、不改迁移。

## 6. 门禁与基线

- 会新增上游补丁：`internal/mcpserver/scope.go`、`server.go`（若改动）。Codex 在 PR 中列出实际被改的上游文件；
  Claude 复核后将 G10 基线增量写入 `tests/architecture/baseline.json`（蓝图 §4.3：改上游需登记原因与退出条件）。
- CI 需全绿：`architecture-guards`、`App`、`go-lint`，以及受影响的 `harness-ci`/`frontend`（预期不受影响，若被触发如实记录）。

## 7. 非目标

- 不改读入口（S1b）。
- 不改发布链、不改 Candidate/Release 语义。
- 不为非受管库增加新行为，不引入新权限模型。

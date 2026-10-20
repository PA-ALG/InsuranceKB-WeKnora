# Q1c · MCP 读取已发布知识：外部 Agent 读同一个固定版本

> 状态：Claude 2026-10-20 提出（Q1 计划的最后一项；用户 2026-10-20 要求 Claude 定方向、Codex 实现）｜ 作者：Claude Code
> 依据：蓝图"人与 Agent 读取同一个已发布版本"、Q1b/S6e 已发布知识工具、现有 MCP 端点（`internal/mcpserver`）
> 实现方：Codex（Go）｜ 审核方：Claude ｜ 真实模型调用：0

## 1. 现状与目标

- **现状**：MCP 端点对受管知识库一律拒绝（`RELEASE_MANAGED_KB`）。外部 Agent 读不到企业知识，也打不开出处。
- **目标**：MCP 端点提供只读的已发布知识工具，复用 Q1b/S6e 的查询服务。
  - 每次调用固定到一个发布版本，并在结果中返回这个版本 ID；
  - 客户端可以带着这个 ID 继续读同一个版本，读出处也用它。
- **不做**：
  - MCP 写入发布版本；
  - MCP 读取原始材料（受管原始库仍拒绝）；
  - 对话式 `ask` 工具接入企业知识。

## 2. 设计（`internal/enterprise/mcptools`，新包）

```go
type Caller struct {
	TenantID uint64
	Readable func(kbID string) bool // 端点知识库白名单 + Viewer 读权限，两者都要满足
}
type Spaces interface {
	SpaceIDs(tenantID uint64) []string
	KnowledgeBases(tenantID uint64, spaceID string) (raw, wiki string, ok bool)
}
type Heads interface {
	ActiveRelease(ctx context.Context, tenantID uint64, spaceID string) (string, error)
}
type Citation struct {
	Document string
	Page     int
	Quote    string
}
type Citations interface {
	Citation(ctx context.Context, tenantID uint64, spaceID, releaseID, member string, evidence int) (Citation, error)
}
type Deps struct {
	Spaces    Spaces
	Heads     Heads
	Knowledge *knowledge.Service
	Citations Citations
	Caller    func(ctx context.Context) (Caller, bool)
}
func Tools(deps Deps) []server.ServerTool
```

### 2.1 工具（按此顺序）

1. **`knowledge_list_spaces`**：无参数。结构化结果为 `{"spaces": [{"space_id", "release_id"}]}`，只列调用方可读、且有 Active 的 Space，按 Space ID 排序。
2. **5 个知识工具**：`knowledge_find_entity`、`knowledge_get_fields`、`knowledge_search_fields`、`knowledge_get_concept`、`knowledge_search_pages`。
   - 参数与 Q1b/S6e 的 Agent 工具相同，另外 `space_id` 必填，`release_id` 可选。
   - 执行时用 `knowledge.NewTools(Knowledge, tenant, {space_id: 本次版本})` 中同名的工具，参数去掉 `release_id` 后原样传入。
3. **`knowledge_read_citation`**：参数 `space_id`、`release_id`（必填）、`member`、`evidence`（非负整数）。结构化结果为 `{"document", "page", "quote"}`。

### 2.2 每次调用的规则

1. **身份**：`Caller(ctx)` 不存在时返回错误结果。
2. **可读**：Space 必须在 `SpaceIDs(caller.TenantID)` 中，并且其原始材料库与 Wiki 库都满足 `Readable`。否则返回 `RELEASE_ACCESS_DENIED` 错误结果，不读取 Head 或发布版本。
3. **版本**：
   - 没有 `release_id`：读一次 `ActiveRelease`，为空时返回 `RELEASE_NOT_FOUND`；
   - 有 `release_id`：不能是空串或 `active`（大小写不敏感），否则返回 `INVALID_REQUEST`；
   - 该 ID 由查询服务按 Space 读取，不属于该 Space 时返回其错误（`RELEASE_NOT_FOUND`）；
   - 已退役的版本在明确指定时可以读取，以便沿用历史引用。
4. **结果**：
   - 成功时 `StructuredContent` 是对象，包含原工具 `Data` 的全部键，并加上 `space_id` 与 `release_id`（本次实际读取的版本）；
   - 文本内容沿用原工具的 `Output`；
   - 错误时 `IsError = true`，文本以错误码开头。
5. **行**：`results` 中每行的 `chunk_id`（`release:<id>:<slug>`）与 `metadata` 原样保留，客户端用它调用 `knowledge_read_citation`。

### 2.3 接入（实现方）

- **`internal/mcpserver/server.go`**（已登记的上游文件）：增加注入额外工具的选项（如 `WithExtraTools([]server.ServerTool)`），额外工具同样经过端点工具白名单与限流（`guardTool`、`filterTools`）。
- **`internal/types/mcp_endpoint_tools.go`**（上游）：工具目录增加一组"已发布知识"，包含以上 7 个工具名。
- **`container.go`**（已登记）：生产环境注入 `Spaces`（releasestore）、`Heads`（releasestore 的 Active 读取）、`knowledge.Service`、出处读取。
- **出处读取**：把 `/api/v1/enterprise/.../citation` 处理函数的核心（按指定版本取 Evidence、核对 PDF 片段与文件哈希）提到项目包中的可复用函数，HTTP 处理与 MCP 工具共用，行为不变。
- **`Caller`**：用 MCP 端点认证写入的 tenant 与端点配置：
  - 知识库白名单用 `AllowsKnowledgeBase`；
  - 读权限用与浏览器企业读取相同的 Viewer 知识库访问检查（`access.ResolveKB`）。
- **前端**：MCP 端点设置页的工具名文案，5 种语言同步。
- 上游文件在 `upstream-patches.md` 追加登记；G10 由 Claude 单独提交。

## 3. 验收（RED：`internal/enterprise/mcptools/acceptance_test.go`，Claude 编写，受保护）

1. 工具名与顺序。
2. `knowledge_list_spaces`：只列出可读、有 Active 的 Space，并带版本 ID。
3. 不带 `release_id`：读一次 Active，结果带 `release_id`，行的 `chunk_id` 指向这个版本。
4. 带 `release_id`：
   - 读该版本；
   - `active` 与空串被拒绝，且不读取；
   - 不属于该 Space 的版本返回错误。
5. 不可读的 Space：拒绝，且不读取 Head。
6. 没有调用方身份：拒绝。
7. `knowledge_read_citation`：
   - 必须带 `release_id`；
   - 返回出处；
   - 不可读的 Space 被拒绝。
8. 实现方另补：端点白名单与限流对新工具生效；`toolCatalog` 原有工具不变；出处函数提取后 HTTP 行为不变（原测试通过）。

## 4. 改动范围

- 新增 `internal/enterprise/mcptools/`；
- `internal/enterprise/`：出处函数提取，只做移动，行为不变；
- `internal/mcpserver/server.go`、`internal/types/mcp_endpoint_tools.go`、`internal/container/container.go`；
- 前端语言包 5 种（MCP 工具名）；
- `docs/design/upstream-patches.md` 只追加；
- 实现方测试。

## 5. 上线

合并后与下一次 App/UI 构建一起上线（需用户批准）。上线后用一个测试 MCP 端点核对：

- 列出 Space；
- 读取 1828 的字段；
- 打开一条出处。

本切片 0 次模型调用。

# S1b · 受管知识库的读入口只读发布版本

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §7.5、§8（G8）、§11（S1）
> 分支：`slice/s1b` ｜ 开工方式：**等确认再开工**（跨 Go 与前端） ｜ 真实模型调用：不需要
> 前置：S1a 已合并（`main@deae12a92`）。本片与 S2a（Python `eval/`）写域不重叠，可并行。

## 1. 目标

受管知识库（属于某个 release scope 的 RAW 或 Wiki 库）的内容，只能通过发布版本读取。原生 Wiki 表、普通检索、
MCP、快问快答都不能再读到未经发布的内容；被拒绝时给出明确原因，不静默返回空结果。

## 2. 现状（2026-10-02 核实）

| 读入口 | 现状 | 问题 |
|---|---|---|
| 原生 `/wiki` GET（10 条：pages、pages/*slug、revisions、folders、index、graph、stats、search、lint、issues） | 只挂 Viewer + KBAccessRead，直接读 `wiki_pages` | 受管库的未发布页面可被读到 |
| MCP 读工具（search_knowledge、grep_chunks、list_documents、read_document、wiki_*） | 都经 `selectKnowledgeBases`（`internal/mcpserver/scope.go:111`） | 不区分受管库 |
| 快问快答 `KnowledgeQA` / `SearchKnowledge` / IM 搜索 | 经 `buildSearchTargets`（`internal/application/service/session_knowledge_qa.go:463`） | 不区分受管库 |
| Agent 模式 | 已排除受管库，改用按轮固定 release 的 wiki 工具（`agent_service.go:1015-1053`） | 无（保持不变） |
| 前端知识库页 | 受管库仍显示"材料 Wiki"与"图谱"标签页（`KnowledgeBase.vue:2325-2390`），调用原生 GET | 本片后会收到 409 |
| 聊天引用抽屉 | `openWikiDrawer(kbId, slug)` 调原生 `getWikiPage`（`AgentStreamDisplay.vue:916`） | 受管库会收到 409 |

## 3. 设计

### 3.1 原生 Wiki 读路由（Go）

- `registerWikiPageRoutes` 中读路由组也挂 `managed.GuardWikiWrite(...)` 同一个守卫（可改名为 `GuardNativeWiki`，
  行为不变：受管 409 `RELEASE_MANAGED_KB`，分类失败 503 `MANAGED_KB_CLASSIFICATION_UNAVAILABLE`，先于 RBAC）。
- 非受管库的读行为完全不变。
- `release-scopes/...` 下的发布读路由**不挂**此守卫（它们读的是发布版本）。
- 启动时断言：`g.kbService` 必须实现 `managed.KnowledgeBaseLookup`；不满足时 router 构造直接 panic，
  不再在运行时静默得到 nil（S1a 审查遗留项）。最好改成编译期约束（字段类型直接要求该接口）。

### 3.2 MCP 读工具（Go）

在 `selectKnowledgeBases` 一处实现：

- 显式请求的 KB 受管 → 返回错误，消息包含 `RELEASE_MANAGED_KB`，并说明"该知识库由发布链管理，请通过发布版本读取"。
- 未指定 KB（默认范围）→ 静默去掉受管 KB；去掉后为空 → 返回错误，消息包含 `RELEASE_MANAGED_KB`。
- 分类器出错或未注入 → 错误消息包含 `MANAGED_KB_CLASSIFICATION_UNAVAILABLE`（失败关闭）。
- 分类按 KB 属主租户（`kb.TenantID`），与 S1a 写工具一致。
- `list_knowledge_bases` 在结果中给受管 KB 标注 `release_managed: true`，不隐藏（让调用方知道它存在、该怎么读）。

### 3.3 快问快答与检索（Go）

- `KnowledgeQA`、`SearchKnowledge`（含 IM `cmd_search.go:87`）在调用 `buildSearchTargets` 之前，对显式选择的
  KB 与显式选择的 knowledge（按其所属 KB）做受管分类：任一受管 → 返回带 `RELEASE_MANAGED_KB` 的类型化错误，
  前端与 IM 显示明确提示，不静默剔除（2026-10-01 用户批准）。
- **Agent QA 路径（`session_agent_qa.go:443`）不改**：Agent 已排除受管库并通过 release 工具读取。若实现时发现该路径
  仍会把受管 RAW 放进检索目标，停下在 PR 中说明，不在本片顺手修改。
- 共用一个服务层辅助函数（放 `internal/enterprise/managed/`），不在三处各写一遍。

### 3.4 前端

- 新增后端只读端点 `GET /api/v1/knowledgebase/:kb_id/release-custody`（放 `internal/enterprise/managed/` 的 handler，
  挂 Viewer + KBAccessRead，不挂原生守卫），返回 `{managed: bool, kind, state}`；分类失败 503。
- `KnowledgeBase.vue`：受管库隐藏"材料 Wiki"与"图谱"两个标签页，默认停在 Schema Wiki 页；在原位置显示一句说明
  "该知识库由发布链管理，内容以发布版本为准"。新增逻辑放 `frontend/src/enterprise/`（组合式函数），`KnowledgeBase.vue`
  只做最小接入。
- 聊天引用抽屉：来自 release 工具的引用（工具结果带 `release_authorities`）改用发布读路由
  `.../release-scopes/:space_id/raw/:raw_kb_id/releases/:release_id/pages/:logical_slug` 打开；
  release 已不是当前 Head 时（409/404），提示"该引用来自旧版本，请重新提问"，**不回落到原生页面**。
  其余（非受管库）引用保持原样。

### 3.5 不变的部分

- 摄取链的配置开关 `NativeWikiWritesDisabled` 不改（原生 discover/cite 作为候选源的改造在 S6）。
- Agent 冻结 release 只接受 G1/G2 variant 的限制不改（通用读取模型在 S3）。
- 历史版本读取（release_id 不等于当前 Head）不在本片（S3）。

## 4. 验收

Claude 提供（受保护，当前 RED）：

| 测试 | 断言 |
|---|---|
| `internal/router/native_wiki_guard_test.go` · `TestNativeWikiRoutesRejectReleaseManagedKB` | 受管 × {Pending, Active} × {Wiki, Raw} 下，**全部**原生路由（读与写）返回 409 `RELEASE_MANAGED_KB` |
| 同上 · `TestNativeWikiGuardFailsClosedWhenClassificationFails` | 分类失败时全部原生路由返回 503 |
| 同上 · `TestNativeWikiReadRoutesPassUnmanagedKB` | 非受管库的每条读路由都被分类且放行到 handler |
| `internal/mcpserver/managed_read_test.go`（6 项） | §3.2 的显式拒绝、默认剔除、Pending 也剔除、分类失败与未注入失败关闭、全部受管时报错 |

Codex 补充（测试名可自定，需覆盖）：

- 启动断言：`kbService` 不满足 `KnowledgeBaseLookup` 时 router 构造失败。
- `KnowledgeQA` / `SearchKnowledge`：显式受管 KB 被拒、显式受管 knowledge 被拒、非受管不变、分类失败关闭。
- `list_knowledge_bases` 的 `release_managed` 标注。
- `release-custody` 端点：受管、非受管、分类失败三种响应。
- 前端：受管库隐藏两个标签页并显示说明；release 引用走发布读路由；旧版本引用给出提示而非回落。

其余门禁：受影响 Go 包 `go test` 与 `go vet`；前端 `npm run type-check`、相关测试、`npm run build`；架构守卫通过；
CI 全绿。新改的上游文件按 G10 规则登记到 `docs/design/upstream-patches.md`（只追加），基线由 Claude 审查后更新。

## 5. 改动范围

- 允许新增：`internal/enterprise/managed/` 下的文件；`frontend/src/enterprise/` 下的文件；对应测试。
- 允许修改：`internal/router/routes_knowledge.go`、`internal/router/router.go`、`internal/router/rbac.go`（仅 kbService
  类型约束）、`internal/mcpserver/scope.go`、`internal/mcpserver/tools_retrieve.go`（仅 list 标注）、
  `internal/application/service/session_knowledge_qa.go`、`internal/im/cmd_search.go`、`internal/container/container.go`、
  `frontend/src/views/knowledge/KnowledgeBase.vue`、`frontend/src/views/chat/components/AgentStreamDisplay.vue`、
  `frontend/src/api/wiki/index.ts`（仅新增发布读取调用）、`docs/design/upstream-patches.md`（只追加登记行）。
- 不得修改：`internal/router/native_wiki_guard_test.go`、`internal/mcpserver/managed_read_test.go`、蓝图、`docs/design/`
  其他文件、`tests/architecture/`、`contracts/`、`harness/`、Agent QA 路径与摄取链。

## 6. 非目标

- 不做通用 release 读取模型与历史版本读取（S3）。
- 不改 Agent 模式与摄取链。
- 不为受管库提供原生页面的"只读投影"——受管库的展示统一走 Schema Wiki 页（S3 会重做）。

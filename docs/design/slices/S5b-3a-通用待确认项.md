# S5b-3a · 通用待确认项

> 状态：Claude 2026-10-25 提出；用户 2026-10-24 决定"不确定的材料放在企业知识页给人确认" ｜ 作者：Claude Code
> 依据：蓝图硬边界 2（只经版本化 REST 集成）、4（Go 只处理通用对象）、§6.3（人工队列）；RV4a 抽检（`internal/enterprise/spotcheck`）的存储、路由与权限写法
> 实现方：Claude ｜ 审核方：Codex（Go 平台、数据库迁移 000010、权限；上游文件 `router.go`）｜ 真实模型调用：0

## 0. S5b-3 的拆分

| 片 | 内容 | 组件 |
|---|---|---|
| **S5b-3a（本片）** | 通用待确认项：提交方给出显示文字与选项，人在页面上选一项；选择只追加；提交方关闭 | Go + 迁移 000010 |
| S5b-3b | 企业知识页"待确认材料"页面 | 前端 |
| S5b-3c | Harness 把登记中的待处理材料连同选项推送上来，读回选择、应用到产品登记并关闭 | Harness |

## 1. 目标与边界

需要人决定的事情，由提交方（Harness）生成显示文字和选项，WeKnora 负责保存、按权限展示、记录谁在何时选了哪一项。

- **Go 不解释内容**：不认识险种、产品或材料角色。标题、说明、选项文字和选项键都是不透明字符串，Go 只校验格式、长度和归属。
- **只追加**：
  - 人的选择逐条追加，关闭前可以改选，以最后一条为准；
  - 关闭只能一次，关闭后不再接受选择。

## 2. 改动

### 2.1 数据与迁移 `000010_enterprise_confirmations`

```sql
CREATE TABLE enterprise_confirmations (
    id             TEXT PRIMARY KEY,
    tenant_id      BIGINT NOT NULL,
    space_id       TEXT NOT NULL,
    subject        TEXT NOT NULL,   -- 提交方的对象标识，如一份材料
    revision       TEXT NOT NULL,   -- 提交方的对象版本
    content_digest TEXT NOT NULL,   -- 标题、说明、选项的 canonical JSON 的 SHA-256
    title          TEXT NOT NULL,
    detail         TEXT NOT NULL,
    options        JSONB NOT NULL,
    created_by     TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX enterprise_confirmations_identity_idx
    ON enterprise_confirmations (tenant_id, space_id, subject, revision, content_digest);

CREATE TABLE enterprise_confirmation_answers (
    id              TEXT PRIMARY KEY,
    seq             BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    tenant_id       BIGINT NOT NULL,
    space_id        TEXT NOT NULL,
    confirmation_id TEXT NOT NULL REFERENCES enterprise_confirmations(id),
    option_key      TEXT NOT NULL,
    note            TEXT NOT NULL,
    answerer        TEXT NOT NULL,
    answered_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX enterprise_confirmation_answers_item_seq_idx
    ON enterprise_confirmation_answers (confirmation_id, seq);

CREATE TABLE enterprise_confirmation_closures (
    confirmation_id TEXT PRIMARY KEY REFERENCES enterprise_confirmations(id),
    tenant_id       BIGINT NOT NULL,
    space_id        TEXT NOT NULL,
    reason          TEXT NOT NULL CHECK (reason IN ('applied', 'obsolete')),
    answer_id       TEXT REFERENCES enterprise_confirmation_answers(id),
    closed_by       TEXT NOT NULL,
    closed_at       TIMESTAMPTZ NOT NULL,
    CHECK ((reason = 'applied') = (answer_id IS NOT NULL))
);
```

- down 迁移按依赖倒序删除三张表。
- `packagedEnterpriseMigrationHead` 升为 10，迁移版本上限测试相应更新（与 S9a 升到 9 的做法相同）。

### 2.2 包 `internal/enterprise/confirm`（本 Spec 冻结类型与错误码）

```go
type Option struct { Key string `json:"key"`; Label string `json:"label"` }
type Item struct {
    ID, SpaceID, Subject, Revision, ContentDigest, Title, Detail string
    Options   []Option
    CreatedBy string; CreatedAt time.Time
    Answer    *Answer   // 最新一条选择（按 seq）
    Closure   *Closure
}
type Answer  struct { ID, ItemID, OptionKey, Note, Answerer string; AnsweredAt time.Time }
type Closure struct { Reason, AnswerID, ClosedBy string; ClosedAt time.Time }
type ItemInput struct { Subject, Revision, Title, Detail string; Options []Option }
type Filter  struct { Status string }   // "" | "open" | "closed"

// Store isolates every record by tenant and Space; failures are *release.Error codes.
type Store interface {
    // InsertItems keeps existing (tenant, Space, subject, revision, content digest) records,
    // including concurrent inserts, and returns the stored items in input order.
    InsertItems(ctx context.Context, tenantID uint64, items []Item) ([]Item, error)
    // ListItems includes each item's latest answer (by append order) and its closure,
    // ordered by CreatedAt, then ID.
    ListItems(ctx context.Context, tenantID uint64, spaceID string, f Filter) ([]Item, error)
    ItemByID(ctx context.Context, tenantID uint64, spaceID, id string) (Item, bool, error)
    // AppendAnswer fails with CONFIRMATION_CLOSED once the item is closed.
    AppendAnswer(ctx context.Context, tenantID uint64, spaceID string, a Answer) error
    // CloseItem closes once (CONFIRMATION_CLOSED afterwards); an applied closure fails with
    // ANSWER_STALE unless its answer is the item's latest one, judged atomically.
    CloseItem(ctx context.Context, tenantID uint64, spaceID, itemID string, c Closure) error
}

func NewService(store Store, opts ...Option) *Service      // WithClock、WithIDs，同 spotcheck
```

- 服务方法第一个业务参数为 `release.Principal`（`TenantID`、`Subject`），与抽检相同；`CreatedBy`、`Answerer`、`ClosedBy` 都取 `Subject`。

- **错误码**：
  - `CONFIRMATION_INVALID`（400）；
  - `CONFIRMATION_NOT_FOUND`（404，也用于他人租户与 Space 之外，不区分）；
  - `ANSWER_INVALID`（400）；
  - `CONFIRMATION_CLOSED`（409）；
  - `ANSWER_STALE`（409）；
  - 沿用 `RELEASE_ACCESS_DENIED`（403）、`SERVICE_UNAVAILABLE`（503）。
- **校验**（全部先校验，再写入）：
  - 一批 1–200 项；
  - `Subject`、`Revision`：1–128 字符，匹配 `^[A-Za-z0-9][A-Za-z0-9:._-]*$`；
  - `Title`：1–200 字（rune），去首尾空白；`Detail`：0–2000 字；
  - `Options`：1–50 个；`Key` 匹配 `^[a-z0-9][a-z0-9:._-]{0,127}$`，同一项内不重复；`Label` 为 1–200 字；
  - 文字不允许控制字符（换行除外）；
  - 同一批里同一 `(Subject, Revision, ContentDigest)` 只出现一次。
- **`content_digest`**：服务端对 `{title, detail, options}` 的 canonical JSON 计算 SHA-256（键排序、无多余空白）。同一对象内容变了就是新项；提交方负责关闭旧项（S5b-3c）。
- **服务 `Service`**（构造、时钟与 ID 注入同 `spotcheck.Service`）：
  - `Submit(ctx, p, spaceID, []ItemInput) ([]Item, error)`：按 `(tenant, space, subject, revision, content_digest)` 幂等；已存在的保持原样返回，包括并发提交时；
  - `List(ctx, p, spaceID, Filter) ([]Item, error)`：按 `CreatedAt`、`ID` 排序；`open` 为未关闭的项（含已有选择、等待处理的），`closed` 为已关闭的项；
  - `Answer(ctx, p, spaceID, itemID, optionKey, note) (Answer, error)`：`optionKey` 必须是该项的选项之一；备注去首尾空白，最多 1000 字；项已关闭时返回 `CONFIRMATION_CLOSED`；
  - `Close(ctx, p, spaceID, itemID, reason, answerID) (Closure, error)`：
    - `reason` 为 `applied` 时 `answerID` 必须等于当前最新一条选择，否则返回 `ANSWER_STALE`，防止应用已被人改掉的旧选择；
    - `obsolete` 时 `answerID` 必须为空；
    - 已关闭时返回 `CONFIRMATION_CLOSED`，同一关闭重复提交也是如此。
- **并发**：
  - 选择与关闭在存储层原子判断"未关闭"，晚到的一方得到 `CONFIRMATION_CLOSED`；
  - `applied` 关闭在同一事务内确认 `answerID` 仍是最新一条。

### 2.3 存储 `internal/enterprise/releasestore/confirmations.go`

- 实现 `confirm.Store`，与 `spotcheck` 共用 `releasestore.Store`，每个 Space 都经 `spaces.Scope` 校验。
- 最新选择按 `seq` 选取。
- 在 `releasestore.Register` 中提供 `*confirm.Service`：未配置 `ENTERPRISE_SPACES` 时为 nil，接口返回 503。

### 2.4 接口

**提交方（API Key，完全访问，同抽检的 `APIKeyRoutePolicy{RequireFullAccess:true}`）**，挂在 `/api/v1/enterprise/spaces/:space_id`：

| 方法与路径 | 请求 | 响应 |
|---|---|---|
| `POST /confirmations` | `{"items":[{"subject","revision","title","detail","options":[{"key","label"}]}]}` | 201 `{"success":true,"data":{"items":[…]}}` |
| `GET /confirmations?status=` | — | 200 `{"data":{"items":[…]}}` |
| `POST /confirmations/:id/closure` | `{"reason","answer_id"}` | 201 `{"data":{"closure":…}}` |

**页面（会话用户）**，挂在 `/api/v1/enterprise/spaces/:space_id/view`：

| 方法与路径 | 权限 | 请求与响应 |
|---|---|---|
| `GET /confirmations?status=` | Viewer，RAW 与 Wiki 库均可读（同会话读取） | 同上 |
| `POST /confirmations/:id/answers` | 与专家编辑完全相同：**Admin**、RAW 库可读、**Wiki 库可编辑**（选择会改变发布内容，用户 2026-10-22 规则"管理员及以上"）。租户关闭 RBAC 时上游的 Admin 守卫只记日志不拦截，Wiki 库编辑权限仍然拦截（2026-10-25 修正） | `{"option_key","note"}` → 201 `{"data":{"answer":…}}` |

- 请求体用抽检同一套严格 JSON 解析：拒绝重复键、未知键、大小写别名键、尾随数据、非法 UTF-8，嵌套超过 64 层同样拒绝。
- 体积上限：提交 512 KiB，其余 64 KiB。
- Space 必须在 `ENTERPRISE_SPACES` 中，否则 404；API Key 与会话路由互不混用。

### 2.5 上游接缝

- `internal/router/router.go`：
  - `RouterParams` 增加 `EnterpriseConfirmations *confirm.Service`；
  - `registerEnterpriseRoutes` 挂载提交方与页面路由，写法同抽检。
- 在 `docs/design/upstream-patches.md` 追加一行。
- `container.go` 不改：服务由 `releasestore.Register` 提供。

**不做**：
- 前端页面（S5b-3b）；
- Harness 推送与应用（S5b-3c）；
- 不改抽检、专家编辑与发布链。

## 3. 验收

**RED（Claude 编写，受保护）**——与 RV4a 相同，只覆盖服务规则：

1. **`internal/enterprise/confirm/acceptance_test.go`**（内存 `Store`，按 §2.2 的接口语义实现）：
   - 提交：
     - 校验各边界：数量、长度、键格式、项内重复选项键、控制字符、批内重复，任何一项不合法时整批不写；
     - 同一内容重复提交，返回已有项；
     - 内容变了产生新项，`content_digest` 与选项顺序有关，与 JSON 键顺序无关；
   - 列表：`open` / `closed` 过滤与排序；非法 `status` → `CONFIRMATION_INVALID`；
   - 选择：
     - 不在选项中 → `ANSWER_INVALID`；
     - 备注超长 → `ANSWER_INVALID`；
     - 改选后最新一条生效；
     - 已关闭 → `CONFIRMATION_CLOSED`；
   - 关闭：
     - `applied` 带最新选择成功；
     - 带旧选择 → `ANSWER_STALE`；
     - `applied` 不带选择、`obsolete` 带选择、未知原因 → `CONFIRMATION_INVALID`；
     - 重复关闭 → `CONFIRMATION_CLOSED`；
   - 隔离：他人租户或其他 Space 的项一律 `CONFIRMATION_NOT_FOUND`；空租户、空主体 → `RELEASE_ACCESS_DENIED`；
   - 未配置（nil 服务）→ `SERVICE_UNAVAILABLE`。
2. **`internal/database/enterprise_migration_head_test.go`**：版本上限为 10，9 不再是完整的迁移集。

**实现方测试**（随实现提交，审核方审查）：

3. **`releasestore/confirmations_postgres_test.go`**（`TestPostgres*`，CI 的 enterprise-postgres 任务运行）：
   - 并发提交只有一项胜出；
   - 选择与关闭并发时，晚到的一方得到 `CONFIRMATION_CLOSED`；
   - 带旧选择的 `applied` 关闭得到 `ANSWER_STALE`；
   - 最新选择按 `seq` 选取；
   - 租户与 Space 隔离；
   - 迁移 up/down 往返，约束生效。
4. **HTTP**：
   - 严格 JSON 与体积上限；
   - 完全访问 API Key 才能提交与关闭；
   - 会话路由不接受 API Key；
   - 响应格式与状态码。
5. **路由**：
   - 经真实 `registerEnterpriseRoutes`：页面选择要求 Admin 与 Wiki 库编辑权限（Contributor、Viewer、只有 Wiki 库读权限的 Admin 得 403；关闭 RBAC 时只有 Wiki 库读权限的 Contributor 也得 403），读取要求 Viewer；
   - 未配置 Space 时 404。
6. **守卫**：`tests/architecture` 照常通过；新增 Go 文件都在 `internal/enterprise/` 下；不出现领域词汇（G2）。

**行为回归**：`go build ./...`、`go vet ./...`、受影响包 `go test`、`golangci-lint --new-from-merge-base=origin/main`。

## 4. 改动范围

- `internal/enterprise/confirm/`（新）；
- `internal/enterprise/confirm_http.go`、`session_confirmations.go`（新），`mount.go`、`session.go`（挂载与依赖字段）；
- `internal/enterprise/releasestore/confirmations.go`（新）、`production.go`（提供服务）；
- `internal/router/router.go`；
- `internal/database/enterprise_migration.go`（版本上限常量）与其测试；
- `migrations/enterprise/versioned/000010_enterprise_confirmations.{up,down}.sql`；
- §3 的测试；
- `docs/design/upstream-patches.md`（只追加一行）；
- `tests/architecture/`（基线）。

## 5. 上线

- 换 App 镜像并执行迁移 000010（只新增三张表，不改已有数据）。另开部署 Issue，需用户确认。
- 回滚：执行 down 迁移删除三张表，换回旧镜像。
- 可与 S5b-3b 的界面一起部署。

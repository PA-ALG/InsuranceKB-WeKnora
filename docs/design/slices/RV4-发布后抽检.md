# RV4 · 发布后分层抽检：机器审核上线的内容按风险抽样交人确认，结论回流门槛

> 状态：用户 2026-10-18 批准开工（"开工吧"），含迁移 000008（本机测试库与演示环境）与上线时 App、UI 各构建 1 次 ｜ 作者：Claude Code
> 依据：蓝图 §6.2（`POST /samples/:id/verdicts`）、§6.3（上线后按风险与字段分层抽检，结论写回 Golden 并校准门槛）、硬边界 4、8
> 拆分：RV4a 平台（Go + 迁移，Codex 实现）· RV4b 抽检台页面（前端，Codex 实现）· RV4c 抽样与回流（Harness，Claude 实现）；审核交叉进行

## 1. 目标

1. **抽样**：每次激活的 Release 中，标注"机器审核"的 Claim 按版本化抽检策略分层抽样，生成待确认样本。
2. **确认**：业务人员在"抽检台"逐条看取值与原文出处，给出"正确 / 不完整 / 错误"，可附说明。结论绑定样本（即 Release 与成员摘要）和确认人，不可改写；改判只能追加新结论，以最新一条为准。
3. **回流**：
   - 按 pack 汇总抽检结论，得到机器审核内容的实测精确率（Wilson 下界）；
   - 低于审核策略目标时，给出"提高门槛或撤销准入"的建议，由人决定，审核策略升版本；
   - 判为错误的条目列入修正清单（人工改判或重新编译，必要时按实体回退）。
4. RV3 试点期间的约束（每次 MACHINE 发布逐条人工复核）由 RV4 接管：试点期抽检比例设为 100%，数据积累后按策略下调。

## 2. 设计

### 2.1 RV4a 平台（Go，新包 `internal/enterprise/spotcheck`）

平台只保存和校验通用的样本、成员与结论，不理解险种、字段与风险（硬边界 4）。`stratum` 是 Harness 给的不透明字符串。

**类型**（包 `spotcheck`）：

```go
type Sample struct {
    ID           string    `json:"id"`
    SpaceID      string    `json:"space_id"`
    ReleaseID    string    `json:"release_id"`
    LogicalSlug  string    `json:"logical_slug"`
    MemberDigest string    `json:"member_digest"`
    Stratum      string    `json:"stratum"`
    CreatedBy    string    `json:"created_by"`
    CreatedAt    time.Time `json:"created_at"`
    Verdict      *Verdict  `json:"verdict,omitempty"` // 最新一条结论；没有时省略
}

type Verdict struct {
    ID        string    `json:"id"`
    SampleID  string    `json:"sample_id"`
    Outcome   string    `json:"outcome"` // correct | incomplete | wrong
    Note      string    `json:"note"`
    Reviewer  string    `json:"reviewer"`
    DecidedAt time.Time `json:"decided_at"`
}

type SampleInput struct{ Slug, Stratum string }
type Filter struct{ Status, ReleaseID string } // Status: "" | "pending" | "decided"
```

**协作接口**（由服务定义；`*release.Service` 直接满足 `ReleaseReader`）：

```go
type ReleaseReader interface {
    Release(ctx context.Context, p release.Principal, spaceID, releaseID string) (release.Release, error)
}

// Store isolates every record by tenant and Space.
type Store interface {
    // InsertSamples keeps an existing (tenant, space, release, slug) sample unchanged and
    // returns the stored sample for every input, in input order (concurrency-safe).
    InsertSamples(ctx context.Context, tenantID uint64, samples []Sample) ([]Sample, error)
    // ListSamples returns a Space's samples with their latest verdicts, by CreatedAt then ID.
    ListSamples(ctx context.Context, tenantID uint64, spaceID string, f Filter) ([]Sample, error)
    SampleByID(ctx context.Context, tenantID uint64, spaceID, id string) (Sample, bool, error)
    AppendVerdict(ctx context.Context, tenantID uint64, spaceID string, v Verdict) error
}
```

**服务** `spotcheck.Service`（`NewService(store Store, releases ReleaseReader, opts ...Option)`；选项 `WithClock(func() time.Time)` 与 `WithIDs(func() string)`，默认用系统时钟与随机 ID）：

- `Submit(ctx, p release.Principal, spaceID, releaseID string, items []SampleInput) ([]Sample, error)`
  - 通过 `ReleaseReader.ReleaseByID(ctx, tenantID, spaceID, releaseID)` 读该 Release，不接受空 ID 或 `active`；读不到返回 `RELEASE_NOT_FOUND`。
  - 每条 `Slug` 必须是该 Release 的成员，否则整批拒绝，返回 `MEMBER_NOT_FOUND`。成员摘要由平台从 Release 取，不信任调用方。
  - 1 ≤ 条数 ≤ 500；`Slug`、`Stratum` 去掉首尾空白后非空，`Stratum` 不超过 64 个字符，同一批内 `Slug` 不重复，否则返回 `SAMPLE_INVALID`。
  - 按 `(tenant, space, release, slug)` 幂等：已存在的样本原样返回，不新建、不改 `Stratum`。返回顺序与输入顺序一致。
- `List(ctx, p, spaceID string, f Filter) ([]Sample, error)`
  - 只返回本租户、本 Space 的样本，按 `CreatedAt` 再按 `ID` 升序；每条带最新结论。
  - `Status` 为 `pending` 时只列没有结论的样本，为 `decided` 时只列有结论的样本，为空时全部列出，其他值返回 `SAMPLE_INVALID`；`ReleaseID` 非空时只列该 Release 的样本。
- `Decide(ctx, p, spaceID, sampleID string, outcome, note string) (Verdict, error)`
  - 样本必须属于本租户、本 Space，否则返回 `SAMPLE_NOT_FOUND`（不区分"不存在"与"属于别人"）。
  - `outcome` 只能是 `correct`、`incomplete`、`wrong`；`note` 去掉首尾空白，不超过 1000 个字符；否则返回 `VERDICT_INVALID`。
  - 结论只追加：同一样本可以有多条，`Reviewer` 取 `p.Subject`，`DecidedAt` 取服务时钟。
- 任何方法遇到 `p.TenantID == 0`、`p.Subject` 为空或 `spaceID` 为空，返回 `RELEASE_ACCESS_DENIED`；`Store` 返回的未知错误原样上抛，由路由层统一转成 `INTERNAL_ERROR`。
- 错误类型沿用 `*release.Error`。新增错误码定义在 `spotcheck` 包：`ErrorSampleInvalid = "SAMPLE_INVALID"`（400）、`ErrorSampleNotFound = "SAMPLE_NOT_FOUND"`（404）、`ErrorVerdictInvalid = "VERDICT_INVALID"`（400），在 `writeError` 中映射状态码；`RELEASE_NOT_FOUND`、`MEMBER_NOT_FOUND`、`RELEASE_ACCESS_DENIED` 沿用 `release` 包的常量。

**存储**：`Store` 接口由服务定义，PostgreSQL 实现放在 `internal/enterprise/releasestore`（或同级新文件）。

- 迁移 `migrations/enterprise/versioned/000008_enterprise_spot_checks.{up,down}.sql`：
  - `enterprise_samples`：`id TEXT PK`、`tenant_id BIGINT`、`space_id`、`release_id`、`logical_slug`、`member_digest`、`stratum`、`created_by`、`created_at TIMESTAMPTZ`；唯一索引 `(tenant_id, space_id, release_id, logical_slug)`。
  - `enterprise_sample_verdicts`：`id TEXT PK`、`tenant_id`、`space_id`、`sample_id TEXT REFERENCES enterprise_samples(id)`、`outcome TEXT CHECK (outcome IN ('correct','incomplete','wrong'))`、`note`、`reviewer`、`decided_at`；索引 `(sample_id, decided_at, id)`。
  - down 迁移依次删除两张表。
- 幂等插入用唯一索引加 `ON CONFLICT DO NOTHING` 后回读，并发提交同一样本只留一条。

**路由**：

| 方法与路径（前缀 `/api/v1/enterprise`） | 鉴权 | 说明 |
|---|---|---|
| `POST /spaces/:space_id/releases/:release_id/samples` | API Key（与现有 enterprise 路由相同：全权限服务 Key） | 请求 `{"samples":[{"slug","stratum"}]}`，响应 201 `{"success":true,"data":{"samples":[Sample]}}`；请求体上限 256 KiB，多余字段与重复键拒绝（`SAMPLE_INVALID`） |
| `GET /spaces/:space_id/samples?status=&release=` | API Key | 响应 `{"samples":[Sample]}`，供 Harness 回流统计 |
| `GET /spaces/:space_id/view/samples?status=&release=` | 浏览器会话，Space 可见，原 view 守卫（Viewer） | 同上，供抽检台列表 |
| `POST /spaces/:space_id/view/samples/:sample_id/verdicts` | 浏览器会话，并要求对该 Space 的 Wiki KB 至少有编辑权限 | 请求 `{"outcome","note"}`，响应 201 `{"verdict":Verdict}`；`reviewer` 取会话主体，不接受请求中的确认人 |

- API Key 路由加在 `enterprise.Mount`，会话读路由加在 `MountSessionReads`，都在本项目包内。
- 会话写路由需要编辑权限守卫：新增 `enterprise.MountSessionSpotChecks(r, deps, guards...)`，在 `internal/router/router.go` 中调用，传入 `RequireKBAccess(..., types.OrgRoleEditor, ...)` 守卫。`router.go` 已在上游补丁登记中，本片只在同一处增加一次调用，在 `docs/design/upstream-patches.md` 追加一行登记，不新增被修改的上游文件。

### 2.2 RV4b 抽检台（`frontend/src/enterprise/`）

- 路由 `enterpriseSpotChecks`：`enterprise/:spaceId/spot-checks`。Space 页右上角增加"抽检"链接。
- 页签"待确认 / 已确认"，分别请求 `status=pending` 与 `status=decided`。列表按 Release 分组，组标题显示发布版本号（epoch）。
- 每条样本：
  - 读取样本所属 Release（`readRelease(spaceId, release_id)`，同一 Release 只读一次），找到 `logical_slug` 对应的 Claim 与条目，显示条目名、字段标题、取值（复用 `EnterpriseField`，含 S3d-4 的分条与缩略版）和出处按钮；出处抽屉固定在样本的 Release。
  - 成员摘要与样本的 `member_digest` 不一致时，显示"该条目已变化"，并禁用结论按钮。
  - 按钮"正确 / 不完整 / 错误"，可填说明（不超过 1000 字）；提交中禁用按钮，失败显示错误并允许重试；成功后该条移到"已确认"。
  - 已确认的样本显示结论、说明、确认人与时间。
- 覆盖加载、空状态（"没有待确认的样本"）、失败重试、键盘可达；无编辑权限时提交返回 403，显示"没有确认权限"。
- 文案 zh-CN，其余 4 种语言同步。

### 2.3 RV4c 抽样与回流（Harness）

- **`catalog/spot_check_policy.json`**（版本化数据）：
  ```json
  {"version": "1", "default": {"rate": 1.0, "minimum": 5, "target": 0.9, "must_check": []},
   "packs": {"schemapack_critical_illness_insurance": {"rate": 1.0, "minimum": 5, "target": 0.9,
             "must_check": ["coverage_responsibilities", "disease_benefit_rules", "exclusions", "waiting_period"]}}}
  ```
  - `rate` 是 0–1 的抽样比例；`minimum` 是每个 pack 每次至少抽几条（不足时全抽）；`target` 是机器审核内容的目标精确率，回流时与 Wilson 下界比较；`must_check` 是必抽字段（字段键）。
  - 没有单独配置的 pack 用 `default`。
  - 加载时校验：版本非空，`rate` 与 `target` 在 0–1，`minimum` ≥ 0，字段键非空且不重复；不合法时返回固定错误码 `SPOT_CHECK_POLICY_INVALID`。
- **`catalog/spot_check.py`**：`load_spot_check_policy(path=None) -> SpotCheckPolicy`，`None` 读包内 `spot_check_policy.json`；`SpotCheckPolicy.for_pack(pack_id) -> PackRule`（没有单独配置时用 `default`）；不合法时抛 `SpotCheckPolicyError`，`code == "SPOT_CHECK_POLICY_INVALID"`。
- **`review/spot_check.py`**（核心、通用）：`sample(release, base, policy) -> list[Pick]`，`Pick(slug, stratum)`。
  - **抽样范围**：本次新上线的机器审核 Claim，即 `review.mode == "machine"`，并且在 `base` Release 中不存在或成员摘要不同；`base` 为 `None` 时取全部机器审核 Claim。没有变化的 Claim 已经在之前的 Release 中抽过，不重复抽。
  - **pack 归属**：由 Release 自身决定。条目（entity 成员）的 `classification_labels` 与哪个 profile 相交，就属于该 profile 的 `schema_pack_id`。归不到 pack 的 Claim 记入 `stratum = "unassigned/rest"`，按 `default` 规则抽。
  - **分层**：每个 pack 分两层。
    - 必抽字段一层全抽，`stratum = "<pack>/must"`；
    - 其余一层抽 `min(数量, max(minimum - 必抽数, ceil(rate × 数量)))` 条，`stratum = "<pack>/rest"`。
  - **可复现**：其余层用 `random.Random(f"{release.id}/{pack}")` 抽取，同一 Release、同一策略结果不变；返回结果按 slug 排序。
- **平台客户端**（`bundle/client.py`）新增：
  - `PlatformClient.submit_samples(space_id, release_id, picks) -> list[Sample]`；
  - `PlatformClient.samples(space_id, *, status=None, release_id=None) -> list[Sample]`。
  - `Sample` 与 `Verdict` 是响应模型，字段同 §2.1。
- **发布接线**：`publish.py` 在机器审核激活 Release 之后，以发布前读到的 Active 为 `base` 抽样并提交样本；人工决定的发布不抽。提交失败不回滚发布，命令输出 `"samples": {"stopped": <code>}`，可以用回流命令补交；成功时输出 `"samples": <条数>`。
- **回流命令** `python -m insurance_harness.eval.spot_check_report --space S [--release R] [--submit]`：
  - 读取样本与结论，按 pack 统计：样本数、已确认数、正确、不完整、错误，精确率与 Wilson 下界（95%）。"不完整"按 S2c 口径不算错。
  - Wilson 下界低于该 pack 的 `target` 且已确认数不少于 `minimum` 时，输出"提高门槛或撤销准入"建议，不自动改审核策略；已确认数不足时输出"样本不足"。
  - 判为错误的条目列入修正清单（slug、Release、确认人、说明）。
  - `--submit --release R` 对指定 Release 补交样本，以它的 `base_release_id` 为 `base`，幂等。
  - 输出一行 JSON 摘要，详细报告写到 `--out` 指定的文件；失败时输出一行 `{"stopped": <code>}` 并以 2 退出，不含路径或密钥。

## 3. 拆分与顺序

1. RV4a（Codex 实现，Claude 审核）：服务、存储、迁移、路由与 Go 测试；
2. RV4c（Claude 实现，Codex 审核）：与 RV4a 并行，用假平台测试；
3. RV4b（Codex 实现，Claude 审核）：依赖 RV4a 的接口；
4. 部署（单独 Issue）：App 与 UI 各构建 1 次，执行迁移 000008。

## 4. 用户已批准（2026-10-18）

- 迁移 `000008_enterprise_spot_checks`：本机测试库与演示环境，附 down 迁移；
- 部署时 App、UI 各构建 1 次。

## 5. 不在本片

- 抽检结论自动写回 Golden（先人工核对后再写，另立切片）；
- 按字段的门槛；
- 消息通知。

## 6. 验收（各子片的 RED 单独提交）

- **RV4a**（`internal/enterprise/spotcheck/acceptance_test.go`，内存 Store 与 ReleaseReader）：
  - 提交：成员摘要取自 Release；不存在的成员整批拒绝；空、超长、重复与超量拒绝；同一 Release 同一 slug 幂等；`active` 与空 Release ID 拒绝；
  - 列表：租户与 Space 隔离；`pending`/`decided`/全部与按 Release 过滤；带最新结论；排序稳定；非法状态拒绝；
  - 结论：只追加、以最新一条为准；确认人取自主体；非法结论与超长说明拒绝；别的 Space 或租户的样本返回 `SAMPLE_NOT_FOUND`；
  - 主体缺失一律 `RELEASE_ACCESS_DENIED`。
  - 实现方另补：PostgreSQL 存储测试（`integration_postgres` 同类标记）、迁移 up/down、路由测试（鉴权、状态码、请求体限制、编辑权限）。
- **RV4c**（Harness）：策略校验；分层与必抽；按 Release 种子可复现；只抽机器审核；发布接线（人工发布不抽，提交失败不回滚）；回流统计、Wilson 下界、建议与修正清单。
- **RV4b**（前端）：列表分组与页签；字段显示与出处固定在样本 Release；成员已变化时禁用；提交成功、失败重试、无权限；加载、空、失败状态。

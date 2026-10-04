# S3b · Go 通用接收与预览：`internal/enterprise/release`

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §6.2、§5.3、§4.2、§8（G11）、§11（S3）
> 分支：`slice/s3b` ｜ 开工方式：写完计划即开工 ｜ 真实模型调用：**不需要**
> 前置：**S3a 已合并**（`contracts/*.schema.json` 与 G9 就位）。S3c（决定/激活/去签名）、S3d（前端按数据生成页面）另开。

## 1. 目标

让平台按**通用合同**接收编译产物，不再按 contract 分派：新增 `internal/enterprise/release/`，实现
`POST /candidates`（接收 CandidateBundle，digest 幂等，结构校验 + 平台不变量）与
`GET /candidates/:id/preview`（与当前 Active 的实体级差异），并用 S3a 导出的 JSON Schema 做结构校验。
本片只做**接收与预览**；决定、激活、CAS 与去掉签名属 S3c。

## 2. 现状

- **`internal/enterprise/` 只有 `managed/`**（7 个文件，S1a/S1b 的受管判定与读取守卫）。蓝图 §4.2 要求的
  `mount.go` 与 `{source,release,read,feedback,expertedit}` **都还不存在**。
- 现有发布链在旧位置：`internal/handler/wiki_release.go`（383 行：Prepare / Activate / Current / PinnedPage /
  PinnedPayload / MinimalSearch）、`internal/application/service/wiki_release.go`（**2040 行**，含
  `PublishAuthorizationV0`、`HumanBatchDecisionReceiptV1`、`Schema67GoldenQualityGateReceiptV1` 三个 ed25519 校验器）、
  `internal/application/repository/wiki_release.go`（689 行）。
- 路由在 `internal/router/routes_knowledge.go:453-494`，前缀
  `/knowledgebase/:kb_id/wiki/release-scopes/:space_id/raw/:raw_kb_id`，含 `/preparations`、`/activations`、`/current`、
  `/releases/:release_id/pages/:logical_slug`、`/releases/:release_id/payloads/:logical_slug`、`/releases/:release_id/search`。
- 迁移：`migrations/enterprise/versioned/000001..000005`。
- Go 已有依赖 `github.com/santhosh-tekuri/jsonschema/v6 v6.0.2`（`go.mod:54`），S3a 的 schema 直接可用。
- **蓝图 §3.2/§10 要求去掉 ed25519 发布信封**（改为审核记录绑定 digest + 审计日志 + 服务间认证），退出点是 S3；
  本片**不删**旧校验器（S3c 删），也不改 `/activations` 的现状。

## 3. 设计

### 3.1 包与类型（`internal/enterprise/release/`）

```go
package release

// 输入身份：来自 context 的租户与主体，由调用方（router 中间件）解析后传入。
type Principal struct{ TenantID uint64; Subject string }

type Member struct {                    // 对应 contracts 的 BundleMember
    Kind         string
    LogicalSlug  string
    Payload      json.RawMessage        // 原样保存，不解析语义
    MemberDigest string                 // 调用方给；本包校验 = sha256(Payload)
    EvidenceRefs []string
}

type Bundle struct {                    // 对应 contracts 的 CandidateBundle
    ContractVersion  string
    BaseReleaseID    string
    Origin           string
    Members          []Member
    Removals         []string
    CompilerIdentity string
}

// Candidate 是本包对外的稳定视图；ID 由 Store 分配。
type Candidate struct {
    ID           string
    SpaceID      string
    TenantID     uint64
    BundleDigest string
    BaseReleaseID string
    Status       string
}

type Head struct{ ReleaseID string; Epoch uint64 }

type Delta struct {
    Added     []string  // logical_slug
    Changed   []string
    Removed   []string
    Unchanged []string
}

type Preview struct {
    CandidateID   string
    BaseReleaseID string
    HeadReleaseID string
    NeedsRebase   bool     // Head 前进了
    Delta         Delta
}

type Error struct{ Code, Detail string }
func (e *Error) Error() string
// Code 取值：CANDIDATE_INVALID / CANDIDATE_NOT_FOUND / RELEASE_ACCESS_DENIED

type Store interface {
    // CreateCandidate 以 BundleDigest 幂等：同 digest 返回已存在的 Candidate 且不新建行。
    // 首次创建时必须同时保存 bundle（成员与 removals），供 BundleOf 取回。
    CreateCandidate(ctx context.Context, c Candidate, b Bundle) (Candidate, error)
    CandidateByID(ctx context.Context, tenantID uint64, spaceID, id string) (Candidate, error)
    // BundleOf 取回该 candidate 提交时保存的 bundle 原文。
    BundleOf(ctx context.Context, tenantID uint64, spaceID, candidateID string) (Bundle, error)
    Head(ctx context.Context, tenantID uint64, spaceID string) (Head, error)
    // MembersOf 返回某个 Release 的 logical_slug -> member_digest。
    MembersOf(ctx context.Context, tenantID uint64, spaceID, releaseID string) (map[string]string, error)
}

type EvidenceResolver interface {
    // Resolve 报告该引用是否存在且 quote hash 一致。返回 (false, nil) 表示"不存在"。
    Resolve(ctx context.Context, ref string) (bool, error)
}

type Service struct{ /* 未导出字段 */ }

func NewService(store Store, evidence EvidenceResolver, schemas map[string][]byte) *Service
func (s *Service) Receive(ctx context.Context, p Principal, spaceID string, raw []byte) (Candidate, error)
func (s *Service) Preview(ctx context.Context, p Principal, spaceID, candidateID string) (Preview, error)
```

- `schemas` 由调用方从仓库根 `contracts/` 读取（`candidate_bundle.schema.json` 等），**本包不读文件系统**，
  便于测试注入。
- **digest 口径（冻结，验收测试按此断言）**：`member_digest = hex(sha256(canonical(payload)))`，
  `BundleDigest = hex(sha256(canonical(bundle)))`；`canonical` = 反序列化到 `any` 后重新 `json.Marshal`
  （Go 对 map 键排序，结果确定）。实现不得改用其它口径。
- 支持的合同版本来自包内常量 `SupportedContractVersion = "1"`（与 `contracts/README.md` 一致），
  与 `schemas` 内容无关；S3a 的 schema 只负责结构校验。
- 平台不变量按 §6.2 只做 Go 该做的那些：canonical JSON 与 digest、成员闭包与引用双射（`MembersOf` 与
  `EvidenceRefs` 指向存在的引用）、访问范围、租户隔离。**不做**字段齐全性、实体消歧、质量评分、文案。
- 不做签名相关任何事；不 import 旧 `service`、`handler`、旧 `wiki_release` 类型（守卫 G1/G11）。

### 3.2 校验顺序（失败关闭）

1. 限长（`io.LimitReader` 同旧实现的风格，上限常量集中定义）与严格 JSON（`DisallowUnknownFields` 不适用于
   `json.RawMessage` 内部，故用 schema 的 `additionalProperties:false` 兜底）。
2. `ContractVersion` 必须等于 `contracts/README.md` 声明的版本（本片为 `"1"`），否则 `CANDIDATE_INVALID`。
3. JSON Schema 校验（`santhosh-tekuri/jsonschema/v6`），失败即 `CANDIDATE_INVALID`，`Detail` 带首条错误路径。
4. `member_digest` 必须等于 `sha256(规范化后的 payload)`；不等即 `CANDIDATE_INVALID`。
5. `Members` 的 `logical_slug` 不得重复，且不得同时出现在 `Removals`；违反即 `CANDIDATE_INVALID`。
6. 每条 `evidence_ref` 经 `EvidenceResolver`；`Resolve` 返回 false 或出错即 `CANDIDATE_INVALID`
   （失败关闭，不静默丢成员）。
7. 全部通过后调 `CreateCandidate`（按 digest 幂等）。

### 3.3 预览

- 取 `Head`；`NeedsRebase = Head.ReleaseID != candidate.BaseReleaseID`。
- 与 **Head** 的成员表比对（Head 为空时全部计 `Added`）：新 slug → `Added`；digest 变 → `Changed`；
  在 `Removals` 且 Head 里有 → `Removed`；其余 → `Unchanged`。四类各自按 slug 升序。
- 不做 rebase 本身（S3c），只报告 `NeedsRebase`。

### 3.4 路由与挂载

- 在 `internal/enterprise/` 新增 `mount.go`：一个 `Mount(r gin.IRouter, deps Deps)`，注册
  `POST /candidates`、`GET /candidates/:candidate_id/preview`，并挂服务间认证与租户解析（复用 `managed` 旁边
  已有中间件的做法；**不新建第二套认证**）。
- 在 `internal/router/` 里**加一行**调用 `enterpriseMount.Mount(...)`（这是必需的上游接缝，按 G10 登记）。
- 旧路由 `/release-scopes/.../preparations` 与 `/current` 等**保持不变**（S3c 再迁）。

## 4. 交付物

- `internal/enterprise/release/{service,types,validate,preview}.go` 与 `internal/enterprise/mount.go`。
- 测试 `internal/enterprise/release/*_test.go`：用假 `Store`（内存 map）与假 `EvidenceResolver`，不连数据库、
  不发网络请求；schema 用 S3a 的真实产物（`os.ReadFile("../.../contracts/...")` 或内联最小 fixture，二者择一并在
  PR 说明）。
- `internal/router/` 的一行挂载与对应登记。

## 5. 验收

- Claude 提供的受保护验收测试 `internal/enterprise/release/acceptance_test.go`（随本片推送，当前 RED）全过。
  它只使用 §3.1 的公开类型与两个方法，用内存假 `Store`/假 `EvidenceResolver` 与内联最小 schema，不连数据库、
  不发网络请求；覆盖：合法 bundle 接收成功且 `BundleDigest` 稳定；同 digest 重复接收幂等且 Store 只被创建一次；
  schema 违规、`MemberDigest` 与 payload 不符、`LogicalSlug` 重复、`EvidenceRef` 无法解析，各自返回
  `CANDIDATE_INVALID`；`ContractVersion` 不等于传入 schemas 的版本时 `CANDIDATE_INVALID`；
  空 Head 时预览把全部成员记为 `Added` 且 `NeedsRebase=false`；Head 前进时 `NeedsRebase=true`；
  未知 candidate 返回 `CANDIDATE_NOT_FOUND`；跨租户预览返回 `RELEASE_ACCESS_DENIED`。
  **具体断言以测试文件为准**，实现不要改它。
- `go test ./internal/enterprise/... ./internal/router/...` 通过；`go vet` 通过；`gofumpt` 通过。
- 仓库根架构守卫通过，G10 新登记 1 个文件后基线**只增这一项**（由 Claude 审查后更新）。
- CI 全绿。

## 6. 改动范围

- 允许新增：`internal/enterprise/release/`、`internal/enterprise/mount.go`、对应测试。
- 允许修改：`internal/router/routes_knowledge.go`（或 `router.go`）**仅新增一行挂载**、
  `docs/design/upstream-patches.md`（只追加登记行）。
- 不得修改：蓝图、`docs/design/` 其他文件、`contracts/`（只读）、`tests/architecture/`、`harness/`、
  旧 `internal/application/service/wiki_release.go`、`internal/handler/wiki_release.go`、既有路由语义。

## 7. 非目标

- 不做决定（`/decisions`）、激活、CAS、rebase（S3c）。
- 不删 ed25519 校验器（S3c）。
- 不做前端页面（S3d）。
- 不改旧 `/release-scopes/...` 路由行为；不新增数据库迁移（S3c 若需要迁移，那时再开）。
- 不调用真实模型。

# S0-R Release falsification Mission Card

> 状态：`FIRST RUN NOT_FEASIBLE / AMENDMENT A SPEC REVIEW PENDING`
>
> 时限：输入身份与专用环境就绪后，最多两个工作日。

## 业务目标

证伪 WeKnora 能否以小而可持续跟版的 patch 承载唯一 serving Active Release。
现在执行是为了在 MVP 前尽早发现整版原子性、读取、权限或升级成本是否不成立。
它不是生产 Release Kernel 交付，也不接真实保险编译链。

## Owner、依赖与交付

- 唯一写 Owner：后续由总控指定的一个 S0-R 开发 lane；
- 基线：开始时最新 `origin/main`，且必须包含 upstream capability
  `80a5003cc99a427098afe184eee6601916d3d156`；
- 环境：隔离测试 Space、专用凭据、exactly 1 RAW KB、exactly 1
  release-managed Wiki KB、仓库基线 PostgreSQL 16 与当前最小索引后端；
- 依赖：046 Spec Approved；不依赖 S0-Q 结果、P2d 实现、provider 或生产部署；
- 预计：一个 Draft PR；两工作日内给出二元终态。

## 第一轮冻结 patch budget（历史结果）

实现只可触及以下 exact production/migration paths：

1. `internal/types/wiki_release.go`（new）
2. `internal/application/repository/wiki_release.go`（new）
3. `internal/application/service/wiki_release.go`（new）
4. `internal/handler/wiki_release.go`（new）
5. `internal/router/routes_knowledge.go`
6. `internal/container/container.go`
7. `migrations/enterprise/versioned/000002_release_falsification.up.sql`（new）
8. `migrations/enterprise/versioned/000002_release_falsification.down.sql`（new）
9. `internal/application/service/wiki_release_falsification_test.go`（new）
10. `internal/handler/wiki_release_falsification_test.go`（new）

允许同步修改：

- `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`：只登记上述 project
  patch 与跟版责任；
- OpenSpec 046 的 tasks/validation：只写真实执行证据。

任何第三个测试文件、额外生产路径、前端、Harness、official migration、
workflow、principal 或通用索引框架需求都超预算，直接输出
`RELEASE_PATH_NOT_FEASIBLE`，不在计时中扩面。

第一轮在 RED 前确认：要把新 Release handler 安全接入现有 RBAC/API-key
authority 与普通 Wiki PUT/DELETE guard，必须修改未列入上述预算的
`internal/router/router.go`。该轮已按合同输出
`RELEASE_PATH_NOT_FEASIBLE`，没有实现功能、测试或 migration。

## Amendment A 候选预算

OpenSpec 048 只提议在上述十个路径之外增加：

11. `internal/router/router.go`

该路径仅用于：

- 向 `RouterParams` 显式注入 `WikiReleaseHandler`；
- 在既有 `/api/v1` RBAC/API-key authority 下调用 release-aware Wiki 路由注册；
- 保持既有 `RegisterWikiPageRoutes` 签名可用，在已授权的
  `routes_knowledge.go` 内增加 production-only 严格 wrapper，避免修改现有
  `router_wiki_test.go` 形成第 12 路径；
- 不改变现有普通 Wiki route 的 principal 语义。

其余 patch、表/索引、migration、read/write surface、fixture 与命令预算全部
不变。任何第 12 个生产/测试路径、第二 migration、全局 service locator、
隐藏 `init` 接线或权限旁路仍立即输出 `RELEASE_PATH_NOT_FEASIBLE`。

只有 OpenSpec 048 合入且书面规格复核通过后，才可从当时最新 `origin/main`
建立新 worktree 重新开始 RED；不得复用第一轮未产生的实现状态。

## 冻结物理预算

enterprise migration 000002 最多创建五张实验表：

- `wiki_release_preparations`
- `wiki_releases`
- `wiki_release_members`
- `wiki_release_heads`
- `wiki_release_receipts`

最多创建五个非主键索引：scope 唯一 Head、preparation digest、release manifest、
release member logical identity、receipt nonce/idempotency。不得修改 official
`wiki_pages`/`wiki_page_revisions` migration identity，不得创建第二个 Harness
Active Head。表名是实验预算，不代表生产 schema 已获批准。

## 冻结 read/write surface

仅允许一个 release API group，语义固定为：

- prepare exact manifest；
- activate exact ready preparation；
- current read：请求开始取得一个 `release_id + activation_epoch`；
- pinned page/payload read：显式 `release_id + logical_slug`；
- release-aware minimal search：显式固定同一个 `release_id`；
- ordinary Wiki PUT/DELETE 对 release-managed KB 拒绝；
- receipt 的 exact-idempotent retry read。

不做 rollback API、Proposal UI、MCP、通用 query DSL、全量 Agent retrieval、
Evidence UI、真实生产 Space 启用或部署。隔离 S0-R HTTP handler 仍必须接入
现有 production router/RBAC chain；该接线只构成载体可行性证据，不得宣称
生产 Release 能力已交付。

## 暂定 PublishAuthorizationV0

授权只用于实验，字段固定为：

`version, action, preparation_id, candidate_digest, manifest_digest,
ready_receipt_digest, review_decision_digest, review_policy_id,
tenant_id, space_id, raw_kb_id, wiki_kb_id, expected_release_id,
expected_activation_epoch, expires_at, nonce, signer_key_id, signature`。

签名字节是除 `signature` 外所有字段的 UTF-8 canonical JSON：字段按字典序、
无多余空白、整数十进制、字符串 NFC、拒绝重复 key/浮点/未知字段。成功与测试
vector 必须由 Go 端重算；046 不将该格式批准为生产 V1。

校验顺序固定：

1. 闭合解析与 canonical digest；
2. 按 `(space_id, wiki_kb_id, nonce)` 查询既有 receipt：digest 相同返回原结果，
   digest 不同拒绝；
3. 验签与 signer；
4. action、scope、expiry；
5. preparation Ready 与全部 digest；
6. 当前 Space/RAW KB/Wiki KB binding 与两个 KB 的当前 ACL；
7. expected release/epoch；
8. 单事务写 immutable release/members、CAS Head、消费 nonce、写 receipt。

任一步失败都不得改变 preparation、release、member、head、receipt 或普通 Wiki
页面；已提交但响应丢失的 retry 必须返回原 receipt。

## 唯一 fixture 与验收

- R0：A/B/C；
- R1：A updated、B deleted、C unchanged、D new；
- 从同一 R0 base 构造两个内容不同的 Candidate；
- 在 preparation、index、CAS、receipt 四处各注入一次失败；
- 激活前后并发 current/pinned read；
- 两个 principal 均可读 R0/R1，随后收缩其中一个 principal 的 RAW/Wiki ACL。

`RELEASE_PATH_FEASIBLE` 必须同时证明：

- R1 通过目标 prepare/index/CAS/receipt 路径激活；
- 同 base 双 Candidate 只有一个 winner；
- 所有 page、payload、minimal search 只见完整 R0 或完整 R1；
- 重复提交幂等；四类失败无半激活；
- ACL shrink 后被移除 principal 对 current/pinned/search 全部 fail closed；
- managed 普通 PUT/DELETE 零写拒绝；
- Harness 没有第二 Active Head；
- 实际 patch、migration 与未来升级 owner 未超过本卡预算。

任一条件失败或超预算即 `RELEASE_PATH_NOT_FEASIBLE`。不得用“还差一点”延期。

## 验证命令预算

只允许：

- 新增两个 focused Go test files 的 exact package tests；
- 新 migration 的 disposable PostgreSQL 16 fresh/up/down/restart；
- R0/R1、双 Candidate、四故障点、并发 read、ACL shrink 的专用 S0-R probe；
- `go test` 仅覆盖 touched Go packages；
- `go vet` 仅覆盖 touched Go packages；
- `openspec validate 046-weknora-release-capability-falsification --strict`；
- `git diff --check` 与 exact scope/sensitive/private-path scan；
- 045 finite adoption check，用于确认新增 patch 登记和 official migration 零漂移。

禁止 full、provider、live、生产 Space、全仓 PG、前端全量、负载平台或安全理论
扩展测试。

## 明确非目标与阻断定义

非目标：生产 Kernel、正式协议、rollback、P2d/043 amendment、source_reader
提权、S0-Q、legacy 清理、部署或 Artifact。

阻断只包括：身份/环境不可信；需要超预算；集合原子性、单赢家、读取隔离、
ACL shrink、guard、失败零写或幂等任一不可成立。普通上游代码风格、理论威胁
模型和范围外重构不阻断本实验。

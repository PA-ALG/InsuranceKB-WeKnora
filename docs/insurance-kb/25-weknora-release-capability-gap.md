# 80a5003 Release capability gap

> 状态：`FACT MATRIX / NO IMPLEMENTATION`
>
> 证据身份：项目 `6605c703282e442a8636d7f323f17396e6f00d49`，其 Git 历史包含
> `80a5003cc99a427098afe184eee6601916d3d156`；采用目标由
> `deploy/upstream/weknora-adoption-target.json` 冻结。

本表只回答 WeKnora 当前 fork 是否具备 S0-R 所需的领域无关能力。分类含义：

- `PRESENT`：当前源码有直接、可定位的能力；
- `PATCHABLE`：有明确可复用底座，但整版合同尚不存在，必须由 S0-R 实测；
- `ABSENT`：生产 Go/SQL/API 中未找到该整版能力；
- `UNKNOWN`：静态证据不足，只允许在 S0-R 冻结预算内求证。

单页乐观锁、history 或 revert 不等于整版 Release。

| 能力 | 结论 | 当前 exact 证据 | S0-R 含义 |
|---|---|---|---|
| 单页不可变历史、manual edit、revert | `PRESENT` | `migrations/versioned/000075_wiki_page_revisions.up.sql` 建 `wiki_page_revisions`；`internal/application/repository/wiki_page.go` 的 `UpdateWithRevision` 同事务保存旧版；`internal/router/routes_knowledge.go` 暴露 revisions/revert | 只复用页面 revision 与版本冲突语义；不得据此通过整版验收 |
| 整版 manifest（A/B/C → A′/C/D） | `ABSENT` | `wiki_pages` 与 `wiki_page_revisions` 没有 `release_id` 或集合 manifest；当前 `manifest_digest` 生产字段只属于 W1 `knowledge_revisions`（`migrations/enterprise/versioned/000001_knowledge_revision_manifest.up.sql`） | 需要有界新增 release/member manifest；不得复用 W1 digest 冒充 Release manifest |
| 原子 activation / expected-head CAS | `ABSENT` | `internal/application/repository/wiki_page.go` 只有单页 `id + version` 乐观锁；生产 Go/SQL 未找到 `active_release`、`activation_epoch` 或 Release Head | S0-R 必须证明同 base 双 Candidate 单赢家；单页 CAS 只算实现素材 |
| pinned/current/release-aware page read | `ABSENT` | `internal/router/routes_knowledge.go` 的 Wiki GET 仅以 KB/slug 定址；当前 Wiki 类型、仓储与 route 无 `release_id` | 实验必须新增最小 current 与 pinned read，且一次请求只固定一个 release |
| release-aware index/search | `UNKNOWN` | 现有 Wiki search 以 KB 为范围；静态源码没有 release filter，但尚未证明最小隔离 namespace 在所有实际索引边界可行 | S0-R 必须在冻结的最小 search surface 证明 R0/R1 不混召回；超预算即 NOT_FEASIBLE |
| release-managed 普通 PUT/DELETE guard | `ABSENT` | `internal/router/routes_knowledge.go` 直接给 KB owner/admin 普通 PUT/DELETE；当前 Wiki model 无 `release_managed` 标识 | 实验范围必须让 managed KB 的普通 PUT/DELETE 确定性拒绝且零写 |
| 当前 ACL 与 ACL shrink | `PATCHABLE` | Wiki reads 已经过 `Viewer + KBAccessRead`，writes 经过 `OwnedWikiKBOrAdmin + KBAccessWrite`（`internal/router/routes_knowledge.go`）；但 pinned Release、绑定 RAW/Wiki 双 ACL 与 Evidence 下钻尚不存在 | 用两个真实 principal 对同一 pinned release 做一次当前 RAW/Wiki ACL shrink；任一路仍可读即失败 |
| preparation/index/CAS/receipt 失败恢复 | `PATCHABLE` | 单页 revision 更新已有事务与 optimistic conflict；enterprise migration 已有独立 source/ledger。没有 Release preparation、nonce、幂等 receipt 或跨边界恢复状态 | 只验证四个规定故障点的零半激活、可重试或已提交回执重读，不建设通用恢复平台 |
| 跟版 patch surface | `PRESENT` | `deploy/upstream/weknora-adoption-target.json` 冻结 exact upstream；`harness/scripts/prepare_weknora_adoption.py` 做有限 check；`deploy/patches/enterprise-llm-wiki-patch-inventory.yaml` 登记 project paths；`internal/database/enterprise_migration.go` 隔离 official/enterprise ledger | S0-R 只可登记一个新 patch entry 与一个 enterprise migration pair；后续升级继续走 manifest + standard Git + targeted gates |

## 结论

当前不能声明 WeKnora 已具备整版 Release Kernel。最窄可证伪假设是：

> 单页 revision、现有 KB ACL、PostgreSQL 事务和薄升级轨道，可能足以在一个
> release-managed Wiki KB 上用有界 patch 补出集合 manifest、CAS Head、
> current/pinned read、guard 与 receipt。

该假设是 `UNKNOWN UNTIL S0-R`，不是实现承诺。046 仅授权下一步按 Mission Card
做两工作日实验；结果只能是 `RELEASE_PATH_FEASIBLE` 或
`RELEASE_PATH_NOT_FEASIBLE`。

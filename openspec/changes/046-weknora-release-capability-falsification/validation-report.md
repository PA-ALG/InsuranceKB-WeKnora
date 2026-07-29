# 046 · Validation report

> S0-R 第一轮身份：base/head/origin-main
> `35c3391412054d5050d9c76ab5aa535165188202`。
>
> Amendment A 后第二轮身份：base/head/origin-main
> `54923501fb75165b2272945ff1f7953150715820`，全新独立 worktree clean。
>
> 最终二元终态：`RELEASE_PATH_NOT_FEASIBLE`。第一轮只读预算核验与独立接口审查
> 确认同一 `BLOCKER`：安全生产接线需要 Mission Card 外第 11 路径
> `internal/router/router.go`；048 加入该路径后，第二轮可执行性审查又确认
> enterprise `000002` 会先执行到 version `2`，再被现有 frozen-head 校验拒绝
> 完成生产 migration phase，修复至少需要第 12 个生产路径。两轮均按 R0.2
> 在 RED 前停止，未实现 S0-R 或生产 Release Kernel。

## S0-R 二元裁决证据

- `internal/router/router.go:60-87` 的 `RouterParams` 只有
  `*handler.WikiPageHandler`，没有 `WikiReleaseHandler`；
- `internal/router/router.go:206-225` 创建既有 RBAC guards，并在所有
  `/api/v1` 路由前安装唯一 API-key authority；
- `internal/router/router.go:276` 是 `RegisterWikiPageRoutes` 的唯一生产调用，
  只传入 `params.WikiPageHandler` 与既有 guards；
- `internal/router/routes_knowledge.go:286` 的注册函数无法取得 release
  service/handler；现有普通 Wiki PUT/DELETE 分别在第 295、296 行直接连接
  `WikiPageHandler`；
- `internal/container/container.go:394` 只把 `router.NewRouter` 交给 DI。
  在 `RouterParams` 不增加 release dependency 的前提下，即使在允许的
  `container.go` 注册新 repository/service/handler，也不能把它接入上述生产
  路由、RBAC 与 API-key authority；
- Go 不能从新文件给既有 `WikiPageHandler` struct 增加依赖字段。修改其 struct
  或 constructor 又需要未授权的 `internal/handler/wiki_page.go`。

以下替代均经审查 `REJECTED`：

- package global 或隐藏 container side effect：绕过显式依赖和并发安全；
- 只在 focused test 中直调新 handler 或额外传 variadic handler：生产唯一调用
  不传依赖，不能证明真实接线；
- 脱离既有 RBAC/API-key gate 注册旁路 route：不能证明当前 principal、双 ACL
  shrink 或 managed write guard。

第一轮关于 enterprise `000002` “未构成阻断”的结论只表示当时未进入 runner
head 审查，已被下述第二轮 exact 证据取代。

## Amendment A 后第二轮裁决证据

- `internal/database/enterprise_migration.go:236-256` 的
  `validatePostgresMigrationSetVersion` 对 enterprise source 把 expected head
  固定为 `1`；`runPostgresMigrationSet` 会先执行 `migrator.Up()` 并读取最终
  version，随后才调用该校验。新增 `000002` 后 schema/ledger 会先到 version
  `2`，再返回 `MigrationSafetyError`；enterprise 分支不会自动 force 或回滚；
- `internal/database/legacy_w1_bridge.go:975-978` 把存在且不为 `-1`/`1` 的
  enterprise ledger 归为 unknown origin，`1015-1022` 也只承认 version `1`
  为 bridged/current；
- `internal/database/legacy_w1_bridge_test.go:1098-1120` 明确把 enterprise
  version `2` 作为应失败 case，`1295-1304` 的真实 PostgreSQL matrix 又断言
  current enterprise version 必须为 `1`；
- 因此获批的 `000002` 无法成功完成当前生产迁移阶段，而且真实执行会形成
  “schema/ledger 已到 2、startup 返回失败”的状态。最小修复已经需要 048
  十一条之外的 `internal/database/enterprise_migration.go`，并继续要求修改
  `internal/database/legacy_w1_bridge.go` 与
  `internal/database/legacy_w1_bridge_test.go`；
- 048 明确规定任何第 12 路径立即再次输出
  `RELEASE_PATH_NOT_FEASIBLE`，且不得继续追加修订，因此未创建 migration、
  RED、Release types/service/handler/router patch 或测试。

两轮累计实际功能 patch、测试、migration 和 patch-inventory 变更均为零，
没有形成 Harness 第二 serving Head 或任何实验 Head。签名算法、双 ACL
black-box fixture 与 HTTP route test 结构均未进入实现，不能据此写 PASS 或
进一步失败结论。

## 已复核静态事实

- `80a5003cc99a427098afe184eee6601916d3d156` 是当前 HEAD ancestor；
- `deploy/upstream/weknora-adoption-target.json` 冻结该 commit、tree
  `18fcf68e7a008ce69929e32233f0b6914040c223` 与 official migration head 75；
- `migrations/versioned/000075_wiki_page_revisions.up.sql` 只建单页 revision；
- `internal/application/repository/wiki_page.go` 的 CAS 是单页 `id + version`；
- `internal/router/routes_knowledge.go` 提供单页 revision/revert，同时普通
  PUT/DELETE 仍对 KB owner/admin 开放；
- 当前生产 Go/SQL 未找到整版 `active_release`、`activation_epoch`、
  `release_managed`、`PublishAuthorization` 或 Ready/activation receipt；
- W1 `manifest_digest` 属于 SourceRevision，不是 Release manifest；
- 045 manifest/thin check/patch inventory 与 enterprise migration ledger
  可承担后续有界跟版。

## 文档门禁

- 第一轮 pre-change baseline
  `go test ./internal/application/service ./internal/handler`：`PASS`，exit 0；
- 第二轮 implementation-plan 独立可执行性 review：`ISSUES FOUND`，上述
  enterprise head 固定值为直接 `BLOCKER`；
- 第二轮 Go baseline 与 S0-R 新 focused tests：`NOT RUN`，在 RED 前触发
  第 12 路径停线；
- PostgreSQL 16 targeted migration/fixture：`NOT RUN`；
- touched-package `go vet`：`NOT RUN`；
- 045 finite adoption check：`NOT RUN`；
- provider、live、full：`NOT RUN`，且不在命令预算内。

本报告只记录二元证伪，不得把 `RELEASE_PATH_NOT_FEASIBLE` 解释为 S0-R、
生产 Release 能力或 MVP 已完成，也不得据此恢复双 serving Head。

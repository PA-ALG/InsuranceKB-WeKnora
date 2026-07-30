# 046 · Tasks

## 046 文档交付

- [x] C1 核验 exact base、80a5003 ancestry 与 adopted target manifest。
- [x] C2 读取当前 Wiki revision、route、ACL、migration 与 thin-upgrade 证据。
- [x] C3 输出 capability gap，严格区分单页能力与整版 Release。
- [x] C4 冻结 S0-R Mission Card 的 exact paths、表/索引、migration、read
  surface、升级责任与命令预算。
- [x] C5 冻结唯一 R0/R1、双 Candidate、四故障点、并发 read 与 ACL shrink
  fixture。
- [x] C6 冻结暂定 PublishAuthorizationV0 canonical bytes、校验顺序与失败零写。
- [x] C7 独立 Spec/Delivery review。
- [x] C8 用户批准按 Mission Card 启动并执行 S0-R。

## S0-R 第一轮二元证伪结果

- [x] R1 从开始时最新 origin/main
  `35c3391412054d5050d9c76ab5aa535165188202` 建 clean 独立 worktree。
- [x] R2 在 RED 前完成 exact 接线预算核验；安全生产接入
  `WikiReleaseHandler` 与 managed PUT/DELETE guard 需要 Mission Card 外第 11
  路径 `internal/router/router.go`，因此按预算立即停止，未执行 RED→GREEN。
- [ ] R3 `NOT RUN`：二元预算阻断成立后未进入专用 Space/凭据、fixture 或
  targeted PostgreSQL 验证。
- [x] R4 两工作日内输出 `RELEASE_PATH_NOT_FEASIBLE`，actual 功能 patch、
  migration 与新增升级责任均为零。
- [x] R5 按 FAIL 停止当前 WeKnora 载体实现路线；不得继续扩面，后续只可重新
  评估单一 serving authority 的承载位置。

R4 的允许终态原定义为 `RELEASE_PATH_FEASIBLE` 或
  `RELEASE_PATH_NOT_FEASIBLE`，附 actual patch/migration/upgrade responsibility。

## Amendment A 后第二轮二元证伪结果

- [x] A1 OpenSpec 048 已加入唯一第 11 路径 `internal/router/router.go`，且用户
  于 2026-07-30 确认书面 Amendment。
- [x] A2 从当时最新 origin/main
  `54923501fb75165b2272945ff1f7953150715820` 建立全新 clean worktree。
- [x] A3 在 RED 前执行 implementation-plan 可执行性审查；确认 enterprise
  migration runner 与 legacy bridge 把合法 enterprise head 固定为 `1`，
  新增已批准的 `000002` 会先迁移到 version `2`，随后被 frozen-head 校验
  拒绝完成生产 migration phase。
- [ ] A4 `NOT RUN`：修复需要第 12 个生产路径
  `internal/database/enterprise_migration.go`，并继续牵涉未授权的
  `internal/database/legacy_w1_bridge.go` 与既有测试路径；按 048 立即停线，
  未写 RED、功能、migration 或测试。
- [x] A5 第二轮输出 `RELEASE_PATH_NOT_FEASIBLE`；actual 功能 patch、
  migration、测试与新增升级责任仍为零。
- [x] A6 按当时 048 规则停止第二轮并记录二元结果，且未恢复双 Head。

## 总控基础设施例外与第三轮恢复

- [x] O1 用户于 2026-07-30 明确裁决：工程合理性优先，不得让人工路径上限
  阻塞正常必需修改。
- [x] O2 仅批准 `internal/database/enterprise_migration.go`、
  `internal/database/legacy_w1_bridge.go` 与
  `internal/database/legacy_w1_bridge_test.go` 三条 migration 基础路径；
  不扩大 Release 表/API/ACL/principal 或通用 migration 平台。
- [ ] O3 从例外合入后的最新 main 建全新 clean worktree，先以现有 matrix RED
  证明 version `2` 被固定值拒绝，再做最小 GREEN。
- [ ] O4 migration 基础 GREEN 后，按原十一条业务路径恢复 S0-R，并继续执行
  R0/R1、双 Candidate、四故障点、并发 read、双 ACL shrink 与 managed guard。

## 永久非目标

- [ ] 不在 046 实现生产 Kernel、P2d、S0-Q、source_reader、MCP、UI 或部署。
- [ ] 不新增 official migration，不修改 upstream migration identity。
- [ ] 不以单页 Demo、历史代码或 Harness receipt 冒充 serving Active Head。

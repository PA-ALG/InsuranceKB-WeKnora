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

## S0-R 二元证伪结果

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

## 永久非目标

- [ ] 不在 046 实现生产 Kernel、P2d、S0-Q、source_reader、MCP、UI 或部署。
- [ ] 不新增 official migration，不修改 upstream migration identity。
- [ ] 不以单页 Demo、历史代码或 Harness receipt 冒充 serving Active Head。

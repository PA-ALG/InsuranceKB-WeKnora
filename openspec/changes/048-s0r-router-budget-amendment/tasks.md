# 048 · Tasks

## 本规格 PR

- [x] T1 从 PR #70 合入后的最新 `origin/main` 建 clean 独立 worktree。
- [x] T2 占用 OpenSpec 048 并更新 046 第一轮真实状态。
- [x] T3 只增加 `internal/router/router.go`，冻结总路径上限十一。
- [x] T4 明确现有 RBAC/API-key authority 内接线与第十二路径 fail closed。
- [x] T5 OpenSpec 048 strict、diff/scope 与独立 Spec/Delivery review。
- [ ] T6 用户复核书面 Amendment。

## 后续 S0-R（本 Change 不执行）

- [ ] R1 仅在 048 合入和 T6 完成后，从当时最新 main 建新 worktree。
- [ ] R2 从 focused RED 重新开始，不复用第一轮实现状态。
- [ ] R3 严守十一条路径、单 migration、五表/五索引与原命令预算。
- [ ] R4 若需要第十二路径或任何其他扩面，立即再次输出
  `RELEASE_PATH_NOT_FEASIBLE`。

## 永久非目标

- 本 Change 不交付 Release Kernel、生产 API、migration、测试或 Artifact；
- 不恢复 Harness Active Head；
- 不扩展 S0-Q、P2d、legacy 清理、provider 或部署。

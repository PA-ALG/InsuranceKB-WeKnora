# 048 · S0-R router budget amendment

## 状态

`SPEC-ONLY / IMPLEMENTATION NOT STARTED`

## 为什么做

S0-R 第一轮已按 046 的二元规则在 RED 前停止：冻结十路径预算无法把新
Release handler 接入 `internal/router/router.go` 中唯一的生产路由入口与既有
RBAC/API-key authority。PR #70 已记录该结果，且没有产生功能、测试或
migration 实现。

这证明第一轮预算少列了一个真实接线路径，不证明 WeKnora 永久不能承担唯一
serving Active Release。总控已同意先做最小预算修订，再决定是否恢复实验。

## 本 Change 做什么

- 在原十路径之外只增加 `internal/router/router.go`；
- 将 S0-R 路径上限冻结为十一，禁止任何第十二路径；
- 冻结该路径只能承担显式依赖注入和既有权限链内的生产路由注册；
- 保留 046 的其余合同、物理预算、fixture、命令预算与二元终态。

## 不做什么

- 不实现或注册 Release API；
- 不修改 Go、SQL、migration、Harness、workflow、Artifact 或部署；
- 不增加测试文件、表、索引、principal、通用路由框架或恢复双 serving Head；
- 不运行 focused、PostgreSQL、provider、live 或 full。

## 后续

本 Change 合入且书面规格复核通过后，S0-R 才可从届时最新 `origin/main`
建立全新 worktree，按十一条 exact path budget 重新从 RED 开始。若仍需要
第十二路径或其他预算扩张，必须再次立即输出
`RELEASE_PATH_NOT_FEASIBLE`，不得继续追加修订。

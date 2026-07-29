# S0-R Router Budget Amendment Specification

## ADDED Requirements

### Requirement: A1 第一轮失败不得被扩大解释

系统 SHALL 将 PR #70 的 `RELEASE_PATH_NOT_FEASIBLE` 解释为冻结十路径预算
无法完成真实生产接线。该结果 SHALL NOT 被解释为 WeKnora 永久不可作为载体，
也 SHALL NOT 授权恢复 Harness 与 WeKnora 双 serving Head。

#### Scenario: 预算失败被误写成载体永久失败

- **WHEN** 后续计划引用 PR #70
- **THEN** 它只可把缺失的生产路由入口列为预算事实，并继续保持单一 serving
  authority 约束

### Requirement: A2 Amendment 只增加一个 exact path

S0-R 的实现预算 SHALL 在原十路径之外只增加
`internal/router/router.go`，总上限为十一条。046 的表/索引、migration、
read/write surface、fixture、测试文件与命令预算 SHALL 保持不变。

#### Scenario: 出现第十二路径

- **WHEN** 实现需要任一未登记的生产或测试路径、第二 migration 或通用框架
- **THEN** Owner 立即输出 `RELEASE_PATH_NOT_FEASIBLE`，不得继续扩面

### Requirement: A3 新路径只能完成真实权限链内接线

`internal/router/router.go` 的修改 SHALL 只用于向 `RouterParams` 显式注入
`WikiReleaseHandler`，并在既有 `/api/v1` RBAC/API-key authority 下调用
release-aware Wiki 路由注册。现有 `RegisterWikiPageRoutes` 签名 SHALL 保持
可用；严格 production wrapper SHALL 位于已授权的
`internal/router/routes_knowledge.go`，不得为此修改现有
`internal/router/router_wiki_test.go` 形成第十二路径。实现 SHALL NOT 使用
package global、service locator、隐藏 `init` side effect、测试专用生产替身
或权限旁路。

#### Scenario: Release route 绕过既有 authority

- **WHEN** Release API 或 managed write guard 未经过既有 RBAC/API-key
  authority，或生产路由没有取得显式 Release handler
- **THEN** 该路径不构成可行性证据，实验 fail closed

### Requirement: A4 恢复实验必须从新基线和 RED 开始

S0-R SHALL 只在 048 合入并完成书面规格复核后，从届时最新
`origin/main` 创建全新 clean worktree。实现 SHALL 从 focused RED 开始，
不得把第一轮的只读接口分析冒充测试或实现进度。

#### Scenario: 复用第一轮状态

- **WHEN** 新实验尝试复用未提交实现、旧 base 或未运行的测试结论
- **THEN** Owner 停止并重新建立 exact clean identity 后再开始

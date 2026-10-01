# 上游补丁登记（蓝图 1001 G10）

规则：修改上游文件只在没有其他办法时进行；每处在此登记，数量只减不增（见蓝图 §8 G10、§4.3）。
"登记"不等于许可：该切片 Spec 必须显式允许该文件，Claude 审查后更新 `tests/architecture/baseline.json`。
替换或回退补丁时同步下调基线。

基线（2026-10-01，`main@878e5e85e`）：被修改或删除的上游文件 440 个，其中 `internal/` 非测试文件 222 个
（实质补丁约 47 个，其余为 0.8.2 升级中的格式改动，S7 回退）。

| 文件 | 切片 | 原因 | 可否上游化 | 退出条件 |
|---|---|---|---|---|
| `internal/application/repository/knowledge.go` | 831 之前 | 来源 revision/SHA 固定接缝 | 否（产品专属语义） | 蓝图 §4.3 接缝清单复核时 |
| `internal/infrastructure/docparser/*`（MinerU、pdfium 等） | 831 之前 | 解析与坐标捕获 | 部分可上游化 | G6A/G6D 定位能力稳定后 |
| `internal/application/service/agent_service.go` | 831 之前 | Agent 按轮固定 release | 否 | 上游若提供按版本读取 |
| `internal/router/routes_knowledge.go` | 831 之前 / S1a | Wiki 路由与受管守卫挂载 | 否 | 上游若提供受管写策略 |
| `internal/router/router.go` | 831 之前 / S1a | 路由挂载点 | 否 | 同上 |
| `internal/container/container.go` | 831 之前 / S1a | 依赖装配 | 否 | 同上 |
| 其余约 430 个（含格式改动） | 831 之前 | 见 git 历史 | — | S7 回退格式改动 |

S1a 待登记（Codex 在 PR 中补全实际清单后由 Claude 复核）：`internal/mcpserver/scope.go`、`server.go`、
`tools_ingest.go` 等 MCP 侧检查点。

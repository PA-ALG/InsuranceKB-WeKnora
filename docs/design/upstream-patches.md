# 上游补丁登记（蓝图 1001 G10）

规则：修改上游文件只在没有其他办法时进行；每处在此登记（见蓝图 §8 G10、§4.3）。
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
| `internal/agent/tools/wiki_write_page.go` | S1a | 创建/更新选定目标后检查共用写策略；缺少装配失败关闭 | 部分（通用策略扩展点） | 上游提供写策略扩展点后移除本地检查点 |
| `internal/agent/tools/wiki_replace_text.go` | 831 之前 / S1a | 替换前拒绝受管内容，避免先修链或修改页面 | 部分（通用策略扩展点） | 同上 |
| `internal/agent/tools/wiki_rename_page.go` | S1a | 重命名与链接重写前检查共用写策略 | 部分（通用策略扩展点） | 同上 |
| `internal/agent/tools/wiki_delete_page.go` | S1a | 删除与链接清理前检查共用写策略 | 部分（通用策略扩展点） | 同上 |
| `internal/agent/tools/wiki_flag_issue.go` | S1a | 创建维护 Issue 前检查共用写策略 | 部分（通用策略扩展点） | 同上 |
| `internal/agent/tools/wiki_update_issue.go` | S1a | 修改维护 Issue 状态前检查共用写策略 | 部分（通用策略扩展点） | 同上 |
| `internal/agent/tools/wiki_source_refs_test.go` | S1a | 既有非受管服务夹具装配写策略，原断言不变 | 否（测试装配） | 上游策略扩展点替代本地装配后恢复 |
| `internal/agent/tools/wiki_write_page_test.go` | S1a | 同上 | 否（测试装配） | 同上 |
| `internal/agent/tools/wiki_replace_text_test.go` | 831 之前 / S1a | 同上 | 否（测试装配） | 同上 |
| `internal/mcpserver/server.go` | S1a | 保留构造函数签名，在生产装配注入共用分类器 | 部分（通用策略扩展点） | 上游提供 MCP 写策略注入后移除本地装配扩展 |
| `internal/mcpserver/tools_ingest.go` | S1a | 按目标 KB 属主分类，在权限授予与文档修改前拒绝受管写入 | 部分（通用策略扩展点） | 同上 |
| `internal/router/router_wiki_test.go` | S1a | 同步必带分类器入口和属主查询装配，原断言不变 | 否（测试装配） | 上游提供原生 Wiki 写策略后恢复 |
| `internal/router/router_api_key_capabilities_test.go` | S1a | 同步必带分类器入口，原能力断言不变 | 否（测试装配） | 同上 |
| 其余约 430 个（含格式改动） | 831 之前 | 见 git 历史 | — | S7 回退格式改动 |

S1a 实际修改 16 个上游文件，其中 11 个此前未偏离上游：Agent 五个写源文件与两个夹具、MCP 两个文件、
路由两个夹具。`internal/mcpserver/scope.go` 未改。按 S1a Spec §6 登记，G10 基线由 Claude 审查后更新；
Codex 未修改守卫基线，也未为抵消新增补丁扩大退役范围。

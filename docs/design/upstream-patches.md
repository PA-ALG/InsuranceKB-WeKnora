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

| 文件 | 切片 | 原因 | 可否上游化 | 退出条件 |
|---|---|---|---|---|
| `internal/router/routes_knowledge.go` | S1b | 原生 Wiki 读路由接共用受管守卫，启动时验证属主查询依赖，并挂载只读 custody 端点；现有路由注册无策略扩展点 | 部分（通用路由策略） | 上游提供原生读策略与扩展路由挂载后移除接缝 |
| `internal/router/router_api_key_capabilities_test.go` | S1b | 路由能力测试夹具补属主查询依赖以满足启动断言，保留原断言 | 否（测试装配） | 上游提供受管读取扩展点后恢复 |
| `internal/mcpserver/scope.go` | S1b | 显式 KB 受管拒绝，默认范围排除受管 KB；现有 scope 选择无读取策略扩展点 | 部分（通用读取策略） | 上游支持 scope 读取策略注入后移除本地检查点 |
| `internal/mcpserver/scope_test.go` | S1b | 非受管选择测试装配分类器，保留原断言及未注入失败关闭验收 | 否（测试装配） | 上游读取策略测试装配可复用时恢复 |
| `internal/mcpserver/tools_retrieve.go` | S1b | 列表标注 release_managed，read_document 在获取 KB 后检查读取策略；后者不经 scope 选择入口，不能改共用摄取路径 | 部分（通用读取策略） | 上游提供文档读取前检查与列表扩展后移除接缝 |
| `internal/application/service/session_knowledge_qa.go` | S1b | 快问快答与搜索在模型解析及目标构建前调用 enterprise 共用读取检查；共用目标构建同时用于 Agent，不能在那里无条件拦截 | 部分（检索准入扩展点） | 上游提供按调用路径配置的检索前检查后移除接缝 |
| `internal/im/cmd_search.go` | S1b | 将类型化读取拒绝显示给用户；现有命令分发会把 error 统一改成执行异常 | 部分（公开业务错误显示） | 上游命令层支持类型化公开错误后移除适配 |
| `internal/container/container.go` | S1b | 经现有 DI Decorate 注入 KB 读取策略，原构造签名及 Agent 路径保持不变 | 部分（模块装配） | 上游提供企业模块装配扩展点后移除接缝 |
| `frontend/src/views/knowledge/KnowledgeBase.vue` | S1b | 最小接入 enterprise custody 组合式函数与状态组件，按受管状态控制原生标签页；无标签页策略扩展点 | 部分（标签页策略） | 上游支持标签页可见性策略后移除接缝 |
| `frontend/src/views/chat/components/AgentStreamDisplay.vue` | S1b | 引用与抽屉内导航交给 enterprise 发布读取逻辑，保留引用版本且禁止旧版回落；无引用解析扩展点 | 部分（引用解析器） | 上游支持注入引用解析器后移除接缝 |
| `frontend/src/api/wiki/index.ts` | S1b | 增加按 scope/release/logical_slug 读取发布页调用，供 enterprise 引用解析使用 | 否（发布协议） | S3 通用发布读取 API 接替时迁入 enterprise 并移除接缝 |

S1b 仅追加本表，不修改 G10 基线。受保护验收文件与既有断言保持不变；基线更新由 Claude 审查后执行。

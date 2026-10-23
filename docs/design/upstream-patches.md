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

| 文件 | 切片 | 原因 | 可否上游化 | 退出条件 |
|---|---|---|---|---|
| `internal/router/router.go` | S4c-1 | 通过既有 DI 和 API-key authorizer 挂载 enterprise source 只读服务；暂用已配置的隔离捕获 scope 核对 tenant/Space/RAW，原路由无企业扩展挂载点 | 部分（通用模块挂载） | 上游提供企业模块注册扩展点后移除路由接缝；S4c-2 引入受管 Space/source 绑定与产物必存后替换捕获范围映射 |
| `internal/router/router.go` | S4c-2a | `RouterParams` 增加 `EnterpriseCandidates`，把候选与发布服务交给既有 enterprise 挂载点；未配置时为 nil，候选路由返回 503 | 部分（通用模块挂载） | 上游提供企业模块注册扩展点后移除路由接缝 |
| `internal/container/container.go` | S4c-2a | 一行 `releasestore.Register(container)`，由项目包自行提供候选与发布服务（读取 `ENTERPRISE_SPACES` 与合同 schema），沿用 `managed.Register` 的装配方式 | 部分（模块装配） | 上游提供企业模块装配扩展点后移除接缝 |
| `internal/application/service/knowledge_process.go` | S4c-2c | 企业 RAW PDF 复用首次解析捕获；捕获全文保留原始换行与 HTML；精确扫描页信号以零 chunk 完成，跳过模型 | 部分（解析产物扩展点） | 上游提供按 scope 保存原始解析产物的扩展点后移除；S10 typed OCR 产物替代扫描消息判定 |
| `internal/application/service/knowledge.go` | S4c-2c | 构造函数接收企业 CaptureScope，经既有 DI 注入 RAW KB 捕获范围；原服务无范围策略扩展点 | 部分（服务策略注入） | 上游提供解析捕获策略注入后移除构造接缝 |
| `internal/router/router.go` | S4c-2c | 页接口先按 EnterpriseSpaces 核对 tenant/Space/RAW，再沿用 G3 映射，按精确 attempt 只读产物 | 部分（企业路由装配） | 上游提供企业模块注册与来源范围解析扩展点后移除路由接缝 |
| `internal/application/repository/knowledge.go` | S4c-2b-1 | 提交登记 released、封存固定；发布事务复用升序知识/资源锁的固定与释放原语，KB 查询及批量删除锁序沿用同一来源权威 | 部分（通用修订保留策略） | 上游提供修订保留策略与事务内来源锁扩展点后移除接缝 |
| `internal/application/repository/resource.go` | S4c-2b-1 | source_file 解绑在事务内按知识行锁检查已发布来源，保持其他关系的解除语义 | 部分（资源解绑策略） | 上游提供资源解除前的事务内策略扩展点后移除接缝 |
| `internal/application/service/knowledgebase.go` | S4c-2b-1 | KB 软删及异步清理的所有副作用前检查固定来源，异步拒绝在清理 defer 之前以 SkipRetry 终止 | 部分（删除准入策略） | 上游提供 KB 删除与任务清理前的统一准入扩展点后移除接缝 |
| `internal/types/interfaces/knowledge.go` | S4c-2b-1 | 知识仓库增加按 tenant/KB 查询固定来源的方法，供同步与异步删除共用 | 部分（修订保留查询） | 上游提供来源保留查询端口后移除接缝 |
| `internal/application/service/knowledgebase_task_cancel_test.go` | S4c-2b-1 | 既有任务清理夹具显式注入无固定来源的知识仓库，保留原取消任务与 payload 断言 | 否（测试装配） | 上游提供删除准入测试装配后恢复 |
| `internal/handler/knowledgebase.go` | S4c-2b-1 | KB 删除分支把来源固定拒绝映射为 409，沿用原有其他错误处理 | 部分（通用删除错误映射） | 上游提供删除准入冲突映射后移除接缝 |
| `internal/application/service/knowledgebase_delete_datasource_test.go` | S4c-2b-1 | 两个既有同步删除夹具注入知识仓库并委托原 KB 删除，保留数据源清理断言 | 否（测试装配） | 上游提供原子删除准入测试装配后恢复 |
| `internal/application/service/datasource_delete_sqlite_test.go` | S4c-2b-1 | SQLite 同步删除夹具注入委托原 KB 删除的知识仓库，保留真实数据源清理断言 | 否（测试装配） | 上游提供原子删除准入测试装配后恢复 |
| `internal/router/router.go` | S3d-1 | 复用企业来源读取装配会话只读路由，按保存的调用租户解析 Space 并对 RAW/wiki KB 分别执行读权限守卫 | 部分（企业路由装配） | 上游提供企业会话读取模块与双 KB 权限装配扩展点后移除接缝 |
| `frontend/src/stores/menu.ts` | S3d-3a | 侧栏增加"企业知识"入口（与知识库并列），文案走 `menu.enterpriseKnowledge`；侧栏菜单是固定数组，没有注册扩展点 | 部分（侧栏注册扩展点） | 上游提供侧栏菜单注册扩展点后改为在 enterprise 模块内注册并移除此行 |
| `frontend/src/components/menu.vue` | S3d-3a | 企业知识入口的图标（复用知识库图标，所在页面高亮）、激活态与顶部分组；图标与分组在组件内写死 | 部分（侧栏注册扩展点） | 同上：上游侧栏支持注册图标、激活态与分组后移除 |
| `internal/router/router.go` | RV4a | 在既有 enterprise 挂载处注入抽检服务，将 API Key / 会话读依赖传入项目包，并挂载要求 Wiki KB 编辑权限的会话结论路由；原路由无企业模块注册扩展点 | 部分（企业路由装配） | 上游提供企业模块与按 Space 的读写权限装配扩展点后移除此接缝 |
| `internal/application/service/wiki_ingest.go`、`internal/application/service/wiki_ingest_batch.go`、`internal/application/service/wiki_ingest_cite.go`、`internal/application/service/wiki_ingest_dedup.go` | S6a | 长文档候选概念只读前 32k、输出截断被当作解析失败；原生窗口、引用与身份稳定化在这些文件内，无可替代扩展点 | 是 | 上游对长文档分段处理候选概念并检查 finish_reason 后撤回 |
| `frontend/src/router/index.ts` | S3g | 注册企业知识关系图路由与 pinned Release 参数；路由表无企业页面注册扩展点，图数据及交互留在 enterprise 自有目录 | 部分（页面注册扩展点） | 上游支持自有页面路由注册后移除接缝 |
| `frontend/src/i18n/locales/zh-CN.ts`、`frontend/src/i18n/locales/en-US.ts`、`frontend/src/i18n/locales/ja-JP.ts`、`frontend/src/i18n/locales/ko-KR.ts`、`frontend/src/i18n/locales/ru-RU.ts` | S3g | 添加企业关系图五语言文案；沿用已登记的集中式语言包加载，无独立模块语言包扩展点 | 部分（语言包注册） | 上游提供模块语言包注册后迁入 enterprise 并移除接缝 |
| `frontend/src/router/index.ts` | RV4b | 注册企业抽检台会话页面路由；沿用固定路由表，列表、版本绑定、确认交互均放在 enterprise 自有模块 | 部分（页面注册扩展点） | 上游支持自有页面路由注册后移除接缝 |

| 文件 | 切片 | 原因 | 可否上游化 | 退出条件 |
|---|---|---|---|---|
| `internal/container/container.go` | Q1a | 既有 Concept Agent 装配注入企业来源解析器，企业 Space 跳过旧 830 投影 | 部分（模块装配） | 上游提供请求级来源策略装配扩展后移除接缝 |
| `internal/application/service/session.go` | Q1a | 构造器注入无状态企业来源解析器，供快问快答与纯检索共用 | 部分（检索策略注入） | 上游提供检索策略扩展点后迁回项目装配 |
| `internal/application/service/session_knowledge_qa.go` | Q1a | 授权后收窄固定材料范围，交付前过滤轮次并标注；兜底提示排除企业全库清单 | 部分（请求级检索策略） | 上游支持检索准入、结果过滤与提示元数据策略后移除接缝 |
| `internal/application/service/agent_service.go` | Q1a | 按轮装配固定来源与搜索结果包装器，企业目标隔离原生 Wiki/文档/图谱/数据工具及全库提示元数据 | 部分（按轮来源与工具策略） | 上游支持按轮来源解析、工具装饰与提示元数据策略后迁回项目包 |
| `internal/application/service/concept_agent_830_g2.go`（项目旧文件） | Q1a | 配置中的企业 Space 不交给旧 830 投影，其他受管来源保持原策略 | 否（项目历史路径） | 旧 830 路径迁出或退役后删除此分支 |
| `frontend/src/views/chat/components/docInfo.vue` | Q1a | 引用按来源与版本分组并显示本地化标签 | 部分（引用展示扩展） | 上游提供引用来源分组和标签扩展后移除接缝 |
| `frontend/src/components/ChatReferencesDrawer.vue` | Q1a | 抽屉显示来源标签并容纳完整文案 | 部分（引用展示扩展） | 上游提供引用 metadata 标签位后移除接缝 |
| `frontend/src/utils/referenceSources.ts` | Q1a | 引用视图保留 metadata，按来源与版本分组并防止标题歧义高亮 | 部分（引用身份扩展） | 上游支持来源身份分组与完整 metadata 投影后移除接缝 |
| `frontend/src/utils/citationMarkdown.ts` | Q1a | 引用类型保留 metadata，明确真实 chunk 身份优先于标题别名 | 部分（引用解析扩展） | 上游引用解析支持 metadata 与完整 chunk 身份后移除接缝 |
| `frontend/src/composables/useChatCitationPopover.ts` | Q1a | 从服务端引用为浮层逐次解析来源文案 | 部分（浮层策略扩展） | 上游支持逐引用 metadata 回调后移除接缝 |
| `frontend/src/composables/useCitationPopover.ts` | Q1a | 浮层生命周期携带来源状态，切换或 web 来源时清理 | 部分（浮层状态扩展） | 上游浮层生命周期支持来源状态后移除接缝 |
| `frontend/src/components/ChatCitationFloat.vue` | Q1a | 渲染引用来源独立标签位 | 部分（浮层展示扩展） | 上游提供 metadata 标签位后移除接缝 |
| `frontend/src/views/chat/components/AgentStreamDisplay.vue` | Q1a | 工具结果及历史恢复保留 metadata 与真实 chunk 身份，分组与浮层复用可信来源 | 部分（引用恢复扩展） | 上游恢复引用完整保留 metadata 并提供映射扩展后移除接缝 |
| `frontend/src/i18n/locales/zh-CN.ts` | Q1a | 中文区分原文检索与已发布知识 | 部分（语言包注册） | 上游提供等义来源文案或模块语言包注入后移除接缝 |
| `frontend/src/i18n/locales/en-US.ts` | Q1a | 英文同步两种来源文案 | 部分（语言包注册） | 同上 |
| `frontend/src/i18n/locales/ja-JP.ts` | Q1a | 日文同步两种来源文案 | 部分（语言包注册） | 同上 |
| `frontend/src/i18n/locales/ko-KR.ts` | Q1a | 韩文同步两种来源文案 | 部分（语言包注册） | 同上 |
| `frontend/src/i18n/locales/ru-RU.ts` | Q1a | 俄文同步两种来源文案 | 部分（语言包注册） | 同上 |
| `frontend/src/router/index.ts` | S3h-2 | 注册企业本版变化页与固定 Release 参数；沿用已登记的路由表接缝，比较和展示留在 enterprise 自有模块 | 部分（页面注册扩展点） | 上游支持自有页面路由注册后移除接缝 |
| `internal/application/service/agent_service.go` | Q1b | 按轮装配已发布知识查询工具与来源提示，保持其他工具白名单和原文范围 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `internal/container/container.go` | Q1b | 将只读知识服务连接到现有 Release SpaceReadView，避免旁路 Store | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `internal/modelcontext/tool_policy.go` | Q1b | 四个已发布知识工具经既有来源短句柄协议提供可引用结果 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/views/chat/components/AgentStreamDisplay.vue` | Q1b | 恢复四知识工具的历史来源元数据与引用操作，阻止 release 引用回落原生知识库 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/components/ChatReferencesDrawer.vue` | Q1b | 已发布字段经可信版本身份打开 CitationPanel，保留嵌入权限边界 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/composables/useChatCitationPopover.ts` | Q1b | 从可信工具引用预览已发布字段，禁止按合成 chunk 身份读取 chunk | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/composables/useCitationPopover.ts` | Q1b | 提供同步引用预览接缝，在访问 chunk 缓存前处理已发布来源与无效身份 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/utils/citationMarkdown.ts` | Q1b | 通过既有引用模块导出企业发布引用预览接缝 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/zh-CN.ts` | Q1b | 同步已发布知识工具与准确出处失败/授权边界文案 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/en-US.ts` | Q1b | 同步已发布知识工具与准确出处失败/授权边界文案 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/ja-JP.ts` | Q1b | 同步已发布知识工具与准确出处失败/授权边界文案 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/ko-KR.ts` | Q1b | 同步已发布知识工具与准确出处失败/授权边界文案 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/ru-RU.ts` | Q1b | 同步已发布知识工具与准确出处失败/授权边界文案 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/utils/referenceSources.ts` | Q1b | Release 引用按完整来源身份高亮，跨 Space 同名合成身份歧义不猜测 | 部分（来源身份扩展） | 上游支持注入精确来源解析器后移除接缝 |
| `frontend/src/router/index.ts` | S6d | 新增固定 Release 的延伸阅读页面路由，复用企业知识导航与出处 | 部分（企业页面自有模块） | 上游提供可注册的页面路由扩展点后迁出 |
| `internal/modelcontext/tool_policy.go` | S6e | 第五个已发布知识工具 knowledge_search_pages 经既有来源短句柄协议提供可引用结果 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/views/chat/components/AgentStreamDisplay.vue` | S6e | 延伸阅读页面工具的步骤名称映射 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/zh-CN.ts` | S6e | 模型整理来源标签与延伸阅读页面工具名 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/en-US.ts` | S6e | 模型整理来源标签与延伸阅读页面工具名 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/ja-JP.ts` | S6e | 模型整理来源标签与延伸阅读页面工具名 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/ko-KR.ts` | S6e | 模型整理来源标签与延伸阅读页面工具名 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `frontend/src/i18n/locales/ru-RU.ts` | S6e | 模型整理来源标签与延伸阅读页面工具名 | 部分（来源工具与引用扩展） | 上游提供可注入的按版本知识工具与引用解析器后移回扩展点 |
| `internal/application/service/wiki_ingest.go`、`internal/application/service/wiki_ingest_cite.go` | S6a-2 | 密集材料的候选列表超出输出上限，窗口只按输入装箱 | 是 | 上游按输出量自适应分段候选抽取后撤回 |
| `internal/application/service/session_knowledge_qa.go` | Q1b-2 | 快问快答读取已发布字段：只选 Wiki 库时跳过原文检索阶段，原文检索为空时交给已发布字段，二者都为空才兜底 | 部分（问答检索扩展） | 上游提供可注入的检索来源插件与兜底判定扩展点后移回 |
| `frontend/src/composables/useChatStreamHandler.ts` | S6d-2 | 对话错误消息与提示接入企业知识错误文案，原始错误保留日志；上游无错误展示转换扩展点 | 部分（错误展示扩展） | 上游提供错误文案转换回调后迁出接缝 |
| `frontend/src/views/chat/index.vue` | S6d-2 | 对话回调与连接错误提示接入同一企业知识映射，保留诊断及非目标错误；上游无统一错误展示扩展点 | 部分（错误展示扩展） | 上游提供可注入的错误展示转换后迁出接缝 |
| `frontend/src/composables/useChatStreamHandler.integration.test.ts` | S6d-2 | 原有完整流处理器测试的模块加载表补入真实企业错误模块，不改已有断言 | 是（测试依赖注册） | 上游测试加载器支持新增模块依赖后删除显式登记 |
| `internal/mcpserver/server.go` | Q1c | 注册自有已发布知识工具并提供额外工具注入；上游没有工具注入扩展点，所有扩展仍经原白名单、过滤与限流 | 是（通用工具注入） | 上游提供等义 MCP 工具注册扩展后删除本地接缝 |
| `internal/types/mcp_endpoint_tools.go` | Q1c | 中央工具目录增加 knowledge 组与七个只读工具，仅映射 retrieve 能力；上游目录无动态扩展接口 | 部分（工具目录扩展） | 上游提供可注入的工具目录及能力映射后迁回项目包 |
| `internal/container/container.go` | Q1c | 将 Space、Head、共用知识与引用校验服务、MCP 身份及 Viewer ACL 注入额外工具；沿用唯一生产 DI 装配点 | 部分（模块装配） | 上游提供企业模块装配扩展后删除接缝 |
| `frontend/src/api/mcp-endpoint.ts` | Q1c | 现有 MCP 分组联合类型追加 knowledge，与服务端目录一致；上游无模块化分组类型扩展点 | 部分（工具目录类型扩展） | 上游支持可扩展分组或包含同义分组后撤回 |
| `frontend/src/i18n/locales/zh-CN.ts` | Q1c | 增加已发布知识组与七个 MCP 工具名称、说明；沿用集中式语言包，无模块语言包扩展点 | 部分（语言包注册） | 上游提供模块语言包注入后迁入 enterprise 并删除接缝 |
| `frontend/src/i18n/locales/en-US.ts` | Q1c | 同步已发布知识组与七个 MCP 工具的英文名称、说明 | 部分（语言包注册） | 上游提供模块语言包注入后迁入 enterprise 并删除接缝 |
| `frontend/src/i18n/locales/ja-JP.ts` | Q1c | 同步已发布知识组与七个 MCP 工具的日文名称、说明 | 部分（语言包注册） | 上游提供模块语言包注入后迁入 enterprise 并删除接缝 |
| `frontend/src/i18n/locales/ko-KR.ts` | Q1c | 同步已发布知识组与七个 MCP 工具的韩文名称、说明 | 部分（语言包注册） | 上游提供模块语言包注入后迁入 enterprise 并删除接缝 |
| `frontend/src/i18n/locales/ru-RU.ts` | Q1c | 同步已发布知识组与七个 MCP 工具的俄文名称、说明 | 部分（语言包注册） | 上游提供模块语言包注入后迁入 enterprise 并删除接缝 |
| `internal/application/service/wiki_ingest.go`、`internal/application/service/wiki_ingest_batch.go`、`internal/application/repository/task_queue.go`、`internal/types/interfaces/task_queue.go` | S6a-3 | 原生 Wiki 共享请求按实际发送边界归类取消，未发送操作以认领与执行标记 CAS 原子释放，保留既有任务重试预算及知识处理位 | 是（通用取消与队列重试） | 上游提供共享发送状态及等义的安全释放接口后撤回 |
| `internal/application/service/wiki_ingest_cite.go` | S6a-4 | 引用输出明确截断时在原批次任务内有界拆分，重建句柄并合并证据；原生引用调度没有扩展点 | 是（通用输出溢出处理） | 上游引用批次支持同等有界拆分、证据合并及取消归类后撤回 |
| `internal/application/service/wiki_ingest.go`、`wiki_ingest_cite.go`、`wiki_ingest_outcome.go`、`internal/models/chat/chat.go`、`llm_debug_wrapper.go`、`langfuse_wrapper.go`、`concurrency_wrapper.go` | S6a-5 | 远程 Chat 及包装层传递目录输出能力，仅候选和引用提高输出预算；确定截断最多拆至深度 3，传输失败仅记录固定错误类别；现有入口无扩展点 | 是（通用能力传递、输出预算及脱敏诊断） | 上游提供同等模型能力转发、按用途预算、有界拆分及安全传输分类后撤回 |
| `internal/application/service/session_knowledge_qa.go` | Q2a | 企业快问快答自动原文复用原生选库授权，模型保留自动扩展前选择；双次过滤后无命中使用固定兜底，原生入口无企业回合扩展点 | 部分（选库扩展与固定兜底） | 上游支持授权后的检索目标扩展、独立模型选择及来源感知兜底后撤回 |
| `internal/application/service/chat_pipeline/into_chat_message.go`、`internal/application/service/chat_pipeline/references.go` | Q2a | 初次与最终模型上下文渲染共用来源层级文字，企业回合保持已发布字段优先并追加专属回答规则；原生渲染没有来源层级扩展接口 | 是（来源上下文渲染扩展） | 上游提供可注入的来源层级、排序与系统规则后迁回企业包并撤回接缝 |
| `internal/agent/finalize.go`、`internal/modelcontext/sources.go`、`internal/modelcontext/model_output.go` | Q2b | 请求内引用注册保留工具显式来源层级与固定版本，统一完成出口按最终回答实际引用顺序记录来源；原生链路没有引用记录扩展点 | 是（来源引用记录） | 上游完成事件记录同等实际引用及工具来源层级和固定版本后撤回 |
| `frontend/src/views/knowledge/KnowledgeBase.vue`、`frontend/src/router/index.ts` | S7b | 回退：删除 830 时期 Schema Wiki 标签、内容区与 6 条 `schema-wiki` 路由，知识库页默认打开"文档"；补丁只减少（S1b、S3g 等登记的接入不变） | 不适用（回退） | 随所在登记行一并移除 |
| `internal/router/router.go`、`internal/container/container.go`、`frontend/src/views/knowledge/KnowledgeBase.vue` | S7d-2a | 回退：删除 G3 产品导入桥的路由参数、注册与 Provide；知识库页删除产品导入能力查询、状态面板与上传分支，上传恢复为上游原样直接打开原生对话框 | 不适用（回退） | 随所在登记行一并移除 |
| `internal/router/router.go`、`internal/container/container.go` | S7d-2b | 回退：删除 G3 平台路由参数与注册、G3 平台处理器的 Provide，以及发布服务的系统自动化策略装配 | 不适用（回退） | 随所在登记行一并移除 |
| `internal/application/service/knowledge_process.go`、`internal/application/repository/knowledge.go`、`internal/types/task.go`、`internal/types/interfaces/knowledge.go` | S7d-2c-2a | 回退：删除 G3 模型派发日志的 7 处挂钩与嵌入调用标签、DocReader 恢复的选取与读取、绑定重解析（`bound` 参数、任务闸门、`RecoveryKey`、`DocReaderReuse`、仓库的分配/推进与元数据合并、可选接口）；`ReparseKnowledge` 回到单一实现 | 不适用（回退） | 随所在登记行一并移除 |
| `internal/config/config.go`、`internal/application/service/knowledge_post_process.go`、`internal/application/service/wiki_ingest_batch.go`、`internal/router/router.go`、`internal/container/recover_pending_wiki_tasks.go`、`internal/container/reset_pending_tasks_test.go` | S7d-2c-2b | 回退：删除 G3 范围配置与产品导入配置字段及其校验调用、6 处原生候选写入策略判断、企业来源页的 G3 回退；两个 container 文件回到上游原样 | 不适用（回退） | 随所在登记行一并移除 |

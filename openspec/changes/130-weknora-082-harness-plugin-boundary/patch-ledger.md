# 保留平台补丁与替代条件

本清单覆盖升级触及的核心接缝，不把旧产品全仓差异重新包装成此次新增功能。唯一集成 Owner=root；写域见 current-slice-paths.json。全部沿现有 REST、Source lifecycle、StageCall 与唯一 Release 权威，无新数据库或队列。

| 接缝/路径 | 必要性与 Owner | 回归证据 | 上游替代/退出条件 |
|---|---|---|---|
| `models/api/{model_dispatch,endpoint,retry}.go`、四 chat protocol client、`models/runtime/connection.go` | root/model_fallback lane；模型重构后在共同实际 HTTP 边界继承发送前记账、结果、唯一重试 Owner；关闭受治理调用的隐式重定向 | api dispatch/no-retry/journal/redirect，chat fallback，embedding dispatch；model-final 全包 PASS | 上游实际 transport 能原子 reserve/mark/record 并暴露每次发送/重试控制后迁入原生能力；不得恢复已删旧 chat/embedding 模块 |
| `service/knowledge_{create,process,post_process,delete,clone_move}.go`、`repository/knowledge.go` | root；保留 SourceRevision/parse attempt/SHA 及 pinned source mutation 门禁，同时采用原生 ACL/完成处理 | 固定来源/G3 解析/不可变来源/删除与重解析、图片入队失败、revision commit | 原生具有同等不可变来源及 revision fence 时用等价接口替代；跨语言来源合同不能随实现替换而丢失 |
| `repository/task_queue.go` | root；在原生 pending op 与 finalizing 事务中校验 revision，避免旧任务提交到新来源 | task_queue_revision_upgrade_test：匹配/陈旧/不同 SHA/非法绑定 | 原生提供相同原子 revision 前置条件时删除本地补丁；不增加平行队列 |
| `service/wiki_ingest{,_batch}.go` | root；原生 ingest/Audit 与项目 revision、page outcome、StageCall 成本及失败分类共存 | wiki7 121 PASS/1 SKIP；实际发送/失败分类及旧引用合同 | 原生操作提供相同版本化输入、调用预算和可恢复输出后删除对应适配；领域准入仍在 Harness |
| `service/agent_service.go`、`concept_agent_830_g2.go`、内部 scope interface | root；对每个 server-resolved tenant/KB 检查持久 custody，RAW-only 也不能绕过 Release；普通 KB 使用原生工具 | concept_agent_upgrade_test、既有 ConceptAgent/工具面回归 | 原生支持原子 pinned Release 和受管源排除/当前 ACL 后迁移；不得以插件在线状态作为受保护数据判据 |
| `router/router.go`、`container/container.go` | root；把既有产品 ingestion、发现、来源、Release 能力挂到新原生依赖图，复用 native System/Audit/Memory 初始化 | router/handler/container/G3 platform focused PASS | 上游稳定注册接口覆盖挂载后集中迁移；业务语义不迁入 router/container |
| `frontend/**` 有限业务挂载点 | frontend_upgrade；上传批次 bridge 保留单次整批提交、未知结果不回落，同时采用上游 upload queue；保留 SchemaWiki/来源/任务 | 263 tests、修复后14项/typecheck/build PASS；80路径独审0 BLOCKER | 原生提供等价集中入口后删本地挂载；不做微前端/远程脚本加载 |
| `database/*migration*`、adoption target、077 SQL | migration_audit；官方110/enterprise5安全前进、pg_search真实版本保证；旧log冻结而不重新写入或物理删除 | migration/adoption131及模式转换测试PASS；13路径独审0 BLOCKER | 历史账本与持久化兼容按公开迁移合同保留；不是可以任意删除的内部 shim |
| `Dockerfile.app`、BA0 manifests、构建/复用脚本 | plan_review 写者；固定 AnyDoc/BrowserSkill 与依赖输入；唯一 lookup-before-build 与精确 image reuse | 156 fixture PASS；18路径独审0 BLOCKER；真实 image NOT RUN | 上游构建入口具备同等输入闭包、固定依赖及制品选择时替代；不保留第二构建权威 |

## 删除与冻结

- `internal/models/chat/remote_api.go`、`internal/models/embedding/openai.go`：SUPERSEDE；使用上游新公开 API/runtime，旧文件不恢复。
- `skills/preloaded/**`：SUPERSEDE；固定上游已转为租户 sandbox skill 来源，本产品没有额外预置 skill 合同。
- 旧 Wiki log 服务/前端入口：SUPERSEDE；新写入走上游 Audit。历史表/正文/identity：FREEZE；077 soft-delete 隔离普通页面读取。数据库恢复依赖一致备份。
- G3/G3.5 历史来源、解析制品、Release 和质量结论：KEEP。升级不能抹除 QUALITY_PARTIAL、Q0 或尚未验证项。

测试替身与 constructor 更新只接上真实新依赖（Tenant、KB write access、SystemHandler、FindPagesByNormalizedTitles），没有放宽生产权限或降低预期断言。机械 fixture 适配属于原合同回归，不伪造行为 RED。

## 核心独审后的边界

前端80/构建18/迁移13路径已独立复核0 BLOCKER。核心生产模型、RAW-only/ACL及router/container18路径静态复核无新增问题；307/308及第四协议chat/stream覆盖已补38项PASS。来源mutation与pin原子性、旧worker跨attempt清理两BLOCKER已通过原子写入/精确UUID清理闭合，尽管基线已存在，本次UPG-04/05/06需闭合。修复Owner迁移到source_concurrency_exclusive_lane，43路径core-review-identity已最终复核通过。

普通KB的enrichment finalizer缺持久slot去重，ack前崩溃仍可能重复减计数。当前G3 isolation关闭summary/qgen/graph/wiki并走direct revision commit，独审据真实配置将其列为BACKLOG；不能把当前G3通过外推为普通KB所有at-least-once行为已通过。不以新增slot表/ledger扩大本次升级。

DocReader生产输入随固定上游变化，因此按组件BUILD_AFFECTED。docker/Dockerfile.docreader两处FROM固定同一个官方Python多架构index；该单文件SHA独审0 BLOCKER，完整运行/解析检查待新镜像，不借用旧容器作目标源码验收。

最终复审另保留两项BACKLOG：普通KB graph/enrichment的knowledge-wide清理及UpdateChunk仍属旧跨代模型；当前G3关闭这些能力。精确chunk清理先删行再best-effort删索引，索引故障可留下占用TopK的孤儿向量；后续优先复用既有pending op或先幂等删索引、成功后删行并传播重试。当前托管RAW不进入普通工具检索，此项不阻断当前切片，不宣称通用索引清理已具持久恢复。

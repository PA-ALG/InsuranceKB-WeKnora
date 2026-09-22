# Task3bk 来源自动恢复：只读设计复核

基于现有实现与 Task3bk 计划；不是未冻结代码审查。无业务调用、无仓库修改。结论：复用原生知识服务可以，但“查 failed 后直接调用 ReparseKnowledge”的薄 HTTP 接线不足以满足并发、未知提交和崩溃恢复。

## 必须闭合的三个约束

1. **原子分配，不是前置检查**：repository/knowledge.go:74 AllocateParseAttempt 只锁行并加一，不核 expected/state；其 knowledge_revision_test.go:207 测试明确并发请求分配 4 和 5。必须把 tenant/RAW/knowledge、原 upload run+ordinal 元数据、expected attempt、failed 状态和幂等恢复标记，与新代次分配在同一行事务中核验/提交。
2. **入队错误不能伪装成功**：knowledge_process.go:2252–2267 的文件重解析 marshal/enqueue 错误返回 existing,nil，留下 pending。新接线不能将其解释为 queued；已知提交失败须保留结构化失败并按目标代次 CAS 终结。不要因此重解析成功兄弟。
3. **失败状态不能挡住迟到任务**：ProcessDocument:2898 对 failed 只告警继续。把 unknown enqueue 标成 failed 后，晚到消息仍可能启动；必须由现有 worker 在准备执行恢复任务时核目标代次及恢复标记是否仍可执行。已有 revision generation fence 保留。

## 最小实现形状

- 入口仍在原 G3 platform scope 下，例如上传绑定资源的恢复操作；server 从 run+ordinal 的 product_ingestion_upload 元数据找知识 ID，不接受客户端任意知识 ID。沿用 G3PlatformMachineAccessService.authorize 的 exact principal/key/双 KB scope 与实时 ACL；恢复是写操作，route 应保留原生重解析的 editor/RAW 写权限语义，不能仅复制 Upload GET 的 viewer/read guards。
- Harness checkpoint 根据真正复用的阶段验证；只复用 uploads 不要求 source 完成。恢复 child 使用**原始上传 run+ordinal**，不要把 child run 当原 upload key。仅 failed 材料生成恢复请求；completed 材料按现有校验复用；pending/processing 等待既有任务，不申请新 attempt。
- 在原 knowledgeService 增加明确 typed 的 bound-reparse 输入或窄方法，内部共享既有文件检查、配置、DocReaderReuse、cleanup、payload 和 enqueue 实现。不要复制整个 ReparseKnowledge，也不要在 handler/Harness 手工分配 attempt 后再调用原 ReparseKnowledge 造成双分配。
- 新增 repository 的窄事务方法：读取并锁定 knowledge，校验完整绑定和 expected/state，计算稳定 recovery key（作用域+原上传绑定+knowledge+expected attempt；同一失败代次只有一个恢复）；在既有 metadata 保存版本化 receipt（expected、allocated attempt、key、dispatch phase、时间和可选 queue task ID），原子发布新 attempt/pending。无新表、无新服务。命中同 key 返回原 receipt，不重开 span、不 cleanup、不 enqueue；不匹配的更高代次返回 stale/conflict，不能自行认作本请求已成功。
- 现有 UpdateKnowledge 是全行 Save（repository/knowledge.go:940）。分配后的旧 existing 指针含旧 metadata，可能覆盖 receipt；bound 分支必须使用事务返回对象或以列更新/CAS保存，阶段结果也按 target attempt+recovery key fence，避免迟到错误覆写后来完成状态。
- span 的 OpenAttempt 不应在幂等判定前触发；仅首次真正分配执行，重复调用零 span 副作用。保留旧失败审计和新结果独立代次。

## Allocate→enqueue 崩溃窗口与未知结果

PostgreSQL attempt 分配与 Redis enqueue 没有原子事务，不能承诺 exactly-once。这次最小合同应是“同一失败代次至多分配一个恢复 attempt，未知提交不盲目重发，任务最终有明确状态”。

- receipt 在分配事务即写 allocated；在 enqueue 前按 target attempt CAS 写 dispatching；成功 ack 写 enqueued+确定任务 ID。不能把 allocated 或 dispatching 当已提交成功。
- 进程在分配之后、dispatching之前死亡：持久状态证实尚未进入 enqueue；恢复核对后返回明确 RECOVERY_DISPATCH_INTERRUPTED/失败，不再次调用 ReparseKnowledge。可以留下一个消费过但失败的目标 attempt，这是正确审计，不是理由再分配。
- dispatching 后结果未知：先读同 receipt、当前 attempt/status、已有 processing receipt/span；若已有可验证进展，继续等待该 attempt。若需查队列，复用现有 Asynq Inspector 加窄的精确 task ID/knowledge/parse_attempt 查询，并给本恢复任务使用确定 TaskID；不能把整个知识的 best-effort HasQueuedTasksForKnowledge(false) 当未入队证明。
- 队列命中或解析已开始，不重发；已 completed 复用；查询错误/不支持为 unknown，不等于 absent。若未知到截止时间，产品任务明确失败并说明提交状态未知；不以新 attempt 自动掩盖。需要将尚未开始的目标恢复任务同步终结时，receipt 的 terminal 状态及 worker 对 receipt 的启动检查一起构成 fence，防迟到队列任务把 failed 复活。已经开始的任务不能凭事后 absence 判断重置。
- 原生 HousekeepingService 已处理 pending 孤儿、结合 span 与队列保护；默认至少70分钟才回收，适合兜底，不能当本次交互恢复的短时机制，也不需要再建扫描服务。原产品 source deadline 负责有界终态。若要求无人工介入地保证跨PG/Redis崩溃之后最终一定重新入队，则要额外的持久调度协议/既有outbox适配，超出上述“明确失败、无盲重试”的最小方案，不能暗中承诺。
- 当前 TaskInspector 接口是按knowledge best-effort扫描；未提供精确代次查询。Asynq内部已有GetTaskInfo能力可在原adapter补窄接口。Lite noop不具备相同证明力，明确unknown/unsupported即可，不假称队列为空。

## 必要最小写域

现有 G3 handler/router/composition 与 machine access；knowledgeService的bound reparse/shared enqueue；**repository/knowledge.go原子条件分配与receipt CAS**（Task3bk计划当前写域须补列此处）；窄types/interface。若采用精确队列核对，再加原 TaskInspector adapter/interface。Harness现有 PlatformClient、checkpoint/source stage、artifact及相应测试。不要修改模型策略、发布权威或增加数据库表。

## 最小 RED 验证

1. 2 completed+1 failed：仅失败材料一次分配/cleanup/enqueue；成功兄弟的attempt、chunks、embedding、receipt不变。
2. 同 expected 的并发重复请求只得到一个target attempt；原上传绑定错、tenant/RAW错、文件替换、非failed或更高无receipt代次均拒绝且零副作用。
3. 分配前崩溃、分配后dispatch前、enqueue接受但HTTP响应丢失、ack后：逐一验证lookup/replay，无第二次分配/重复enqueue。
4. marshal/明确enqueue失败不是success；pending有明确失败原因，旧失败审计仍可读。
5. unknown到deadline终态后迟到任务不再启动；旧请求报错不能覆写target已completed或后来新attempt。检查现有failed可重试分支被恢复receipt正确约束。
6. worker重启/轮询重复、source pending→processing→completed等待；成功校验/字段缓存继续复用，不触发历史任务重放。
7. metadata receipt不会被旧对象Save覆盖，重复请求不会新建span。队列查询错误/unsupported不能变成absent后重发。

以上为设计约束和可执行反例，不代表实现或真实平台验收通过。

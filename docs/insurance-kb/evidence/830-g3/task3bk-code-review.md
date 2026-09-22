# Task3bk 已实现切片独立只读复核

冻结 manifest SHA256：abf27c0ea98a5e62cb57a67104c8c1358d19e28ef773f469ec74b51cff3d27b1；base964f968001f37f2b835b01960dbb4b81ef4361bf。22个文件逐个核hash，无漂移。工作树：/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-performance。仅读代码、测试及现有回执，执行了两个无网络/无数据库业务的微型行为核验；无仓库改动、业务请求、模型、构建、部署。结论 BLOCKER 1 / BACKLOG 1。

## BLOCKER

**B1 成功心跳日志未接到默认运行日志级别；测试改变级别掩盖了部署缺口。**

位置：harness/src/insurance_harness/service_shell/worker.py:164–167；service_shell/cli.py:196–213；harness/tests/test_service_shell_worker_039.py:735附近。

心跳wrapper在成功时调用logging.INFO，异常才WARNING。现有wiki-worker启动仅构造uvicorn.Config，源码没有为insurance_harness/root logger配置级别/handler。使用相同本机依赖，直接构造uvicorn.Config(FastAPI())后只读检查logging.getLogger('insurance_harness.service_shell.worker')得到 effective_level=WARNING、isEnabledFor(INFO)=False、isEnabledFor(WARNING)=True。故真实正常启动会丢弃成功续期记录，无法得到本修复承诺的最后成功心跳及完整时序；只能看到失败warning。新增测试caplog.at_level(INFO)人为覆盖了这个运行差异。

最小修复：在既有CLI日志配置中明确接通该命名诊断logger的级别/handler（不要只开Uvicorn level，不必将其他库全部打开INFO），保持JSON字段白名单；增加默认worker启动配置下INFO可被目标handler接收的测试，不能依赖caplog将生产logger临时调级。无须修改租约、重试或增加日志服务。

## BACKLOG

**N1 metadata-only通用默认读取在恢复run上会与checkpoint的小制品读取发生identity-map冲突。**

位置：harness/src/insurance_harness/product_ingestion/checkpoint_artifacts.py:53–67；checkpoint_store.py:54–74。

触发：调用新list_effective_artifact_references(scope,run_id)省略artifact_kind，且run已有checkpoint_plan/receipt。metadata查询先将本地ProductArtifact（含plan/receipt）加载到同一个Session，payload设置defer(...,raiseload=True)；紧接checkpoint_receipt→_small_artifact→session.get复用已有ORM对象，读取row.payload即InvalidRequestError，不会自动重新加载。现有source loader明确指定source_snapshot，所以当前已实现业务路径不触发，列BACKLOG而非扩大阻断范围。

已用SQLAlchemy SQLite内存最小样例确认：先select(...defer(payload,raiseload=True))，随后session.get同ID返回同对象，访问payload报InvalidRequestError。未新建平台数据库。修复可先完成小checkpoint授权，再查询metadata，或让_small_artifact显式加载其小payload；继续保持大source payload不被查询。补已有恢复run、artifact_kind=None的测试。不要简单移除raiseload使大payload偷偷懒加载。

## REJECTED

- “本切片关闭来源安全检查”：未见。Go operation proof只在完整成功load后登记，key/identity/binding/owned proof匹配才复用；新verifyBatch operation重新建map。每条引用之前仍经过knowledge/revision/resource实时校验；新请求仍重开firstParse，已有测试覆盖下一operation backing file失效与binding变化拒绝。没有将缓存命中等同于当前权限通过。
- “Python缓存大几何或跨run串用”：未见。缓存限定每scope一条，键包含scope/run/完整ArtifactReference序列/验签公钥实际字节；缓存值是冻结SourceBlock tuple。每次命中仍读当前受授权引用；首次加载前后比较refs。SourceBlock缓存不是新的来源权威，首次完整hash/签名校验仍在原读取链；大geometry不保留。
- “regex改变canonical文本/摘要”：未见。BODY_CONTROLS与STRUCTURED_CONTROLS精确对应旧ASCII控制字符集合；原NFC条件保留，正文不规范化。ASCII枚举测试及既有canonical/routing测试回执支持语义保持。
- “删batch构造放宽字段验证”：未见。单窗原来通过构造临时FieldTaskBatch证明数量/重复hash；新边界直接检查1..10及唯一task_sha256，原后续FieldTaskV1.model_validate和来源依赖检查仍保留。移除的是随后丢弃的batch序列化/hash。
- “日志泄露材料/凭据”：未见。heartbeat/reclaim仅job/space/generation/时间/异常类型；transport没有URL、header、body、异常message。reclaim日志在事务内发生且代码明确其是attempted transition，DB终态仍权威；不应作为commit成功凭证。
- “清旧错误会删除原失败审计”：未见。改动只清当前Knowledge.ErrorMessage（分配后的旧对象及成功索引状态），未删除processing span/调用/旧任务制品。
- “本切片已经修复自动reparse或并发租约根因”：REJECTED。它仅优化重复计算并补诊断；自动恢复和代表性大输入4并发完整闭环不属于本次已实现范围，不能从测试GREEN推导。
- “源码GREEN等于部署/G3通过”：REJECTED。已读取71 passed/2 deselected组合回归、43 extraction passed、Go service包PASS及git diff --check无问题；其余测试数来自Root回执。没有构建/部署/真实模型或业务验收。本审查仅确认上述冻结切片与指出两项，不改先前G3未完成结论。

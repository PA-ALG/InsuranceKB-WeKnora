# Task3bk 等待期 fanout 复用切片：独立只读复核

基线3fb14a1b11088d5df41004aecb4fe7a377c40c4c；冻结manifest SHA256=442b60b52ded1f4a9156e4463758bc9ca74f4e77084ee1793f004529d2ff3ec2。5个文件逐个核hash，无漂移。仅源码、测试、现有回执审查，未改仓库、未跑大套件、未构建/部署/业务调用。

## BLOCKER

未发现本切片阻断项。

production compose_product_worker明确注入_scoped_window_plan_identity，按当前完整scope和run调用list_effective_artifact_references(field_plan)，要求唯一product制品。该接口沿用已审核的当前run/继承checkpoint授权，只返回完整冻结引用，不拉33.8MB正文。缓存键是(scope,run,refs)，缓存值只有job ID tuple；每scope最多保留一套，未缓存字段/来源正文。

_window_jobs仅在完整计划读取、窗口/字段唯一性验证、全部enqueue_window幂等登记成功、前后引用一致后发布缓存。半途中断或引用变化均不缓存。重启无内存缓存，复走既有持久登记；缓存身份变化也重新读取/核对。并发调用最多重复进行原有幂等登记，不会发布半套job IDs；Python单个字典值替换发布完整(key,job_ids)对，scope/run不同不能错配命中。现有数据库登记/任务代次隔离没有被替换。

advance即使命中仍逐job调用当前JobStore状态，未将缓存命中当任务成功；只有全部SUCCEEDED/BLOCKED/DEAD_LETTER才进入原extract汇总屏障。缺失job仍抛错，不被当完成。未配置identity reader的旧调用方仍保持完整读取路径，不产生无授权缓存。extract汇总的read_window_plan已移至asyncio.to_thread，后续预期字段集与终态结果完整性比较保留。

## BACKLOG

本次新增差异没有需追加的BACKLOG。既有大输入4并发租约根因、自动reparse闭环和其他同步计算成本继续属于原Task3bk未完成范围，本切片不宣称已处理。

## REJECTED

- 缓存导致跨scope/run、跨plan复用：与完整键、每次授权metadata读取及前后refs比较不符。
- 重启丢缓存便丢任务/重复外发：缓存只优化已完成fanout的本地读取；durable window/job和既有幂等ID继续权威，重启正常重核，不直接调用provider。
- 部分登记失败被缓存吞掉：tuple构造在任一enqueue异常时退出，赋值位于完整成功之后；旧实现RED和新反例覆盖未知入队响应、引用中途改变。
- 测试通过即真实并发或部署通过：不成立。已读取RED3失败、修后25 progression/runtime/composition passed（30.64s）、14 pipeline/composition passed（37.13s）；git diff --check无问题。没有重跑大套件、真实输入并发、构建、部署、模型或平台业务。本结论仅适用于这5个冻结文件。

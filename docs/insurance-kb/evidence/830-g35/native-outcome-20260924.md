# G3.5 P0-2 原生生成失败治理（软件切片，未部署）

沿2026-09-24用户批准的九项计划，root唯一写者。目标是关闭原生引用/正文失败却显示健康完成及多层盲重试；不并建模型执行器，不扩展source parse状态机，不声称原生具备Harness的raw断点恢复。

## 已定位与修复

- 原包装器对EOF发送三次；Pass0失败又进legacy extractor；文档失败再排回整文队列。现在调用包装层及SDK至多单次发送，外部缺少完整响应为OUTCOME_UNKNOWN，响应格式为FAILED，明确未发送为NOT_RUN；旧字符串重试分类器退役。
- 引用批吞掉调用/JSON错误，Map仍用短Description/Details写页。现在聚合保留成功兄弟、失败批位置和类型；未知chunk handle或无依据新slug同样失败；任一必需引用批不完整时零SlugUpdate。成功批在原trace记录真实chunkID，日志不是raw恢复权威。
- 页面生成失败被err=nil当no_change。现在向聚合返回失败；锁取得与页面处理失败分别判断；已写成功页保持，失败父Wiki span不会EndSpan为done。source解析成功继续有效，Wiki终态后沿原revision binding释放enrichment slot。
- 原dead-letter写入与删除分离，且不出现在Wiki主界面。现在原pending repo提供可选窄guard：发送前原行execution_id CAS、成功claim+marker CAS删除、失败同事务锁行→写归档→删pending。WikiStats返回tenant/KB范围的failed_operations，前端展示生成失败记录，查询失败不返回虚假0。
- 按完整op/knowledge/revision分组，合法显式版本按最高ParseAttempt选择，迟到旧通知不能覆盖新代；同代不同身份、非法身份与已开始组独立隔离，retract保留顶层栅栏。整个选中cohort先持久标记，任何Begin失败都在模型前退出；最终发送门核对已有同版本dead-letter，恢复只归档，不执行Map/Reduce。单文档scrub保留marked/claimed行。后台恢复器只重建trigger，不另造op。

## 验证证据

真实RED：EOF包装calls=3；引用EOF仍返回2个updates；生成EOF err=nil；最新待办掩盖已发送兄弟；未知c999被吞；全NOT_RUN误记FAILED；WikiStats没有失败数；旧队列无发送前guard。环境/fixture错误未充当RED。

定向软件GREEN：core 8.203s；service/repository 10.982s/10.953s；Wiki回归5.054s。PostgreSQL独立临时schema实测归档插入失败不删pending、删除失败回滚归档、旧claim不能完成新claim、scope隔离和JSON未知字段保持，2个测试同时在SQLite/PG通过（2.693s）。临时schema及首轮本机转发已清理。Vue模板编译PASS。

最终回归 `/private/tmp/g35-p0-2-final.jsonl`：137通过/2跳过（SQLite并发分支及无独立环境的旧Release并发测试），本次PostgreSQL事务/竞争/同版本查询/scrub均实测通过，临时schema和转发已清理。代次选择重设计后的服务回归 `/private/tmp/g35-p0-2-service-final.jsonl`：90通过/1同上旧Release环境跳过，3.489s。独立设计及实现复核均0 BLOCKER，20源文件SHA匹配 `/private/tmp/g35-live-20260924/native-outcome-review/identity.json`。

## 精确边界与剩余项

execution_id保护选中queue operation，现有dead-letter继续保护失败/未知exact revision的迟到通知；成功Complete删除后任意未来重复提交不承诺exactly-once。它不保存模型raw/单元checkpoint；Begin提交但未真正发送的崩溃也保守按unknown隔离。已删除claim不被当作成功归档；commit回执不明时source slot可能保留待清理，不用再次发送模型消除此不确定性。归档失败保留marker，后续任务只重试结算。

本轮真实模型、产品制品构建、部署、Candidate/审核/发布和业务数据写入均0；PostgreSQL只创建并清理测试schema。健康原生对照仍须正常网页在同workspace新空隔离KB上传同PDF；旧11页降级样本不能当健康基线。P0-2业务验收仍NOT RUN，G3.5未完成。

追加真实RED与收口：Complete/Archive CAS=false被吞、发布读取/写入失败不返回、repo失败页残留成功链接、Begin后才enqueue导致模型calls=2、旧marker误伤新代、scrub删除在途标记、late-R1覆盖R2、同代冲突发送以及未知最高代回退。均先反例后实现，日志保存在私密g35工作目录。页失败统一由wikiPageFailures负责贡献文档归属/摘要/日志/trace输入；发布返回逐slug结果，成功兄弟保持。输入选择回到独立设计后由selectWikiInputCohorts单一模块负责，不增加分布式执行器。

BACKLOG（不阻断当前软件合同）：失败徽标尚无直接文档定位；failed_operations为归档记录数；每文档trace的failed_slug_writes仍为整批计数；legacy nil不覆盖显式代次已有代码约束，独立小用例可后补。新原生健康基线/真实覆盖度/正式发布仍NOT RUN。

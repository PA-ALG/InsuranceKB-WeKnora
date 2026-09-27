# G3.5 R6：多窗口依赖合并与一次局部重审

用户G3.5全项授权持续；当前优先跑通完整流程，质量/覆盖语义调优后置。
root唯一写者。基线为已部署12fae12319149e3bd4880a27919bc3b1dfac252e；
执行树830-g35-multiwindow，原knowledge-admission的coverage WIP不在本次交付中。

## 软件验证矩阵

| 要求 | 实现 | 验证 | 状态 |
|---|---|---|---|
| R6-AGG-1 | domain保留明确映射，aggregate服务端闭包，native_pipeline消费 | local ref命名空间、共享成员、内容冲突、缺窗/来源/owner/内容篡改 | PASS |
| R6-REVIEW-1 | v10复用原审核策略；review_compilation封装一次初审、局部裁剪与二审 | 局部失败、全局失败、无survivor、无第三次、来源过滤 | PASS |
| R6-RECOVERY-1 | StageCall沿用；二审显式refined operation；初审initial审计key、最终product唯一 | 真实JobStore/worker，初审后与二审后crash不重发、preparation失败后checkpoint重用发布 | PASS（最终冻结worker 6项/202.95秒） |
| 历史合同 | v1/v6/v9首审输入/提示词及operation不变 | 旧native、review、replay、checkpoint、持久pipeline | PASS（71项/138.54秒） |
| 当前现场协议 | v4普通页经原准入覆盖，typed仍单窗围栏 | v4 worker重启/发布1项43.43秒 | PASS（fixture） |
| 容器交付 | 仅Harness API/worker，配置及APP/UI不变 | 构建1次，可回滚切换05:41:07Z、Head/ledger不变 | PASS |
| 真实业务 | 原账号/KB/材料正常入口 | 正常任务至epoch23、页面终态及verify PASS；新自由知识0 | PASS（主流程），新增知识BLOCKED |

Revision1 manifest 9130662d475da030444d018dc0ac3d1cb6765c807bdd3859894cd4878e252e1a，
18/18哈希匹配，独审发现两个可复现阻断：audit-only裁剪不改变正文hash导致operation冲突；
未过滤隔离窗口原文导致v10超预算。修复均先RED；audit-only持久两种crash 2PASS/57.03秒，
290k无关原文过滤反例通过，保留引用仍完整验证。调用统计同时支持v10 initial/refined，
6新增RED后与pruning共35PASS。

Revision2 manifest 60572d1cb0a7d7f1f0370a4b5e08f9b20d7d3cbb7a71351bcad09643ff8826fa，
21文件冻结，独立复审0 BLOCKER。机械类型修正addendum d63fc91a…同值验证，独审结论不变。
最终commit a587823fe38b6328297cf5cd42c85f36a84fabc4；final manifest 703e07ff…；
定向103PASS/57.55秒、metrics29PASS/4.89秒、完整worker6PASS/202.95秒；
15源码mypy/20 Python文件ruff PASS。仅Harness构建1次成功，image 4f8529ce…，
deployment manifest 9f766eab…独审0 BLOCKER；容器切换05:41:07Z PASS，API/worker精确镜像及健康已核验。

未扩大：多材料、多实体、typed relation聚合保持围栏；不新增平台/队列/发布权威。
原文及模型生成来源门槛、评分、provider策略和上下文预算不变。
独审BACKLOG：aggregate canonical response/raw hash和member_type可进一步交叉验证；
当前由原projector和artifact custody保持，不作为本次纵切阻断。

现场只读预检：Active仍epoch22/release-89ceefc7-6c91-4562-976f-cdbcb77d8215，
active jobs/outbox均0；此为切换前只读预检；切换后同说明书新正常任务已提交，业务结果待记。
完整G3.5质量验收仍后置；不得把fixture或发送完整原文等同真实质量/全覆盖PASS。

## 正常业务窗口结果

2026-09-26 05:42:14.810815Z—05:45:52.920387Z，正常UI单次上传原说明书，
run310651e0-f2d8-410d-84df-70abe46a4ac5，218.11秒，终态partial_success。
当时API显示合计7调用（3 source+4 Harness）/0复用；后续按dispatch时间复核，3条source回执
发生于2026-09-23 09:36:47—09:37:28Z，早于本run，实际是4次本轮Harness语义调用＋3条历史source回执。
旧API复用标记不可信；Harness stage ledger4条全recorded/diagnostic=null，无字段新调用。
原身份匹配及字段沿用成功，正常编译、草稿、审核、发布和verify均完成。
Active epoch23/release-9dd59066-341f-41d5-8163-a499b0486398；verify PASS：
79字段/26verified/53missing/80members/50citations/1search。原已有自由页保留，新自由成员0。

原生发现及准入HTTP调用正常返回，但v4准入c11—c14输出REJECT且existing_target非空，
违反既有audit-only合同；strict_projection拒绝整份准入，错误native admission audit-only decision invalid。
未到最终自由知识审核，未触发R6多窗裁剪；当前材料仅一个原生窗口，不能记live multiwindow PASS。
模型raw/完整审计保留，未人工删字段、改判REFERENCE或重试；质量及通用模型协议稳定性统一后置。
UI任务详情已核对：发现失败、正常发布/检索检查完成、可恢复入口可见但未触发。

DELIVERY：software/container health/local live PASS；provider调用确有recorded回执，
provisioning本次无变更（运行配置hash未变），GitHub live NOT RUN。BUSINESS主流程PASS，
新增自由知识/typed关系/模型标志样本BLOCKED，跨窗live NOT RUN；完整G3.5仍未验收完毕。

收尾只读独立复核0 BLOCKER：原raw/canonical哈希链匹配，12fae与a587的audit-only拒绝条件相同；本次有界证据未显示部署导致的回归，不扩大为全局无回归。

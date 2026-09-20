# Task3bn 集中修复与平台复验

基线63ac9e460092ecc3b27b8d56ea077bb813705581；沿用OpenSpec129和现有G3环境。当前为软件验证阶段，尚未部署本切片。G3整体BLOCKED，不能用上轮2648-1正常发布覆盖重复上传/失败恢复问题。

| Requirement | 实现及证据 | 软件状态 | 本切片实际部署/网页复验 |
|---|---|---|---|
| G3-AUTO-1/3 上传复用 | production ScopedPlatform补齐SHA查询代理，经真实PlatformClient/HTTP适配器验证跨批绑定且旧metadata不改 | PASS，相关18项测试 | NOT RUN |
| G3-AUTO-4 确定性错误终态 | stage adapter将本地AttributeError/TypeError归为既有不可重试错误，避免重复等待一小时 | PASS，真实worker两类RED→GREEN | NOT RUN |
| G3-AUTO-4/5 状态读取 | 列表复用有界摘要查询，详情按需；迟到详情不得覆盖已观察的新阶段/终态 | PASS，前端41项及类型检查；Python列表23项 | NOT RUN |
| G3-AUTO-2/6 模型格式边界 | 各语义入口共用仅单个完整json围栏兼容，拒绝重复键、非JSON常数、多段和外部解释；保留原响应 | PASS，C定向36及相关86项 | NOT RUN |
| G3-DISC-1 覆盖统计 | 分别记录已发送/复用、已校验、未发送；有技术失败时不虚报完整检查 | PASS，含第二窗口失败反例 | NOT RUN |
| G3-DISC-2 Schema排重 | Schema键/名称/已知概念与别名排除，未提供及失败字段也排除；语义近义不确定不发布，关系可引用原页面 | PASS（软件）；实际模型所有近义识别能力未据此确认 | NOT RUN |
| G3-AUTO-3/4、G3-DISC-1 独立恢复 | checkpoint v6在来源/Schema/已签当前发布依赖下复用字段，按有效前缀恢复；generation与final review失败分开 | PASS，v6及原审查反例均关闭 | NOT RUN |

验证明细：root上传/阶段18通过；前端竞态首轮2失败39通过，修复后41通过4.23秒（PTY session69023/34010）。最终类型检查exit0，日志`/private/tmp/g3-platform-independent-deploy-20260913/task3bn-frontend-typecheck.log`。C定向36通过90秒，相关86通过260秒，Ruff通过。独立冻结子集首审1个BLOCKER（前端状态竞态），修复复审0个；报告`/private/tmp/g3-task3bn-frozen-subset-review.md` SHA946165f5a453ada75b7fdd718adbec904e31d50abbd0194025402dbe1b8d0699。该子集审查不覆盖尚在实现的v6恢复域。

真实已记录响应的离线检查：faf5182c的发现调用afb4375e-5779-432a-b8ca-66a85fc3cf4d，原raw SHA8d687eed8436b020a1238943a56ed2899a8bf63f6137f39ce4b04fc2d5d8de69；旧JSON入口拒绝，新入口接受，原raw不变，模型新调用0/业务写入0。随后读取同run原compile_request/context/window audit，按生产入口相同的canonical serialization完成独立候选投影PASS（含证据与Schema排除）；首次诊断脚本错用普通JSON序列化被拒绝，修正诊断脚本后通过，生产代码未因此修改。这不是最终模型审核或自由知识发布。回执`task3bn-recorded-json-boundary-check.json`、`task3bn-recorded-discovery-projection.json`。

新网页样本准备：平安安医保（优享版）医疗保险2662-1，官网条款/费率表/说明书三个原PDF，首页目视核对，租户含删除记录SHA和同名匹配均0。文件及下载来源在`/Users/houjing/Documents/LLM_wiki/g3-acceptance-inputs/2662-1/download-provenance.json`。当前尚未上传。上一轮2648-1三PDF用于重复上传及独立发现恢复，旧59c9/5b737用于已有抽取后发布失败恢复；1835缺可信主体等价证据，维持明确待确认，不能声明已发布。

部署计划只更新Harness与UI，复用APP、DocReader、数据库、现有模型与审核配置；没有新增数据库或权限。六维delivery和各网页run须以实际执行回执分别更新。本切片5～10分钟目标、规模和长稳均未取得新的通过结论。

## 2026-09-20 续行核对

原G3服务仍运行Task3bm镜像，API/worker健康；本切片未构建、未部署。网页再次直接读到2648-1终态partial_success及34/34/6，未触发恢复或模型调用。

C父响应恢复边界复核0新增BLOCKER，报告`/private/tmp/g3-task3bn-discovery-replay-review.md` SHA4c26032ff93ebfa7b8a8f1aa33177721c7d6293c9b6a14c706d46d520cd93735。合法原响应复用，确认已记录但不合法的失败单元才可在显式子恢复中新调用；未知发送不重发。

A恢复v6软件已覆盖原B1（失效阶段未决调用）及首轮B2（保留待确认/拒绝处置）。独立复审B1关闭；B2还剩同一设计范围内的处置产物继承缺口：首次变Head恢复完成检查点、编译尚未输出就失败，再次恢复需继承且重新绑定原处置。报告`/private/tmp/g3-task3bn-recovery-final-review-02.md` SHA1046a7927e2900235449203daf9bd0570486933ca8cdd17a5a95a362452d5898。已退回原Owner按最小worker反例修复，不增加新服务/表/环境。该项关闭前不开始构建。

下一步顺序不变：修复及限定复审→一次更新Harness/UI→网页独立发现恢复、重复上传和已有失败恢复→2662-1全新三份材料完整链路。所有业务结果仍须实测，旧正常发布不覆盖恢复失败，也不推导5～10分钟。

续行现场基线：2026-09-20T01:16:50Z，网页点击任务“刷新”，现部署列表GET实际200/17.318044177秒/309221字节。只读日志元数据`/private/tmp/g3-platform-independent-deploy-20260913/task3bn-before-deploy-list.http-timings.json`；没有调用模型。后续用同入口比较新轻量列表。

root最终旧冻结恢复组实际执行20/20通过，388.55秒，日志`/private/tmp/g3-task3bn-final-recovery-tests.log`；这次执行在B2可选处置继承修复前，不能替代该修复的新反例GREEN。

## 2026-09-20 软件最终冻结

A最后B2实际RED→GREEN：首个变Head子任务检查点成功、编译产物前失败，再次恢复继承原处置与receipt约束并绑定当前request，保留原PENDING，新增发现/最终检查模型调用0。窄例1 passed/5 deselected，76.52秒；旧wire1 passed/13 deselected。独立最终复审原B1/B2全关闭，0剩余BLOCKER，报告`/private/tmp/g3-task3bn-recovery-final-review-03.md` SHA 8dbd28e05ad04c76f2c77c65ee48e7863e49283b372d64333040d914ad2a72d3；8文件冻结identity SHA db36eb001baab8b29fdab0b8c9dd844a22769520d49a4ed195a38cc5e0f570b9。上述均为离线worker fixture，非真实provider或网页业务。

root全改动Python Ruff发现列表代码及test_api四处超长行，仅机械换行后全部PASS；不改变逻辑，原列表23项语义回归适用。独立review确认四处机械格式RED豁免。diff-check通过。当前提交包含已审软件与证据；本切片容器构建/健康、配置部署、真实provider、local live、GitHub live分别仍NOT RUN。原环境的健康只证明旧制品运行，不代替本提交部署。

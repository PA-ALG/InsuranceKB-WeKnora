# Task3bn 集中修复与平台复验

沿用OpenSpec129和现有G3环境。Task3bn 源码0940f36497a7已于09-20部署；当前09-22继续核查其真实恢复失败，集中修复尚未部署，G3整体BLOCKED。下表保留当时软件冻结口径，实际部署与业务结果以文末按日期的记录为准，不能用2648-1正常发布覆盖恢复问题。

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

## 2026-09-20 部署后网页实测

Task3bn 已只更新受影响 Harness/UI，复用原 APP、DocReader、PostgreSQL、Redis 和运行配置。Harness 镜像 sha256:d76dbcaa3d034189eea096a87660996d434421d143ab0f9abcd0ce7b606b36d3、UI 镜像 sha256:d488e95945f58a0967fd07108cacd32b0c83360e48d123d0bb57cc6ec2bfc57e，源码均为 0940f36497a7e7921b45aafab2362d6ca44182ff；处理服务和前端健康，数据库迁移、配置变更、模型调用和发布写入均为0。原容器保留回滚。

列表性能真实对比：部署前列表 GET 17.318044177 秒 / 309221 字节；部署后 0.318828452 秒 / 25772 字节。部署后显式详情 GET 1.214670547 秒 / 16186 字节。性能改动已在真实入口生效。

重复上传实测：网页再次上传2648-1相同三份PDF，接收与来源阶段成功，三份材料绑定到既有知识ID；归并阶段模型调用收到上游 Gemini 400 `User location is not supported for the API use`，平台以 `IDENTITY_MODEL_CALL_FAILED:provider_http_status` 终止，0字段重抽、0发布写入。该结果证明重复材料接线与原结果复用入口已生效，但受当前模型网关地域限制，不能宣称本次增量发布完成。

平台恢复实测：网页点击2648-1已有发布任务的“恢复自由发现”，平台创建任务 2be3b35b-e390-5825-9ddd-43a6e856ccaa，检查点阶段约1秒终止为 `CHECKPOINT_INVALID`，0模型调用；原任务、材料和字段结果均保留。随后网页恢复旧抽取任务 59c9bf37-b650-50f2-8a1c-65b9563e9023，仍未形成发布结果。该项仍为平台遗留问题，不能用离线 fixture 通过替代真实恢复通过。

新产品2662-1三份原材料仍未上传，避免在 Gemini 当前明确地域拒绝期间消耗全新产品首次网页验收样本。当前 G3 状态：软件、构建、容器健康、列表性能 PASS；重复上传业务与恢复业务 BLOCKED；全新产品网页验收 NOT RUN。主要外部阻断为模型网关地域限制，平台恢复检查点仍需依据真实运行数据修复。


## 2026-09-22 真实故障定位与集中修复（尚未部署）

仅使用既有环境、真实持久记录和公开GET核验。服务健康，原active仍为 release-70dd8e65-a844-4e7c-97fd-15107cdd3bfb / epoch13。此次构建0、部署0、迁移0、业务写入0；2662-1尚未上传。

| 检查 | 实际结果 | 范围 |
|---|---|---|
| 2be3b35b checkpoint | BLOCKED：`checkpoint artifact producer fence changed`；父faf有2个source_processing_attempt producer_generation3，source任务成功代次4 | 已部署函数+真实DB，仅SELECT/SHOW；初次只读事务不允许FOR SHARE，随后以SQL语句防护禁止写入 |
| d830d5e2 checkpoint（5b737子） | 本地proof、3份当前来源及签名/parse attempt均PASS；旧workflow2/base epoch11不支持切到当前13 | 真实原因不等于解析失败；任务09-20 16:34:55.363138Z已blocked，无一直运行 |
| 原字段重基兼容 | 2be 74字段，7.785秒；d830 82字段，15.219秒；现有纯函数均PASS | 只读输入、仅内存投影，不写结果/不生成发布candidate/不替任务运行，不能算BUSINESS PASS |
| Gemini实际worker | HTTP200，3.133秒，内容OK.，零重试，1次实际发送 | prompt仅Reply only OK，未发送文档；原usage为prompt120/completion2/total163/reasoning41，按提供方原值保存 |
| API网络诊断 | API仅内网，无默认出站路由；worker有既有provider-egress且调用成功 | API里首次ConnectError未发送模型请求，不是实际worker网络故障；没有改网络/配置 |
| 网页入口 | 登录页，等待用户自行登录 | 不读取Owner密码；离线工作不因此停止 |

恢复单入口与安全原因码：新增两项测试在旧代码均以泛化CHECKPOINT_INVALID断言失败（94.71秒），实现后2 passed/52.17秒；原v6当前Head重基及未知发送反例2 passed、4 deselected/231.50秒，原未知发送继续不发新调用。Ruff通过。运行warning为Starlette testclient/httpx弃用提示，非业务错误。

source审计生命周期修复：选择器同时过滤当前及继承的audit-only refs，原审计保留，最终输出fence仍严格相等。新增真实repository/WorkerLoop两例RED→GREEN，相关checkpoint contract/recovery/source阶段24 passed/303.86秒（owner报告，root已核对实际diff与新测试）。尚待合并本轮旧workflow2兼容的限定回归及独立审查；不能把上述结果写成真实网页恢复或G3完成。

本轮合并软件验证：旧workflow2保持旧v2记录不变，新恢复计划v7显式执行workflow2；变Head后复用已验证字段，重新编译，旧自由发现审核不进入新输出。真实repository/worker fixture贯穿至发布成功，随后扩展为首个v7在preparation故障、孙任务继承4项重基证明继续完成：最终1 passed/274.67秒，两代恢复的归并、字段、发现、最终检查新增模型调用均0。中间208.56秒一次失败为测试误断言内部异常码，平台公开终态正确为PRODUCT_STAGE_FAILED:preparation，纠正断言后通过，不作为产品RED。v7合同、旧v6 wire及诊断短批5 passed/38.29秒。scope绑定错误已恢复原NonRetryable语义，独立RED→GREEN 1 passed/4.47秒。

root在最终合并生产代码上重跑source审计生命周期2 passed/18.82秒，9项改动Python文件Ruff通过，git diff --check通过。独立最终复核仍在执行；上述为本地软件结果，部署与真实网页验收尚未执行。证据位于工作树tmp/g3-diagnostics-20260922/：legacy-rebase-tests.txt SHA a68a191e8d8ca1bcb993d07e44fb14bc072643831fd90a6301579ba60c2775eb；source-audit-lifecycle.txt SHA 01467d058334587b171a8a1f60d8018723f0616f7acb76bff6d4ac0b567054c9。

一次部署准备：仅Harness API/worker，复用当前compose、原配置、挂载、网络与数据库，不改Go/UI，不迁移。部署前无活动任务才更新，健康或配置一致性失败则回原镜像；准备脚本尚未执行。数据卷/dev/vdb1实测108G/已用97G/可用11G，无扩容或清理。

最终独立复核完成：5个生产文件冻结SHA逐一一致，BLOCKER0。报告tmp/g3-diagnostics-20260922/final-review.md SHA1966963f3ae1091292de13acdce6405ed6caa586266861ecffc8a33928263d3e；确认旧wire、v7有效产物隔离、二次恢复proof链、原scope失败语义及严格generation fence。非阻断后续项为独立入口policy错误边界、一次性部署包装的assert/rollback显式后验和新入队时间点竞态，不扩成本轮长期部署框架。软件冻结后才开始一次Harness构建/部署；截至本段运行验收仍NOT RUN。

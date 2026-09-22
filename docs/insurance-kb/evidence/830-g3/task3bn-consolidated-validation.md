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

## 2026-09-22 集中修复部署结果

源码dc635e8e2151ba52941394426890c4a033698ca2，唯一新镜像sha256:a7c6ebeccd77ebb263999093d7fb1c00b9b1dbbd86b607290ff4f6b6cf056155，构建1次37.219秒，依赖缓存复用。只替换原Harness API/worker；UI、Go、DocReader和数据库未构建/迁移，运行环境配置摘要、挂载与网络均保持一致。

部署尝试2次：首次Compose在60秒启动等待配置下exit1，已回滚至旧镜像且两服务healthy；详细Compose输出未保留，不能确认其唯一失败原因。Docker日志显示旧两服务45秒内未退出并经历强制终止，新容器运行约77秒后被回滚停止。新镜像隔离、禁网CLI导入烟测PASS/6.726秒。保留首次失败回执，随后只把受控部署等待改为180秒、保留错误输出并补rollback后验，同一镜像第二次更新PASS，没有任何代码重构建。新的API/worker健康，前后Active Release一致为release-70dd8e65-a844-4e7c-97fd-15107cdd3bfb/epoch13，活动任务均0。

软件PASS、精确容器健康PASS、原配置复用PASS、local live健康及current读取PASS；provider单次受控探测PASS发生在本次部署前，配置和外呼适配器未变；GitHub live NOT RUN。部署结束时网页仍在登录页，本轮业务当时NOT RUN。后续真实业务见下节；G3整体未完成。完整无密钥机器回执见task3bn-recovery-20260922.json。

## 2026-09-22 原账号恢复及网页业务复验（进行中）

用户要求复用处理过这批材料的账号。核对历史创建/授权记录后，确认原专用测试账号仍存在，临时凭据文件已丢失。本轮仅恢复该测试账号凭据并撤销其旧会话，账号/租户10003/权限/材料保持，未新建账号、未关闭认证、未改应用代码或部署。正常网页登录成功，原RAW库和历史任务可见。私有凭据不进入Git或公开回执。

网页恢复2be3b35b后，平台任务b3fab26f-9392-5045-9eea-b4148e4fc219在2026-09-22T03:40:44.811614Z至03:44:53.424001Z完成，248.612秒（4分8秒），partial_success。34有效/34未提供/6失败，原字段新增调用0，自由发现实际新增2调用，页面显示复用9调用/7阶段。checkpoint16.136秒、discovery19.892秒、compilation48.999秒、preparation51.621秒、review34.814秒、publish37.126秒、verify26.847秒（总耗时另含排队切换）。最终发现未形成有效新知识，保留DISCOVERY_EMPTY及原响应，不补抽普通字段。

平台自动发布至release-c667f177-d4ae-46df-a1a8-658e8824aa4c/epoch14；平台验后PASS，74字段、75成员、69引用、1条产品检索。浏览器实际打开该版本独立字段“投保范围”及原PDF第12页，正文可见。验证记录中的missing_field_count=40为非有效字段合计，任务终态细分为34未提供+6失败；legacy finalization.model_call_count=0不含stage_calls，应以API详情及持久调用记录实际2次为准。

随后通过网页恢复d830d5e2，平台创建76eafa2b-324b-51a1-8582-27492adbfe6c，03:45:24.101799Z至03:53:40.018891Z完成（495.917秒），partial_success，13有效/17未提供/52失败，模型新增0/复用10。发布epoch15/release-40116374-35ce-43f3-b15c-90caeac12f78，平台检索和23引用检查PASS。新增2662-1三原文件SHA与准备记录一致，上传前在knowledges含历史删除记录的SHA匹配数为0。全部接续均由平台任务执行，无业务脚本、手工候选、字段修补或代发布。


## 2026-09-22 首次上传回执缺陷及集中修复

2662-1三份原PDF通过网页首次上传，最后上传03:54:16.652739Z，run368c59f1-fa81-4c99-a5ff-ba5940b5e84d。三份原生解析均completed，调用回执分别12/3/6，合计21次且均有确认响应。source首次保存AVAILABLE/0调用的在途回执，后续同parse/processing attempt合法追加被旧唯一key误拒，ValueError使其长期重试。首次无干预验收BLOCKED；修复后恢复不覆盖该结论。

重复上传恢复run ae55548d-7328-5516-9989-d9210a2142b9已明确needs_confirmation，1次Gemini身份调用，原响应已存。JSON合法，但identity引用排序与单材料身份值证据不满足合同；仅内存排序诊断后仍存在不受证据支持的值。不手工补身份/跳过证据，不自动重调，归并语义容错作为明确遗留。

根因修复归属processing_audit深模块：追加不可变快照、同处理尝试进展验证、迟到未知响应精化、阶段终态事实多重集、计数去重、旧summary精确SHA兼容。无新表或迁移。原worker source轮询测试真实RED（source processing receipt changed），API增长快照两项真实RED（错误计3、应为2）。本地source/receipt/checkpoint关联44 passed；后续audit/API32 passed；恢复关联68项初次66 passed，另2项为已有错误诊断合同的旧测试断言，按真实NonRetryable绑定变化及CapacityBlocked解析版本变化细分后2 passed/1.63秒，无对应生产代码变更。

实际三材料6份回执离线回放PASS：在途计数未知、已记录下限21，最终summary准确21不重计；输入SHA21c08e901b8d4fe887860385bb84c543d958dbd809a4ae96053fe3156081cd1d。读取只用GET/SELECT，离线回放业务写入0、模型新增0。独立代码复核进行中，部署NOT RUN，G3整体仍BLOCKED。


| 适用 Requirement | 当前实现 | 验证证据 | 状态 |
|---|---|---|---|
| G3-AUTO-3/6 成功解析及审计复用 | artifacts追加不可变快照，processing_audit统一合并 | source轮询worker通过、原字节不变；真实3文件6回执/21调用离线回放 | CODE PASS / DELIVERY NOT RUN |
| G3-AUTO-4 明确终态、正确统计 | 无效/冲突回执NonRetryable；API读视图按dispatch去重 | 冲突worker明确dead_letter；在途unknown；迟到精化和SHA/原counts一致性RED→GREEN | CODE PASS / DELIVERY NOT RUN |
| G3-AUTO-5 真实服务接线 | 仅现有Harness API/worker受影响 | 软件34 passed/9.76秒，Ruff及diff检查；部署尚未执行 | NOT RUN |

独审发现两项同域缺口并集中修复：成功summary的旧未知回执不能遮住迟到结果；聚合去重不得改material counts同时沿用旧receipt SHA。两项RED为2 failed/.67秒，最终含两反例的34项测试通过；原回执及summary不变，读视图指向真实最新SHA。初冻审查不代表修后通过，修后独审仍待最终报告。

最终修后独审0 BLOCKER，独立相关70 passed/69.17秒，Ruff PASS，冻结SHA一致。报告SHA025431896045c016d7d2cb1f000b709437b14ef636dbe77c5363a44beefa81ba。BACKLOG：list_artifacts默认1000条上限可能截断极大/长轮询任务审计，当前三来源未触及；不能据此声称千文件规模通过。开始一次Harness构建部署，网页业务仍待实测。

部署PASS：80f0af20b78ddc4bdcf05603cbd3573ddcb7679e，镜像ae8f288b5daec784971014250238d484996f82d0ed81be69ff30219e6b18d998；唯一构建2.685秒，原Compose更新一次成功，API/worker均healthy，env摘要/挂载/网络不变，DB/Go/UI未变。已知source等待任务自行恢复，网页进入产品归并；无业务脚本、无重新解析。终态待观测，首次无干预验收仍BLOCKED。机器回执task3bn-source-audit-deployment-20260922.json。

网页后验：原368c任务自主source/routing成功，页面累计22模型调用（native21+identity1），终态needs_confirmation/IDENTITY_RESPONSE_INVALID:ValueError，耗时38分15秒包含开发/部署等待，不能作为正常吞吐成绩。原生回执已追加且不再重复等待，未重解析、未重放原生调用。

进一步贯穿检查不部署：同一已存响应在内存仅规范引用集合后adapter及原生定位投影3/3 PASS；v3联合产品归并仍因issuer简称/全称冲突NEEDS_CONFIRM，未生成持久候选。首期资料同一产品名、medical_insurance明确，完整条款备案号/代码可用，辅助材料身份由既有v3联合互补；公司名不同是剩余决定性边界。未知简称关系不手工改成同一公司。用户已收到归并规则方向异步选择（平台Gemini原文+候选联合判断 / 保持严格人工确认），不是再次申请操作授权。

非语义容错先完成：identity引用排序/重复规范化保留原raw和改动审计，悬空/跨材料/未经支持的身份值仍拒绝；RED3 failed/.64秒，GREEN13 passed/1.30秒，相关39 passed/36.98秒，未部署。不能为该小改再部署后才发现下一个归并问题。

末轮运行状态：原账号正常登录，现有数据/角色不变；两条真实恢复发布PASS，新2662解析回执故障修复已上线且自主续跑，22次调用准确显示。当前新产品没有进入字段抽取/编译/发布，不能宣称G3整体完成。后续不依赖登录操作，待联合issuer规则确定后集中实现、复用旧响应优先、必要失败单元再调模型，最后统一更新并重新网页验收。

引用集合容错最终独审0 BLOCKER；独立27 passed/.81秒，原列表审计/unknown ref/foreign locator探针通过；报告SHA3623abe8884a396d2122f33018ae3340bae7fbc2fe576a0f48f412e1fb6d1878。代码可集成，但本小改不单独构建部署，等待联合归并规则收口再统一交付。

### 2026-09-22 公司声明策略收口（未部署）

G3-AUTO-1/3/6：用户确认平安人寿简称/全称同公司，平台已有可信ResolutionPolicy新增作用域明确的issuer_aliases。原proposal、PDF证据和模型raw不改；新声明入policy SHA，旧省略字段原哈希保持。Python RED3（不支持声明）→115 passed/17.34s；Go新向量RED（严格合同拒绝）→identity与batch回归PASS/26.964s，旧v1/v2/v3向量通过。真实368c已保存响应→原生来源→Python归并3 CREATE/一医疗险绑定/3来源→Go严格resolution/binding重放PASS/2.101s，新增模型0、业务写0。完整发布未执行，网页恢复仍NOT RUN。实现冻结后独审，再一次更新受影响APP/Harness。

最终独立复核BLOCKER0/BACKLOG0/REJECTED0；报告SHA 4605e3ed7392ecfa4daa5873708d755cd0e715ad2849b8ae5268aad28940e3fe，独立Python115 passed/15.03s、Go冻结向量与真实replay PASS/2.303s。软件冻结；下一步APP/Harness各一次构建更新，部署和网页验收仍NOT RUN。

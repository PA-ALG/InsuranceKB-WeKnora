## Task3ae/af code verification, 2026-09-15

Task3ae repository RED reproduced false recovery eligibility; GREEN: 26 recovery tests PASS (180.09s). Task3af repository RED reproduced the actual extra DocReader call; GREEN: 15 parser/recovery regressions PASS (7.677s), with the external exported fixture not run, plus the explicit no-automatic-retry binding PASS (3.532s). Exact logs and hashes: `/private/tmp/g3-platform-independent-deploy-20260913/task3ae-af-code-verification.json`. Independent frozen-patch review: 0 BLOCKER, 1 BACKLOG: a journal read error is currently treated as recovery inapplicability and can fall back to full reparse; this edge is not described as complete failure-resilience coverage.

The new path uses a NEW ParseAttempt, references immutable original DocReader evidence in the new signed artifact, and performs new chunking under current configuration. It does not claim complete chunk/vector checkpoint reuse or historical raw embedding response custody. Actual historical artifact availability and full worker publication remain NOT RUN. The next joint APP build has a 5400-second bound, reuses partial prior compilation cache without claiming it fully warm, and retains 2 CPU / 4GiB limits and disk reserve checks. Existing database/services are reused; no new source uploads or runtime processing during deployment.

# 2026-09-15 Task3ad build outcome and recovery follow-up

Task3ad CODE remains PASS at 5aa5d05. The actual binary build started at 2026-09-14T15:41:24Z and stopped with BUILD_TIME_BOUND_EXCEEDED at its 2400-second bound; receipt task3ad-app-build-receipt.json is FAILED. Runtime rebase, smoke and deployment were NOT RUN. The live APP remains 297d4db13a55, with existing Harness 8dd22 and UI 7a1249. No business run or provider request occurred during this build. Initial system Python preflight failed before any build due to missing hashlib.file_digest; the actual build used project Python3.12.

The previous fourth acceptance remains FAILED. Read-only follow-up proved source reparse alone cannot reopen its product retry capability, and ordinary full reparse repeats DocReader. Tasks3ae/af prepare explicit source revalidation and immutable DocReader-result reuse using a NEW ParseAttempt. Historical chunk-plan reuse is not claimed. Failed-source call summary incompleteness and lack of embedding raw-response custody remain explicit gaps.

# G3 平台接线进度（2026-09-14）

当前结论：G3 **未完成**。以下代码、部署事实不能替代三份真实原材料的平台独立验收。

最新状态（2026-09-14 14:40，以下分节保留历史）：APP 已更新至 9e0979f61，UI 与常驻 Harness 为 d7812093；调用统计与 embedding 每批20条配置已经部署。两次真实网页运行分别在来源解析和首页路由阶段终止，均未发布。当前修复 Task3y 首次解析正文与定位共用同一持久化产物，尚未部署。原 active Head 仍为 epoch 9、7个产品、493个字段、516个成员。

- 用户授权数据盘只增加10GiB；既有Colima数据盘100→110GiB已完成，原26个运行容器恢复。未新建数据库服务、VM或材料专用服务。
- APP镜像构建和精确启动检查PASS，已替换现有G3应用，旧容器保留用于回滚。源码e00f7908eee649a40531e6363d7984502b212fe1，镜像sha256:0dd7bffabf63258b55ef33e52b59c6e247976afa789f79750087d9d7f43df5d3。
- 原产品→分组→独立字段Wiki导航已部署并通过浏览器点击验证。当前前端镜像sha256:ed04d6c1d9f799eb1e374389aa3e99418da22cf43dcb85cc0e02ce01b315cbab，原固定release/字段URL保留。后续发现状态面板尚待本轮构建、部署。
- 原Qwen embedding配置由停止的本机19030地址恢复为DashScope官方兼容接口，正式GET/PUT/读回PASS，凭据保留。未执行provider probe。

## 自由知识接线（CODE）

现有材料解析结果经独立于Schema字段关键词的有界章节选择，进入生成、证据校验和独立审核。生成/审核调用分别持久化；只有整组ACCEPTED合入现有Candidate，其余保留原响应、原因、审计记录并继续普通字段。Schema不自动修改。

- 选择器16 tests PASS；纯适配层20 tests及预算/update-only追加回归PASS。
- 原编译门禁5 tests PASS；独立审核/新页/陈旧hash/缺分及待审追加9 tests PASS。60–79分保留待审，不宣称已发布。
- 常驻完整任务流程2 tests PASS，含三份材料、发布后的仅失败字段补抽。再验证生成/审核响应已持久化、阶段提交中断后的恢复：1 test PASS，165.64秒，模型MockTransport，无真实业务效果。
- API 18 tests、任务面板27 tests、配置8 tests PASS。状态白名单不暴露原模型文本；只有任务终态且verify成功才显示已发布。
- 已补发现通过但原任务未发布的补抽门禁：先核对原自由成员已完整进入当前签名发布基线，否则明确待确认。两条回归PASS。
- 相同原文但实体/Schema版本绑定改变必须失效，focused PASS。
- 生成格式错误、审核格式错误、内层PASS但处置REJECT/PENDING、完整ACCEPTED与两种补抽基线共7场景PASS；与版本失效合计8场景通过。独立复核原BLOCKER已关闭。

## 首次运行前的待验收清单（历史状态）

1. 本轮发现状态/常驻任务实现的最终冻结、镜像部署与真实入口验证。
2. 全新产品三份PDF从网页上传，平台自主运行至可检索/证据可回查；实际阶段耗时、总耗时、模型调用数及缺失/失败字段数。
3. 真实Schema外知识示例以及重复/噪声处置。历史开放页或fixture不作为这项实证。
4. 服务/权益多类型实体的常驻处理与统一发布接线。目前服务Schema与清单属于结构资产，不能据此宣称8条服务已发布。

截至首次运行前：本轮真实上传0、模型调用0、发布变更0。其后真实运行见下文。5–10分钟仍只是优化目标。

## 首次真实运行：FAILED（保留，不改写为通过）

源码d7812093，APP、前端、Harness均已部署并健康。冻结回执位于本机`independent-acceptance-freeze.json`。网页上传全新“平安创享盛世金越（尊享版26）终身寿险（分红型）”三份PDF后，平台创建任务`8e5693b4-6365-458b-89e6-7ced242b200d`。

- 接收阶段成功，source阶段以`SOURCE_PARSE_FAILED:保险条款.pdf`明确失败；任务终态2026-09-14T04:59:38.335359Z。未到抽取、编译或发布。
- 条款及说明书原文解析后，在向量化时收到HTTP400：批次文本数量不能大于20。实际既有APP环境为`BATCH_EMBED_SIZE=100`；费率表完成解析。
- 原文件标识：条款`88d0e1e4-3c58-4d98-8e4e-8afaff535f0f`；说明书`7c7083c7-bfad-4e71-adb1-ce436910ad53`；费率表`8871ec5f-5c87-468a-af57-b74452db820d`。原文件均保留，无手工接续发布。
- 浏览器文件选择工具响应明显延迟，不能把工具往返时长当平台处理时长。上传完成精确时间待核对；不得用任务seal时间无说明替代最后一份文件接收时间。
- 浏览器API此前显示model_call_count=0，但Go桥丢掉了`model_call_count_complete=false`及处理摘要；0不代表源向量化没有发生。补齐typed转发，并从已有模型dispatch回执核对实际调用数。
- 本次失败已结束测量。后续配置修复/部署及新的独立运行另记，不能与此次拼接宣称通过。

### 首次失败运行补充核对与修复状态

- 来源 dispatch 表已记录12次embedding发送：条款5次HTTP400、说明书5次HTTP400、费率2次HTTP200；这些条目的transport_retry_index与worker_retry均为0，不能把它们报告成自动重试次数。费率摘要正常完成但标准SDK Chat缺journal记录，因此12只是已记录发送数，不是完整模型调用总数。
- Go状态桥修复已提交dd99972f19b6d9bf305f1227107c845d5c714bfd，针对真实HTTP GetRun/ListRuns测试通过，独立review无BLOCKER；尚未部署。
- dd999应用构建依赖层命中缓存，编译阶段客户端报Docker EOF；回执为INCOMPLETE，无可用新镜像。其后18295与Docker socket不可连，恢复诊断中，不能记为健康或已修复。
- Docker数据盘100→110GiB已经执行，复用原VM与服务。此容量调整不代表宿主实际空闲空间相同；13:31宿主可用2.9GiB。

- 后续诊断确认VM未停止、26容器仍运行，无近期OOM；断开的是宿主端口/socket转发。已仅重建两项SSH local forward并保留旧无监听socket，未重启VM、Docker或数据库。宿主18295/health现返回status:ok，Docker server28.4.0可达。BuildKit旧构建已明确Canceled，未部署。
- 标准SDK Chat dispatch修复完成真实RED与GREEN：成功、HTTP错误、传输错误、既有去图重试、登记/发前/发后记账故障，及既有Gemini raw路径回归通过（2.137s），未发生真实模型调用；等待独立复核与部署。

## 第二次真实网页运行：NEEDS_CONFIRMATION，未通过全链路验收

应用修复源码9e0979f61722a45d4b6b36464043ba8ff87da6f1，镜像ae871f43b767fe76410cb4a9b8feb659a5de4a7a558b5c8853b93c160e9c7486，构建16m49s、精确制品烟测PASS，原应用替换PASS；BATCH_EMBED_SIZE=20。数据库、原文件、原发布Head保持沿用。

- 新样本：平安e生保（悦享版）医疗保险，E保险条款.pdf、产品说明书.pdf、费率表.pdf。此前RAW25份与Active7产品均无该样本。仅通过网页选择三文件上传，任务2f0b1dc5-008b-4902-934b-b4ff7c1efcdf。
- 版本冻结时间2026-09-14T06:00:11.318404Z。网页上传HTTP200日志时间06:01:56Z（精度1秒），终态06:05:50.447326Z；至待确认约3分54秒，不能称发布耗时。
- 接收27.027s；DocReader三材料分别42.291/56.075/46.799s，分块3.622/0.500/0.606s，embedding42.652/28.164/19.401s，摘要15.650/11.936/15.724s（条款/说明书/费率顺序）。这些并行阶段不可相加当总耗时。原文最后处理完成06:03:55.002092Z。
- source快照阶段81.393s；routing阶段4.102s，终态needs_confirmation，原因FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE。抽取、校验、编译、审核、发布均NOT RUN，缺失/失败字段数不适用，页面显示0不代表字段质量通过。
- 完整来源调用回执23次：条款14、说明书6、费率3，transport_retries=0、interrupted=0，model_call_count_complete=true。本轮抽取/发现调用0。
- 真实根因：三个首页均有完整名称，但已持久化的312个canonical检索块全部UNRESOLVED。首次上传普通解析输出与后续固定builtin native-capture输出不同：条款和说明书LF/CRLF不同；费率还存在Markdown标题与版面空白差异。严格字符串定位因此全部失败；不是用户缺名称。
- 本轮保持终态/原文件/解析/模型记录，无人工填身份、无候选拼接、无发布脚本、无测量中代码修改。后续需从首次解析时统一文字与页码坐标并持久化，不能以模糊匹配放宽证据。

### Task3y 修复验证（代码已验证，尚未部署）

- 首个实际RED证明缺少首次产物时，旧快照入口仍调用DocReader并返回成功。首次解析签封、CRLF与跨页定位、重复文字定位、重启后零再次解析、篡改拒绝等首轮定向回归通过，测试体10.603s。
- 补充真实入口测试确认G3调用builtin/native_capture、非G3保持原auto配置；随后快照及重启复用没有第二次Read。
- 真实入口测试又发现保存失败后DocReader span仍done，以及父块合成表头造成子块原文坐标偏移。均保留RED后修复，正在统一回归。
- 独立复核要求父子分块在首次签封前统一唯一序号，以满足正式manifest严格递增规则；要求有效first artifact与旧cache并存时校验完整摘要及位置绑定，禁止旧cache旁路。两项不能以helper通过替代实际接线验证。
- 清理的仅为本轮停止使用的`/private/tmp/g3-platform-go-cache`临时编译缓存（约1.2GiB）；保留默认Go缓存、原材料、解析及模型回执、数据库和回滚容器。没有新增业务运行。
- 最终合并回归PASS：35个顶层测试、含子用例共50项，测试体60.119s；gofmt与diff检查通过。父子唯一序号和首次产物/旧缓存绑定均获得实际RED后修复，独立复核PASS。文件摘要及测试回执见`first-parse-tests-20260914.json`。这些结果不替代下一轮真实网页验收。


## 第三次真实网页运行：FAILED，来源封存绑定缺陷

Task3y 源码4e7ab884e5e4b8a7bc406d63fb300f0bdb2a8320已部署为APP镜像364ba4d7c75aaa86b303027efd76c7c423d35220cd7cebc23bd19e704a5ba4a2，exact smoke及部署PASS。运行前冻结2026-09-14T07:35:01.190265Z，数据库/服务/旧第9版沿用，RAW此前28份。

- 全新“平安盛世金越（尊享版26）终身寿险（分红型）”说明书、条款、费率三PDF，仅通过网页上传。任务d1dd4a86-a4ae-49f3-93e0-decbf56ca9d0；上传HTTP200于07:37:30Z（精度1秒），07:38:13.974671Z明确failed，约44秒至失败，不是发布耗时。
- 三份原材料解析和摘要均完成，parse attempt均为1。DocReader分别8.623/8.762/8.449秒，分块0.128/0.123/0.086秒，向量化5.182/5.278/4.781秒（说明书/条款/费率）。并行阶段不相加当总耗时。
- source阶段0.457秒，首份快照HTTP409，任务原因PRODUCT_STAGE_FAILED:source，队列明确dead_letter。身份、字段、发现、编译、审核与发布均NOT RUN，字段数量不适用。
- 实际记录14次模型发送全部HTTP200：8次原文embedding、3次摘要Chat、3次摘要embedding；各材料4/6/4次，transport_retry与worker_retry均0。任务API显示0且model_call_count_complete=false，是source摘要未提交导致的不完整统计，不可报实际0。
- 只读根因检查确认三份首次产物原文hash及全部124个正式文本块的签封范围正确。首次资产另有11个父块，正式仓储和revision清单仅text子块；绑定函数误要求消耗全部父块，导致拒绝。不是缺页码、缺产品名或模型抽取失败。
- 本次没有重写原材料、修改验收中的代码、手工快照接续或发布。旧第9版/7产品/493字段未变。

### Task3z 源绑定修复及平台恢复（进行中）

- RED使用真实仓储text-only清单，两个正向场景旧代码失败；修复保留正式清单决定权，仅允许签封资产中存在额外父块。38个顶层、61个含子测试PASS，三份现有首次产物124块及页码映射通过，原件未改。独立复核PASS。
- 平台来源恢复入口开发中。恢复将创建关联子任务并保留原失败，由平台队列复用已有解析。初次失败与后续恢复必须分别计时，后续全新产品验收仍NOT RUN。
- G3总体仍未完成；服务类型完整接线、真实Schema外发现实证等原遗留未由本次代码验证推导解决。

Task3z 最终CODE回归：来源61项、Go网关22项及严格请求最终12项、前端38项、Harness分组46项不同测试通过，独立复核PASS。Harness旧heartbeat测试的依赖fixture已更新并验证，生产heartbeat语义不变。含完整任务流水线的测试使用fixture端口，不是真实发布；部署与网页恢复仍NOT RUN。测试与源码摘要见source-recovery-code-tests-20260914.json。

## 来源恢复真实运行与首页分类修订

Task3z 源码0c22aa18aeb18e75dc201f9af2164002a47da6bd已完成既有APP/UI/Harness替换及健康/静态入口验证：APP ab332e7d1a9b7cefa59f9d8536c665dae6303220c98daddf036fc8d385db2e17；UI 3a35b3a71ada2f9cb15cbfb6c7a6040733d7d8bacedb571cf8ab83d376ab168c；Harness 2c5d442d7b0134b20b9d56fd90e1cdfddc1e830eb4df16c788e81b578e9c5e19。旧APP/UI容器及Harness配置保留；数据库和原材料沿用，无迁移。

- 冻结2026-09-14T09:17:04.099722Z，网页点击正式“重试来源校验”一次，平台创建50687540-c345-581d-aa7c-6199d162b7bd，原失败d1dd保持不变。开始09:19:04.690324Z，终态09:20:24.966374Z，80.276秒至待确认，不是发布耗时。
- uploads成功4.783秒；source成功25.527秒；routing阻断13.522秒。完整调用统计：本次新增0，复用历史14，未执行字段抽取/编译/发布，字段数不适用。
- 三份已保存 source_snapshot 共124/124 EXACT_BLOCK，Markdown和Native与首次资产完全一致。说明书和条款首页名称规范化一致。费率表完整首页标题“《平安盛世金越（尊享版26）终身寿险（分红型）》年交费率表”不被原整行规则接纳，导致FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE；不是解析失败、缺页码或模型失败。只读机器诊断保存在/private/tmp/g3-recovery-routing-diagnostic-01/report.json。
- 用户明确要求 Gemini + Schema候选判断，已冻结Task3aa：去除首页整行匹配前置门槛，复用现有identity一次持久化分类，成功后封存来源归属及resolved_routing。普通字段不补齐、不重复抽取；真实身份/版本冲突仍提示。当前是开发状态，尚未部署、尚无新增模型分类或发布结果。
- UI恢复入口新增needs_confirmation+后端cap支持，RED 1失败33通过，GREEN含API共41通过，独立复核PASS。只负责提交平台恢复请求，不在浏览器判定产品身份。Harness实现及完整接线回归进行中。

Task3aa CODE已验证并独立复核PASS。前端单独冻结7a12493526d6022a6091008e42ecbb46f2845d73并构建中；后端从同一现有分支追加。恢复focused20项及完整平台流水线fixture1项通过；最终身份/冲突/旧重试兼容16项通过，最终10项identity适配通过。旧重试兼容专项仅验证持久化身份回执重用，未当作真实发布。首次完整composition成功路径通过，冲突路径暴露空原因，已汇总子判定原因并验证明确AMBIGUOUS_IDENTITY。真实三份snapshot验签后的最终模型上下文41,130字节、11中文Schema候选、全部三个首页完整名称均被提供；没有执行模型或生成业务身份。详见model-routing-code-tests-20260914.json。部署和真实网页恢复仍NOT RUN。

## Task3aa 部署与真实分类结果（2026-09-14）

以上 NOT RUN 为当时状态。随后部署完成：APP沿用0c22/ab332e7d；UI源码7a124935、镜像6b6cc0c007e439f8a1dcb2902d47f4bebd3e1e0d4d9f97c7b60e905b4d736b36；Harness源码0931e22101fb0dfb6308b47e3c85bc1251172469、镜像e8374c7e85e34d5370bfbfc8aeb48ae44b5f45370ca93f5e1d565e29385fc2f5。既有服务健康、UI静态入口验证PASS，数据库/配置和原文件沿用。精确回执在/private/tmp/g3-platform-independent-deploy-20260913。

- 10:13:55.893072Z冻结；仅网页正式“重试产品识别”创建590980a5-803a-5d3f-bee9-d910a32187fd。开始10:15:45.987385Z，终态10:16:35.274146Z，49.287秒至待确认，不是发布耗时。运行中没有修改代码、配置或接续业务。
- uploads 0.242秒、source 2.763秒、routing 0.574秒，identity 38.456秒。来源新增调用0/复用14，实际新增Gemini分类1次。提供的三份当前材料首页均包含完整名称，11中文Schema候选；实际HTTP请求45,532字节。Gemini三份均返回“平安盛世金越（尊享版26）终身寿险（分红型）”、whole_life_insurance，角色brochure/terms/rate-table均合法正确。
- 模型原响应9,190字节完整持久化，call_id=3db4b0b5-5d62-452c-afe3-c21d89d2f7f9。供应商原usage为prompt22559/completion1744/total29510，保留原值，不从其加总差异推断费用。
- 平台首个错误为IDENTITY_RESPONSE_INVALID:ValueError：模型在identity_evidence_refs中冗余加入classification引用。只读内存诊断进一步发现备案号误引名称块（真正备案原文已在offered输入）；再排除此链接问题，v2逐材料完整身份门仍拒绝互补的说明书公司、条款代码/备案及费率表名称。rate-table拼写本身合法，不是失败原因。诊断没有修改原raw/proposal/数据库，未调用模型或生成实际候选。
- 字段抽取、编译、审核、发布均NOT RUN，字段数不适用。10:19:04.795292Z只读确认Active Head仍epoch9/release-2f46c14c-5f6f-46cb-8eb2-e6afc7e5933e。原失败与待确认记录完整保留。此轮不能算平台链路验收PASS。

Task3ab已冻结：平台增加同产品互补证据的v3归并（旧v1/v2不改），由正式恢复机制复用已记录分类响应。当前处于开发验证，尚未部署；后续全新产品三份原件完整验收仍NOT RUN。

Task3ab CODE收束：联合身份/旧v2定向25项、最终备案适配10项、恢复49个不同测试、API19项、Go版本/原342字段Candidate与增量8顶层及16子项、Go Bridge组通过。新增互补三材料完整worker测试88.43秒、已记录分类恢复worker82.36秒、原流水线兼容3项225.47秒均PASS。以上全部是fixture，未调用真实供应商或发布业务结果。原实际响应的本地回归得到一个绑定、三份来源、12条原文件证据；原null与raw保持。

独立复核曾发现产品代码可以冒充同值备案号的补链缺陷；已用补链和既有version引用两条路径RED复现，修复要求明确类型证据，10项最终适配测试与真实备案原响应均通过，复核PASS。旧v1/v2算法与恢复wire保持。复用回执在实际job lease内持久化，任务后续失败仍有统计；API和Go只透传明确的复用计数及usage。源SHA、测试日志摘要见joint-identity-code-tests-20260914.json。部署、网页恢复与新产品完整验收仍NOT RUN，不由CODE PASS推导完成。


## Task3ab actual deployment and webpage recovery

APP source297d4db and Harness source297d4db were deployed on the existing G3 environment; UI7a1249 was reused. APP image2a2c94b516913a56e1dd98fa8be07f2cb9e2500610f7cacf80a6c63814a33d4b passed isolated binary/dependency checks, and application/API/worker health passed. The ordinary APP runtime build was interrupted while reinstalling dependencies; the first local rebase failed remote lookup. Both failures are retained. Successful rebase used the verified cached binary and exact existing local runtime base, with one added binary layer; it is explicitly not a successful BA0 runtime build. Separate build/recovery/smoke/deployment receipts remain under /private/tmp/g3-platform-independent-deploy-20260913.

Webpage retry of590980a5 created7b652803-6b5e-59c9-b750-19a878e3b273. It ran14:00:02.916129Z–14:00:48.454094Z (45.537965seconds to FAILED). Source/routing/identity succeeded; one original Gemini classification response reused, zero new model calls. The platform passed joint product identity using the original recorded response. Field planning then failed because1662 optional collection nulls in the existing Go published projection were rejected by Python tuple fields. Field extraction/compile/review/publish were NOT RUN. G3 independent full-chain acceptance remains BLOCKED;45.54seconds is not publication latency.

Actual classification request facts: the three current files supplied22 first-page blocks (584/1703/4983characters),11 Schema candidates and one plausible existing identity. All three model labels were whole_life_insurance and their material roles were brochure/terms/rate-table. Classification itself was correct. Redundant first-page rate rows, duplicated evidence text and task metadata are recorded as prompt-efficiency follow-ups; classification input was not full historical corpus.

## Task3ac code validation

Bounded compatibility change: only recognized optional collection slots in a copied published-member view convert explicitnull to empty collections; original signed base, scalar nulls, required evidence and all populated fields remain unchanged.5 focused tests passed. Actual saved signed base and identity reconstruct8 product bindings and retain493 old fields/8 pages/1 definition exactly against502 original page-member payloads. The check then exposed8 oversized original field windows; the largest was629253bytes against the configured300000byte context cap, chiefly repeated allowed-source metadata.

Field planning now uses the same rendered context and request-envelope preflight as dispatch and recursively splits oversized batches. It preserves task/source/cache identities, max10 fields, configured limits and prompt bytes. Only capacity errors split; other errors and an impossible singleton are explicit errors.9 pipeline checks and the complete joint-product worker fixture (1test,74.36seconds) passed. Independent frozen-four-file review found0BLOCKER. No real provider call, new candidate or release is inferred from these tests. New Harness deployment and fresh three-file business acceptance are NOT RUN at this record.

Actual saved-input split check PASS in36.95seconds:75 unchanged tasks occur exactly once in30 windows of2–3 fields, largest context281482bytes≤300000 and largest complete HTTP envelope298600bytes≤2000000; output cap remains16384tokens. Original502carried members and base bytes are unchanged. This is local pure planning, with0provider/0business effects; real product latency is not yet established. Report: /private/tmp/g3-field-plan-diagnostic-01/check-split.json.
# Task3ac deployment and fourth independent acceptance

## Task3ad code and runtime-parameter follow-up

The existing model settings endpoint changed only this tenant's embedding `max_concurrency` from inherited default (0) to 1; exact readback verified every other model parameter and credential-presence metadata unchanged. No restart, model dispatch or product continuation occurred (`embedding-concurrency-update.json`). This reduces bursts; a token-rate scheduler is not implemented or claimed.

Task3ad eight code/test files passed root's independent review with zero blockers and exact SHA checks. Sixteen focused tests passed, covering explicit G3-only policy wiring, preserving legacy behavior and accounting, original error propagation, whole-list invocations 5→1, connection-error sends 2→1 in the controlled test, and empty-success-response sends 3→1. Four RED/GREEN logs and file hashes are in `/private/tmp/g3-task3ad-result-01.json`. Initial sandbox cache access failure is setup-only; the separate service RED proved the missing policy. CODE PASS; APP deployment and business recovery NOT RUN at this freeze. No billing configuration was changed.

**Diagnosis correction after the run:** the user's account screenshot shows CNY199.91 available; a separate notification says the model's free quota was exhausted. [Alibaba's exact error-code definition](https://help.aliyun.com/zh/model-studio/error-code) maps this `429 insufficient_quota` message to TPS/TPM rate limiting, rather than insufficient balance. A post-run saved-model debug request using a short synthetic input succeeded and returned 1024 dimensions (`embedding-availability-diagnostic.private.json`). The initial advice to restore billing quota was unsupported and is withdrawn. This diagnostic is separate from the failed business run; no product material was reprocessed. The [rate-limit documentation](https://help.aliyun.com/zh/model-studio/rate-limit) also distinguishes rate limits from balance and documents 1,000,000 TPM for this model in Beijing. The actual per-account limit was not read from the Aliyun console.

Task3ac source `8dd22b327c5261644b9865ce3119179be889477c` is deployed in the existing product API and worker, image `sha256:80420b69ce3dc44dcdaabe8867138eb7ce2752a4a9d0a9c34cb209159d74aff7`. Both containers passed health checks. Existing APP, UI, PostgreSQL, Redis and DocReader were reused; no migration was needed. Deployment receipt: `/private/tmp/g3-platform-independent-deploy-20260913/harness-null-collections-upgrade-receipt.json`. Freeze passed at `2026-09-14T14:50:42.186065Z` with 31 existing originals and six terminal prior runs. Three new SHA/MD5 values were absent from the live inventory.

Webpage upload selected all three originals for **平安盛世金越养老年金保险（分红型）** in one batch. Platform-created run: `f0776a58-90a8-419c-ae0a-7e6d3c478996`. Last-upload HTTP 200 finished at `2026-09-14T14:57:01.529Z`. The platform reached FAILED at `2026-09-14T14:59:24.060036Z`: **142.531 seconds to a failed terminal**, not time to searchable publication. No code, configuration, container, model request, task continuation or publication was manually supplied after upload.

| Material | PDF text parsing | Vectorization | Summary | Result |
|---|---:|---:|---:|---|
| 产品说明书 | 11.680 s | 4.501 s | 11.045 s | completed |
| 保险条款 | 11.531 s | 4.714 s | 11.364 s | completed |
| 费率表 | 90.447 s | 25.388 s | not run | embedding failed |

All three first-parse results were saved. The rate table failed with **HTTP 429 `insufficient_quota`** from `qwen3.7-text-embedding`. There were 109 actual provider dispatches: 107 Qwen embedding and two Gemini summaries; 92 HTTP 200 and 17 HTTP 429. The rate table alone made 100 dispatches for 35 distinct request hashes. Inspection found `batchEmbedWithBackoff` replaying the entire list up to five times. All transport/worker retry indexes were zero, which does **not** prove absence of this outer replay. This is a platform defect requiring Task3ad; replenishing quota alone does not correct it.

All returned parsing spans have terminal statuses. The two completed materials remain in platform storage. Original file hashes, first-parse persistence markers, model dispatch identities and request digests, provider outcomes and phase timestamps are preserved. Field extraction/validation/compilation/review/publication never started, so field missing/failure counts are **NOT RUN**, not zero-quality-failures. Active release remains `release-2f46c14c-5f6f-46cb-8eb2-e6afc7e5933e`, epoch 9.

Additional observed gaps: the product summary reports `model_call_count=0`, `model_call_count_complete=false` because the source stage failed before aggregating source receipts; the actual 109 calls above are from persisted per-file span records. At the current viewport, history pushes the upload toolbar out of pointer reach; keyboard activation of the existing upload menu worked. General recovery from a failed field_plan stage remains unavailable. These are not closed by container health or fixture tests.

Evidence directory: `/private/tmp/g3-platform-independent-deploy-20260913/`; `platform-fresh-fourth-result.json`, `fourth-upload-http-receipt.json`, `fourth-model-call-receipts.json`, `fourth-source-processing-summary.json`, three `fourth-spans-*.private.json`, inventory and before/after Head receipts. **BUSINESS acceptance BLOCKED; G3 is not complete.** No 5–10 minute success claim is supported.

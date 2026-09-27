# A1 最小兼容决策（2026-09-27）

这份记录补全执行初期漏写的接缝决策；no-commit合并已发生，不能追记成此前完成。此前只发生本地冲突处理及模型RED/GREEN，无提交/部署/数据库/模型外发。后续按本冻结范围继续。

## 模型与凭据

沿原models行ID与parameters持久化格式；不批量重写凭据，不变更Harness独立模型配置及secret引用。上游runtime.Resolve接受既有provider/base_url/extra_config（包括remote_model_name与thinking_control），Connection接收原service解密后的APIKey/AppID/AppSecret与CustomHeaders，Spec override为新增可选字段。复用上游legacy_rows_test、wire tests及项目credential/redaction检查；运行前对已配置模型解析后的endpoint/protocol/name做脱敏差异核对，差异不静默接受。

唯一重试Owner为发起工作流。受治理解析上下文由KnowledgeModelDispatchJournal.Bind设置WithModelAutomaticRetryDisabled；原生StageCall预算仍归现有阶段Owner，api.Endpoint只执行发送与reserve/mark/record，不决定业务重放。embedding/api.withRetry必须尊重禁用；OpenAI multimodal fallback也必须尊重禁用及journal失败。每次实际发送绑定准确body digest/model/purpose/attempt；reserve/mark失败零发送，已发送未知不重试。普通未治理调用沿原生显式policy。首切片含非流式chat/embedding及共用transport；streaming沿同一transport且禁止绕过记账，完整业务stream验收不据fixture宣称完成。

已验证RED：api/model_dispatch_test.go的旧新接口缺少journal时，success/http/transport无记录，reserve/mark仍发送；禁用重试仍2次发送。终端保留 /private/tmp/upg-model-red.log，复制至升级证据。GREEN仅该focused测试，不是全模型/业务通过。

## 数据库与恢复

官方与enterprise独立ledger，已知基线official75 / enterprise5，上游目标official110；没有数字冲突。冻结head和bridge classifier必须共同升级，既有75/e5须被准许前进至110/e5，dirty、未知来源或未来head继续拒绝。仅迁移脚本编号更新不能实现升级。

上游077删除wiki_log_entries及log页，是不可逆数据丢失。当前方案保留旧表/页作为冻结历史，采用上游audit activity新读取入口，不恢复整套旧log写入服务；up/down不得删除历史。如新页面逻辑无法与保留旧页共存，先以测试定位并在现有接缝修复，不直接删数据。

应用回滚与DB恢复分离：旧镜像拒绝高于75的官方head，禁止仅切旧镜像。真实迁移前冻结当前容器/镜像/config、两个ledger和备份，验证恢复到旧头后再由旧镜像只读核对Release/来源。pg_search与物理DB恢复检查仍待migration审查完成，不提前运行数据库迁移；不另建长期服务。

## 历史来源、Evidence及页面

KEEP knowledge_revision_source 的固定对象/存储后端/parse attempt，g3-platform-source-snapshot.830.v1与签名域均不变。旧解析成功结果不因实现版本变化失效；PDF/native digest、Unicode codepoint定位及原件引用不重新生成。读兼容采用既有C5/C6持久fixture、TestReadFixedRevisionSourceReturnsOnlyExactPinnedObject、TestRevisionSourceUsesStoredBackendForBackfillAndFixedRead、TestSchemaWikiCitationRevisionAdapterReopensPersistedUnicodeCodePointOffsetsForFrozenC5及G3PlatformSourceSnapshot测试。来源撤回/当前ACL读取即时检查，读取不触发解析或provider。

冲突中的delete/reparse/move必须将现有pinned-source门禁放在新平台mutation前；parse完成与revision commit原子绑定不能被上游无revision的完成路径替代。普通非托管KB保留新原生流程，托管Wiki依赖持久Release约束而非Harness在线状态。

## 当前切片与门禁

当前只实现UPG-01/04/05/07/09相关升级兼容；UPG-02/03/06/08的最终门禁仍NOT RUN，不得由A0已完成推导。既有合同保持的要求用现有回归保护，不伪造旧实现必失败；新增缺口必须先保存真实RED。迁移A1最后以审查pg_search结论补齐，迁移代码须有最小测试RED。

| ID | 当前失败/保留检查 | implementation / Owner | 最终验证 |
|---|---|---|---|
| UPG-01 | upstream ancestry exit1；38 conflicts | 固定上游diff / root | ancestry、source/image/config分层身份 |
| UPG-02 | 旧/新同版REST fixture尚未对照，NOT RUN | harness现有PlatformClient / root后续切片 | 同一Harness构建双fixture |
| UPG-03 | 代表Schema替换未验，NOT RUN | 现有Harness catalog/admission / 后续 | 仅Harness变化的闭环/构建影响 |
| UPG-04 | 既有固定来源/Release回归；冲突会丢revision门禁 | knowledge revision/citation/g3 source adapter / root | 既有fixture + 真实旧内容/新tracer/source click |
| UPG-05 | 发送无journal、disabled仍2次；新tests已RED | models/api + runtime/connection + service既有Owner / root | API失败矩阵、旧持久恢复、唯一预算 |
| UPG-06 | 既有offline/ACL/managed-write回归保留，NOT RUN | config/router/release guard / root后续 | 普通/托管/offline/撤回负向矩阵 |
| UPG-07 | head75 vs新110；75/e5被新guard拒绝；077破坏历史 | database/adoption/migration / migration lane待明确授权 | upgrade/classifier/数据恢复，应用回滚分报 |
| UPG-08 | 新Docker依赖与旧component影响合同未核对 | 构建冲突路径 / root后续 | 逐组件input identity、实际cold/warm成本 |
| UPG-09 | 旧chat/embedding已被上游删除但产品journal留在旧模块 | 模型api迁移及核心冲突补丁 / root | 删除旧实现、保留理由/测试/Owner清单 |

### A1 迁移独审补充与执行冻结

独审确认无需引入新ledger：显式接受已发布75/e5 checkpoint→官方110/e5；不能接受任意未知中间版本。077保留wiki_log_entries，不再双写；旧log page正文/identity保留但转archived并设置deleted_at软删除（普通List默认不按status过滤，单独archived不足以隔离），防止上游取消log过滤后重新进入普通读取。原status恢复依赖升级前一致备份，不把down称为无损恢复。

pg_search迁移099会在条件不满足时NOTICE并跳过，因此ledger110不能证明索引扩展升级。复用现有migration safety入口，embedding未禁用时做版本可用性preflight及0.22.6 postcondition；skip_embedding保持原明确模式。实际备份/恢复包括旧ParadeDB v0.22.2-pg17、旧app、两个ledger、data-files/对象及外部retriever身份，未演练仍NOT RUN。

A1三项决策至此冻结；B1继续本地实现，实际迁移/部署不因此授权启动。迁移lane独占current-slice-paths.json所列路径，先RED后实现；root保持唯一集成。 frontend lane独占frontend/**，只做升级已有界面的适配/必要验证，无Docker/部署/provider。

B1构建只读复核发现 AnyDoc tagged Go/Rust 与 license 来源未进BA0 identity、依赖下载未完全固定，现进入 UPG-08 已授权适配范围。构建写域与唯一Owner在current-slice-paths.json冻结；先以本地fixture验证identity/依赖闭包，再合并实现，不提前消耗镜像构建预算。迁移lane新增两个独立职责文件的精确路径已补入清单；发现时已有本地未提交文件，不追溯声称此前已列明。

B1预审修订：RAW-only Agent目标不能依赖同时选择Wiki才能识别托管，现有ConceptAgentService将按每个server-resolved tenant/KB检查唯一Release custody，返回受保护原始库；插件关闭或Head缺失仍拒绝原始检索回落，普通KB保持原生工具。内部scope改为知识库范围，不新增公共REST/第二Head。另三个原生chat协议的多模态fallback也必须消费同一no-retry/journal门禁并递增attempt。两个问题先RED；root修Agent，frontend_upgrade转为仅model_fallback_exclusive_lane写者，最终由不同xhigh reviewer复核。先前model-agent-review-identity仅记录修复前审查，不继续当最终identity。

B1构建资产裁决：upstream d5cb84258明确删除host preloaded skills并统一租户sandbox镜像skill来源（internal/agent/skills/source.go、tenant_source.go）。当前产品无自定义预置skill合同，skills/preloaded采用SUPERSEDE，不恢复被替代内部路径；BA0 manifest/runtime保护和exact-image smoke删除该过时输入，新增license/BrowserSkill等实际runtime输入。旧runtime recipe仍因不同而拒绝复用。start_exact_image.py与runtime-reuse tests已加入build专属写域。

C1/C2 bounded范围已推进到UPG-02/03/06：同一Harness消费与基线逐字相同的Go签名来源/发现fixture；新Go端重新生成后由既有cross-language test对比。Schema修改和准入提示策略切换只调用现有Harness编译/策略模块，用本地临时workbook与源码摘要验证Go未变；这不授权更改正式Schema或新的provider执行。

C2前端复核发现上传入口与API helper连续查询两次capability；若true→false，null回执被忽略，用户文件无提示丢失。root接管已停止frontend lane的有限两文件修复：入口仅调用既有helper的一次capability+整批上传，只有明确null进入原生确认框，未知/失败仍不fallback；先保存真实RED再修复。

C2迁移独审修正：75→110固定packaged链的clean中间checkpoint是合法中断恢复点，不视为未知版本；dirty/未来版本/来源指纹仍拒绝。skip_embedding精确false的模式转换在既有advisory lock内幂等补齐目标扩展及现有enterprise003 embeddings合同，旧账本不force/重置，失败停止。原099保持不变，真实迁移与恢复未执行。

C2构建独审修正：AnyDoc MIT文本进现有license bundle及烟测，BrowserSkill zip在同一exact-image smoke中校验CRC、manifest版本及引用worker/popup文件；本地AnyDoc入口读取同固定dependency lock。无新制品权威，无镜像build或部署。

C2核心独审识别两个基线已存在、但当前托管来源路径可达的并发缺口，仍阻断UPG-04/06/05的交付：pin预查与实际mutation分离，旧worker失败后的按knowledge整体清理可伤及新attempt。本轮在原有knowledge/revision职责内收敛：mutation与pin检查同一row-lock事务；worker失败写入/清理必须服从当前attempt及其自身资源身份。先RED，不新增表/ledger/队列/通用锁平台；发现必须扩大持久协议的设计分歧先回报。普通KB子任务重复finalizer是继承问题，当前G3关闭summary/qgen/graph/wiki而走direct commit，不进入本轮修复，作为显式BACKLOG保留，不声称普通KB的at-least-once完成语义已解决。

C2模型独审静态确认四协议/redirect门禁正确，root随后接管既有两测试文件补307/308表驱动及OpenAI completions chat/stream覆盖；属于原行为验证，无生产修改，不伪造旧实现RED。

C2来源并发扩域经实际调用链确认：native reparse可以在processing/finalizing推进attempt，单纯service预查不能阻止旧worker在新attempt清理后插入旧chunks。允许现有ChunkRepository增加原子CreateChunksAtRevision接口：同knowledge row锁内校验tenant/KB/attempt/SHA并插入本批chunks，复用现有插入内核，不新增持久协议。对应interface/repository/test写域已先冻结，再RED→实现；所有受此方法影响的mock按真实调用更新，无静默fallback。

C2并发清理实现新增同职责service/knowledge_*upgrade.go，并在knowledge.go的isKnowledgeSourceReplaced加入KB/attempt/SHA检查（同文件路径重新解析仍须识别代际变化）。root发现文件后补记Owner清单，不追溯声称此前已列明；这仍是旧attempt不能影响新attempt的同一不变量，不新增公共协议。

D2准备只读复核确认DocReader浮动Python tag无法形成稳定base输入。root在原Dockerfile两处FROM固定经官方registry核验的同一个多架构index digest，并记录arm64子manifest；保留原跨平台能力，不新增base build-arg或构建框架。先记录未固定输入RED，独审此单文件修订后才构建。

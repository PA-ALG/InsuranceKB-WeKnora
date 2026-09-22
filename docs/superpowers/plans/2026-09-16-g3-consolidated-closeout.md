# G3 集中收尾修复与重验 Implementation Plan

> **For agentic workers:** 使用 superpowers:executing-plans / test-driven-development。Owner=root；三个显式独立写域，跨域连接由root集成。各项先RED后实现，全批GREEN和独立复核后只统一部署一次受影响组件。

**Goal:** 修复用户已确认的六项遗留，再验证正常网页上传、增量复用、技术失败恢复至发布和证据回查。
**Architecture:** 沿用WeKnora上传/解析/来源/唯一Release及Harness持久任务、检查点和字段缓存。以已有已发布结果和来源绑定实现增量；无新服务/数据库/审批平台，未确定结果的外部发送不盲重试。
**Tech Stack:** Go/Gin/GORM/Asynq、Python/SQLAlchemy/P1 JobStore、Vue、现有PostgreSQL和Colima。

用户2026-09-16已确认六项集中修复和重验；沿用OpenSpec129 G3-AUTO-1—6。原设计docs/superpowers/specs/2026-09-13-g3-platform-independent-design.md与工程基线适用。3186实测task3bl报告是失败/耗时依据。普通字段缺失及业务质量后置，不能增加补抽门槛。

## 方案与复用边界

复用现有能力，排除另建编排框架、删除来源校验或把历史脚本接入正式流程。
- 技术恢复依据持久job/call终态、响应确定性和依赖；公开按钮仍创建独立child。未知发送不重发，已确定供应商拒绝的显式恢复与自动重试分开。
- 上传前按SHA256/size去重并保存小型manifest；沿现有metadata快路径，缺关联时通过服务认证exact-scope指纹查询恢复，成功后调用既有attach_original/seal。manifest放既有artifact/control记录，不另建关系平台；不得改写旧Knowledge元数据。
- 原生失败文件恢复复用ReparseKnowledge的公共内部逻辑；按expected attempt/绑定/恢复key原子分配，队列结果未知先查回执，成功兄弟不重做。具体边界沿用Task3bk已复核方案/private/tmp/g3-task3bk-reparse-design-review.md。
- 增量校验复用现有loadPublishedLegacyBase830G3提供的可信已发布投影，对完全相同的成员/产品身份与来源块复用已验证证明，当前知识/修订/资源绑定及撤销仍检查。新增或变更证据走原完整校验；缓存缺失回落完整路径。避免依赖缓存命中才能正确处理。
- discovery沿现有span/window/adapter做真实序列化字节预算分窗，模型只收必需语义和短引用；完整审计留服务端。每窗持久raw、稳定operation key；最终独立review绑定最终输出，不拼造审核。
- 终态以现有finalization为唯一读权威，不为同步内部基表增加JobStore写协议。公开状态统一聚合；完整阶段wall时间包含排队/等待/重试，与最后attempt耗时区分。
- 首读只按证据优化：后台已定位来源index缓存抖动和重复首产物验证；前端已是按指定PDF页渲染，尚无证据要求重写前端。

## Owner matrix

A / g3_recovery_analysis：Python checkpoint_store.py/checkpoints.py/checkpoint_artifacts.py/recovery.py/model_execution.py/artifact_models.py/artifacts.py/store.py/models.py/stages.py/api.py、platform_client.py、composition.py 及对应既有tests；必要窄failure/source_recovery辅助模块。只在stage source职责内修改，uploads职责留给root合并。不改P1协议或新增表。upload manifest的create_run/HTTP接线由root在A提交后集成。
B / g3_upload_analysis：Go internal/handler/product_ingestion.go、product_ingestion_bridge.go、g3_platform_machine_access.go与其handler/router、knowledge_create/process/repository知识恢复的窄方法、interfaces/types及对应tests；只负责上传复用和原生失败重解析。Python只提供独立upload_manifest.py模块及测试/接线补丁给root，不与A同时改公共文件。不碰来源权威/发布校验文件。
C / g3_discovery_analysis：Python knowledge_compiler/g3_discovery_routing.py、product_ingestion/discovery.py/discovery_stage.py及对应tests；需要pipeline/compilation连接时先报告root后单写。不碰A域或调用真实模型。
root：Go concept_source_authority/reuse/g3_published_*相关来源/候选复用与tests；Python upload连接及跨组件集成；文档、部署、实际网页验收。前端仅有明确接口/读取瓶颈时改现有组件，先回归测试。
Review：独立只读冻结diff，不修改实现。

## Task 1：恢复和状态（A）
- [ ] RED：已记录供应商HTTP拒绝有显式恢复入口、未知dispatch不重发、scope/hash/旧generation篡改拒绝、重复按钮幂等。
- [ ] 实现结构化失败判定和已有检查点引用，不增加人类错误文字前缀白名单；v1–v3原字节兼容，必要新合同显式版本化。
- [ ] RED→GREEN：2成功+1失败来源，只对失败项调用窄恢复口；成功来源复用，提交未知/截止时间明确终态。
- [ ] RED→GREEN：来源失败仍保留兄弟调用数，公开终态一致；阶段wall覆盖重试、最后attempt另记；8+1+10=19且未知不当零。
- [ ] 运行对应product_ingestion测试、ruff。不触发provider。

## Task 2：重复上传与原生恢复（B；root集成Python）
- [ ] RED：已有文件跨批复用、同批重复去重后expected_count正确、旧metadata不变、跨tenant/KB拒绝、SHA/size/type不符拒绝。
- [ ] 持久manifest先于原件写；新文件metadata lookup优先，无关联按原manifest指纹恢复；attach/material关系仍由Harness拥有。
- [ ] RED：expected代次并发只分配一次；分配/入队崩溃或响应丢失不重复分配/盲enqueue；迟到旧代次不可覆盖；enqueue明确错误不报成功。
- [ ] 共享原生解析逻辑完成有界恢复，保留旧审计；新接口强制现有editor/source scope，不放宽ACL。
- [ ] 运行定向Go测试及root跨语言上传/恢复合同测试。

## Task 3：真正增量与首读性能（root）
- [ ] RED：可信已发布完全相同成员+来源不再打开历史大index/首产物；新字段/不同来源/撤销/篡改仍完整校验或拒绝。
- [ ] 复用既有签名published projection和当前绑定检查，按不可变身份比较；旧release缺投影保留原完整路径。
- [ ] RED：超过16来源缓存不全部清空；有界逐出及operation证明正确，跨请求当前绑定/签名仍检查。
- [ ] 用保存候选/来源离线测量输入与重复校验次数，不增加模型调用；确认不是放大timeout掩盖问题。
- [ ] 运行service/types定向回归、go vet。对当前真实候选做跨阶段离线回归及代表性任务心跳验证。

## Task 4：自由发现预算和恢复（C）
- [ ] RED：本轮已保存输入原实现超预算；多材料完整span分窗不按Schema筛掉后段，所有请求低于实际context/transport预算。
- [ ] 精简模型projection，完整来源、哈希、定位、覆盖留server；原文不改写。每窗原响应/失败独立保存，普通失败不阻断已验证字段发布。
- [ ] 先多窗生成再确定性去重/校验；独立review绑定最终composed_output hash。若审查也需分窗，覆盖和聚合必须有明确合法证明，不能复用错误局部hash。
- [ ] RED：已记录窗口重投影零外发；调用前失败可重新规划；未知发送拒绝重发；最终review缺覆盖不发布自由知识。
- [ ] 对discovery既有tests与编译连接回归、ruff。

## Task 5：全批集成与一次部署
- [ ] 每项记录RED/GREEN、实现路径、测试、未测限制；统一源码diff冻结、独立复核，修复审查发现后一次冻结。
- [ ] 只构建受影响APP/Harness/UI（有改才构建），DocReader/数据库复用；不清缓存或启动第二环境。
- [ ] 先烟测服务、权限、source/release协议，再开始测量。上传或恢复不构建。

## Task 6：真实网页验收
- [ ] 全新产品三份原材料网页上传；平台分类、模型抽取、编译、自动审核、发布、检索、字段页和原文定位；期间不改代码/手工接续。
- [ ] 重复上传/追加材料：确认原解析/有效字段复用、只必要调用和变更；历史发布不损坏。
- [ ] 对保留的真实技术失败从网页恢复；故障注入仅用隔离服务已有测试口/可控替身离线做，不随意停共享DB。公开恢复结果实际调用/复用分别记账。
- [ ] 记录总耗时、阶段wall/attempt、真实调用及费用可用项、字段三态、51类定位检查；关闭观察一段时间后确认任务自主推进。
- [ ] 未通过项明确BLOCKED；所有六项及三类验收闭合才标当前G3完成，不包含业务质量、1000文件/生产长稳。

## 实施期边界核对（2026-09-16）

- root 已只读保存3186任务的真实candidate/compile_request/compile_delta及前一发布候选到本机临时目录，供离线回归，不作为平台运行输入。新候选732字段，657历史字段逐项完全相同。
- 已发布父候选的 corpus 仅包含它当批3份材料，历史来源仍在签名 BaseRequest.Sources。复用须同时比较完整成员/绑定与源块，并重查当前知识、revision、source、resource；无 corpus receipt 的历史源额外重算 source ID（绑定resource ID、file hash、size、MIME）并比较已发布 evidence.RevisionID，不能因不在当批corpus就重放所有祖先。存在注册receipt的条目继续逐项比较receipt。
- 来源缓存RED：装满16项后加入第17项，旧实现只剩1项；改为有界LRU淘汰1项。来源签名、当前绑定及跨请求重新核验边界保留。
- Go独立写域测试编译期间因另一个lane尚在RED而暂未闭合的编译状态不记功能RED；待全批代码冻结后集中GREEN。

## 用户追加：独立自由发现与 Schema 排除（2026-09-16，替换 Task4 混合输入方案）

用户明确要求：自由发现与Schema抽取分成两个阶段，发现有价值信息、实体、概念及关联；Schema已包含的字段及对应概念不再生成自由发现页面。

- 独立持久discovery stage只从解析原文、实体身份和紧凑排除索引生成候选；排除索引为Schema字段名称/别名/概念ID及已有概念标识，不携带字段值或整批field_delta。
- Schema synthesis只产字段delta和字段校验；discovery单独保存窗口raw、coverage、候选、去重处置、调用与终态，可独立恢复。无Schema的未来调用方可直接消费发现输入接口，不需伪造必填字段。
- 最终compilation汇合两个结果；自由候选的独立复核仅接收候选、原文、排除索引和服务器计算的最终composed output hash。审核绑定最终输出，不把局部review改hash伪装成全局review。自由组审核通过才发布其exact最终输出；拒绝/待审/失败时全组自由候选剔除，字段only候选按既有规则校验。不得审核后部分过滤再改hash，也不为本轮普通发现问题反复补审，普通字段结果不受影响。
- Schema包含字段（含unknown/抽取失败）均不能通过free页面重复生成；模型收到排除规则，服务端按canonical identity/alias再执行准入，语义不确定项待审。关系允许引用已有字段/概念页面，不复制已有正文。
- 当前复用既有实体/概念身份和页面链接；“包含/适用/依赖”等独立关系记录及专门UI是否纳入本轮已询问用户，未确认前不扩大此数据合同。
- root独占pipeline/checkpoints/models/store/progression/composition工作流v3接线，沿现有持久任务和串行阶段推进，不另造队列/框架；v1/v2已有run使用兼容wrapper与原检查点，不能改写历史记录。
- 参考：本仓库wiki_ingest.go/wiki_ingest_batch.go的分段、短引用与按需已有知识读取，以及nashsu/llm_wiki的analysis→generation、SHA增量缓存和来源链接；不复用绕过唯一Release的直接写Wiki方式。

### 本轮接线分工与审核实现补充

- A追加拥有models/store/checkpoints/checkpoint_store/checkpoint_artifacts/progression的workflow3与checkpoint v5接线；root保留pipeline/composition/API/来源manifest集成。旧workflow1/2与checkpoint1–4不重写。
- root为前端已有任务列表增加discovery阶段中文名，不新增页面或状态平台。
- 最终审核复用现有bundle合同：真实自由发现LLM的context/response/proof单独持久化；显式组合审核adapter消费字段规则结果、精确最终输出和free整组审核证明，生成自己的ReviewResult（implementation=platform-combined-field-discovery-review.830.g3.v1）。其完整semantic context哈希描述组合程序的输入，不冒充LLM完整上下文；raw是组合程序输出，原模型响应保持独立。

## Task3bn：真实网页复测后的集中修复（2026-09-17）

基线源码63ac9e460，正常全新2648-1已发布且网页字段原文第12页可见；增量ab0b7d18因生产_ScopedPlatform缺SHA查询代理阻塞，1835恢复051f9096供应商已恢复但身份合并待诊断。新发现原响应为标准单json代码块，严格边界兼容不足；独立发现恢复入口仍缺。全部保留现场，不在运行中修改结果。

本切片唯一写域（覆盖上方同路径旧派工）：
- A/g3_recovery_analysis：任务列表与轮询轻量化，product_ingestion/api.py、store.py、frontend/src/components/knowledge-base/product-ingestion-status.vue及其API类型和测试；先核对现有Go转发能力，避免为查询参数新建接口。其他root所需API恢复接线等A交回后再修改。
- C/g3_discovery_analysis：先只读1835身份根因；随后单独派发语义JSON共用边界、discovery_stage统计、discovery_composition及对应测试；不写API/store/checkpoint。
- root：生产composition SHA代理及实际接线测试、独立发现恢复/checkpoint与集成（API/store等A交回后才写）；身份修复在根因明确后另指定独占写域。文档、复测、冻结及部署仍root。
- reviewer：仅冻结身份只读复核，不顺手改生产。
- B/g3_admission_finish：独占 knowledge_compiler/g3_evidence_identity_v2.py、g3_evidence_identity_v3.py及新增窄证据身份helper/对应测试；仅在既有来源证据支持的公司正式名/简称等价时归并，不使用品牌子串或样本硬编码。不改root的pipeline/checkpoint或A的API/store。

RED必须来自本轮真实响应/实际组合入口/数据库任务状态，不把缺依赖当RED；先复用已记录响应离线投影，再必要真实调用。Go发布性能另记录为当前优化问题，优先移除并发完整状态审计的放大器，未有证据前不再启动一次Go重编译。

### Task3bn 恢复实现边界（2026-09-18）

A交回轻量列表后接 checkpoint v6/rebase：独占checkpoints.py/checkpoint_store.py/checkpoint_artifacts.py、pipeline.py、新增窄rebase模块与API恢复提示/相关测试。root不并发改这些文件；root仅前端恢复按钮、上传边界、文档/部署。复用现有retry-processing入口，已发布partial_success且discovery技术失败时该明确动作只恢复discovery，不要求新增Go端点。v1—v5字节合同保持不变。

v6保留旧plan/来源/字段证据，worker核验后基于当前已签发布快照重算resolution/request。当前Head变化只使受影响的运行产物失效，不重发完成模型调用。先对旧完整字段集合应用原validation报告，再按新request所需task SHA选择可复用结果；carry的已发布字段不重复投影，必要task缺失或来源/Schema变化则明确阻断，不自动补抽。新的base/request/delta以独立rebase产物同checkpoint fence持久化；旧candidate/delta及其proof不改写。只有已验v6receipt可激活新运行输入，后续Head再变化由已有CAS拒绝。discovery先核原全部未决call，再匹配窗口上下文；未知发送不能通过新base/input SHA避开检查。独立只读设计依据/private/tmp/g3-task3bn-checkpoint-rebase-design-review.md。

发现generation技术FAILED从discovery恢复；generation已成功但独立final review技术FAILED则从compilation恢复并保留发现候选。可信汇总/原调用/fence决定阶段，不用错误文本前缀猜测；PENDING/REJECTED仍需既有审查决定，不当成可自动补审的技术失败。

2026-09-19集成反例：recorded父响应的内容仍畸形时，不能无限回放导致显式恢复永远失败。C独占discovery_stage.py及对应tests，在真实child恢复中先按当前相同解码/投影规则检查父raw；合法（含本轮围栏兼容后可读者）继续复用，仍不合法才为这个失败单元发一次新的child调用，保留父raw及失败审计。新调用自身失败不在同阶段自动追加；未知发送仍先阻断，合法业务PENDING/REJECTED不因此补审。此项不改变Schema字段抽取与发布权限，不扩大模型重试预算。

v6独立复核两项同一失效边界修正：Head变化后即使调用原本位于成功prefix，只要其discovery/compilation阶段将重执行，仍须核对全部原及继承调用的已记录结局，未知外发不能随prefix截断被绕过。原自由组合法PENDING/REJECTED须保留不发布的业务处置及证据；恢复后续字段发布不能重新生成或补审自由组，不能把旧review改成新输出的审批。沿现有receipt/产物adapter实现字段only恢复，无新表或服务，Owner A；两个真实worker反例先RED再集中修复复审。

B2实现绑定：完整验证原prefix及原compilation的discovery_final_summary后，PENDING/REJECTED且Head变化时在现有checkpoint输出中保存rebased_discovery_disposition，引用原summary的artifact id/SHA/状态及当前request SHA。receipt保留discovery处置，compilation先检查经receipt验证的该规则产物，只组新字段候选，不加载或合并旧free候选、不新调最终模型。原非PASS summary/模型review字节和hash保持原审计意义，以来源引用标明保留处置，不能冒充新审批。后续再次rebase须验证并重新绑定该可选处置。B1仅拦将重执行单元的未知外发，不全局否定无需重做的历史未知调用。

1835缺少官方简称映射证据，保留身份待确认，不用产品名/品牌子串推导主体相同，也不在本轮扩大双端身份协议；已证实供应商调用恢复和三阶段复用，未发布。

### 2026-09-22 真实失败边界：先贯穿检查，再集中修复

沿用用户已批准的 G3、OpenSpec129 与现有环境。用户再次要求 tracer bullet / deep modules：本轮不按单个异常部署，不新建服务、数据库或编排平台。

已读真实记录：2be3b35b 恢复在本地 checkpoint 验证失败，原因是 source_processing_attempt 在 source 第3代保存而阶段第4代成功。该审计记录按既有设计应持续保留，却被选择器混入只能来自成功代次的阶段输出。d830d5e2 的本地记录、三份来源签名与解析版本均通过，但旧 workflow2 的 base epoch11 与当前13不同，现有协议不允许重基；盲升为 workflow3 会增加自由发现阶段，不能这样处理。

复用与模块边界：
- 保留现有 JobStore、source 逐次审计写入、checkpoint references、签名来源、纯 rebase_checkpoint_inputs 和发布 CAS。
- CheckpointStore 唯一负责按产物寿命选择可复用输出；处理审计保留原记录且不冒充最终输出，最终输出仍严格核对 fence。root/g3_recovery_contract_audit 独占 checkpoints.py、checkpoint_store.py、新增 audit lifecycle 测试。
- root 将恢复校验从 pipeline 闭包收敛为单一恢复验证入口，封装本地证明、来源、Schema/当前发布依赖与重基；pipeline 只调入口及已有阶段提交机制。失败输出稳定、安全的检查阶段/原因码，不输出原异常正文。唯一写域为新 checkpoint_validation.py、pipeline.py 与诊断测试。
- 旧 workflow2 兼容设计已独立核对：新增最小 v7 恢复 wire，显式 execution_workflow_version=2；v1—v6 字节不变，协议能力 supports_rebase 由 checkpoint 模型集中提供，调用方不继续散布版本字符串判断。新 child 仍执行 workflow2，不增加 discovery。只在实际变 Head 且完成重基 receipt 后，执行视图使用重新验证的 field-only delta，并重新执行 compilation；原自由发现与审批保留历史审计，不能套在新输出上。同 Head 保持原候选/审批复用语义。g3_legacy_rebase_design 等 A 交回写域后负责 checkpoint 模型/存储/产物、验证入口中的兼容接线与专用测试，root 不并发写。禁止改写旧 DB 记录；不增加表、服务或迁移。

验收 tracer：真实 source 多轮等待 → 已成功来源与审计共存 → 下游失败 → 平台恢复 → 复用字段 → 基于当前发布编译 → 发布 → 字段证据回查。先在真实 repository/worker 测试中复现跨代次与变 Head 两条边，并离线读取实际失败记录检查后续合同；统一验证和独立审查闭合后，只更新受影响制品一次，再进行网页恢复和全新2662-1三文件验收。离线投影不持久化、不代执行业务任务，不算平台通过。

运行证据：真正 worker 的 Gemini 受控探测 HTTP200 / 3.133s / 单次发送，提示仅 Reply only OK，未发送材料。API 容器按既有设计仅内网，其连接错误不构成 worker 网络故障。两个失败记录对 epoch13 的纯重基投影分别成功（74/82字段，7.785/15.219s），未写DB、未生成发布候选。网页当前登录失效；已请用户在可见页面登录，开发与离线验证继续。

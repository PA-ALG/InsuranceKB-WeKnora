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

# 当前状态（2026-09-12 G3 性能与识别修复）

当前分支 codex/830-g3-performance 从已部署 cfe7e040 建立，继续现有 OpenSpec 129 的 G3-P1/P2/P3。用户已授权最小读取修复、具体材料识别修复、小批量中断恢复验证；不新建任务平台，不进入 G4。线上 epoch 6 / 7 产品 / 493 字段保持。P1 实现与独立复核通过，真实候选的验证复用段为 0.17–0.21 秒，尚待部署实测；P2 的 15 份来源重放、18 项 Python 测试与 Go 跨语言/旧版本兼容通过；P3 真实产物回放、临时 JobStore 进程中断恢复及 4 项 reserved/unknown 保护测试通过。PG 并发与真实 provider-inflight unknown 未验证。不得按下面历史段落重建数据库或重跑旧发布脚本。临时资源隔离窗口 04 的 19 个非 G3 容器已经 restore，并核验全部恢复运行。

以下为历史记录。

## 当前执行：G3 已获明确启动授权（2026-09-07）

当前 SOURCE 执行已 STOP：用户“授权”已记录并实际执行一次 v3 apply；先创建 weknora_g3_830 空库，再在 pg_restore 返回 rc=1 时停止。数据库子进程退出与整体子进程重新初始化发生在恢复窗口内，22:02:01 UTC 重新接受连接；具体触发原因尚未确定。旧环境共享该 PostgreSQL，因此不得以来源记录快照相等宣称没有可用性影响。当前源库选定快照与执行前一致；目标 0 用户表/仅 plpgsql。上传、来源补登记、provider、G3 应用启动均 NOT RUN，未重试、未删除现场。公开回执 source-runtime-apply-stop-public-01.json；原授权有效但首次失败即停止的窗口已结束。下一步是 source-runtime-isolated-recovery-proposal-01.md 的独立复核和新增故障隔离范围审批。以下较早状态为历史，不覆盖本段；软件 commit39943a247 保持，G3仍WIP/FLOW NOT RUN/QUALITY DEFERRED_TO_Q0。

当前收口：D backend最终repair2独立PASS（报告5e9c4f0b…，BLOCKER0），B1与B2全部关闭；final freeze2b32e49f…，11文件全部匹配。service完整回归408.944s、最终handler/router2.802s/2.768s及vet通过；原始坏UTF8/Unicode探针独立转绿，G1/G2兼容保留。root service→Gin→冻结UI/Python两状态完整互操作PASS，30项冻结输入身份匹配；根结论见lane-d-root-software-integration.json。全部当前代码写域关闭，剩余后端修复额度0。G3仍WIP、FLOW NOT RUN、QUALITY DEFERRED_TO_Q0；真实SOURCE尚待此前外发批准，后续真实C输入/策略/受控模型窗口及发布验收也未执行。用户“结构确认”和安佑福1828材料已处理，禁止重复询问结构或推定具名信息。

最新：后端repair1完整三包回归PASS（408.944s/3.427s/3.799s），B1实际service→Gin→冻结UI/Python的DRAFT/READY完整5实体342字段互操作PASS、正文不变。repair1独审4b45e09d…确认B2解码后Text和stored-ID检查通过，但发现raw JSON坏UTF8/lone surrogate会被Go decoder先替换后接受；原反例保留。方案5b67f955…独审PASS，最终第2轮dispatch2d7300a9…仅G3 handler+test，既有raw canonical helper丢弃返回值、只验原字段，增加same-wire G2/G3分支回归。原9后端文件和全部UI/Go/Python/C/common冻结，不授权第三轮。G3仍WIP、FLOW NOT RUN，外发原问题待实际回复。

当前软件门禁（2026-09-08）：UI首轮修复已独审PASS并提交b7a26b8aa；后端11文件初次独审收口为2项BLOCKER：read_sha对真实U+2028采用错误转义preimage，及preparation_id未按D Text严验/handler先trim。原11源码、31日志、独立反例及实际service→Gin→冻结UI失败证据均已保全；独审报告lane-d-backend-independent-review-01.json SHA416d80fa…，方案9ff57eb0…独审PASS，首轮修复dispatch0941c4de…仅开放G3 service/schema handler与两份G3测试。Go/Python/C/common/UI/fixtures和另外7后端文件关闭。接下来是修后独审及原前端互操作；真实SOURCE/C/provider/DB/build/deployment仍NOT RUN，原外发问题待实际回复，结构确认已接受。下述较早进度为历史，当前状态以本段和startup.json为准。

唯一 Owner=830-G3总控/root；G3=WIP，FLOW=NOT RUN，QUALITY=DEFERRED_TO_Q0，NOT_FOR_PRODUCTION。已成功 fetch，base/main=075d9c38c01e48abfe7985985dc503099cf9b19a；专用工作树 `.worktrees/830-g3-implementation`，分支 `codex/830-g3-implementation`。

首切片：真实 v5 工作簿已生成 11 pack/profile、801 字段；A/B独立复核BLOCKER0，总控Python17、前端17、Go接口及类型检查通过。用户已回复“结构确认”，exact Catalog确认回执保存；具名信息已非阻断询问。安佑福1828条款/说明书/版本待核费率表已保留。15原始PDF准备：4已有W1 revisions共287 chunks实际读取/hash/前后版本一致；11新PDF native预检输出保存。十一份新材料已离线生成204 embedding inputs及exact Go transport bodies，693129bytes，尚未外发。C历史B2过强问题已回设计，原评审结论撤回记录保留；设计2两文件及集中wire修复冻结，independent56/root A+C73 tests、ruff、strict mypy通过，独立复审BLOCKER0。D候选/页面合同整合复核通过后已进入DTO；actual27多行正文暴露共享canonical拒绝问题，修订7的C/common兼容代码已由root独立核验81项及正文/嵌套身份检查通过；当前来源回执兼容8代码已独立复核通过（C79/common82、root A/C/common99），D已恢复完整342候选DTO/fixture实现：actual旧医疗各含1个与新Profile不同的unknown key；68/344 legacy方案因违反卡精确67要求已撤回，改为只限两条全空unknown的具名lineage对齐设计，恢复每医疗67/整包342，旧release不动；模型delta和机械carry分别保留raw。已确认可复用G2同包新增逻辑实体，无额外主数据人工注册前置；需要真实pack/Profile与待审页面接线。新隔离环境只读核实storage本地/vector随DB、无待处理任务；Redis15已占用改独立队列。4原文件hash已读回，只有3条source custody row，第4缺口保留。11请求guard的持久化失败/并发启动问题已修复，9 tests及独立复审通过，尚未serve。复审临时安装76包后移除新建venv，覆盖日志身份已如实纠正。来源环境脚本两轮集中修复后v3独立复核BLOCKER0/BACKLOG1，第三次实际只读preflight PASS；两次只读预检失败原样保留，没有执行apply。旧01/03/04完整native原字节已无损持久化，02一次独立禁网解析补存成功，全部15capture/hash已核验；02当前source row仍缺。模型/上传/DB写/镜像构建/生产动作均0，G3 FLOW仍NOT RUN。启动记录见 `docs/insurance-kb/evidence/830-g3/startup.json`。以下G2历史状态不覆盖当前G3授权。

最新D独立复审：完整342字段及2,247,500字节容量通过；原11/root110 bounded tests通过，但三个重算hash攻击仍被接受（身份anchors、确认语义、同identity原文替换）。D软件BLOCKED，首轮集中修复已先冻结，Go暂停未GREEN；见lane-d-python-independent-review-01.json及lane-d-python-repair-dispatch-1.json。来源upload v2独立33项/9 probes通过，完整执行预览已发用户，当前授权回复未收到，apply/upload/provider仍0。

D最新：原三项修复经独立24 tests/8 probes/ruff/mypy全部通过，root4补充攻击也通过；新source覆盖不一致保持BLOCKED。已回设计明确selected材料完整blocks+carry及per-owner来源并集，设计2独立0/0后派第二次且最后有界D Python修复。旧代码/fixtures快照保存于d-repair1-snapshots；Go继续冻结，来源外发仍待当前用户回复、无执行。

D当前软件进展：source coverage第二次最终复审PASS（30 tests、ruff/mypy、BLOCKER0/BACKLOG0）；root独立核对actual134字段、27来源精确并集、第二正文块引用及3 raw。最新synthetic完整POST为2,254,490字节，342字段；代码/fixture冻结，见lane-d-source-coverage2-independent-review.json。Go仅两文件恢复严格镜像及跨语言验证，handler/service/UI仍关闭。真实C模型执行路径另有设计缺口，不能自动扩建通用模型平台；来源外发审批仍待用户回复，所有真实效果0。

最新（2026-09-08）：Go完整镜像首次独审2项BLOCKER：strict wire字段出现性/null及3个C source Hash类型漏验；四个C重算反例、354跨语言snapshot和完整types回归独立PASS，原Go/RED快照保留，正在准备一次集中修复。UI本地并行顺序调整独立PASS，原Task4已派mock RED→实现；backend与最终UI接受/commit/整合仍等修复后Go独审PASS。结构确认单列PASS，具名元数据单列待补；来源外发原问题仍待用户回复，所有真实效果0。

最新软件门禁：D Go首轮修复独立PASS（原2BLOCKER关闭、4 C反例/354跨语言snapshot/fulltypes/gofmt通过），source8db0e765…、test72e2c166…，报告lane-d-go-repair1-independent-rereview.json SHA17d1153f…。Python与Go类型镜像写域均关闭。后端Tasks1/2/3现已派出，UI本地实现正在全量检查；两者仍需独审/整合。原外发批准仍未收到，真实SOURCE/C/model/DB/build/deployment/业务效果均0。

UI最新独审：原8文件/17份日志身份全部匹配，独立25项页面测试、46项G2回归、actual两条历史字段对齐通过；唯一BLOCKER是结构化Text/identity误放行内部TAB/LF/CR。完整重哈希反例已复现，报告lane-d-ui-independent-review-01.json SHA c206bffc…。原代码/日志保全，按既有修订7v2只开放API及spec两文件首轮修复，保留正文TAB/LF/CR，六个Vue文件冻结；见lane-d-ui-repair-dispatch-1.json SHA d600c0cc…。PDF worker额外测试为既有依赖路径环境限制，不计PASS或产品失败。后端Tasks1/2/3仍实现中，真实SOURCE/C/provider/DB/build/deployment/业务效果仍0。

UI当前软件门禁：首轮修复独立PASS，原UI-B1关闭（BLOCKER0/BACKLOG0）；source52ec691d…、spec37713e5c…、freeze6cdd98c5…，报告lane-d-ui-repair1-independent-rereview.json SHA3fb2d779…。原完整重哈希反例已拒绝，正常输入接受；独立26项页面及46项G2回归通过，正文TAB/LF/CR保留、LF/CRLF hash不同，FreeWiki投影与冻结Python/Go一致。六个Vue文件逐SHA未变，UI写域关闭。后端Tasks1/2/3仍未完成；尚无真实G3上传/模型/DB/构建/部署/发布效果。

后端Task3范围补齐：真实query入口遗漏已先回设计，v1 bool分类方案因current双读TOCTOU撤回，v3独立PASS（cc80ae37…）后仅追加internal/handler/concept_free_wiki_830_g2.go，backend总写域12路径。Read/Issue原子入口同pin分类与投影/签发前校验，保留G2首值/空值行为，不增加未知query拒绝或新wire。dispatch见lane-d-backend-query-owner-dispatch-1.json；实现/最终回归及独审仍未完成，全部真实效果0。

---

## 当前终态：G2 FLOW PASS（2026-09-07）

G2核心流程已完成，QUALITY=DEFERRED_TO_Q0，NOT_FOR_PRODUCTION；GitHub live=NOT RUN。唯一Owner=root，G2写域在本次证据收尾后关闭；没有启动G3。

当前Active release-9cb493e3-8d27-4a0f-8f29-93e2a078725b / epoch5；两次快照2/2、两个产品134字段、1共享定义4关联、1开放示例，共140成员。定义hash不变；21/21来源发布门通过，4条引用/3PDF服务端与浏览器抽查通过，原DB未变。

真实Agent会话a28701d8-dcd7-47d7-a017-57cbc3648381完成wiki_search→wiki_read_page→“被保险人就是受保险合同保障的人。”，同版/成员/来源均通过，模型实际3/13。原首次fake-DNS失败外发0；一次恢复使用临时单域名公网映射，已恢复原hosts SHA58850f4a…a0f7。旧执行器把工具预告/参数闭合误计重复的失败记录保留，strict sidecar验证原raw PASS，11负例及独立审查通过；没有为此重跑模型。

证据入口：docs/insurance-kb/evidence/830-g2/g2-closeout.json、current-flow-status.json、agent-final-flow-verification.json及OpenSpec128 validation-report。源码99ec069、backend d7c673/app image600a…、UI444a…；本次收尾没有改运行源码。24/24是准入协议回放，不是专家金标；129字段未知及66/81/95原始分保留。

环境限制：窄面板PDF局部裁切为布局backlog；全局代理fake-DNS保持用户原配置，未来Agent使用需正常解析/新的有界验证窗口。本次已验证流程通过不代表未来网络配置持续可用。

### 以下是历史执行阶段；当前结论以上述终态为准

## 最新状态：G2 两次隔离发布及页面/来源验证完成，最后 Agent 待执行

CURRENT=FINAL_AGENT_PLAN_INDEPENDENT_REVIEW；Owner=root；G2=IN_PROGRESS，QUALITY=DEFERRED。
实际第二包 bdc806e2084afde6651e85c83a88e3d5395487398bea9b4b2c509473a663d684 已完成一次 Review（来源复验通过）与一次 Activate。当前 release-9cb493e3-8d27-4a0f-8f29-93e2a078725b / epoch5；2/2计划快照，140成员、A70保持、4关联、4引用、3PDF、原DB未变均实际PASS。
真实浏览器目录两产品、各67字段、1开放知识、4条同版定义链接与理赔PDF第15页canvas/高亮PASS。窄桌面面板部分裁切记录为布局backlog。

最后Agent仍未执行；用户既有批准有效。冻结prepare plan067878b3c9001eb08519361475b437669f7105c7ab2f1109bd853e7e4f9414cc位于/private/tmp/g2-agent-smoke-execution/prepared/run-plan.private.json；g2_bundle_review审实际plan后root执行1turn、max13模型HTTP，无整轮重试。来源编译/审核已用10/10，不再调用。
源码HEAD99ec069冻结；app d7c673/image600a…、UI444a…不变。最新证据：b-source-publication-execution.json、b-local-live-verification.json、b-ui-live-verification.json、g2-final-software-check.json（42 tests PASS/strict spec/diff）。
NEXT=Agent实际search/read/answer与日志计数→更新OpenSpec验证矩阵/独立收尾。无生产/G3/Q0/push/merge。

### 以下为历史阶段记录，当前状态以上述段落为准

## 最新状态：来源修订整包已获用户批准，执行发布

用户当前回复“批准”，对应完整来源修订候选 bdc806e2084afde6651e85c83a88e3d5395487398bea9b4b2c509473a663d684；实际批准 b-source-human-explicit-approval.json SHA a53fb9b93e5d754cd05c6b99c4de0c25bc951d2f5ef70a1b5d0665c11bba83a9。140 成员实际 Draft HTTP201，preparation g2-b-draft-bdc806e2084a。新编译与独立审核已成功，原始95分，global10/10；旧81/A66保留。

CURRENT=SOURCE_B_APPROVED_PUBLICATION_FINAL_REVIEW；NEXT=一次Review来源复验→一次Activate→R5 API/UI/PDF→已授权finalAgent。root新发布runner20a624…76c2，plan c39faa…0eb4。Head最后实测仍R4；B未激活，G2未完成。下文是历史阶段记录，不作为当前阻塞。

## 当前执行：修订包外发已获当前用户明确批准

用户对完整修订材料发送至DeepSeek、编译1次/独立审核1次明确回复“批准”；真实授权见b-source-recovery-explicit-user-authorization.json，SHAe5c8a111…42a3。自动审批已允许同一冻结compile命令启动。
Root执行session67999，run_id g2-b-source-compile-001；新candidate仍未生成。后续只执行预留review1，无重试。旧自动审批拒绝保留为历史，不再是当前阻塞。

## 最新阻塞：自动审批要求当前外发确认

SOURCE_RECOVERY=LOCAL_READY_MODEL_NOT_RUN；两次自动审批均拒绝，没有进程/request/ledger effect；ledger仍8。原始授权历史已恢复，但第二次auto-review明确不接受历史日志/证明作为可信用户批准。禁止换路径执行。
完整实际payload：docs/insurance-kb/evidence/830-g2/b-source-recovery-deepseek-request.json（3996ab…633f）；人读说明b-source-recovery-external-preview.md。待当前用户明确批准向DeepSeek发这份材料，最多compile1/review1。需记录真实回复，不将未来审批预填。
Root新runner76222a…91f5，actualcompile runbook review29d05…56c3；输入review修正版eb66…d7c4；旧8c63错误SHA回执保留且已废弃。新assembler2a0ec…84b8 code review BLOCKER0，尚无新candidate。First oldB Review失败，Head实测R4、oldDraft仍draft且reviewdigest空。已授权finalAgent仍NOT_RUN，必须等BActive。

## 当前状态更新：B 来源编号恢复（2026-09-06）

CURRENT=G2_B_SOURCE_IDENTITY_RECOVERY；Owner=root；HEAD99ec069保持。
B旧候选9edc805e已获用户整包批准，实际Draft201；实际Review503 CONCEPT_SOURCE_AUTHORITY_UNAVAILABLE，Review1/Activate0/provider0。Head实测仍R4 release-0236279f-df73-4433-bebc-cad70f95b989。
根因：terms旧attempt1的两BlockID误配attempt3 revision；原文相同。来源准备少验attempt/deleted/完整manifest。当前目录已从只读DB快照按attempt3重建，另修正辅助产品身份BlockID。旧raw/候选/审批/Draft/失败回执不修改。
恢复OpenSpec128-G2-SOURCE-RECOVERY已先记录，旧checker接受错误输入的RED已复现，新增5项guard检查GREEN。新输入/private/tmp/g2-b-source-recovery-prep；g2_sources复核输入；g2_bundle_review准备独立bounded runner。依据用户合理额度扩展授权，新增compile1/review1，上限全局10/B6，无自动重试。新候选须完整展示并具名整包确认，不冒充旧hash批准。
NEXT=冻结输入及runner review→两次受控模型调用→新候选整包确认→G2发布→真实UI/source验证→已授权Agent。无新Goal/生产/G3/Q0/push/merge。
证据：docs/insurance-kb/evidence/830-g2/b-publication-source-failure.json、b-source-recovery-budget.json、b-source-recovery-authorization.json。

# HANDOFF — Enterprise LLM Wiki

> 当前运行/交接状态的唯一入口。贡献规则只以 [`AGENTS.md`](AGENTS.md) 为准；
> 规格和历史讨论分别留在适用 OpenSpec 与历史合订文档，不在这里重复。

## 1. 当前结论（2026-09-06）

**G2 正在执行，尚未完成；两次计划发布已完成一次。** 用户已明确优先串通真实流程，原始 66 分保留，Q0 质量验收后置。用户已批准首包完整候选发布，并已回复“授权”允许 B 材料交由 DeepSeek 生成/独立审核及最后一轮 Agent 验证；必要合理的 G2 有界额度扩展已预批。无需重复申请这些授权。

首包 `70cb4b6e…363c5` 已正式 Active：`release-0236279f-df73-4433-bebc-cad70f95b989`，epoch 4。70 成员、原 67 字段、1 共享定义、2 关联及源 PDF 字节/身份均 PASS；原数据库 unchanged。目录、固定版本字段跳转、开放知识入口和 PDF 第 1 页定义高亮均完成真实浏览器验证，独立复核 0 阻断。

当前源码 HEAD `99ec069277cf3336962e5fa2ecaafed19e8aad35` 冻结供 B 请求绑定；后端运行源码 `d7c67303916e6f608458de4980cf83d807390022`，app image `sha256:600a5a1cf93f4d2ecbe5466b7733c8d82395cdcad99fb501fb50ddf224220b19`，UI image `sha256:444a3de28ef348317320968a0472d3823fde1598f4519a02c7ee67c6d2c2b158`。隔离 app 18194 / UI 18195、数据库 `weknora_g2_594`。旧失败 Draft、JSONB 失败和静态文件权限失败均保留历史，不代表当前状态。

B 已完成真实生成及独立审核：B001/B002 格式失败保留，B003 完整结构恢复 VALIDATED，review001 实际 PASS、新 free page 81 分。模型已用 B4/4 / 全局8/8，不再调用编译模型。实际候选 `9edc805e52950e5363d0d0c9d84e286015f9d47c8d662e4ee7b0f74f1ed9a5ad`，文件 SHA `a193255504f44fd163df5d96d8dc1d94da9e45e773d25c27d91d2d16e723ef2a`，140 成员；A70 全量保留、B67（2有值/65未知）+1示例、共享定义关联4。独立整包复核 BLOCKER0。

用户已回复“批准第二包并发布到 G2 隔离环境”。真实批准记录 `b-human-explicit-approval.json` SHA `183a49e9af0627d1eee4f7d34c1218ee1bfa970400c25f662dc8d125dc0b97dc`，完整预览 `b-human-review-preview.md` SHA `416db733cec1e15cd17faa314ead4810c94d6fee209c87cd95af409ef375fef1`。不再等待任何第二包批准；最后一轮 Agent 既有批准继续有效。

实际 B Draft HTTP201/140 成员通过，preparation `g2-b-draft-9edc805e5295`，线上 Head 仍 A 第4版。B Review+Activate 私有执行器已准备，最终script `b0e7fb52526975f3ef3d9494d5fbaad0ee2406fc1b16b18145f8f0f346290bc3`，plan `5299d615fa0df94ebbb1bc974d78acc2d6c581db4ae612b7e5f0e931a78de0db`，identity `b64387f07914470f3e0b04a0b56cfac3707a67e10ef6fab28e4b7d383f76cb5d`，待独立review；尚未签名/POST。复用既有两把独立钥匙和相同app/config，不构建/重启。执行后读取实际R5回执，跑root只读 verifier `/private/tmp/g2_verify_b_live.py`，再进行真实浏览器和已授权最终Agent。

CURRENT=B_APPROVED_DRAFT_PUBLICATION_FINAL_REVIEW；NEXT_READY=签名平台审核/来源复验→发布R5→2/2快照/4链接/来源PDF回验→最终Agent。G3/Q0/生产仍不在范围内。

最新事实与证据入口：[当前流程](docs/insurance-kb/evidence/830-g2/current-flow-status.json)、[面向用户进度](docs/insurance-kb/evidence/830-g2/g2-current-status.md)、[首包线上回验](docs/insurance-kb/evidence/830-g2/a-jsonb-local-live-verification.json)、[目录浏览器回验](docs/insurance-kb/evidence/830-g2/directory-ui-browser-verification.json)、[B 首次执行](docs/insurance-kb/evidence/830-g2/b-compile-001-execution.json)、[B 格式纠正预算](docs/insurance-kb/evidence/830-g2/b-format-correction-budget.json)。历史执行事实留在各自冻结回执。

**MVP-815 已完成代码交付与 C7 可见验收。** 正式代码已由
[PR #123](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/123) 以一个
squash commit 合入 `main`：

- MVP code commit（已在 main）：`ef47bee2b93d6a9cb4511133deaef6e700d915ce`；
- tree：`d868e8f2fd51250c71366c8c723f500482e7de44`；
- parent：`dfa87e11d5a434b6823582285c17498e715dd8f1`；
- 工程交接文档：[PR #124](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/124)；
- PR #124 合并后的最终 `origin/main` HEAD：
  `99205db986eae2a9fa4bc956c053b94298d0b114`；
- 交付方式：从当时最新 `origin/main` 重建最终状态，**未合入或整体 squash
  149 条历史迭代提交**；
- 远端门禁：两套 deterministic、两套 PostgreSQL integration、两套
  wheel-smoke 全部通过。

**830 G1 已完成。** PR #126 已合入：

- G1 合并基线 `origin/main`：`0e7a26568`；tree：`b96aa35fd2fe86283757deb258920c489de4b4b6`；
- G1 状态：`PASS / FLOW=PASS / QUALITY=DEFERRED / NOT_ACCEPTED_FOR_PRODUCTION`；
- G1 closeout：[`g1-closeout.json`](docs/insurance-kb/evidence/830-g1/g1-closeout.json)；
- G1 D3 app image：`sha256:37918140b2902918f8e7cbb89008bc47d1480e9e65d2056c54b6b5317a5e6eeb`；
- G1 真实 app build：总墙钟约 `131m07s`，其中 `make build-prod=6557.9s`。

用户已于 2026-09-04 确认在 G1 与 G2 之间先完成一次性 **BA0 本地构建复用工程门**，
并已明确授权 BA0 implementation。BA0 不是产品 Goal，不改变 WeKnora/Harness 架构或
G2 DoD。以下保留 BA0 关闭时的产品状态和构建身份，不代表本次文档修订分支：

```text
CURRENT_AUTHORIZATION=NONE
CURRENT_PRODUCT_GOAL=NONE
CURRENT_ENGINEERING_GATE=BA0_LOCAL_BUILD_REUSE
BA0_KIND=ENGINEERING_GATE_NOT_PRODUCT_GOAL
BA0_STATUS=PASS
G1_STATUS=PASS
G2_STATUS=LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION
ORIGIN_MAIN_BASE=0e7a26568a2164f9501e409f38fee0d4a62539cb
ORIGIN_MAIN_TREE=b96aa35fd2fe86283757deb258920c489de4b4b6
IMPLEMENTATION_BASE=874e50d44aec5941faae045e761280aa69aee1a3
IMPLEMENTATION_BASE_TREE=2ec76af38258a0220d5dc117a9b789890345e7d7
WORKTREE=/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-ba0-implementation
BRANCH=codex/830-ba0-implementation
OWNER=830-BA0总控
CURRENT_RED=NONE
NEXT_PHYSICAL_RESULT=RETURN_TO_USER_FOR_G2_AUTHORIZATION
NEXT_ACTION=RETURN_TO_USER_FOR_G2_AUTHORIZATION
REAL_APP_BUILD_BUDGET=2
REAL_APP_BUILDS_USED=2
REAL_APP_BUILD_BUDGET_REMAINING=0
```

BA0 终态（2026-09-05）：D2 恢复构建与 exact reuse PASS，D3 制品烟测 PASS；
累计真实构建 2/2（原失败1 + 用户新增授权恢复成功1），复用 build=0，D3 build/pull=0。
冻结构建源 `fe9a97d092fbb470985bf32c5c4e5a9e6ec135c9`，完整 identity/image/receipt
见 `docs/insurance-kb/evidence/830-ba0/ba0-closeout.json`；累计授权历史见同目录
`recovery-authorization.md`。本地 Git 已确认 BA0 经 PR #127 合入
`origin/main@a4e6a15c8`；本次文档修订未重跑 HTTP/业务或 GitHub live 验收。


批准设计：[`2026-09-04-830-ba0-local-build-reuse-design.md`](docs/superpowers/specs/2026-09-04-830-ba0-local-build-reuse-design.md)。
可执行计划：[`2026-09-04-830-ba0-local-build-reuse.md`](docs/superpowers/plans/2026-09-04-830-ba0-local-build-reuse.md)。
适用规格：[`127-830-ba0-local-build-reuse`](openspec/changes/127-830-ba0-local-build-reuse/)。
BA0 `PASS` 后必须把授权清零并
`RETURN_TO_USER_FOR_G2_AUTHORIZATION`；不得自动启动 G2。

### 830 有限修订交接（仅文档）

用户已授权把本次确认内容写回现有 830。文档 Owner 为本任务；分支
`codex/830-discussion-amendment`，base 为本地 `origin/main@a4e6a15c8`，worktree 为
`.worktrees/830-discussion-amendment`。写域仅蓝图、28 执行章程、29 Goal Cards、
AGENTS 与本文件；原工作区及 B0/G1/BA0 历史证据保留。

修订项与对应 Goal 见[蓝图 §0.1](jlx_enterprise_llm_wiki_technical_blueprint_830.md#01-2026-09-05-有限修订范围)：
可替换编译/独立审核、原文优先与知识价值、专家修订来源、Schema/缺口增量、实体级
发布隔离、平台流程与 Q0 质量分层。实现仍待各卡开工和验证；本次不改变产品 PASS 状态，
不启动 G2，也不产生 Provider/Docker/部署效果。

D0 已核对 R830-01—06 的蓝图/Goal 卡覆盖、五文件边界、Markdown 本地链接与格式，
以及五份 BA0 状态块与 base 逐字一致；结果为文档检查 PASS。独立复核针对本次冻结
diff，结果随交付报告给出。产品实现、业务质量、HTTP/容器和远端 CI 均不由此推断。

## 2. 用户应体验什么

正式 MVP 入口知识库是 `medical-insurance-mvp`。进入“产品 Schema Wiki”后，
应看到：

- 产品：平安 e 生保（尊享版）医疗保险；
- 徽标：`当前 MVP · 只读`；
- `7 个分类 · 67 个字段`；
- 中文字段名为主标签，英文 `field_id` 仅作次级技术标识；
- 字段值保留 `present / absent_explicitly / unknown` 语义；
- 可从字段打开“原文来源”，切换来源并查看固定页码、框选与引文。

`C6-ISOLATED-R1-ACCEPTANCE-*` 是历史隔离验收库，不是产品入口。页面显示
“产品 Schema Wiki 暂不可用”是 fail-closed 状态，不能据此判断代码版本不存在。
整个页面不可用时先查 entry/serving 映射、唯一 Active Head/release members 和
Wiki + RAW 双 ACL；只有引文正文不可用时再查 native source custody 与
citation-token 运行时签名环。

frozen release scope、named-human decision ring 与 publish-authorization ring 只
属于 Candidate 决策/发布链，Golden evaluator ring 只属于后续 C4；它们都不是 C7
只读体验的前置条件。只读演示不得为了“让页面可用”而打开这些写链路。

端口也不是版本号：

- `8081` 是 C7 期间明确保持不变的旧生产实例；
- `18085`（UI）与 `18094`（隔离后端）是当次 C7 验收环境；
- 正式版本身份由 Git commit/tree、镜像/二进制 SHA、release ID 与 activation
  epoch 共同决定，不能用“打开哪个端口”代替。

## 3. C7 验收事实

C7 使用既有 epoch2 做纯读重开，没有重新审批、签名、发布或推进 Head：

- 验收源码：`9fcf3386833d822a31f2de13fdf76c3eb6b13795`；
- 验收 tree：`7314d1c9bc82dc7efb114affb6f2450d0dbd36ae`；
- 隔离后端二进制 SHA-256：
  `aa069e2566fd0b88fb6280bae8f1759d390fefdcfd32e1820602e0bdaa2ebc34`；
- Active-current 与 explicit-pinned/no-fallback：PASS；
- 7 分类、67 字段：PASS；
- citation preview/content：17/17 PASS；
- canonical lineage：1 个 `text` + 16 个 `parent_text`，唯一 owner 全部 PASS；
- C1 self-hash/native manifest、双 parse 摘要、Unicode code-point offset：PASS；
- 三份 PDF 的页码、bbox、file SHA、quote SHA 与可见高亮：PASS；
- UI 来源切换与三份 PDF 可见验收：PASS；
- 五表终态：preparations/releases/members/heads/receipts =
  `2/2/150/1/2`，验收前后不变；
- 旧 R1、epoch2 release/receipt/Head/75 members、生产 `8081`：不变；
- business DB writes、provider/model、C4、Candidate、release、receipt、Head、
  approval、signature effects：全部为 0；隔离角色密码轮换 1 次，未持久化敏感值。

B0 已把授权范围内的只读副本放入 Evidence Pack。用户冻结输入
`c7-ui-visible-terminal.json` 的 external SHA-256 为
`20575de17ca3a5a98e540848a245ef1af4a27d3e2feca12c7a38424350d45b50`，
canonical self-hash 为
`1d57527fbfa3dbfae9b11d14295a4efde0cc0c379b8d5c506c05ce8a0ea59ff6`。
此前记录的 `0e24db1d6ae4632acb538d03b18d84d2ffd0d41b8c39ef6cb5d251318dfa3396`
对应后续 `c7-ui-cache-corrected-terminal-20260831.json`；两份回执绑定同一 815
commit/tree/backend binary/epoch2 release，但必须分别登记，不能互相替代。

## 4. Chrome 可见验收的正确路径

需要复用用户现有 Chrome 登录态时，使用 Computer Use 直连
`com.google.Chrome`（`node_repl` + `@oai/sky`）。这条路径不依赖 ChatGPT/Codex
浏览器扩展，也不要求切换 Chrome Profile。

必须把两个问题分开：

1. 能否控制 Chrome；
2. WeKnora 站点会话是否仍已登录。

扩展未安装不等于 Chrome 不可控；页面跳到 `/login` 也不等于控制通道故障。
不得把密码、session、token 写入仓库、回执或日志；需要登录时由用户在可见页面
自行完成。

## 5. C4 历史后续边界（不是当前队列）

旧提交 `6d56618d0d9796e10d87f93e6b04188a49da9296` 只作历史参考，**不在
main**。它绑定旧 Candidate、固定 reviewer=`linyao`、固定
attestor=`workspace-owner-houjing`，真实结论是 `QUALITY_FAIL`。

若未来路线重新授权 C4，则必须：

1. 从最新 `origin/main` 新建独立 OpenSpec/Mission；
2. 先冻结业务目标、Metric ID、输入权威、预算、provider/model 边界和人工责任；
3. 使用当前 main 的 canonical Candidate/Evidence/Golden 合同，禁止复制旧哈希、
   旧 reviewer/attestor 或把 `QUALITY_FAIL` 改写成 PASS；
4. provider/model、DB、审批、签名、Candidate/release/Head 等外部动作分别申请并
   记录，默认均为 `NOT RUN`；
5. C4 的失败不能修改当前已验收的 C7 serving release。

历史详细接手卡见
[`docs/insurance-kb/26-mvp-815-engineering-handoff.md`](docs/insurance-kb/26-mvp-815-engineering-handoff.md)。

## 6. 仓库整理状态

已创建完整 Git 引用归档：

- 文件：`../archives/insurancekb-weknora-pre-cleanup-20260831.bundle`；
- mode：`0600`；
- bytes：`147412595`；
- SHA-256：`7d35f64fe2611148ca96760752d6a1c331be8f62433fc07ec274647e66a31725`；
- `git bundle verify`：PASS；486 refs，complete history。

当前主工作区和 4 个历史 worktree 为 dirty，全部保护；任务私有回执、发布证据、
凭据相关目录也不自动删除。clean worktree 的精确处置清单见
[`docs/insurance-kb/27-mvp-815-repository-cleanup.md`](docs/insurance-kb/27-mvp-815-repository-cleanup.md)。

## 7. 绝不再踩的坑

- 端口、知识库名称、容器名称都不是版本身份；必须核对 commit/tree、制品 SHA、
  release/epoch。
- frozen 历史向量与当前工厂输出应分别通过 canonical/typed 校验；不能强迫新
  Candidate 派生哈希等于旧 release，也不能改旧向量“让测试变绿”。
- Python 持久化 quote offset 是 Unicode code-point 域；Go frozen reader 不能按
  UTF-8 byte 下标切中文。
- `parent_text` 必须先完整验真到 canonical native child；overlap 只按唯一连续、
  manifest 顺序和 non-overlap contribution owner 选择，不能“取第一个”。
- task-private replay 缺私有工件时不能向 PostgreSQL lane 泄漏 module-level skip；
  lane 必须 tests > 0、skipped = 0。
- 本地绿不等于 CI 绿；合并前必须等远端真实门禁。
- 不从 dirty 工作区构建正式交付，不整体 merge 历史分支，不在 main 保留推倒重来
  的中间实现。
- 启动 Docker/Colima 可能自动恢复 `8081` 容器；未确认生产影响前不得把“启动
  本地依赖”当作无副作用操作。
- `start_all.sh --no-pull` 当前仍会执行 `compose up --build`，不能当作 D3 复用入口；
  BA0 D3 必须使用 exact image 和 standalone `CONTAINER_ARTIFACT_SMOKE`，且
  `--no-build --pull never`；它不连接业务数据库，也不冒充 G2 的 HTTP 产品验收。
- 不得为测量主动清空 BuildKit/Go cache 或重复冷构建；相同 artifact identity 必须先
  lookup，命中时 Docker build invocation 必须为 0。
- 凭据不得出现在命令行 DSN、traceback、文档或 Git；异常泄漏后先轮换再继续。

## 8. 接手阅读顺序

1. [`AGENTS.md`](AGENTS.md)
2. [830 技术蓝图](jlx_enterprise_llm_wiki_technical_blueprint_830.md)
3. [830 开发执行章程](docs/insurance-kb/28-development-execution-charter-830.md)
4. [830 Goal Cards](docs/insurance-kb/29-goal-cards-830.md)
5. 本文件
6. [BA0 本地构建复用设计](docs/superpowers/specs/2026-09-04-830-ba0-local-build-reuse-design.md)
7. [BA0 实施计划](docs/superpowers/plans/2026-09-04-830-ba0-local-build-reuse.md)
8. [B0 Evidence Pack](docs/insurance-kb/evidence/830-b0/)
9. [MVP-815 工程接手卡](docs/insurance-kb/26-mvp-815-engineering-handoff.md) 与
   [OpenSpec 120](openspec/changes/120-schema-wiki-medical-596-1-mvp/) 只作已冻结历史
   证据；后续 Goal 仍须自己的授权与适用 OpenSpec。

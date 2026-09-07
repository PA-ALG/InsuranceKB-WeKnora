# G3 验证矩阵

G3=WIP，FLOW=NOT RUN，QUALITY=DEFERRED_TO_Q0，NOT_FOR_PRODUCTION。以下为当前切片事实，软件通过不代表真实业务验收完成。

| Requirement | 实现 | 验证/证据 | commit | 状态 |
|---|---|---|---|---|
| G3-R1 软件 | schema_pack_catalog_830_g3.py；真实11包801字段 | catalog-a-independent-review.json；catalog-root-integration-verification.json，17 checks PASS，原值/hash独立复算 | f91fc40；精确文件SHA在证据内 | PASS |
| G3-R2 软件 | G1 Profile复用，可变节点与精确主映射 | 11包节点7/7/7/8/7/8/8/8/7/8/7；整包profile-review.md | f91fc40 | PASS |
| G3-R2 人工结构确认 | 用户已回复“结构确认”，exact Catalog确认有效；不重复询问 | profile-user-confirmation.json | f91fc40 | PASS |
| G3-R2 具名元数据 | 结构确认人的显示姓名、后续人工待办负责人尚未提供 | 已发送非阻断询问；不推断账户名为真实姓名 | 无 | NOT RUN |
| G3-R3 目录软件 | protected Go GET＋Vue通用目录 | 独立复核BLOCKER0；总控Go、17前端checks及类型检查通过 | f91fc40 | PASS |
| G3-R3/R5 批次页面软件 | 严格G3解析、Preparation/Active固定版本展示、Profile及历史字段对齐 | lane-d-ui-repair1-independent-rereview.json；原UI-B1关闭，独立26页面＋46 G2回归PASS，正文逐字保留 | 本次UI集成提交；exact八文件SHA见lane-d-ui-repair1-freeze.json | PASS（本地软件） |
| G3-R3 实际目录/字段/来源 | 目录代码完成，真实多pack链待接 | 本地页面/隔离Release/来源/检索未执行 | 无 | NOT RUN |
| G3-R4 来源准备 | corpus-files-v4.json选15原始PDF；15个实际native输出已保留 | native-capture-inventory-v2.json、existing-native-preservation.json、native-02-supplement-result.json；02 standalone capture PASS，当前source row仍缺；原扫描页失败回执保留，4已有W1 revisions/287 chunks实际重开；native来源custody仍待核验 | f91fc40 | PASS（准备层） |
| G3-R4 批次软件 | C设计2及修订7/8兼容切片通过；新旧来源回执接线闭合 | batch-c-design2-final-verification.json；独立56/root A+C73、ruff/strict mypy PASS；历史原日志保留 | 5efe84b5a；exact source/test SHA见receipt；新多行复现另存 | PASS（软件；真实批次NOT RUN） |
| G3-R4 真实批次 | actual SourceRevision/Policy/Seed/model结果尚未冻结 | provider HTTP=0；source-runtime-isolation-plan.md及11 request guard独立复审完成，未运行 | 无 | NOT RUN |
| G3-R5 完整卡 | 未发布/未质量准入 | 真实批次、字段页、来源与搜索均未执行 | 无 | NOT RUN |

## DELIVERY 六维

| 维度 | 状态 | 证据与边界 |
|---|---|---|
| software | PASS（A/B）；PASS（A/B/C）；PASS（D Python完整候选）；PASS（Go完整镜像）；PASS（UI Task4）；PASS（backend Tasks1/2/3软件） | catalog-root-integration-verification.json；C design2独立复核通过；修订7 C/common独立81项及正文/身份probe PASS；来源回执兼容8独立79/common82与root99 PASS；D Python actual134/342及2,254,490-byte容量独立PASS；Go首轮修复独立PASS，4 C反例/354跨语言snapshot/fulltypes通过；UI首轮修复独立26/46通过；backend两轮修复独立PASS，真实闭环待执行 |
| container health | NOT RUN（G3） | existing G2 docreader进程已只读核实用于解析预检，不是G3应用验收 |
| provider probe | NOT RUN | 产品provider HTTP=0 |
| provisioning | NOT RUN | 新DB/上传/SourceRevision/backfill=0 |
| local live | NOT RUN | G3实际页面/流程尚未观察 |
| GitHub live | NOT RUN | 尚未push/PR/远端CI |

结构确认已接受，不再索要重复批准；具名元数据尚未提供，不由程序代签。所有原始质量分数与失败回执保留。

来源隔离执行准备：v3脚本独立复核 BLOCKER0/BACKLOG1，10项假环境测试通过；第三次本机只读preflight PASS，exact回执 `source-runtime-v3-actual-preflight-03.json`。apply/provider/upload仍NOT RUN，前两次失败回执不覆盖。

C/D真实正文接缝：`cd-multiline-canonical-reproduction.log` 保存actual base27多行值及C多行hash失败。未改写源文本；修订7v2设计与C/common代码复核均PASS，见`cd-multiline-code-independent-review.json`；D完整fixture仍待实现。完整C source receipt还需解决当前W1 source registration与历史C5 admission字段的接缝，不以占位hash补齐（见`c-source-wiring-inventory-01.md`）。

修订7代码已在 `de38eb252979713415d8fa34946084f7f344cbc0` 冻结，root独立81项通过及完整正文/嵌套身份probe通过，精确文件与原始日志见 `cd-multiline-code-independent-review.json`。修订8设计 `0b2e9241…` 经独立复核BLOCKER0，已先冻结OpenSpec和C-only写域后进入实现，当前源码尚未闭合；见 `c-source-registration-design-independent-review.json` 与 `c-source-registration-dispatch.json`。

修订8最终独立BLOCKER0，C79/common82、root A/C/common99通过；代码身份见 `c-source-registration-independent-review.json`。原C写域关闭，D按既有v2合同及修订7/8恢复五文件域，完整342/8MiB与Python-Go一致性仍NOT RUN，不开放handler/service/UI。上传v1独立7类BLOCKER，首轮集中修复中，原stub RED明确仅为脚手架时序证据。

D Python首审BLOCKED（3项）：原11/root110 bounded PASS与完整342/2,247,500-byte容量PASS保留；新增重算hash攻击证明身份anchors、确认语义、同SourceBlock身份内容闭包遗漏。见lane-d-python-independent-review-01.json；首轮修复lane-d-python-repair-1.md先冻结，Go暂停未GREEN，handler/service/UI仍关闭。来源upload v2独立复核BLOCKER0（33 tests/9 probes），执行包复核PASS，用户外发批准待回复；无apply/upload/provider。

D Python repair1原B1/B2/B3独立PASS（24tests/8probes，ruff/mypy），root4额外重哈希攻击PASS。新同域source coverage阻断：身份块外的selected材料字段正文被请求拒绝。已回设计2，明确request精确selected+carry并集与per-owner selected+owncarry+实际关联concept来源；独立设计0/0后派第二次/最后D Python修复，Go继续冻结。旧code/fixture gzip快照和原始失败日志保留；active page envelope复用澄清独立PASS，仅设计，无部署。

D source coverage第二次最终复审PASS：30 tests in97.68s，ruff/strict mypy及独立精确source并集/owner引用探针通过，BLOCKER0/BACKLOG0。source e8e0dbcd…、test86edf3d9…、candidate e7be83db…、POST09b64b3e…（2,254,490bytes），freeze811eb4d0…。root独立actual G2 134字段/27来源/3 raw/canonical/容量核对PASS。报告lane-d-source-coverage2-independent-review.json SHA0b21ea94…；Python两轮修复关闭，Go两文件恢复，handler/service/UI门禁不变；全部fixture为synthetic protocol，真实批次、provider、DB、部署均NOT RUN。

D下游执行计划及待审对齐展示设计完成独立复审（初审2项已修，终审BLOCKER0/BACKLOG0），exact冻结见lane-d-downstream-design-freeze-1.json。已明确Create前source验证、G3-only create-draft operation和授权历史snapshot派生两行展示；不增加DTO或公开KB元数据。Go完整C重算仍有有效RED，当前实现未闭合，下游写域仍关闭；实际C/profile执行方案仅只读候选，未派新生产实现。

D Go首次完整独审2项BLOCKER，原完整types/四C反例/354跨语言snapshot通过但不能替代strict wire与Hash漏验修复；报告lane-d-go-mirror-independent-review-01.json SHA f2624564…。原Go及独立有效RED已保全，首轮集中修复不重开Python/C/common。UI本地顺序调整独立PASS（lane-d-ui-local-order-amendment-review-1.json SHA dcf96bca…），仅原Task4 mock实现已派；backend、最终UI接受/commit/集成仍等修复后Go独审PASS。所有真实批次/provider/DB/build/deployment仍NOT RUN。

D Go首轮集中修复独立PASS（BLOCKER0/BACKLOG0），source8db0e765…、test72e2c166…，freeze ca6f6daf…，报告lane-d-go-repair1-independent-rereview.json SHA17d1153f…。原2项关闭，四C反例与354 Python-Go snapshots、完整types48.408s、gofmt通过；root复核全部准确身份与3 fixtures未变。原Go/原RED继续保留。后端Tasks1→2→3已按已审计划派出，UI mock实现并行；这不代表后端/UI完成，也不代表真实SOURCE/C/provider/DB/Draft/Review/Activate或部署已执行。

D UI Task4首次独立复核BLOCKED（1项、BACKLOG0）：8文件/17 owner日志身份一致；独立focused25、G2页面/citation46、actual两条空unknown历史对齐通过。结构化身份内部LF完整重哈希仍被接受，违反修订7v2；原文件/日志保存在d-ui-review1-snapshots及d-ui-review1-evidence，报告lane-d-ui-independent-review-01.json SHA c206bffc…。首轮有界修复仅开放batchConcept830G3.ts及其spec，严格结构化文本与exact typed body分离，正文TAB/LF/CR保留；dispatch d600c0cc…。六个Vue文件不变，最终UI接受尚未通过。额外pdfJsPort Denied ID为现有跨worktree依赖环境限制，不属于PASS或产品回归；真实效果仍NOT RUN。

D UI首轮修复独立PASS（BLOCKER0/BACKLOG0）：原完整重哈希parser_identity LF反例现拒绝，正常输入仍接受。source52ec691d…、spec37713e5c…、freeze6cdd98c5…；报告lane-d-ui-repair1-independent-rereview.json SHA3fb2d779…。独立26页面/46 G2回归通过，所有8文件及11原始日志身份一致，六Vue文件未改。结构化字符串/对象键拒绝全部C0+DEL，exact typed body保留TAB/LF/CR，LF/CRLF hash不同；FreeWiki投影与冻结Go/Python一致。旧失败/修复RED保留，UI写域关闭。后端仍实现中，组合软件门禁和全部真实执行仍未完成；本结论不包含浏览器、上传、provider、DB、build、部署或发布。

D Task3 query入口原owner matrix漏列，已在实施前补齐：lane-d-backend-query-owner-amendment-3.md SHA1b8ff9d0…及独审cc80ae37… PASS，仅追加现有concept_free_wiki_830_g2 handler（总12路径），测试使用已开G3 handler test。原子Read/Issue入口在同一pin下分类/读取/签发前拒绝既有3类G3 query异常；原G2 first/empty/mixed行为保留。v1 TOCTOU方案和v2文字缺口原件保留，不计代码修复轮次。此为SPEC/派工，不是backend CODE PASS；有效RED、实现、完整回归和独审仍待保存，真实效果仍NOT RUN。

D backend初次独审收口：11源码身份匹配，独立service303.020s/handler3.103s/router3.965s回归PASS；Spec BLOCKER2、code quality无新增阻断。实际service→Gin响应有28个U+2028，read_sha错误绑定escaped preimage，冻结UI拒绝；prepID六类不合法值可写Draft，G3 handler还会trim重写。报告lane-d-backend-independent-review-01.json SHA416d80fa…，原始证据完整保留。方案9ff57eb0…独审PASS，首轮集中修复dispatch0941c4de…仅四文件；未改类型、UI、fixture或C边缘空白规则。此时backend仍BLOCKED，全部真实业务执行NOT RUN。

D backend repair1：完整三包/vet PASS，B1已关闭；root实际Create/Load+Gin renderer→冻结UI/Python两状态PASS，5实体342字段、28个U+2028及所有逻辑正文不变。独审报告4b45e09d…仍BLOCKER1：B2 decoded Text与stored检查已通过，新增raw JSON坏UTF8/lone surrogate替换边未封闭。首轮四源码gzip及所有日志保留，repair2设计5b67f955…独审PASS、dispatch2d7300a9…仅两handler文件，剩余最后一轮预算，无新基础域或外部权限。尚不能把backend或真实G3流程记为PASS。

D backend最终软件收口：repair2最终独审5e9c4f0b… PASS/BLOCKER0，final freeze2b32e49f…逐11文件一致；仅G3 raw preparation_id在typed decode前由既有canonical helper校验、不使用返回值改写原文。原bad UTF8/lone surrogate反例现400/spy0，valid UFFFD/emoji/literal backslash-u和同坏字节G1/G2原行为保留；独立原探针2.295s、wire矩阵2.628s通过。service408.944s完整回归仍对应未变源码，最终handler/router2.802s/2.768s及vet通过。root已核30冻结身份及service→Gin→原UI/Python两状态5实体342字段完整互操作。历史失败/原始日志不重写，root总回执lane-d-root-software-integration.json。全部当前代码写域关闭；此为LOCAL SOFTWARE PASS，G3 FLOW、实际SOURCE/C/model/DB/build/deployment/release均NOT RUN，QUALITY仍DEFERRED_TO_Q0。

# G2 执行记录

## 启动简报 · 2026-09-05 18:25 +08:00

- 授权：用户明确“开始启动 G2 的工作吧，新开一个 G2 的总控窗口”；只执行 G2。
- `TASK_PROJECT=LLM_wiki (local-6ce8fa782294fc34e613b3ff169e9a1c)`。
- `REPO_ROOT=/Users/houjing/Documents/LLM_wiki/insurancekb-weknora`。
- `WORKTREE_PATH=/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g2-concept-free-wiki`。
- `BASE_COMMIT=e7f57b3628adf97929471de9b4add3ff75c29b8b`，tree=`006104da4eac991cf9f1e64361c5a02375e3c03e`；已 fetch 核验，包含 PR #128，无后续差异。
- `BRANCH=codex/830-g2-concept-free-wiki`；唯一结果、集成与外部动作 Owner=`830-G2总控`。
- `CURRENT_GOAL=G2 / GOAL_PRODUCT_STATE=NOT_YET_DEMONSTRATED / FLOW=NOT RUN / QUALITY=DEFERRED`。
- `CURRENT_RED=NO_SHARED_CONCEPT_OR_VALUE_ADMISSION`；真实输入编译回放见 [initial-gap.json](initial-gap.json)。
- `NEXT_PHYSICAL_RESULT=已有共享定义由两个真实 FieldAssertion 链接；同版聚合随实体集合改变而定义正文 hash 不变；垃圾候选拒绝且不进入正式视图`。
- `LAST_REAL_RESULT_AT=NONE_FOR_G2`；G1 历史结果不能重置 G2 计时。
- 首切片时间盒 1.5 工作日；物理演示最晚 2026-09-07 18:25 +08:00（同时执行连续48小时无产品变化 STOP）。整卡 4–6 工作日。

### 冻结输入与资产处置

| 资产 | 处置与核验 |
|---|---|
| G1 closeout、BA0 closeout、PR #128 五文档 | KEEP；历史字节和授权字段不改 |
| G1 C5 bundle | KEEP；原目录为空，找到 `c5-bundle-v3-recovered`；四文件外部 SHA 全等于 G1 actual-input-authority；真实回放14 pass/0 skip |
| G1 entity manifest | KEEP；真实重算 `3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c`；76成员，free_wiki为空 |
| 现有 WeKnora preparation/review/release/CAS/ACL、JSONB成员 | KEEP；G2用独立版本payload接线，无新表 |
| G1 专用只投影旧 Candidate、空 free_wiki 校验 | KEEP 历史合同；G2新版本 REWIRE，不放宽旧解析器 |
| 概念/free_wiki正文→member.Content | REWIRE；从结构化payload确定性重建，供既有Search/Agent读取，不建立可编辑正文权威 |
| OpenSpec009 概念表、Harness current revision与投影 | FREEZE审计；其当前执行语义 SUPERSEDE，不复活 |
| Schema/专家定义、原始条款与说明书 | 优先复用；每项来源及locator在运行前冻结，不能从实体条件推导通用定义 |

24 项 Seed Cases 的逐项输入、预期处置和digest必须在任何G2编译/准入运行前冻结；尚未冻结即 NOT RUN。它们不是Q0 Golden。可替换实现必须独立执行并保留输入/原始输出，不使用生成者自评分。

### 验证、成本与外部对象

- D0：启动/Spec/计划/输入hash；Docker SKIP。
- D1：focused Python/Go/Vue tests及局部编译；复用既有依赖，Docker SKIP，不调用全构建。
- D2：冻结integration head及可重算artifact identity后，受影响app最多1次、frontend最多1次构建；均先lookup，同identity命中必须build=0。未影响镜像REUSE。此为本卡必要构建上限，不继承BA0历史预算。
- D3：只运行D2 exact image，`--no-build --pull never`；真实业务HTTP/页面/source click，不能替用BA0 artifact smoke。
- 启动时实际用量：Provider=0；app build=0；frontend build=0；部署/DB写入=0。
- 启动时Provider预算（后续修订见下文）：复用815既有配置：`https://api.deepseek.com/v1` / `deepseek-v4-flash`（私有request identity只读核验）。具体G2请求输入、模型参数与执行identity未冻结前调用=0。首轮最小预算为分析1、编译1、独立审核1；仅同一失败允许一次登记纠偏调用，总上限4，不换模型、不新增服务。后续需要扩大必须按章程报告。
- 固定builder=`g1-build`；BA0 app `sha256:8cb32d7f638669b2f741ab82ba86d84517e3ec6569e036970d5412d62c75e9eb` 已本地查到；它不是G2制品身份。
- 默认Colima宿主socket不通；官方 `colima ssh --profile default -- sudo docker ps` 可读，既有clone `WeKnora-p0-clone-postgres-vsnd11r2`、redis保留；未重启profile或生产。后续复用官方CLI通道，不把socket故障当产品RED。
- 外部写域仅待冻结的G2隔离NOT_FOR_PRODUCTION对象、隔离runtime及唯一D2镜像；生产8081、生产Active、G1历史Release只读。具体scope、端口、credential文件与命令在执行前列明；未列对象不写。

### 写域与STOP

总控当前只写 `HANDOFF.md`、本目录、紧凑G2 OpenSpec及实施计划。产品只有一个有界实施Owner；其精确文件在OpenSpec Owner matrix登记，reviewer始终只读。首轮只启动一个只读内部审计，没有新可见实施窗口。

STOP沿28章程§6/§8及29 G2卡：第二层前置、同一真实阻断一次纠偏再失败、不能确认identity、超时、任何新服务/新表/第二authority、来源回验低于100%、定义被聚合回写、范围外费用或生产动作。YELLOW（5生产文件/500行/4小时）只触发总控有据范围复核。G3/Q0及生产发布未授权。

## 接缝核验

G1旧合同在真实冻结材料上可运行，但不支持concept links，并确定性拒绝非空free_wiki。126不能承载G2，009与现行数据authority冲突；满足“已保存可复现缺口 + 现有合同不能安全解决”的OpenSpec新建条件。新建128仅承接当前G2，不增加产品Goal或平台前置。

## YELLOW范围复核与写域接管 · 2026-09-05 23:10 +08:00

开工墙钟已越过4小时，按28§6登记YELLOW；G2真实产品状态仍未改变，48小时计时和演示截止不重置。
已完成的只是输入/接缝核验、最小Spec与独立复核。范围仍为原M1物理结果，无新表/新服务/第二层前置，
调用与构建均为0。24项Seed Cases固定，真实C5输入已持久保存，native projection与815 parse hash一致。

内部实施agent一直处于pending_init，未获得实际执行机会；总控已interrupt并明确收回全部写域。
现在由总控作为唯一实现writer执行Task1既定五个Harness路径，与任何实施lane无并发写入。
独立复核仍只读。先写定向RED并保存原始日志，随即最小GREEN，不继续扩写治理文档。

## 用户授权并行推进 · 2026-09-06

用户明确同意通过总控并发推进G2。冻结Harness五文件identity见task1-review-identity.json，
当前18项定向测试及两个模块mypy、ruff通过，均为离线协议。代码超过500行触发YELLOW；
仍仅两个新生产模块，无新服务/表/Head，Task1补齐审核记录与派生成员后停止扩张并交独立复核。
总控保留集成与外部动作；平台合同lane独占新增types/concept_free_wiki_830_g2.go及其test，
工作树830-g2-platform-contract，基线fetch后仍e7f57b362。该lane只消费冻结vector，不改Harness。
另一只读lane已找到实体594的真实原文，但尚无平台SourceRevision，导入必须复用既有链。

## STOP / RETURN_TO_USER · 2026-09-06

集中修正复审关闭source scope、protected definition、audit/member和alias hash四项；
existing/output实体版本仍没有与request snapshot精确绑定。当前vector里request v1而两个
FieldAssertion.entity_version为空，bundle仍通过；冻结candidate为71074e3306b0a132ba6f63b6497cb1b5427ba3bfc15e846cee31a6827edb512d。
按28§6停止追加修复，当前所有产品写域关闭，Go lane已确认停止并保留唯一test草稿。
22项focused tests通过不代表此缺口关闭；产品FLOW仍NOT RUN。
精确剩余修复与资产处置见stop-entity-version-binding.json；全部未跟踪资产见stop-untracked-assets.json。
两个工作树未移除，均无相对base未集成提交；未commit/push/构建/provider/部署/DB写入。

## 恢复授权 · 2026-09-06

用户明确“可以追加，如果不是很不合理的扩展，G2的申请的额度都给予通过”。
恢复当前实体版本绑定修复；合理且必要的G2有界扩展由总控登记后推进，不再重复申请。
现有源码、输入和review身份保留，不改历史STOP事实。当前新增步骤仅修复生成/输出/已有
快照的实体版本绑定，定向RED后GREEN和独立复审，随后恢复同一Go合同接线。
写域：总控concept_compile_830_g2.py、同名tests、vector和evidence；Go lane待新vector冻结恢复。
不据此启动G3/Q0或生产发布，预算扩展须仍有具体原因及实用量记录。

## 并行实施与隔离来源复制 · 2026-09-06 01:15 +08:00

首个代码提交e88f27fe6208822a56ee28bd6e8d9a3698e3445f：离线协议25 tests、ruff、
mypy及独立复核通过；真实G2 FLOW仍NOT RUN。Go lane推进原发布链，主控推进UI和来源运行时。
UI修正已有身份漂移，15 tests通过；导航集合补充六个有效RED负例后继续修复，未冒充完整UI验收。

按用户合理扩展授权，执行runtime-plan.json中D1隔离来源准备。只读核验纠正：原数据库
knowledge_revision_sources实际为0，历史C5来源文件存在不等于该表有封存记录。
目标weknora_g2_594创建前不存在；通过现有PG容器pg_dump/createdb/pg_restore复制完成。
源/目标Head均release-6239c4c8-a3eb-414a-b05c-e3c74f6ddc28、epoch3，source表均0。
原库无写入；新库复制PASS，文件卷/容器/auth/backfill/import尚NOT RUN。
当前实际用量：DB新建复制1次；provider=0；app/frontend build=0；应用部署=0。
来源准备目标为新隔离DB和runtime，非生产；首次SourceRevision补齐不能省略。

## 有界测试操作员配置 · 2026-09-06 01:32 +08:00

G2来源应用与docreader已复用精确镜像启动；应用health HTTP200，构建/pull仍0。
两处已有runtime文件中的已知管理员凭据均正常login HTTP401，不继续猜测或重用历史临时JWT。
按用户已批准的合理必要G2扩展，冻结新增provisioning：只在weknora_g2_594现有users和
tenant_members各增加一行明确标记的G2测试操作员，tenant10003 admin、非system admin、无跨租户权；
不改已有用户密码、不注册无关tenant、不改原weknora或生产。随机密码仅0600私有文件，使用既有
密码哈希算法，再走正常auth/login核验角色。该操作员的自动化测试不代表专家人工语义背书，Q0仍DEFERRED。
同时仅修改新G2容器内config/config.yaml启用既有knowledge_revision_source.backfill_enabled，
记录配置SHA后重启同一精确容器；不改变镜像、不新增schema/table/authority。

## 真实输入与集成修复 · 2026-09-06 02:35 +08:00

原文backend读取修复已独立复核BLOCKER=0，RevisionSource定向套件PASS3.524s，提交03a2b96aa。
runtime仍为旧G1 exact image；修复后的实际backfill不能提前记PASS。UI切片已提交5b9ddb265。
Go发布及Agent两lane并行实施、总控独立审查；共享Go cache轮流编译，避免多包冷编译相互争用。

真实G1四个chunk已从隔离库导出，内容SHA匹配C5；17条code-point引文逐字匹配，旧quote
以schema-wiki-text.v1校验，再为G2转换raw UTF-8 SHA。导出的source projection只作冻结输入，
不冒充live source authority。C5 manifest_self与WeKnora chunk manifest是不同preimage；
后者与当前DB f2190b...一致，未发现该处漂移。

根因修复范围：G1→G2引文hash转换；迁移必须使用两阶段source authority，旧ReadExactRevision
按设计永久拒绝，不可作为成功校验；页面/Agent release与epoch绑定；Agent显式RAW target、
缺失provider和跨租户seal边界。sources真实bridge仍需接入，Review/Activate默认失败关闭。
HTTP错误映射已有效RED（两路径500非503）后GREEN3.310s，g2_sources独立复核BLOCKER=0。

B upload被自动审批拒绝，工具未启动，provider调用0。已核实两份公开PDF来源与现有
DashScope/qwen3.7-text-embedding目的地，具体2PDF/20请求授权问题仍待用户回答。
原有合理额度授权继续覆盖独立代码工作；未用替代服务或路径绕过外发拦截。

## 代码集成完成与 A 原文修复实跑 · 2026-09-06 02:55 +08:00

平台切片77f8fea05、Agent切片3c655294d已提交；19个代码/测试文件SHA冻结，6个Go包检查
通过，原始输出见integration-validation.json。67个G1字段与17条引文已生成离线迁移输入，
保留64unknown/2present/1absent_explicitly，没有重写旧事实或冒充真实发布。

依用户持续授权，登记一次合理构建额度扩展：app总上限由1增至2，以一份中间来源修复镜像
解除A backfill阻断，另一份留最终source bridge集成；未受影响frontend/docreader不在本步骤构建。
固定中间build_source_head=3c655294daa3aecf3b27fcba2e408d63a4a17f60，builder=g1-build，
先按既有BA0 selector精确lookup，命中则build0。仅更新既有G2隔离应用，再对A source backfill
做实际HTTP核验；不依赖B外发授权，不调用embedding/compiler，不改变生产。见interim-build-plan.json。

### R4 physical A progress (2026-09-06)

- Sixth code commit `b8cde87d8`: native PDF producer/Go decoder; independent root review0.
- Actual isolated docreader Python capture: 39 pages / 45120 codepoints / 40657 bboxes; actual A artifact accepted by Go decoder (1.775s). Native 8 unittest cases also ran in actual docreader dependency environment (0.022s), no bootstrap dependency stubs; raw log `/private/tmp/g2-native-runtime-unit.log`.
- Intermediate app build from `3c655294d` PASS, image `sha256:8916569d1bc2fe068febb68e7bfdebe95ac1ae03a9fd6dec8b096aa9270682b6`; installed only in G2 app. Initial config owner error was observed and repaired without changing config bytes; health/login200.
- A backfill HTTP200: source row0→1 in G2; source file SHA/1047811bytes/39pages/pinned verified. Original DB/source rows0 and both release heads epoch3 unchanged.
- Read-only citation signing ring prepared/applied only for isolated source previews, separate from human review/publish authority. No human review/publish key configured.
- Native source bridge and dedicated G2 viewer are integrated in separate bridge worktree; UI37 tests/typecheck + independent review0, including persisted Go authority vector. Legacy G1 carryover source revalidation was then under implementation/review; it subsequently passed review and was integrated in4c5aea9bf below.
- B upload/embedding still unexecuted pending the specific external-data approval. Provider calls0. FLOW NOT_RUN; QUALITY DEFERRED.

- Docreader build and isolated exact-image upgrade PASS (`sha256:ac944d934fcd30c77e4ff28d19f1b4d6dd147012a6553c4678274c1f0be35868`), gRPC health SERVING; previous container preserved. Formal gRPC Read and ReadStream both returned identical actual A Markdown/native metadata: 39 pages, 45120 codepoints, native artifact SHA `8f735c46740c4988a6d742a0c15f4baacc7c42ed8668e81aef922a0aff5a1bf6`. See `native-a-grpc-validation.json`; two local gRPC calls, zero provider calls, FLOW remains NOT_RUN.


### Integrated source bridge and delivery recovery (2026-09-06)

- `4c5aea9bf` commits the source bridge and dedicated viewer after independent BLOCKER0 and root7-package Go /37 frontend tests/typecheck PASS. This is code evidence only.
- Actual-A provider0 compile-request preflight then exposed multiline text rejected by reused Schema canonical. G2-only canonical repair was sent for independent review and subsequently committed asf23e2d7e6 below; prior passing short vectors did not establish this path. The real request has17 legacy locator SourceBlocks (derived from4 durable legacy chunks) plus1 native leaf; preserve all source text exactly.
- The second app build failed before code compilation because builder `/dev/vdb1` had20G used and0 available. Failed BA0 receipt is preserved in `final-app-build-failure-4c5aea9bf.json`. Attempts are now2 (one prior PASS, one failure); standing user approval supplies one recovery attempt, total max3.
- Dedicated builder `g1-build` data disk resized20→40GiB, Docker28.4.0 restored, actual19G free. No image/volume deletion or cache prune; default runtime unchanged.
- Frontend static build and Docker image PASS, source4c5aea9bf, exact image `sha256:ad6f3c8944bb081f022ad74267787ab9f3d647d4b6f4360beeebdf6123836fa5`. New isolated UI at127.0.0.1:18195 has actualindex200 and proxy login200 for tenant10003. Docker did not publish the loopback port on the internal-only network; the existing G2 egress network was attached, publication verified, no new network or widened binding. Receipt preserves the initial incomplete outcome and repair.
- At this recovery checkpoint UI talked to the already-verified intermediate app3c655294d; final G2 app/candidate/activation had not run. Final app delivery is recorded below. Provider calls0, B external-data approval still pending, FLOW NOT_RUN and QUALITY DEFERRED.

- Canonical recovery committed `f23e2d7e6` after final7-package Go and27 Python tests, independent BLOCKER0; actualA request hash67bd6ad8…a7e3. Recovery app build started at this frozen head.
- Actual A provider command was rejected by automatic approval review before process creation: derived67-field snapshot/public terms transmission to DeepSeek lacked destination/payload-specific approval despite standing G2 budget authorization. No attempt-started marker or provider ledger exists; calls0. A-specific async approval requested. No workaround or alternate external call made.

- Captured actual A gRPC output passed the service native-quote resolver for page1 insured definition and page2 eligibility, with wrong-page/altered-quote/parser-drift rejection. Service test PASS3.467s; source/native/parser hashes unchanged, no provider/DB/Docker calls. `a-native-service-quote-validation.json` is captured-data validation only, not online G2 release/FLOW.

### Provider预算修订登记 · 2026-09-06

启动预算总4次，后续总6次的口头计划（A/B共用1次纠偏）由当前冻结预算替代为总7次：
seed分析1、A编译/独立审核/编译纠偏各1、B编译/独立审核/编译纠偏各1。原因是两个真实实体快照
各需独立编译审核，且完整67字段输出超出早期8192 token余量；每实体只预留一次有据纠偏，
不含隐藏重试或换模型。依用户“合理必要扩展均通过”授权登记，精确身份见
provider-budget-revision.json（文件SHA d3cd597e060d2939837d08531cb19c02c03f69544e9e6c391a46d056f65ab70b）。
这是预留额度，实际Provider仍0。A最多3次的具体DeepSeek外发申请及B的DashScope外发申请仍待回复，
总预算不替代目的地与payload审批；未批准部分不得执行。

### 最终构建结果 · 2026-09-06

恢复app build已PASS，源码f23e2d7e62cffebc076cd453dbcf6be6be8b16bc，
image sha256:2bbd893134c4979580ce0b451c394020af8af61a4d1dd0c3d75d100dd4b01c43，
linux/arm64、750931118字节，BA0六个制品标签一致。累计app3/3次（2PASS、1磁盘满失败），
未启动额度0。前端累计静态1次/镜像1次，恢复阶段复用0新增构建。最终隔离app升级已启动，
尚不把构建成功计作G2快照或FLOW验收。

### 最终隔离交付核验 · 2026-09-06 05:30 +08:00

最终f23 app镜像已通过身份校验并部署至weknora-g2-594-app；旧中间容器保留为
weknora-g2-594-app-before-f23e2d7e6。UI nginx重载解析新容器地址后，app health、
app正常login、UI代理login及index均200，tenant10003。当前Release读取200、epoch3；
既有G1引用预览和PDF读取200，1047811字节及SHA与冻结A原文完全一致。
首次回读脚本曾把citation_id末尾多抄一字符而400，从已有真实authority读取准确ID后复验PASS；
没有产品代码/配置修改。原库source0、G2 source1及两库Head均精确等于此前backfill后的状态。
升级及只读验证见final-upgrade-receipt.json和final-runtime-read-verification.json。

当前产品验收仍为G2真实快照0/2、Provider0、FLOW NOT_RUN、QUALITY DEFERRED。
下一关键路径为获准的真实A编译与独立审核、实际候选人工确认及隔离发布，随后B导入/第二快照与
定义hash不变、聚合hash变化、页面/搜索/Agent/source-click联合验收。没有虚构模型执行或人工签名。

### 两项具体外发获准并真实执行 · 2026-09-06

用户在确认用途后明确“授权给你，你执行下”，批准A公开条款+派生67字段到DeepSeek最多3次，
B两份公开PDF到DashScope最多20请求。A实际compile002因audit缺失/错误key及3字段evidence
顺序重排被拒；仅追加系统纠偏提示（独立review0）后compile003通过。review001独立返回PASS/89。
总实际3次、254692 tokens；所有原始HTTP响应、raw message、参数和hash均保存，未修补输出。
既有assemble_bundle生成候选57740bec…80e21，原始输出绑定/页面清单/1定义67字段2链接通过。
实际平台Draft POST随后返回HTTP400，错误schema wiki preparation invalid；未虚构Draft或发布，正在
独立定位Go解析与旧G1基线接缝。G2真实Active快照仍0/2。

B本地native解析44/17页及实际Go splitter生成37/9 chunks，正常仅2个embedding批次。发现原
复制库summary/wiki/qgen开启，且生产默认重试最坏可能40次，因此上传前补本次执行专用
20请求计数限制，固定同一DashScope HTTPS目的地、只许可冻结37/9整批，配置临时切换及finally
恢复记录于b-bounded-execution-plan.json。该限制不构成新产品服务/镜像/容器/网络，尚未执行。

### 实际审核与B失败原因闭合 · 2026-09-06

上节review001的PASS89仅是早期Python结果，随后实际Go Draft HTTP400已证实其raw遗漏contract；
Python默认值掩盖遗漏，故旧候选/预览已明确作废，不得确认或发布。依用户合理扩展预批，先登记
将unused seed槽移给A，A最多3→4、全局仍7；review002仅纠正raw格式提示、未提供旧分数或要求PASS。
第4次真实响应raw完整但分数66（15+10+15+10+8+8），低于80；candidate assembly正确拒绝
PAGE_ADMISSION_REQUIRED。A实际4次329829 tokens，accepted Draft0/Active0。不改分、不刷分。
独立审查确认目前review prompt/schema没有PASS与80门槛一致性及评分锚点，登记离线修复项，
不把decision字面PASS作为候选准入通过。

B首次导入创建terms knowledge5ad208d2…10c8后解析失败，计数限制拒绝文本顺序，provider0；
实际37个文本hash逐一相符，common.Deduplicate maps.Values造成输入乱序。保留零账本，
先登记精确多重集、转发原序的replay（独立BLOCKER0/fake测试PASS），实际再解析触达provider。
DashScope5次均HTTP400，明确每批不能超过20；没有成功向量批次，第二PDF未上传。
两次执行都已停止临时guard、准确恢复KB/model/SSRF及app health200，原库配置不变。
下一次有界执行须按原完整37/9白名单分20/17/9，继承已用5次而非重置预算；仍总计最多20。

B分批执行实际PASS：terms同一knowledge attempt3，brochure e7722140-3486-437b-9952-f3d66d6fb539
attempt1，两份completed及active chunks37/9。沿用原5次失败账本，新增20/17/9三个200子批，
累计8/20次。count在每次上游调用前落盘，禁止source重复尝试；完整文本白名单未改，向量返回索引
正确拼接。本轮临时KB/model/SSRF恢复精确相等、guard停止、app health200、原库配置不变。
实际总账见b-embedding-partition-ledger.json（已包含前5次，不能再和replay账本相加），执行见
b-guarded-partition-receipt.json。此PASS只代表两PDF导入/向量化，不代表B模型编译/发布或G2 FLOW通过。

B来源封存回验PASS：上传自动capture已有A+B+B三行，其中B两行的binding为空；原先只允许A一行
的前置检查实际STOP且没有backfill。冻结精确3行快照并独立复核后，分别seal当前attempt3/1，
保持source ID不变，原文SHA、页数44/17、大小及chunk37/9全部符合，binding/manifest完整。
原库source0不变；G2 source3精确为A+B+B；两库Head均release6239…epoch3不变。
见b-source-sealing-verification.json。来源回验新增provider0，G2 Active仍0/2。

本轮交付检查：OpenSpec128 strict验证PASS（退出0；工具遥测联网失败不影响校验结果），
JSON解析/已知凭据扫描/diff-check通过；机械事实文档修正免RED由独立reviewer确认。
本轮没有产品代码修改、构建、生产发布或G2激活。A候选准入仍拒绝，B模型编译/两快照对比/
页面搜索Agent及G2来源点击联合验收尚未完成，FLOW NOT_RUN、QUALITY DEFERRED。

### 用户纠正阶段目标后补齐人工分支 · 2026-09-06

用户明确G2当前核心是串流程，随后“继续推进g2”。原蓝图80为自动候选门，60–79人工决定，
G2验FLOW而Q0验领域质量；此前将66作为全卡停工依据不准确。OpenSpec128/原plan Task5先登记
v2人工候选+admission，设计独立BLOCKER0后RED→实现。v1字节及>=80不变；v2原review/raw/66
保持不变，确定性pending集合进入candidate hash，拟议Draft与正式Active分离，沿原具名整包签名。
Python新增15项RED后两模块42GREEN，ruff/mypy及独立review BLOCKER0；真实compile003/review002
无新增provider装配v2 candidate70cb4b6e…363c5，pending1/proposed70。完整67字段预览已保存。
Go types/service/四个release分支/source verifier接线及负向测试完成；四包定向回归PASS，独立复核BLOCKER0。

按用户合理必要扩展预批，登记新增一次app构建额度：累计上限3→4，先BA0lookup，只有miss构建。
前端协议/代码不变，frontend/docreader新增build0。已只读核对builder40G/可用15G；升级脚本保留
旧app、固定G2 DB/两网/三卷/loopback18194/configSHA，UI代理登录成功后才PASS，独立review0。
真实Draft脚本只允许固定candidate/Head、正常tenant10003登录和POST，严核完整scope/70成员/
空reviewdecision，未签署或激活，独立review0。尚未执行build/upgrade/Draft；必须等Go最终复核和代码冻结。

构建等待期间只读审计24 Seed：原case冻结未变，缺准入前分类与完整编译/审核执行输入，不能反灌expected形成循环测试。
完整处置attempted0/24，仍NOT_RUN；仅15项ValueScore结构/边界检查15/15 PASS。详细缺项见seed-execution-gap-audit.json，
此审计无provider/DB/Active效果，不能作为M1/M2或24/24验收通过。

B第二快照provider-zero预检v2：总控只读导出说明书9个durable chunks（SQL SELECT，仅隔离库）；
其原文和生产embedding输入hash逐项/按序/多重集均与冻结白名单一致，无重传/重嵌入。真实条款第1页
定义句与A body逐字相同，native全文/page/chunk唯一匹配，16字符bbox完整，仅登记来源备选，不创造字段事实。
见b-second-snapshot-preflight-v2.json；仍待A Active精确基线及B实体版本/事实目录/实际引用SourceBlocks。

### v2交付执行进行中

代码冻结commit871f6e1028ebbde453cdd60b0b787f95103ad7c9，Python42PASS、Go定向包PASS及独立review0后提交。
先写human-app-build-plan.json，再走BA0唯一入口；lookup miss后单次BUILD_AFFECTED，累计真实app构建4/4。
构建会话12623、builder ID u6gomwa7sqadszfj7o55o225w仍运行，human-app-artifact.json保留INCOMPLETE；
不能重复启动构建。只读资源复查编译进程持续运行、Docker卷40G可用13G，无已观察到的资源耗尽。
本记录不是构建/升级/Draft成功回执，完成后分别补实证。

构建期间完整候选预览已提供，用户对exact候选70cb4b6e…363c5明确“批准整包并在 G2 隔离环境发布”。
批准事实冻结a-human-explicit-approval.json，随后先登记a-human-publication-plan.json，再准备一次性执行脚本。
Draft脚本仅增批准身份守卫及回执时态，SHA730c34e916da4dee747b9fe6c701197aa9b329871844693f79d8eb804078ee8e，
独立增量review0确认还原后逐字回到旧已审SHA，机械修订免RED；不修改旧build注册时脚本SHA历史。
用户批准不代表平台Review/Activate已经发生，这两项仍待实际回执。

### 实际v2 Draft完成

BA0 app构建PASS，exact image sha256:73c39699dcb9298093e70aca06746f8b71889ec9d8094b9c6a896a24a699391a，
source/integration均871f6e1028ebbde453cdd60b0b787f95103ad7c9。隔离升级及UI proxy login200 PASS，
旧app保留app-before-human-v2；随后只读app/UI/docreader身份、G1 preview/PDF200及PDF SHA/bytes、
原库source0/G2 source3和双Head epoch3精确验证PASS。见human-upgrade-receipt及human-runtime-read-verification。
已批准A候选实际POST Draft HTTP201，70成员、完整manifest/candidate/source/scope/expected Head全部相符，
review decision仍空且Head不变。见a-human-draft-create.json；human Review/Activate尚未发生。
真实Draft review_policy_id=52e24cb2b78832acbd74ccba422093485f621841731de18e0e6b06d83ee79107；
后续执行稿须按平台现有policy派生（含真实NUL分隔）绑定此值，不能沿用离线错误转义预估。

### 真实Review停止：PostgreSQL表示差异

用户批准后实际一次执行已配置两独立public rings，app配置SHA f0c30a2d9fef33d727e00f06845247d0137dac0376c4e23f1ec646445b478947，
仅同一G2 app重启、正常login/Head3 PASS；human receipt已按exact批准签署，Review POST一次返回400，
activation POST0，停止并保存a-human-review-failure.json。私钥仅保存在任务私有目录，未进入app/仓库。
只读实际DB证明stored manifest与候选JSON树完全相同，但JSONB变更键序/空格，原ManifestDigest799769...04d5b
与读取字节SHA0eb51...97838不同，G2直接byte digest拒绝发生在签名检查前。Draft仍draft且review_digest空，
原库source0/G2source3、双Head epoch3不变。见a-postgres-review-diagnosis.json。不得重跑原state脚本或改数据库摘要。


### 2026-09-06 JSONB 修复设计与真实数据库向量

独立设计复核 g2_bundle_review：BLOCKER0。G2 严格 canonical 解析失败必须直接拒绝，不能回落宽松/raw 比较；replacement 使用新 preparation_id 和普通 Create/source 复验，旧失败 Draft 不修改。
真实 PostgreSQL17.9 SELECT-only fixture：`harness/tests/fixtures/concept_free_wiki_830_g2_postgres_roundtrip.json` SHA `db0a3f80cb4fe6a5f6230f9cfc4f51deead04b192e9c8dc60335d3a7ef2dd349`；6成员，before/after 精确 JSON 字符串保存；树相等、raw manifest 不等。查询SHA `b33d60d96405d6d6146bdd6a95f806a69889e8026ef8cdc4f04d77f73444e849`，DB写/provider0。
当前 CODE 修复进行中，尚未新构建/部署/Review成功/Activate。双 public rings 已在上次失败前正确配置，修复升级必须保留 config SHA `f0c30a2d9fef33d727e00f06845247d0137dac0376c4e23f1ec646445b478947`。

Task6 broad service regression completed with exactly two failures: the G2 Agent branch still called the global raw/order member comparator, and one older test asserted that obsolete comparator. Agent production correction was registered in the existing R6/Task6 owner scope and independently reviewed BLOCKER0 before implementation; G1 branch unchanged. Final corrective focused run pending at this record.
B provider-zero local source proposal is frozen at `/private/tmp/g2-b-local-source-catalog-proposal.json` SHA `59e2a65e7ae75dbb3fdd452374d4c9d6a129623b222cda37457882d8c783a731`: two B field quote candidates (waiting_period, coverage_and_renewal_terms) and one complete scenario example for free_wiki. These are source selections only; no B Candidate/Active/provider result is inferred.

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
- 当前实际用量：Provider=0；app build=0；frontend build=0；部署/DB写入=0。
- Provider候选复用815既有配置：`https://api.deepseek.com/v1` / `deepseek-v4-flash`（私有request identity只读核验）。具体G2请求输入、模型参数与执行identity未冻结前调用=0。首轮最小预算为分析1、编译1、独立审核1；仅同一失败允许一次登记纠偏调用，总上限4，不换模型、不新增服务。后续需要扩大必须按章程报告。
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

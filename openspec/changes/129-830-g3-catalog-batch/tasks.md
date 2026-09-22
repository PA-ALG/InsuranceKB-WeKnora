# 实施任务

## 2026-09-15 当前独立平台收尾（原历史 FLOW 不等于本轮通过）

- [x] G3-AUTO-3/5/6：有界引用/增量候选传输，保持原完整候选及发布校验；共享跨语言及真实入口测试。
- [x] G3-AUTO-3/4/6：按有效检查点恢复，复用三态结果和原调用，轻量提交/状态，消除错误前缀决策主体。
- [x] 受影响组件部署，网页恢复当前失败任务，报告实际时长、调用、字段状态、检索及证据回查；不能用辅助脚本或 fixture 宣称独立验收。

已批准设计/Owner/RED边界见现有 platform-independent 设计和计划的2026-09-15修订。2026-09-22 本地平台FLOW已通过：既有任务网页增量恢复及全新3190-2三PDF首次网页上传至发布均完成；详见 `docs/insurance-kb/evidence/830-g3/task3bn-platform-closeout-20260922.md`。现代checkpoint身份失败raw零调用重投影、规模/质量为明确后续项，不能将本结论扩大到生产。

- [x] 核验 main/工作树/工作簿和 G2 终态，保存真实合同 RED。
- [x] 冻结首切片合同及向量；独立审查写域。
- [x] A：RED→无损工作簿 Catalog 编译/Profile 校验→focused GREEN；17 PASS、独立复审 BLOCKER0。
- [x] B：按冻结合同接入既有目录/Profile；17前端 checks、Go接口及类型检查通过，真实部署另记。
- [x] 生成真实 11 包及可审整包展示映射，用户已回复“结构确认”；后续用户“我本人”及已授权记录补齐确认人/队列负责人，旧回执保留。
- [x] 冻结真实 corpus、标签/阈值/采信及后续 G3 物理切片。
- [x] 完成 G3 真实批次/页面/隔离 Release/source/search 及只读独立复核。

- [x] C：设计2与集中修复、独立复核、root73 tests完成。
- [x] D：原合同及1/2/4/5/6修订无损整合；三hash公式补回后独立复核通过，冻结DTO/types/fixture写域。
- [x] D：strict DTO、机械继承与两unknown对齐、actual342跨语言fixture及完整8MiB容量检查；Python与Go均独立PASS。
- [x] D：既有handler/service/UI接线的软件实现和完整fixture互操作独立通过。
- [x] D：真实候选、来源与发布闭环完成，第 7→8→9 版及独立读回复核通过。
- [x] 来源准备：15实际native capture逐件校验；v3隔离脚本独立复核及本机只读preflight通过。
- [x] 来源执行准备：完整upload v2 runner独立复核及执行包复核PASS；具体验证窗口/预览已发用户。
- [x] 来源实际执行：用户已授权；15 份本机来源导入/登记及来源回读完成，PDF 保留本机。
- [x] D Python首轮三项修复及第二轮source覆盖修复已独立通过；原始RED与旧快照保留。
- [x] D Go完整镜像：初审2项BLOCKER经首轮集中修复独立PASS；原失败证据保留，四C反例/354跨语言snapshot及完整types回归通过。
- [x] D UI本地Task4：首轮修复独立PASS（26页面/46 G2回归），原失败保留，8文件冻结并提交b7a26b8aa；实际后端互操作另验。

- [x] D backend Tasks1/2/3：两轮有界修复后独立PASS（B1/B2关闭），完整回归/原反例/前后端互操作通过；11文件冻结，真实执行另验。

- [x] 原 R1—R5 最终矩阵、实际导航变更与恢复、读取/重启/DNS 故障修复、历史/检索/UI 独立验收完成。

结项：G3 FLOW PASS；QUALITY=DEFERRED_TO_Q0；NOT_FOR_PRODUCTION。完整结果见 `docs/insurance-kb/evidence/830-g3/g3-final-closeout-20260913.md`，保留历史失败与后续业务待办。

## 2026-09-22 PR #130 CI 收尾（用户授权继续修复并提交）

Owner/integration=root；复用当前工作树与既有G3-AUTO-1—6实现，不部署、不调用模型、不改变验收标准。
当前RED：远端Ruff 57项（5文件），PostgreSQL任务因测试跨模块导入失败而收集中断；本地相同Ruff已复现。全量mypy/collection先检查，避免只修第一道检查。
写域：上述CI发现对应Harness源码/测试及本OpenSpec/验证记录；仅格式、测试导入和实际类型/回归缺陷。不得禁用检查、扩大ignore、删除测试或改原始证据凑通过。生产语义变化须有可复现RED并独审。
步骤：保留RED → 分类集中修复 → 本地同CI静态/测试门禁 → 独立复核冻结diff → root提交推送 → 核验远端CI。实际部署及模型调用保持0。

CI预检追加事实：strict mypy `src tests` 为3659 errors/147 files，旧全量collect为7274项+1导入错误。按独立域并行收口（dispatching-parallel-agents技能），不屏蔽检查：A独占Harness product_ingestion源码、jobs/store及service_shell/worker；B独占knowledge_compiler源码；C独占tests/product_ingestion；root独占其余tests、规格/最终集成。跨域错误只报告，交对应Owner，不并发写；所有lane不commit/push/deploy，不做provider/业务调用。最终独审由完成写域外的reviewer执行。

并行队列调整：compiler源码类型已清零后，root将 `harness/tests/test_g3_bounded_model_execution_830.py` 与 `harness/tests/test_g3_bounded_review_windows.py` 两文件当前编辑结果交B继续收口；root停止写这两文件（含格式化），其余顶层测试仍root。现有受控JSON模型/窗口类型优先复用，不以cast替代结构合同。

CI收口写域再平衡：A确认尚未编辑 `product_ingestion/discovery.py`、`discovery_stage.py`，现交root补齐类型及回归；A从写入/格式化清单排除两文件。仅既有发现接口的准确注解和已复现检查修复，不改发现/发布策略。

A明确交出尚未写入的 `product_ingestion/verification.py`、`identity.py`、`extraction.py` 给root继续同批CI类型收口，A停止触碰含格式化；其余A写域不变。现有公司策略19项编译回归、归并/别名/增量候选/字段恢复54项回归通过，尚不替代最终全量检查。

A确认 `product_ingestion/api.py` 尚未编辑，交root补齐现有入口类型；A暂停该文件含格式化。root额外审查识别恢复模型字段顺序影响encoded/digest的问题，A恢复三版原字节，C新增三版固定字节/摘要回归（3 PASS）；不能用Python类注解改动破坏持久回执。

CI集中回归追加：root发现类型收口将 `published_compile_members` 的 JSON 行返回值错误改为 Pydantic 对象，导致 lossless candidate transfer / preparation 失败；现接管 `compilation.py` 与 `candidate_transfer.py` 恢复原公开返回语义，只在既有编译构造边界建模。RED为原有 candidate transfer 测试及真实worker fixture preparation失败；不改测试断言。旧 replay fencing 测试则显式选用既有 legacy 恢复入口，现代 public checkpoint 路径保留独立覆盖。独立审查以不可变tree执行，修正后复核最终delta。

本轮CI源码冻结tree `326aa8f640c3035a79abdda77a34542eb9ce903b`：独立只读审查 BLOCKER 0，Ruff/strict mypy（668文件）及有界回归 PASS。root已恢复 adapter 原边界，指定恢复窗口6 PASS；详细矩阵见 `docs/insurance-kb/evidence/830-g3/task3bn-pr130-ci-20260922.md`。完整确定性及PostgreSQL由提交后的exact GitHub CI继续核验；保持Draft，不推导merge-ready或新部署。

3f3a4cade推送后，远端strict/Ruff/wheel通过；PostgreSQL集成复现test_job_store_postgres_035 fixture把迁移head硬编码为0015，而实际upgrade(head)为0018。追加同一CI收口：A仅写该测试文件，核对迁移事实并保留强断言，不回退迁移/不skip、不接触业务数据库；root处理后半段全量新增失败与最终集成。下一次推送仍须集中回归/独审，不部署。
A的PG测试写域补充：同一真实日志还包含 `test_job_migration_postgres_035.py` 与 `test_source_lifecycle_migration_postgres_021.py` 的过时head断言，追加这两文件归A；其余不变，保留迁移拓扑/升级/拒绝危险降级测试。
完整worker fixture 的新增RED也已定位：测试默认创建workflow3，却沿用workflow2“空发现仍审核一次”的预期；当前独立发现合同明确空候选不调用审核模型。root仅更新 `test_pipeline_runtime.py`：同时覆盖历史v2与当前v3，保留v2原审核/重启/单字段补抽断言，为v3明确检查EMPTY最终回执和0审核调用，不改生产逻辑或放宽失败判断。
完整ingestion扫描终态584项：572 PASS，2失败、10 fixture errors。上述workflow审核预期归root；C仅写 `test_undispatched_recovery.py`（旧source-only fixture误接现代checkpoint入口）与 `test_workflow_v3.py`（v5旧预期，当前v6审计协议），核对合同后精确更新，保留原危险恢复反例和所有能力断言，不改生产。

完整扫描后追加根因（仍同一CI收尾，效果为0）：
- G3-AUTO-3 / G3-DISC-1：workflow3单字段补抽RED为自由发现调用2而应为1（`/private/tmp/g3-ci-restart-green.txt`）。当前generation context带整批request hash及派生ref，字段变化误使独立发现失效。root负责发现输入依赖边界及其回归；先冻结窄设计再实现，最终审核继续绑定当前完整输出。
- G3-AUTO-5：当前0018→0002降级时低版本preflight发生过晚，SQLite已删除0016/17/18表列；现有scope测试6个原断言真实RED，不能把起点降到0003。已核对Alembic env/public hooks及0015既有聚合preflight：选择0016/17/18在首条DDL前委托0015统一计划预检。计划目标在MigrationContext内从真实起点解析一次（含相对/base），按实际跨越revision检查其已有数据合同，避免越界拒绝；offline跨越需DB检查领地必须在DROP前拒绝。A独占0015/16/17/18迁移文件及test_scope_migration_016.py（包含新增绝对/相对/中间起点/offline反例），前述4迁移测试写域不变。root不并发写这些文件；不得运行业务数据库、部署或降级现场。
- G3-AUTO-5：MVP architecture词法测试把只读`call.identity.provider`误当执行authority。C独占test_mvp_admission_030.py，按已审诊断精确识别AST metadata读取、保留其他authority禁令并补调用/导入/赋值反例；不改src或扩大模块排除。
- wheel本地RED来自uv0.9.26 macOS SystemConfiguration panic（backend未启动），远端Ubuntu同构建PASS；保留原测试不加skip，完整远端结果仍须核验。

G3-DISC-1/G3-AUTO-3 修复设计冻结（root写域：discovery.py、discovery_stage.py、model_execution.py及对应discovery/pipeline测试）：选择generation context v4稳定输入，独立reviewer已只读确认方向。复用现有source router、精确call replay、v1 replay receipt/metrics及最终strict projector；不新建缓存/发布权威。v4 source ref绑定完整SourceBlock（含文本），entity ref绑定完整实体binding，concept ref绑定完整definition（含aliases），均有domain/version；source窗口/coverage同用稳定ref，删除generation不需要的整批request/base hash。投影边界确定性映射回当前canonical refs并严格重验；父raw保留。v3按显式contract仍可回查/投影，v3→v4属于协议变化不跨版本猜测复用；最终审核继续绑定当前完整输出。复用还核对原call的model/prompt policy、request字节/hash；未知结果不重发。
RED：真实worker单字段补抽调用2vs1及新增test_discovery_local_dependencies首项context不等（3.36秒）；后者只隔离全局request身份变化，不作为完整request验收。回归须覆盖非空proposal重新投影、来源/实体/schema/profile/concept/exclusion/budget变化失效、旧v3回查和ref篡改拒绝。范围边界：非空发现已发布后exclusion index新增成员属于真实输入变化，不能忽略该变化强复用；本次不把EMPTY或输入完全不变的通过扩大到所有发现增量策略。
真实worker复验补充：v4使用完整binding时仍2次调用，差异仅首次CREATE到既有实体MATCH的接入回执（resolution_disposition/resolution_refs/candidate_id/entity_candidate_sha256/binding_sha256）；实体/版本/身份锚、来源、schema/profile/evidence未变。因此v4 entity generation identity明确排除这5个接入过程字段，保留其余完整binding。这是同一输入依赖修复的进一步RED，不丢产品身份或版本证据。原binding及接入回执仍留服务端compile_request；新增CREATE→MATCH稳定性回归，之后再冻结审查。
v4 worker现已证明发现调用保持1次；回归继续暴露聚合summary遗漏`reused_from_run_id`（实体summary已有父run，聚合只有reused=True）。root在同一discovery_stage聚合边界传递当前真实retry parent；不改原模型调用/receipt。RED为test_pipeline_runtime[3]的既有父run断言，不能删断言。
最终完整ingestion603项记录为600 PASS/3失败：预算回放fixture缺request custody字段（C补齐现有DTO，不绕校验）；workflow migration fixture缺Alembic环境（A使用真实EnvironmentContext目的地0017保留字节断言）；旧source recovery一次RUNNING、单例fresh1 PASS（暂不改实现，继续整组复验）。独审唯一BLOCKER为AST guard允许metadata转交调用/赋值/return，C限定Compare直接字符串相等并补反例。root恢复后核对实际diff、统一复验并复审最终tree；不隐藏原失败。
第二批最终复审tree aebf7ab5e7fa509cb17008531cc3ee225e6bca30：独立reviewer BLOCKER0/BACKLOG0/REJECTED0；前轮a632源码审查无源码阻断，AST阻断现关闭。root最新Ruff全仓PASS、strict669 PASS，source/recovery/预算/workflow/MVP整组102 PASS，v3完整worker1 PASS52.30s；证据见task3bn-pr130-ci-20260922。root统一提交推送，实际远端完整CI随后核验，保持Draft；本轮部署/provider/业务effects仍0。

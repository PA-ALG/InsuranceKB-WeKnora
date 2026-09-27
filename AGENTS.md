# Enterprise LLM Wiki 项目必读与贡献规范

> 本文件是仓库唯一的项目必读、贡献与 SDD 流程入口。`README.md`、
> `CLAUDE.md`、`HANDOFF.md` 和 OpenSpec 注册表只能链接到这里，不得复制或
> 改写本文件的流程规则。`HANDOFF.md` 只记录运行/交接状态；适用 OpenSpec
> 只记录某个 Goal 的 Requirement 与验证事实。

本仓库的产品本体是 **Enterprise LLM Wiki**。WeKnora 提供企业平台、权限、
上传、解析、检索和 Wiki 载体；Python Harness 负责寿险语义编译、治理、
Candidate、审核与发布授权。正式线上知识只有一个 serving Active Release
authority；当前条件接受 WeKnora 承载该 Active Head。Harness 不保存第二个
serving Head，旧 PostgreSQL `current_release`/ReleaseSnapshot/publisher 链只作
冻结审计，不构成当前实现授权。

## 开工前唯一阅读序列

任何任务开始前必须从本文件开始，并依次阅读：

1. 830 任务先读 `jlx_enterprise_llm_wiki_technical_blueprint_830.md`、
   `docs/insurance-kb/28-development-execution-charter-830.md` 与
   `docs/insurance-kb/29-goal-cards-830.md`；非 830 任务跳过本项
2. `docs/superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md`
3. `docs/superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md`
4. `jlx_enterprise_llm_wiki_complete_728_v3.md` 的 `§M0` 与当前任务相关章节；
   只有总体架构评审才要求阅读全文
5. `HANDOFF.md` 的最顶部当前状态块
6. 对应的 `openspec/changes/<NNN>/`；B0 是已授权的证据冻结/资产裁决，不新建
   OpenSpec，也不授权产品实现

`CLAUDE.md` 不再维护另一份必读清单；其他开发入口必须指回本节。

所有任务（包括非 830、总控派工和审查）另须遵守
[工程质量与执行效率基线](docs/insurance-kb/28-development-execution-charter-830.md#engineering-quality-baseline)。
这是用户于 2026-09-15 明确要求的项目通用规则：先核对 WeKnora 原生及项目既有能力，
按稳定职责和接口解决根因；遇到无法判断的实质设计分歧应与用户讨论，不能靠持续增加
临时分支跑通样本。核心工程原则在本文件维护，细化执行规则只在上述基线维护，
两者共同适用，不另增审批、验收或编排平台。

2026-09-05 用户已批准的现有 830 有限修订范围及 R830-01—06 见
[830 蓝图 §0.1](jlx_enterprise_llm_wiki_technical_blueprint_830.md#01-2026-09-05-有限修订范围)。
该次只修改该节列出的五份文档，在现有规格内修订并执行 D0/独立复核；不新建产品
Goal/OpenSpec。后续实现消费修订后的蓝图与 Goal Cards，G2 启动授权仍独立。

## 核心工程原则

以下原则适用于整个项目，按当前 Go/WeKnora、Python Harness 与 Vue 前端的职责和
技术栈执行；细化执行要求见上述工程基线。本节不改变已确认的产品合同与任务授权。

1. **架构与领域优先**：计划阶段以清晰、可持续演进的目标架构为导向，明确业务目标、领域边界、模块职责、依赖方向和数据流后再编码，不得以短期实现便利牺牲整体设计。保持 WeKnora 平台与唯一 serving Active Head、Harness 寿险语义编译与治理的职责边界。设计必须完整，实现应当克制；不做推测性抽象，复用抽象延迟到第二个真实用例出现时引入，单一场景直接实现；已确认的协议、权限与跨语言边界仍须显式定义。
2. **以 Deep Modules（深模块）追求优雅设计**：模块应高内聚、低耦合，以简单、稳定的接口封装有实质价值的能力与内部复杂度，让调用者只需理解业务语义，不必了解内部步骤、存储细节或恢复机制。围绕领域职责和信息隐藏划分模块，相关不变量由唯一模块负责；避免只有转发、透传参数或要求调用者按隐含顺序拼装流程的浅层包装。必要的协议适配层可以保持薄，但业务复杂度应由其后的负责模块封装；深模块不等于大文件，也不意味着跨越权限、事务或领域边界合并职责。手写代码按单一职责拆分，新增或重构后的单个文件不得超过 500 行，接近上限时优先调整模块边界；同一模块可由多个内部文件实现，不以机械拆文件代替职责设计。生成代码、锁文件和冻结证据不适用此行数限制；既有超限文件在相关变更中逐步治理，不触发无关的全仓重构。
3. **保持边界与数据流清晰**：协议模型、领域模型、持久化模型和视图模型不得相互泄漏；跨边界数据须完成校验与显式转换，避免跨层共享可变状态。Harness 与 WeKnora 只通过版本化 REST 和 Source lifecycle event 集成，不共享数据库、Redis/Asynq 或队列，不引入第二个 serving Head。
4. **安全与隔离默认开启**：按多租户、多用户场景设计，明确 tenant、Space、principal、当前 ACL 与数据隔离边界，遵循最小权限和失败关闭原则。外部输入、上传材料与模型输出均视为不可信；密钥、凭据和未经授权的敏感内容不得进入代码、日志或响应，必要业务内容仅向有权主体提供。
5. **面向并发与故障设计**：后端主动考虑幂等性、竞态、事务边界、超时、取消、重试、背压和资源释放；复用既有 JobStore、Outbox、租约与检查点，保留有效的中间成功结果。重试须有唯一决策 Owner 和明确预算，禁止无界重试、吞错或以隐式共享状态掩盖问题。
6. **保障完整前端体验**：控制渲染成本、异步状态和并发请求，保持清晰的 UI 结构；用户流程覆盖加载、空状态、错误、重试、操作反馈和可访问性。页面、引用与 Agent 内容遵守同一 Release 和当前权限合同，状态查询与预览不得隐式触发解析或模型调用。
7. **复用稳定的业务语义**：先核对 WeKnora 原生及项目既有能力，优先复用稳定模块；不因代码外形相似而过早抽象，确需重复时注释说明独立演进或暂不抽象的原因。新增依赖前检查对应组件的 `go.mod`、`harness/pyproject.toml`、`frontend/package.json` 等实际依赖清单和锁文件，查阅当前版本文档、类型定义或实现后再判断能力缺口；确需引入时优先成熟、维护良好的库，不重复实现通用功能。
8. **为未来维护者保留上下文**：代码、注释、测试和架构文档是长期协作媒介。非显然的设计决策、兼容约束、已知缺陷和临时方案必须记录原因、影响范围、风险及移除条件；技术债务关联现有可追踪任务，关键架构决策同步到现有 ADR/架构文档，禁止缺少上下文的 `TODO`，不另建一套治理台账。
9. **确保变更可验证、可观测、可回滚**：改动应行为可测试、运行状态可观测、故障可定位，并评估对外契约兼容性与回滚路径。测试和真实运行证据分别记录，不以 fixture、provider-zero 或本地构建成功代替真实业务验收；错误和日志保留经脱敏的诊断上下文，验证与构建按实际影响范围执行。
10. **删除优于兼容**：已授权范围内的内部路径重构直接删除被替代的过时实现，不新增兼容层、deprecated shim 或双写逻辑维持内部旧路径。版本化 REST、Source lifecycle event、持久化格式和数据库迁移等对外合同的兼容性单独评估；必要过渡须有唯一 Owner、适用版本、退出条件和删除验证，不得形成双重权威。冻结审计代码、历史迁移、数据和证据按既有资产处置规则保留，不借重构擅自清理。
11. **以 Tracer Bullet（曳光弹开发）验证设计**：在当前已授权目标内，先选择最小但有真实用户价值的纵向切片，贯通入口、领域逻辑、持久化或外部接口、用户可见结果和必要观测，尽早验证架构假设与关键集成风险，再沿同一条可演进实现扩展能力。切片应进入目标架构并可持续保留，不能靠一次性脚本、旁路 Demo 或先横向建完整平台替代；设计完整指当前切片的职责、合同与失败路径完整，不要求预先实现所有未来能力。第一条链路也须遵守权限隔离、来源、审核、单一 Release 权威和必要错误处理；保持测试先行，测试替身仅用于相应测试层，未执行的真实集成明确记为未验证。每次根据真实反馈调整设计，已有有效证据按需复用，不因采用此方法扩大 provider、数据库、发布或部署授权。

> **变更速查**：提交前先运行 `git diff --check`，再按受影响组件完成必要检查。Go 运行受影响包的 `go test`；Harness 在 `harness/` 下运行相应的 `uv run pytest`，并执行适用的 `uv run ruff check .`、`uv run mypy src tests`；前端在 `frontend/` 下运行 `npm run type-check`、相关测试及 `npm run build`。纯文档修改不构建应用；构建沿用基线的 `SKIP / REUSE / BUILD_AFFECTED`。Schema 变更使用所属组件现有迁移机制（WeKnora 的 `migrations/` 与 `scripts/migrate.sh`，Harness 的 Alembic），验证升级、兼容与回滚策略；存量数据搬迁、修复或回填另按对应 runbook 验证。真实数据库迁移、回填和部署只在既有授权窗口执行，不作为普通提交前检查自动运行。

## 强制 SDD 流程

所有会写仓库、改变行为、迁移、配置、外部状态或验证口径的工作必须按以下
队列推进；后一步不得补写前一步证据：

1. `Goal`：记录业务目标、唯一 Owner、范围、非目标和 STOP 条件；需要外部写入
   或新授权时先取得 Mission Card 批准。
2. `OpenSpec`：先占号并冻结适用 OpenSpec；每项 Requirement 使用稳定 ID。
3. `RED`：为每个 Requirement 记录能在旧实现上失败的最小测试/检查；环境错误
   和缺依赖不得冒充 RED。
4. `Implementation`：仅修改 Owner matrix 中的路径；跨 Owner 或范围扩张立即
   `BLOCKER`，回到 OpenSpec/计划修订。
5. `Validation`：建立 `Requirement → implementation → test → commit → status`
   矩阵；状态只能是 `PASS | BLOCKED | NOT RUN`，fixture/provider-zero 不得冒充
   真实业务效果。
6. `Deployment`：代码 GREEN 不等于已部署。migration、backfill、provider、
   Candidate、Draft、review、publish、activation、live probe 均须逐项写
   `PASS/BLOCKED/NOT RUN`，未执行不得推断为成功。
7. `Review/Integration`：独立 reviewer 只复核冻结 identity；唯一 integration
   Owner 在 CI 与矩阵闭合后才可合入。不得从 review lane 顺手改生产。

### 豁免

仅纯只读事实核验、审查、监控，或已批准 Goal 内不改变行为的正常验证可以免于
新建 Mission Card/OpenSpec。机械文档/格式修正可以免 RED，但必须在 PR 中写明
豁免理由、精确路径、适用 Requirement ID（若有）及 Reviewer 明确确认。豁免
不能授权 production、migration、provider、DB、deployment 或外部写入。

### 队列与角色

- `Owner`：唯一写者，维护 `CURRENT / BLOCKER / NEXT_READY / TERMINAL`，当前项
  完成后自动进入已批准的下一项。
- `Reviewer`：只读、基于冻结 commit/tree/index 审查；只输出
  `BLOCKER / BACKLOG / REJECTED`，不得形成第二写 lane。
- `Integration Owner`：只负责已批准的机械集成、CI 与最终 identity；不得扩大
  Requirement 或替各 lane 设计新协议。
- `Deployment Executor`：只在单独授权窗口按 runbook 执行，失败即 STOP 并保留
  部分回执；不得把本地/fixture 结果写成 live 事实。

### 状态分层

- `SPEC`：Requirement 已冻结，未说明代码或部署完成。
- `CODE`：实现和 bounded tests 已闭合，未说明真实 provider/DB/live 已执行。
- `DELIVERY`：构建、迁移、配置、部署与 live 回执各自独立记账。
- `BUSINESS`：真实 Candidate/Golden/Review/Active 等业务结果；不得由 fixture、
  provider-zero、代码 GREEN 或容器停止状态推导。

`DELIVERY` 必须再拆成以下六个互不替代的观测维度，每个维度只允许
`PASS | BLOCKED | NOT RUN`，并绑定自己的 identity/receipt：

1. `software`：源码、local build 与 bounded tests；不得包含远端 CI，也不得推导
   镜像或 live 状态。
2. `container health`：exact image/container 的进程与健康；不得由 CI 或宿主端口推导。
3. `provider probe`：exact provider/model/endpoint 的受控调用；provider-zero 只能记
   `NOT RUN`，不得推导语义效果。
4. `provisioning`：migration、配置、public-key rings、backfill 与部署前置；代码中
   存在实现不等于已 provision。
5. `local live`：本地/Colima exact runtime 的实时观察；runtime 停止只能记
   `NOT RUN`，不得写成应用失败。
6. `GitHub live`：GitHub Actions CI、environment/deployment 与远端回执；本地
   software GREEN 不得推导 GitHub live，GitHub CI 也不得推导本地 live。

六个维度之间禁止横向推断；只有各自证据才能改变该维度状态。

### 当前 120/122 状态

截至 2026-08-31，MVP-815 最终有效代码已由 PR #123 以单个重建提交
`ef47bee2b93d6a9cb4511133deaef6e700d915ce` 进入 main，未合入或整体 squash
149 条历史迭代提交。OpenSpec 120 的既有 epoch2 纯 GET C7 已完成 FLOW/UI、
7 分类/67 字段、17/17 citation 与三 PDF 验收；旧 R1、release/receipt/Head/
75 members、五表与生产 8081 不变，DB/provider/model/C4/审批/签名/发布 effects
均为 0。精确源码/tree/制品/回执身份见 `HANDOFF.md` 与 OpenSpec 120
validation report。

OpenSpec 122 与旧 EC-02 只保留历史质量证据；旧实验结论是 `QUALITY_FAIL`，
不在 main。C4 定制仍为 `DEFERRED`，必须从执行时最新 main 新开 Mission，重新
冻结 Candidate/Golden/Evidence、Metric、人工责任、provider/model 与预算；不得
从 C7 PASS 推导 C4 PASS，也不得修改已验收 serving release。

### 当前 830 G1 / BA0 状态

`G1 · 实体页图与独立 FieldAssertion` 已由 PR #126 合入
`origin/main=0e7a26568` 并终态 `PASS`；冻结回执为
`docs/insurance-kb/evidence/830-g1/g1-closeout.json`，适用历史 OpenSpec 为
`openspec/changes/126-830-g1-entity-field-assertion-pages/`。G1 的隔离 Release 仍为
`NOT_FOR_PRODUCTION`，Schema67 质量仍为 `DEFERRED`。

以下保留 BA0 关闭时的产品状态和构建身份；不代表当前文档修订的分支/写域：

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


BA0 设计入口为
`docs/superpowers/specs/2026-09-04-830-ba0-local-build-reuse-design.md`，实施计划为
`docs/superpowers/plans/2026-09-04-830-ba0-local-build-reuse.md`，适用 OpenSpec 为
`openspec/changes/127-830-ba0-local-build-reuse/`。G2 及后续仍为
`LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION`；BA0 `PASS` 后总控
必须先 `RETURN_TO_USER`，不得自动创建 G2 worktree/OpenSpec、写 G2 代码或产生外部 effect。

2026-07-24 生产架构设计与 2026-07-21 北极星继续保留产品、Evidence、Conflict、
弱模型、Candidate 批审和过程护栏，但其 PostgreSQL serving authority、
P11/P12 Projector 与 fenced projection 执行方向已经 superseded。

历史 Mission 0 顺序（仅作架构背景，不是当前任务队列）：

```text
Mission 0
├── 80a5003 Release capability gap matrix → S0-R
└── S0-Q 立即并行
           ↓
S0-R PASS AND S0-Q PASS
           ↓
MVP 纵向闭环；legacy 仅按需改接，物理清理后置
```

S0-R 是输入就绪后的两工作日证伪窗口，不是生产 Kernel 交付承诺；S0-Q 必须
消费 WeKnora/W1 冻结解析制品，禁止人工清洗 Markdown。MVP profile 暂定
`1 Space = 1 RAW KB + 1 release-managed Wiki KB`，不是永久企业不变量。
OpenSpec 043 为 `SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`，不得按旧
`wiki_projector` 语义原样实现。

## MVP 主航道协作

任何会写入仓库、修改迁移/功能规格/行为，或改变 GitHub/外部状态的交付任务，
开工前都必须由 Owner 向用户提交 **Mission Card** 并取得逐项批准。Mission
Card 至少包含：

- 业务目标与现在做的理由；
- 唯一写 Owner、执行模型与 reasoning effort；
- 依赖、预计 PR 数、预计周期；
- exact 验收条件、明确非目标；
- 阻断问题定义。

纯只读事实核验、审查、监控，以及已批准任务内的正常验证，无需另开 Mission
Card；这些例外不得被扩大为写入或外部状态变更授权。未获批准不得写实现、迁移
或功能规格。GitHub 上已有分支、PR、旧测试或历史现场不构成开工授权；W1、
P1、G0a 等后续功能仍须各自取得 Mission Card 批准。

当前排期不包含 Claude。三个 Codex lane 采用“两个独立开发 lane + 一个动态
review/integration lane”，角色按任务轮换。review lane 空档只执行用户已批准
的任务或只读准备，不固定等待。跨 agent 必须有唯一写 Owner；每项工作从最新
`origin/main` 的独立 clean worktree 开始，不得并发写同一文件域。

默认执行模型为 `gpt-5.6-sol high`。只有数据丢失、安全、权限、迁移、真实并发、
跨模块最终审查等高风险任务使用 `xhigh`。`max`/`ultra` 不得作为默认值，必须
由用户单独批准，并提供代表性 eval 证明其收益。

Reviewer finding 只能归为：

- `BLOCKER`：可复现、在 Mission Card 范围内，并会造成明确验收失败、安全/
  权限缺陷、数据损坏或真实并发错误；
- `BACKLOG`：真实但不阻断当前用户价值，进入后续 Mission Card；
- `REJECTED`：不可复现、低概率假设、范围外重构，或不影响当前产品合同的
  Tencent/WeKnora 上游通用问题。上游来源不能免除当前链路实际依赖能力的正确性责任。

普通 PR 最多一轮修复复审，高风险 PR 最多两轮。两轮后仍出现同域新的基础问题，
停止追加补丁，回到设计或拆分 PR。达到 Mission Card 验收且 CI 通过后及时合并，
不追求理论完美。一个 PR 只交付一个用户价值，默认应在 1–2 个工作日完成且
reviewer 可在 30 分钟内理解；超出时拆分，或重新取得用户批准。

硬门禁：

- 没有 OpenSpec 不写功能代码，先测试后实现。AI 默认不 commit/push；用户对指定 Mission 明确授权后，只有总控 AI 可在 exact identity、独立复审和门禁通过后执行 commit/push/PR/merge，开发与评审 lane 不得自行执行。
- 生产只允许经批准、身份冻结的 MiniMax/Qwen/Qwen-VL 能力档弱模型；强模型
  只能用于隔离的离线标注或评测，不能成为生产依赖。
- ReviewPolicy 是按 Space 版本化配置，合法模式为
  `machine_auto | human_batch | hybrid | trusted_import`。任何自动资格缺失、
  漂移、撤销或安全阻断都确定性回落 `human_batch`；人工动作绑定完整
  CandidateRelease，而非逐页面操作。
- 新建 Space 的安全默认值必须是 `human_batch`。
- 生产 `machine_auto` 只有在 G0b 批准后，才能通过显式、版本化的
  ReviewPolicy binding 在其 exact AutomationScope 与 covered capabilities
  内启用；环境、调用者标签或隐式默认均无效。
- superadmin 只可对 exact CandidateRelease 执行一次性 ReviewDecision 动作；
  不得直接改 active pointer，也不得绕过完整性、Space ACL、
  Provenance/Attestation 或恶意内容与其他安全检查。
- 应用只回答 Active WikiRelease 中的已发布知识。原始资料只用于证据核查、
  审核和补编；缺少已发布知识时返回不足或请求补充条件。
- Harness 与 WeKnora 仅通过版本化 REST 和 Source lifecycle event 集成，不
  共享数据库、Redis/Asynq 或队列。MCP 仅是后续 Active Query 消费者适配器。
- WeKnora 新改动必须来自 S0-R capability gap、独立 OpenSpec/Mission Card
  和有界 patch budget；旧 P11/P12 Projector 编号不再自动授权，W1 只保留
  已交付合同。
- Wiki、Evidence、Conflict、版本、不可变 Release、回滚、当前 ACL 与单一
  serving Active Head 是生产闭环不可省略的合同。PostgreSQL Job Store/Outbox
  继续服务任务可靠性，但不得形成第二个 Release serving pointer。
- 第一方 `LLM-wiki-black` 资产只作为迁移来源；保险领域生产逻辑统一收敛到
  Python 3.12 Harness。第三方资产继续按各自许可证管理。

实施采用小 PR、单一领域不变量、strict TDD、独立复审。样本数量、worker 数和
文件数只来自版本化 CapacityProfile 或具体验收画像，不得写成产品硬上限。
总体规划会话维护 Roadmap、控制板、任务卡与验收，不写功能代码；执行会话按
独占文件域实现；评审会话只报告发现，修复退回原 Owner。

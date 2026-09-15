# 28 · 830 开发执行章程

> 适用范围：830 技术蓝图的开发、联调、验收与合并
> 本文只定义 HOW：队列、WIP、证据、停线、写域与合并纪律；WHY/WHAT、数据合同和
> 组件归属只引用 830 技术蓝图，不在此重复。
>
> 当前执行态：`G1=PASS / CURRENT_AUTHORIZATION=NONE / BA0_STATUS=PASS`。BA0 是
> G1 与 G2 之间的一次性工程门，不是产品 Goal；G2 及后续仍为
> `LOCKED_PENDING_EXPLICIT_USER_AUTHORIZATION`。

以下保留 BA0 关闭时的产品状态和构建身份，不代表本次文档修订分支/写域；
文档修订授权与边界见蓝图 §0.1。

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


## 1. 唯一权威与唯一队列

执行权威从高到低固定为：

1. `jlx_enterprise_llm_wiki_technical_blueprint_830.md`：产品目标、逻辑/物理架构、
   数据权威与硬边界；
2. 本章程：执行治理；
3. `docs/insurance-kb/29-goal-cards-830.md`：逐 Goal 的物理结果、DoD 与证据；
4. `AGENTS.md` / `HANDOFF.md`：当前状态、精确身份和下一步，不得发明路线。

冲突时低位文件立即停止执行，并修正低位文件以服从高位权威；只有通过第 9 节路线
变更门并得到用户明确批准后，才可修改高位权威。不能用 Handoff、旧 Spec 或历史代码
覆盖蓝图。815 只作为已证明的物理主链和资产基线；830 不重新架构
`WeKnora upload/parse/SourceRevision → Harness compile → Formal Candidate/ChangeSet →
WeKnora Preview/Review → unique Active Release → source click`，冲突的旧执行口径一律显式
标为 `SUPERSEDE`。WeKnora 始终是唯一 Wiki、唯一审核入口和唯一 serving Active；
Harness 不得产生第二 Wiki、第二审核或第二 Active。

唯一产品 Goal 顺序为：

    B0 → G1 → G2 → G3 → G4 → G5 → G6A → G6B → G6C → G6D → Q0 → G7

当前一次性交付 transition 为：

    G1 PASS → BA0 engineering gate → RETURN_TO_USER → explicit G2 authorization → G2

BA0 占用唯一执行 WIP，但不进入产品 Goal 顺序、不增加产品进度，也不得改变 G2 DoD。

- 全程产品 `WIP=1`：同一时刻只能有一个 Goal、一个 `NEXT_PHYSICAL_RESULT` 和一个
  结果 Owner；纠偏也占用该 WIP。默认一个实现写域，满足第 7 节的同 Goal 受控并行条件
  时最多允许两个互斥写域，但不能形成第二个产品结果或提前建设下游 Goal。
- 不得跳卡、并卡、倒序、预开 successor，或以“可并行”为由提前实现下游。
- `Q0` 必须在 `G6D` 后、`G7` 前运行。此前按当前 Goal 实现可替换编译与独立审核的
  初始实现、协议回放、真实隔离链路和确定性负向检查，持续报告 `QUALITY=DEFERRED`；
  不以提前完成专家标注/领域优化阻塞平台开发，也不把接口桩或 Seed Cases 当成真实流程。
  专家 Canonical Golden、领域指标和生产准入由 Q0 承接，不另建质量平台或调参支线。
- 下一 Goal 只有在当前 Goal 真实 `PASS`、Evidence Pack 完整、总控关闭当前写域、
  适用工程门通过且用户明确授权后才能启动；前卡 PASS 是必要条件，不是自动开工授权。

## 2. 结果硬、路径软

每个 Goal 可以调整实现路径，但结束结果、顺序和验收门不可调整。总控把 Goal 切成
`0.5–1.5` 个工作日的小任务；每个小任务必须只交付一个可直接观察的
`NEXT_PHYSICAL_RESULT`，不能同时承诺“顺便完成”第二结果。

启动简报必须冻结：

| 字段 | 要求 |
|---|---|
| `GOAL_ID` | 当前唯一 Goal |
| `CURRENT_RED` | 当前真实链上的唯一可复现失败或未成立状态 |
| `NEXT_PHYSICAL_RESULT` | 本任务结束时可打开、调用、比较或回点的唯一结果 |
| `FROZEN_INPUT` | exact Git、数据、Schema、模型/Provider、WeKnora 与策略 identity |
| `VALIDATION_LEVEL` | 本任务适用的 `D0 / D1 / D2 / D3`；按最高实际风险选择，不得默认升级 |
| `DOCKER_ACTION` | 仅可为 `SKIP / REUSE / BUILD_AFFECTED`，默认 `SKIP`；非 `SKIP` 时列 exact image |
| `ARTIFACT_IDENTITY` | 本次复用、构建或运行制品的可重算输入 identity；不能只写 Git SHA |
| `OWNER` | 唯一结果 Owner |
| `WRITE_DOMAINS` | exact path 与外部对象；未列即只读 |
| `NON_GOALS` | 下游、通用化、平台化和后置强化 |
| `TIMEBOX` | `0.5–1.5` 个工作日和明确截止时间 |
| `REAL_DOD` | 能改变本 Goal 产品状态的真实证据 |
| `STOP` | 超时、重复失败、第二层前置和外部阻断的终态 |

小任务启动后的第 2 个工作日必须做真实演示：使用冻结真实输入，在真实相邻组件上
展示该物理结果或展示精确失败。连续 48 小时代码/文档增长，但 Goal 的真实产品状态
不变，自动停线；commit、测试或 Spec 状态不能重置计时。

产品进度只认可 29 号 Goal Cards 定义的真实状态变化。以下只能作为支持证据，不能
增加进度：`SPEC PASS`、测试 `GREEN`、fixture/synthetic replay、receipt 数量、代码
或文档行数、文件数、接口桩、截图数量、typed failure。报告不得用百分比或“完成了
多少子卡”代替：

    CURRENT_GOAL
    GOAL_PRODUCT_STATE
    CURRENT_RED
    NEXT_PHYSICAL_RESULT
    LAST_REAL_RESULT_AT
    EVIDENCE_PACK

## 3. Definition of Done 与 Evidence Pack

### 3.1 Goal Definition of Done

一个 Goal 只有同时满足以下条件才可 `PASS`：

1. 29 号 Goal Card 的唯一物理结果在冻结真实输入与真实集成运行时中成立；
2. 运行代码、输入、输出及 WeKnora 对象具有可重算的 exact identity 和 lineage；
3. 该卡当前阶段的正向门、反向门和不变量由可复核结果或真实回点证明；协议/来源定位
   正确不等于领域语义正确，Q0 业务裁决还须独立专家金标和逐项评估，不能由生成者自评替代；
4. 验收分母、阈值和预期集合在运行前冻结，运行后未删除失败样本；
5. 没有第二 Wiki、第二审核、第二 Active、第二 Evidence authority 或未授权外部写入；
6. Evidence Pack 完整，并经只读审查 lane 核对；
7. 当前写域已关闭，未留下会改变结果的半成品或隐含前置。

合同允许的业务 `UNKNOWN` 可以诚实保留，但不得把 expected-present、未尝试、解析
失败或缺失证据改写为 `UNKNOWN` 来过门；不得跳过字段、格式、样本或负向场景；
不得用人工补齐后的内容冒充模型成功。模型原始输出/指标与专家修订后的输出/指标必须
分别冻结、分别报告，人工修订产生新 revision，不回写原始模型分数。

2026-09-05 获用户授权的文档修订仅按蓝图 §0.1 的 R830-01—06 检查五份现有文档的覆盖与
一致性，并独立复核冻结 diff；不为文档检查启动 Provider、Docker 或重跑产品验收。
该文档检查通过只说明规格修订可用，不解锁产品 Goal、不构成领域质量 PASS。

### 3.2 Evidence Pack

Evidence Pack 是当前 Goal 的最小可复核索引，不是第二套 Evidence 系统。它只引用
蓝图定义的单一内容/Evidence authority 和不可变原始制品，至少包含：

- `GOAL_ID`、任务 identity、base/head SHA、提交清单与运行时代码 identity；
- 冻结输入、Schema/合同、数据集、模型/Provider、配置和 WeKnora 版本 identity；
- 真实 request/raw/terminal/output、hash、时间、调用计数及原始保存位置；
- expected/actual/diff、机器验收结果、失败样本和负向门结果；
- 可回点的 SourceLocator，以及对应 Candidate/page/review/release/Active identity；
- 真实演示记录与复现步骤；
- 模型原始报告和专家修订报告两个独立条目；
- 外部写入清单、未发生副作用证明、剩余风险和资产处置标记。

缺失、`UNKNOWN`、跳过或人工说明不能代替原始制品。Evidence Pack 的数量、体积或
receipt 数量本身不构成 PASS。

## 4. 风险分层验证与代码资产治理

### 4.1 D0–D3 与 Docker 动作

验证按实际风险分四层；层级决定允许动作，不替代当前 Goal Card 的 `REAL_DOD`：

| 层级 | 适用范围 | 必须做 | Docker 约束 |
|---|---|---|---|
| `D0` | 文档、Schema 文档，以及不进入 runtime 的纯规则或配置变更 | 格式、链接检查及直接相关的 focused tests | 禁止 Docker；`DOCKER_ACTION=SKIP` |
| `D1` | 日常代码切片 | focused tests、受影响模块的局部编译；需要相邻组件时复用常驻基础设施与 `dev-start` | 不构建镜像；只可 `SKIP` 或复用 exact artifact |
| `D2` | 冻结 integration head 后的集成制品确认 | 总控按 change-impact 只构建实际受影响镜像一次，并记录不可变 digest | 仅总控可 `BUILD_AFFECTED`；未受影响镜像 `REUSE` |
| `D3` | Goal 的真实部署与验收 | 只部署 D2 产出的同一 digest，运行该 Goal 的 `REAL_DOD` | 不得再次 build；`DOCKER_ACTION=REUSE` |

`DOCKER_ACTION` 只有 `SKIP / REUSE / BUILD_AFFECTED` 三个合法值，默认 `SKIP`。
`REUSE` 必须命中完全相同的 `ARTIFACT_IDENTITY`；`BUILD_AFFECTED` 只能用于 D2。
日常验证不得把 `build-all` 或 `start-all --no-pull` 当作普通正确性检查。只有所有镜像的
输入都被真实影响时，总控列出每个受影响镜像并逐项 `BUILD_AFFECTED`，其结果才可能等价于
一次全构建；“谨慎起见”不是全构建理由。

### 4.2 构建触发与 artifact identity

某镜像只在以下任一条件成立时进入 D2 构建清单：对应 runtime 源码必须嵌入镜像；
Dockerfile、build context、entrypoint、base image、lockfile、依赖 manifest、build args 或
platform 改变；或当前不存在可用的 exact artifact。docs-only、tests-only、可从外部路径
加载且未进入镜像输入的 Schema/Prompt/Harness 局部改动，以及同一 identity 的重复验证，
均不触发构建。

`ARTIFACT_IDENTITY` 至少包含 service、相关 source subset、Dockerfile/context、lockfiles、
base image digest、build args 与 platform；不适用项须显式标记，不能只用 Git SHA 代替。
D2 输出必须把该 identity 绑定到不可变 image digest。只有 runtime、data、config 和 Goal
identity 全部一致时，Goal 真实运行结果才可复用；真实物理边必须重新成立时，不得拿旧缓存、
旧 receipt 或同名 tag 冒充本次结果。

D2 必须 `lookup-before-build`：exact hit 只能返回 `REUSE`，Docker build invocation=`0`；
miss 最多执行一次 `BUILD_AFFECTED`。同一 identity 命中多个 image、label/OS/arch 不符或
inspect 失败时一律 fail closed，不能按 `latest` 或创建时间选择。D3 只启动 D2 绑定的 exact
image，必须显式 `--no-build --pull never`；当前会执行 `compose up --build` 的
`start_all.sh --no-pull` 不构成 D3 入口。BA0 的 D3 只做 standalone、无业务依赖的
`CONTAINER_ARTIFACT_SMOKE`；不得为它另建数据库初始化链或把它写成后续产品 Goal 的 HTTP
health 验收。

### 4.3 集成、单一实现与 worktree 收尾

总控拥有唯一 D2 integration build 权。Win1、Win2、Win3、WeKnora 窗口和只读审查 lane
不得为同一 integration head 重复构建；它们只提交 change-impact 与 focused verification。
PR 边界按“可独立保持 main 健康的物理集成结果”划分，不按 agent task、窗口、worktree 或
提交数量划分。

每个产品能力只有一个目标生产实现。第 7 节允许的最多两个互斥写域仍须服务同一 Goal、
同一 `NEXT_PHYSICAL_RESULT`；不得借验证或兼容工作形成第二产品结果。确需临时兼容双轨时，
必须在启动简报登记唯一 Owner、明确 expiry 和删除验证，过期即删除或停线裁决。

新建的 830 worktree 在 Goal `PASS` 或 `STOPPED` 后、移除前，必须检查并登记脏文件、相对
正式 base 的未集成提交清单，以及每项 `KEEP / REWIRE / FREEZE / SUPERSEDE` 与物理处置；
未完成该收尾不得移除。worktree 只是施工空间，不是归档。历史 branch/worktree 只在 B0
登记；B0 裁决和用户授权物理处置前不得删除。

### 4.4 验证预算与既有验收权威

B0 只从已有日志、receipt 或 CI history 重算当前验证入口的样本窗口、样本量与 p50/p95；
样本不足记 `NOT_MEASURED + reason`，不阻断 B0，待首次获授权的 D2/D3 实测补齐，不为测量
启动环境。验证预算不得预写死 30 秒、3 分钟、20 分钟等阈值。同一
`ARTIFACT_IDENTITY` 出现重复 `BUILD`，或验证超过预算却没有 `NEXT_PHYSICAL_RESULT`
变化，立即标记 `YELLOW` 并停止新一轮构建/验证，由总控复核。

D0–D3 只约束选择成本与制品复用，不降低任何现有 Goal DoD 或 Evidence Pack，也不授权
建立第二验证、receipt 或制品平台；所需 identity、digest 和结果只写入现有 manifest 与
Evidence Pack。

缓存只是固定本机 builder 的性能状态，不是制品 authority。缓存被安全清理只允许导致
下一次变慢，不能改变 artifact identity 或正确性；不得为了测量主动 prune cache、重复冷建
或构造临时源码 identity。当前 BA0 的详细边界以
`docs/superpowers/specs/2026-09-04-830-ba0-local-build-reuse-design.md` 为准：最多一次合法
app image build，随后同 identity 请求必须在 lookup 阶段零构建复用。

## 5. SDD、TDD、OpenSpec 与提交纪律

- 严格执行 SDD/TDD。先保存当前真实失败，再写最小 RED 回归；按同一失效机制集中修复
  受影响的接口和阶段，跑 focused verification 与必要的相邻组件检查，再验证对应真实边。
  不把“一个根因”解释成只能改一个症状或每修一个分支必须构建部署；具体按 §11 执行。
  全套适用验证在 Goal 关闭前运行，不在每份材料或每次恢复时重复。
- 新建 OpenSpec 的唯一触发器是：已有一份已保存、可复现的真实失败，且现有合同
  无法安全解决它。两项缺一即不得新建；新 Spec 还必须直接产出当前下一物理结果，
  不能承载未来平台或 successor。
- OpenSpec 的目录、ID、API、字段、类型、枚举和错误码使用英文；标题、目标、场景、
  验收、非目标与规范正文使用中文。不得维护中英文两份语义 authority。
- 正常开发每 `2–4` 小时、每个最小 GREEN slice 或交接前，以最早者为准形成小提交。
  每个提交只关联一个 `GOAL_ID` 和一个 `NEXT_PHYSICAL_RESULT`，提交说明必须写明二者。
- 分支是资产来源，不是合并单位。禁止整包合并半成品/混合分支；总控只能选择性接入
  已验证提交，并逐项记录 source SHA、目标落点和回归结果。
- 所有既有资产在接线前必须标注：`KEEP`（原样保留）、`REWIRE`（保留行为、改变
  接线）、`FREEZE`（保留审计、不再扩张）、`SUPERSEDE`（旧执行语义失效）。未标注
  资产不得进入活动 Goal。

## 6. 一次纠偏、复杂度线与前置递归

“同一真实阻断”由冻结输入、失败物理边和错误指纹共同识别。它只允许一次纠偏；
开始前必须登记：真实失败证据、为何原路径不能继续、唯一新增步骤、exact 写域、最
长时限，以及紧随其后的原 `NEXT_PHYSICAL_RESULT`。

纠偏必须满足：

1. 只新增一个步骤，不改 Goal 结果门，不开新 Goal/successor；
2. 完成后立即回到原流程，重跑原真实边，不得顺便重构或平台化；
3. 同一阻断第二次失败，立即 `STOP/RETURN_TO_USER`，由用户裁决；
4. 若 A 需要前置 B，而 B 又要求新前置 C，视为第二层前置，立即
   `STOP/RETURN_TO_USER`；不得用拆卡、OpenSpec 或第三个窗口隐藏递归。

复杂度只按以下两级处理：

- `YELLOW`：预计或实际达到 5 个生产文件、500 行生产代码或 4 小时中的任一项。
  它只触发总控复核范围、diff 和更小切片，不自动判失败；复核结论必须入 Evidence
  Pack。
- `RED`：需要新服务、新数据库表、第二 Wiki、第二审核、第二 Active、第二 Evidence
  authority，或通用 Prompt 平台。未经用户明确批准不得实施；发现即停线。把同一
  能力换名、藏进 adapter/receipt 或写在 WeKnora/Harness 另一侧仍视为 RED。

## 7. 单写域协作与集成权

总控每次只签发一份产品结果简报。以下是默认边界，精确路径仍须在简报中列出；
默认边界不构成并行授权。

| 角色 | 唯一写域 | 禁止 |
|---|---|---|
| 总控 | Goal 状态、派工简报、资产处置、Evidence Pack 索引、唯一集成分支与 D2 构建 | 与窗口竞争产品实现；用局部 GREEN 改产品状态 |
| Win1 | 当前 Goal 明示的 Harness 业务/编译路径及同切片测试 | WeKnora 核心、审核/Active 复制品、未列路径 |
| Win2 | 当前 Goal 明示的验证、Golden/质量消费路径及同切片测试 | 改冻结门槛、回写模型原始结果、另建 Evidence authority |
| Win3 | `WRITE_DOMAINS=∅`；纯只读审查 lane | 修改代码/文档/制品，边审边修，代替 Owner 产证据 |
| WeKnora 窗口 | 当前 Goal 明示的 WeKnora `internal/`、`frontend/` 或其 migration 切片 | Harness 寿险语义、第二 Wiki/审核/Active、无授权外部发布 |

默认只有一个实现窗口拥有非空产品写域。仅当同一 `NEXT_PHYSICAL_RESULT` 确实横跨
Harness/WeKnora 或实现/验收两块互不重叠的路径，且串行会让集成物理结果无意义地等待时，
总控可在同一 Goal 下授权最多两个并行写域。授权前必须额外冻结：互斥 exact paths、
共享合同 hash、唯一集成顺序、每条 lane 的 0.5–1.5 日交付、冲突处理人和共同截止时间。

受控并行仍只有一个产品 Goal 和一个结果 Owner；任一 lane 不得自行宣布 PASS、提前做下一
Goal、修改共享合同或产生独立 Candidate/Release 终态。第三个非空实现写域、路径重叠、
接口边做边改或出现第二个物理结果，立即退回串行并触发范围复核。每个文件、数据库对象、
外部对象和证据制品始终只有一个写 Owner。Win3 永远只读，不计实现写域。

总控是唯一 integration、D2 build、push/PR、冲突裁决与 merge authority；其他窗口只交付本地
小提交和证据，不得自行合并、整包 cherry-pick 或形成第二集成线。

Win3 每 2 小时只读检查：当前 Goal/状态是否真实、`NEXT_PHYSICAL_RESULT` 与截止、
活动 diff 是否仍在写域、是否出现第二层前置，以及 YELLOW/RED 是否被登记。发现
RED、重复阻断或第二层前置时只发 `STOP` 报告，由总控冻结写域；Win3 不提供新实现
延长任务。

## 8. 强制停线与复盘

出现以下任一情况立即停止当前 Goal 的代码、Provider 和外部写入：

- 连续 48 小时没有 Goal 产品状态变化，或第 2 个工作日没有真实演示/精确失败；
- 同一真实阻断的一次纠偏再次失败；
- 出现第二层前置、`RED` 复杂度或越过写域；
- 小任务达到 `TIMEBOX`，验收只能靠 `UNKNOWN`、跳过、改分母或人工补齐；
- 同一 artifact identity 重复构建，或验证超出已测预算且没有下一物理结果变化；
- 需要改变队列、结果门、数据权威，或产生第二 Wiki/审核/Active/Evidence；
- 运行 identity、冻结输入或权威合同无法确认。

总控冻结 exact 状态与所有写域，在半个工作日内形成停线复盘：

1. 最后一个真实产品状态、最后物理结果及时间；
2. base/head、冻结输入、外部对象和活动 diff；
3. 阻断指纹、原始失败证据、时间线和已用的一次纠偏；
4. 是否触发第二层前置、YELLOW/RED、越权或验收作弊；
5. 未合并资产的 `KEEP/REWIRE/FREEZE/SUPERSEDE` 处置；
6. 可复现步骤、Evidence Pack 链接和需要用户裁决的互斥选项。

复盘期间不得后台继续施工，也不得自动开第三次尝试。用户只能裁决：按原 Goal/原
结果门恢复、以固定失败终态关闭，或通过路线变更门。

## 9. 路线变更门

普通代码、环境、Provider、测试或进度失败不触发路线变更，只进入当前 Goal 的纠偏
或停线。凡涉及 830 蓝图 WHY/WHAT、唯一顺序、数据 authority、WeKnora 唯一
Wiki/审核/Active、Goal DoD，或要求改造已证明的 815 主链，必须：

1. 先 `STOP/RETURN_TO_USER`，保存真实不可行证据与停线复盘；
2. 说明现有合同为何无法解决，并给出不恢复第二系统的最小选项；
3. 取得用户明确批准；
4. 按权威顺序更新蓝图、章程、Goal Cards 和短状态入口；
5. 对受影响资产标注 `KEEP/REWIRE/FREEZE/SUPERSEDE`，重新冻结输入与 DoD 后再开工。

不得事后降低门槛、回写旧 Evidence Pack 或把失败 Goal 改名为新 Goal 来绕过变更门。

## 10. 每两小时控制问题

总控与 Win3 只回答五个问题：

1. 当前唯一 Goal 和下一物理结果是什么？
2. 自上次检查以来，哪个真实产品状态发生了变化？
3. 当前 diff 是否只服务该结果并保持单写域？
4. 是否出现重复阻断、第二层前置、YELLOW/RED 或验收作弊？
5. 若现在停线，Evidence Pack 是否足以让另一人独立复现与裁决？

任一答案不明确，停止新增代码，回到当前真实红灯。

<a id="engineering-quality-baseline"></a>

## 11. 工程质量与执行效率基线（2026-09-15 用户确认）

本节适用于整个 Enterprise LLM Wiki 项目、所有 Goal、实现、修复、总控派工和评审，
不只适用于 G3。业务结果、工程正确性、可维护性和执行成本共同约束实现；单个样本跑通
不构成可交付的软件设计。规则落实在现有设计、代码和必要验证中，不新增审批、签名、
验收平台或长期重构项目；用户既有授权有效，不因本节重复索要批准。

### 11.1 先复用，再确定必须补的能力

- 动手前在现有任务说明中简述：具体问题、已查的 WeKnora 原生/本项目/MVP 能力及路径、
  可复用部分、实际缺口、唯一负责模块和外部接口。已有说明可直接引用，不为每次修改新写方案。
- 优先复用稳定实现、成熟库和既有接口；只为明确缺口增加适配。参考原生代码须核对本地
  版本和实际限制，不把“上游有”当成正确性保证，也不为了复用继承已确认的缺陷。
- 例如本地 `wiki_ingest.go`、`wiki_ingest_batch.go` 和 `recover_pending_wiki_tasks.go`
  已有持久待办与触发器分离、按需页面读取和运行内缓存、退出统计等设计，可按需参考。
  原生 Wiki 的直接写页路径不能绕过本项目已确认的来源、审核和唯一 Release 合同。
- 遵循职责单一、高内聚、低耦合、组合优先和按需抽象：只在实际需要替换的解析器、模型、
  业务编译器、审核器或存储边界建立窄接口，不为预测中的需求建通用框架。

### 11.2 适配层有边界，核心流程有唯一实现

- 领域规则、任务状态、外部 I/O 与界面展示分开负责；核心逻辑不依赖某次任务编号、临时
  文件路径、测试知识库 ID、某个样本名称或固定模型家族。能力策略通过显式配置注入，
  身份只负责权限与数据隔离，模型身份按实际配置校验和记录。
- 薄适配器只做协议/数据转换和调用既有能力，不能重新实现恢复、审核、发布或业务事实。
  跨语言边界以公开合同和一致性样例约束；禁止业务模块调用另一模块的私有函数串流程。
- 临时脚本可以诊断或执行一次迁移，不能成为正常上传、编译、恢复、发布的必经路径。
  兼容分支必须明确处理哪一版本、唯一 Owner 和退出条件，并复用现有 §4.3 的记录。
  不为减少文件数把不同职责塞进一个巨型文件，也不以包装层数量衡量设计质量。

### 11.3 成功结果可恢复，失败恢复由状态和依赖决定

- 解析、向量化、抽取等昂贵工作按可独立恢复的处理单元保存结果及依赖身份。后续兄弟任务
  失败不能丢弃已完成的有效结果。整批发布可以保持原子性，中间成功计算仍须保留。
- 幂等与复用键区分数据作用域、输入版本和影响结果的策略；有意按协议跨实现复用时明确
  兼容条件，不能仅因代码提交号变化全部失效，也不能错误复用不同模型/参数的向量。
- 恢复从有效检查点和失效依赖推导待做单元；结构化错误类型辅助判断可恢复性，禁止将
  错误字符串、某次 run 前缀或不断增长的阶段白名单当作恢复流程的主体。
- 长时 I/O、反序列化、哈希和模型调用不占据任务心跳所需的事件循环，不在共享锁或数据库
  事务内等待外部调用。复用既有 JobStore、租约和代次隔离，防止旧任务回写；不另建队列。
- 请求可能已发送但结果未知时先核对既有回执/供应商幂等能力，不盲目补发；不能无条件
  声称外部调用 exactly-once。技术失败、未执行和业务未知分别保留，禁止互相替代。

### 11.4 调用治理与失败成本是基础能力

- 每条外部调用链只有一个明确的重试决策 Owner；SDK、批处理和任务层的自动重试需统一
  预算，不能叠乘。仅重试必要失败单元；参数/权限等永久错误先修正，限流按供应商提示
  和有界退避处理。并发和速率按实际共享配额限制，不能通过多 worker 绕过预算。
- 实际发送尝试、响应/不确定终态、耗时和可获得的用量在成功、失败、取消、超时路径都
  记录，复用与新调用分开汇总。统计独立于业务产物是否生成，缺失用量标为未知而不是零；
  HTTP 200 不等于有效业务输出。复用已有记录存储，不新建观测平台。

### 11.5 模型输入与内部审计结构分离

- 模型只接收本次所需字段/问题、必要规则、去重后的相关原文和短引用编号；完整来源身份、
  哈希、权限与审计对象留在服务端。禁止把同一来源元信息在每个字段内重复展开后直接外发。
- 分批依据实际序列化后的输入/输出预算，结合提供方限制和已有测量；先消除重复上下文，
  再决定窗口，不靠无限拆小批次掩盖输入膨胀。不硬编码产品字段数为平台能力上限。
- 保留原文优先、保义编译和精确来源；不得为缩短输入静默丢掉条件/例外/表头。自由发现
  不能只用 Schema 字段匹配选材，覆盖不足必须可见，不伪装成“没有信息”。

### 11.6 按变化和依赖处理，读取路径保持轻量

- 新增材料只重做受新输入影响的工作，历史对象以已验证的不可变引用和必要摘要复用。
  若既有发布合同要求完整候选，在发布边界集中组合；不得每个阶段/每个字段反复携带、
  解码和校验全部历史正文。方案说明主要成本随新增量、关联量还是历史总量增长。
- 状态查询、页面浏览、引用和预览不重新解析原件、不隐式调用模型。异步任务提交先持久
  记录并及时返回可查询身份，昂贵准备由 worker 处理。不可变结果可缓存，当前权限与
  来源撤销仍按既有合同校验；缓存不存在只影响性能，不能影响正确性。

### 11.7 集中检查真实边界，不逐症状部署

- 外部接口在适配边界统一检查响应数量、顺序/index、维度、空值、错误类型和内容结构；
  字段缺失与合法空值按合同区分。共享状态的读写采用一致同步方式，取消后任务正确收尾。
- 同一失效机制重复出现时，先查所有受影响阶段，例如来源读取、字段规划、抽取准备和
  结果校验中的心跳阻塞，集中修复共同机制；不再“加一个分支→构建→换阶段再失败”。
- 用已有真实失败记录和代表性大输入验证跨组件合同，必要时使用故障注入或并发检查；
  mock/局部测试不能代替实际序列化、接口和部署接线。先离线复用记录，修复后只跑必要
  的真实边；检查通过且无新变更/失败/未决风险后停止重复验证，继续交付。
- 交付报告说明结果、关键调用/重算/构建次数、实际耗时与未测限制。可扩展、高可用等
  结论需对应规模或故障恢复证据；不以增加服务数量或测试数量证明质量。

### 11.8 按组件构建，缓存可丢失，入口可复现

延续 §4 的 `SKIP / REUSE / BUILD_AFFECTED`，按实际制品依赖决定动作：

| 变化 | 默认动作 |
|---|---|
| 上传材料、恢复任务、分类或内容变化 | 不构建应用，复用现有部署 |
| 外置模型/批量/运行参数 | 校验并更新配置，必要时只重启相关进程 |
| Python 业务逻辑 | 验证并更新 Harness 制品，复用无关 Go/前端 |
| Go 逻辑 | 只编译受影响应用，复用依赖、构建缓存及其它组件 |
| 前端逻辑 | 只更新前端制品，按其实际部署方式交付 |
| 文档、测试、未打入制品的提示词或 Schema | 不触发无关组件构建 |

实际打入镜像或互相嵌入的组件须按依赖构建，不能虚报复用。构建来源采用冻结源码快照，
不把无关文档提交当作全部组件变化，也不锁住整个活动工作目录等待构建结束。嵌入版本
信息必须如实对应组件来源。依赖层与代码层分离，缩小构建上下文；缓存为空可合法冷建，
不能因缺缓存标记而失败。正式构建入口在仓库维护，禁止靠临时字符串改写 Dockerfile
才能导出/部署；复用已有构建工具，不新建制品平台。

### 11.9 设计不确定时讨论，评审聚焦当前缺陷

当现成能力无法满足要求、职责/数据权威不清、必须改变已确认合同，或只能继续堆叠特殊
分支时，先说明已核对的代码、具体缺口、可选方案与代价，并给出建议，请用户讨论。
不以“先跑通”掩盖未决架构问题；已授权范围内的常规实现选择由 Owner 完成。

开发说明与现有评审检查本节相关项即可，不要求新增表单。当前切片若重复付费/重复重算、
丢失成功结果、破坏恢复或来源、依赖临时脚本/样本特例才能完成，应作为当前工程缺陷
修复，不能用 FLOW PASS 覆盖。未涉及的历史债务登记到现有清单，不以全项目重写阻塞
当前交付；成熟适配器、合理兼容层本身不是缺陷。优化与结构修复以减少实际成本和明确
职责为依据，保留必要证据与唯一权威，不用删除校验换取表面速度。

# 28 · 830 开发执行章程

> 适用范围：830 技术蓝图的开发、联调、验收与合并
> 本文只定义 HOW：队列、WIP、证据、停线、写域与合并纪律；WHY/WHAT、数据合同和
> 组件归属只引用 830 技术蓝图，不在此重复。
>
> 当前执行态：`G1=PASS / BA0_DESIGN_AND_PLAN_ONLY`。BA0 是 G1 与 G2 之间的一次性
> 工程门，不是产品 Goal；G2 及后续仍为
> `LOCKED_PENDING_BA0_PASS_AND_EXPLICIT_USER_AUTHORIZATION`。

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
- `Q0` 必须在 `G6D` 后、`G7` 前运行。此前只保留已批准的扩展点和冻结输入，
  不提前建设 Golden/调参支线、通用质量平台或 Q0 的替代入口。
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
3. 该卡所有正向门、反向门和不变量均由机器结果或真实回点证明；
4. 验收分母、阈值和预期集合在运行前冻结，运行后未删除失败样本；
5. 没有第二 Wiki、第二审核、第二 Active、第二 Evidence authority 或未授权外部写入；
6. Evidence Pack 完整，并经只读审查 lane 核对；
7. 当前写域已关闭，未留下会改变结果的半成品或隐含前置。

合同允许的业务 `UNKNOWN` 可以诚实保留，但不得把 expected-present、未尝试、解析
失败或缺失证据改写为 `UNKNOWN` 来过门；不得跳过字段、格式、样本或负向场景；
不得用人工补齐后的内容冒充模型成功。模型原始输出/指标与专家修订后的输出/指标必须
分别冻结、分别报告，人工修订产生新 revision，不回写原始模型分数。

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

- 严格执行 SDD/TDD。先保存当前真实失败，再写最小 RED 回归，只修一个根因，跑
  focused verification，随后立即重跑同一真实边；全套适用验证在 Goal 关闭前运行。
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

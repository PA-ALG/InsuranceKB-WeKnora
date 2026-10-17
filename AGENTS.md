# Enterprise LLM Wiki 协作约束

本文件适用于本仓库及其所有开发分支。用户后续明确指令优先。当前唯一技术权威是
[`jlx_enterprise_llm_wiki_technical_blueprint_1001.md`](jlx_enterprise_llm_wiki_technical_blueprint_1001.md)
（下称"蓝图"），事实依据见 [`docs/design/01-调研结论.md`](docs/design/01-调研结论.md)，切片 Spec 在
[`docs/design/slices/`](docs/design/slices/)。开发只需读蓝图、本文件与当前切片 Spec。830 蓝图、
`docs/insurance-kb/`、`docs/superpowers/`、`HANDOFF.md` 与 `openspec/` 为历史背景，冲突时以蓝图为准。

## 产品定位

本仓库的产品是 **Enterprise LLM Wiki**：把寿险材料持续编译为有实体、有版本、有来源、
可审核、可整版发布与回滚的企业知识，人与 Agent 读取同一个已发布版本。WeKnora（Go/Vue）
是唯一 Wiki、审核、Release、Head 与读取权威；Python Harness 负责保险领域编译并提交
Candidate。

## 硬边界

1. 一个 scope 只有一个 WeKnora Head；Harness 不保存 serving Head，不建第二 Wiki、第二审核、
   第二 Evidence 生命周期。
2. Harness 与 WeKnora 只经版本化 REST、Source lifecycle event 与 `contracts/` 下的 JSON Schema
   集成，不共享数据库、Redis/Asynq 或队列。
3. 持续跟随 WeKnora 上游升级：项目代码放在自有包与扩展点中；修改上游文件只在没有其他办法时
   进行，每处登记在 `docs/design/upstream-patches.md`，数量只减不增。以最终效果为准，确需改上游
   或重写接口时可以做，但必须登记原因与退出条件。
4. Go 平台代码只处理通用 CandidateBundle / Member / Evidence / Locator / Release；险种、Schema、
   消歧、质量评分、业务文案只在 Harness。
5. 受管 KB 的所有读入口只读 Active 或 pinned Release；所有写入口拒绝旁路。原始材料只作
   证据与补编，不直接回答业务问题。
6. 具体产品事实必须有可回验的原文或专家修订来源。模型补充的通用概念必须标注
   `MODEL_GENERATED`，与有原文依据的内容分开显示。
7. 来源定位失败返回 typed error；不打开当前版本代替历史版本，不猜相似文本，不跳第 1 页。
8. 发布采用"先发布后抽检"：确定性检查通过、所属 pack 已通过质量准入、独立审核分数达到
   可配置门槛的内容才能自动上线并标注"机器审核"；其余进入人工队列。门槛调整必须留版本。
9. 模型通过 OpenAI 兼容接口按阶段配置；质量结论只认生产目标模型。密钥、凭据、本机路径、
   内网地址不得进入代码、日志、测试数据或文档。

## 首要原则：解决通用机制，不按样本打补丁

1. **严禁 case 定制。** 产品代码、提示词与配置不得按产品编号、样例材料、固定 release/run ID、
   测试夹具或预期答案增加特判或捷径。旧失败 case 可以成为回归测试，修复必须对应一个
   可说明的通用规则。
2. **领域规则是数据。** 险种字段规则、关键词、组成要素、展示分组写在版本化 SchemaPack /
   FieldExtractionConfig / PresentationProfile 中；代码只按少量枚举（如 `audit_kind`）分派。
3. **验收能反驳过拟合。** 至少用两款不同险种或不同结构的材料验证受影响机制；离线回放证明
   工程链路，不代表真实模型质量已通过。

## 核心工程原则

1. **架构与领域优先。** 先明确业务目标、领域边界、模块职责、依赖方向和数据流再编码；设计
   完整、实现克制；新的共性抽象延迟到第二个真实用例出现时引入。
2. **Deep Modules。** 模块以少量稳定接口封装有实质价值的能力，调用方不需要了解内部步骤、
   存储细节或恢复机制。手写文件不超过 500 行，接近上限时调整模块边界，不机械拆文件。
3. **边界与数据流清晰。** 协议模型、领域模型、持久化模型和视图模型不互相泄漏；跨边界数据
   在边界校验并显式转换；不跨模块访问私有名；生产代码不含测试钩子。
4. **安全与隔离默认开启。** 明确 tenant、Space、principal 与 ACL；外部输入、上传材料和模型
   输出均不可信；失败关闭。
5. **面向并发与故障。** 幂等、竞态、事务边界、超时、取消、重试、背压和资源释放；每条外部
   调用链只有一个重试 Owner 与明确预算；成功结果可恢复复用，结果未知先对账不盲目补发。
6. **完整前端体验。** 覆盖加载、空状态、错误、重试和可访问性；页面、引用与 Agent 内容遵守
   同一 Release；预览和查询不隐式触发解析或模型调用。
7. **复用稳定能力。** 先核对 WeKnora 原生与本项目已有能力；新增依赖前检查 `go.mod`、
   `harness/pyproject.toml`、`frontend/package.json` 及锁文件。
8. **为维护者保留上下文。** 非显然的设计决策、兼容约束和已知缺陷写明原因与移除条件；关键
   决策同步到蓝图 §14；禁止缺少原因的 `TODO`。
9. **可验证、可观测、可回滚。** 测试与真实运行证据分开记录；错误与日志保留脱敏的诊断上下文。
10. **删除优于兼容。** 内部路径被替代后直接删除旧实现，不留 shim 或双写；对外合同、持久化
    格式与迁移的兼容单独评估并写明退出条件。
11. **Tracer Bullet。** 先做最小但有真实业务价值的纵向切片，贯通入口、领域逻辑、持久化与
    用户可见结果，再沿同一实现扩展。
12. **按领域组织代码。** 目录与文件按职责命名，不使用 Goal、mission 或版本后缀。

> **变更速查**：提交前运行 `git diff --check`。Go 运行受影响包的 `go test`；Harness 在
> `harness/` 下运行 `uv run pytest`、`uv run ruff check .`、`uv run mypy src tests`；前端在
> `frontend/` 下运行 `npm run type-check`、相关测试与 `npm run build`；架构守卫在仓库根运行
> `pytest -q tests/architecture`。Schema 变更使用所属组件的迁移机制（WeKnora `migrations/`，
> Harness Alembic），并写明升级与回滚。

## 分工与协作

- **分工（2026-10-14 用户调整：Codex 额度有限）**：用户决定方向、批准预算、提供只有用户才有的材料。
  **Claude 是总控**：进度与排期、切片拆分、调研与架构、Spec、验收测试、架构守卫、开 Issue、向 Codex 派工、合并、交接记录。
  **实现与审核交叉进行**：每个 Issue 写明"实现方"与"审核方"，两者不能是同一方（下面"简单改动"例外）。
  - 默认 **Claude 实现**。审核按复杂度分两档（Claude 在 Issue 或 PR 里写明归哪一档和理由，用户可随时改档）：
    - **简单改动，Claude 自审后直接合并**：只改文档、模板、注释或配置取值；只改测试或让守卫基线下降；
      不改行为的小重构；按审核意见做的修改；单个模块内、净改动约 200 行以内，且不涉及下面任何一项的 Harness 改动；
    - **复杂改动，交 Codex 审核**：新模块或 Spec 冻结的公开接口；跨组件合同（`contracts/`、REST、事件）；Go 平台或前端；
      持久化格式、数据库迁移；安全、权限、租户隔离；并发、重试、预算与真实调用链路；质量评分口径；净改动超过约 200 行；
  - 以下情况改为 **Codex 实现、Claude 审核**：以 Go 平台（`internal/`）或前端为主的切片；需要长时间本地构建或全量测试的切片；
    Claude 判断需要独立实现视角的关键路径。Codex 额度紧张时一律由 Claude 实现，Codex 只做审核；
  - V5 同学按 Codex 的角色参与。
  同一组件的运行时代码同时只有一个实现切片；写域不重叠的切片在各自的工作目录里并行。流程全文见蓝图 §9。
- 协作通道是 GitHub 公开仓库 `PA-ALG/InsuranceKB-WeKnora`。每个切片的步骤：
  1. Claude 写 Spec 与验收测试，验收测试**单独一个 RED 提交**推到 `slice/sN`，开 Issue（写明实现方、审核方、RED 提交 SHA、工作目录、预算）；
  2. 实现方在该 Issue 的工作目录里实现，本地过门禁，把最新 `main` merge 进来（不 rebase），开 PR（`Closes #N`），按
     `.github/pull_request_template.md` 交接；
  3. 审核方审计当前 head（见下"审核方的做法"），批准或列出编号修改项；实现方修改后，审核方只复核增量；
  4. Claude 在**审核方已批准当前 head（简单改动为 Claude 自审结论）、CI 全绿、范围符合 Spec** 时 Squash merge，合并后告知用户。部署、迁移、仓库设置与超出
     Issue 预算的真实调用仍需用户批准。Claude 实现的 PR，若 Codex 48 小时内无法审核（如额度用尽），由用户决定放行或等待。
- **实现方的规则**（Claude 或 Codex 实现时都适用）：
  - 只做 Issue 指定的切片，只改 Spec"改动范围"列出的路径；
  - 实现提交不改 RED 提交里的验收测试、蓝图、`docs/design/`、`tests/acceptance/`、`tests/architecture/`、`contracts/`（守卫基线只在
    数字下降时用脚本更新；`contracts/` 只由 Spec 规定的导出命令生成）。Codex 实现时这些路径一律不改；Claude 实现时如发现
    Spec 或验收测试有错，**单独提交**修正并在 PR 中写明原因，由审核方逐条确认。唯一例外：Spec 允许修改上游文件时，实现方在
    `docs/design/upstream-patches.md` 追加登记行（不改已有行）；G10 基线仍由 Claude 审查后更新；
  - 提审前本地过完验收、守卫与受影响组件门禁（相对 S0 失败清单不新增失败）；不 deselect、不加 xfail/skip、不改已有断言；
  - 不自行申请或扩大真实模型调用、构建、部署与数据库迁移；Spec 有错或走不通时停下，在 Issue/PR 中写明，不自行换方案；
  - Codex 实现时不自行合并，合并由 Claude 执行。
- **审核方的做法**：
  - 读 Issue、Spec 与 PR diff；核对与 Spec 的符合度、正确性（边界、失败路径、并发与资源）、守卫与边界规则，以及
    `git diff <RED 提交>..HEAD` 未改验收测试（改了必须是单独提交且写明原因）；
  - 可以跑相关测试；全量测试以 CI 为准，不重复跑；
  - 用 `gh pr review --comment` 发**一次完整结论**：首行署名，写明"批准 head `<sha>`"或编号修改项（每项写文件、行与理由）；
  - Claude 审 Codex 的 PR 时另外在本地重跑验收、守卫与受影响组件门禁；
  - Claude 自审简单改动时，在 PR 里写明归档理由、自查过的失败路径与门禁结果，不写"自审通过"了事。
- **Codex 节省额度**：只看指派给自己的 Issue/PR；审核一次给全结论，不分多轮零散评论；不重复跑 CI 已覆盖的全量测试。
- **Codex 的职责边界**：架构、方案、Spec、验收标准、任务拆分与排期归 Claude；Codex 遇到这类问题在 Issue 或 PR 中提出，
  由 Claude 与用户决定。
- **派工与回报（2026-10-17 起，两边都不轮询）**：GitHub 仍是唯一的工作记录（任务是 Issue，交付是 PR，结论是评审）；
  派工与回报靠事件通知。
  - Claude 只向 Codex App 的总控会话（"InsuranceKB 总控｜GitHub 任务与开发调度"）派工，用 `codex queue` 写入一条
    以 `[来自 Claude Code]` 开头的消息，写明 Issue/PR 号、要审的 head、上一轮意见在哪里；只指路，不复述 GitHub 上已有的内容。
    派实现任务时同时在 Issue 里发"做 issue #N"，留下开工记录。总控按需分发给各条线并汇总。
  - Codex 做完需要 Claude 处理的事（计划已发、PR 已开、评审已发、被阻塞需要决定），在最终回复里单独写一行
    `@Claude: #<号> head <提交> <结论>`，例如 `@Claude: #183 head fa5dc6d 批准`、`@Claude: #182 需改 R1，见 review`；
    没有需要 Claude 处理的事（包括定时检查一类的回复）不写这个标记。结论本身照旧发在 GitHub。
  - 本机的 Codex Stop 钩子把带 `@Claude` 的行写进本机收件文件，唤醒 Claude 的后台监听；Claude 被唤醒后去 GitHub 读结论，
    **同时读 `reviews` 与 `comments`**（共用账号的结论可能在任一处）。收件文件只是门铃，不存结论。
  - 派工后过了合理时间仍没有门铃，Claude 去 GitHub 对账一次，必要时重派。`codex queue` 没有送达回执，消息要等会话空闲才执行，
    Codex App 重启可能丢失排队消息。
- 收到"做 issue #N"（Codex 是实现方）或"审 PR #N"（Codex 是审核方）时：
  1. `gh issue view N --repo PA-ALG/InsuranceKB-WeKnora`（或 `gh pr view N --repo ...`）读取任务；
  2. 读 Issue 指定的 Spec，以及蓝图、调研结论中与本切片相关的章节；
  3. 实现方在 Issue 下回复一条评论，用自己的话复述目标、改动范围与完成标准，再列实施计划；按 Issue 中"开工方式"执行：
     小切片发出计划即开工；大切片等 Claude 或用户确认。审核方直接按上面的做法给结论。

  Issue 与仓库文档已包含全部背景，不需要其他转述。
- **工作目录**：每个 Issue 一个独立的 git worktree：`.worktrees/sN`，分支 `slice/sN`，由 Claude 开 Issue
  时建好并装好依赖（Harness `uv sync`，涉及前端时 `npm ci`），Issue 里写明路径。
  - 实现方只在本 Issue 的工作目录里改代码、跑门禁；不切换主目录的分支，不进入其他 Issue 的工作目录；
    审核方用 detached 的临时工作树（如 `/tmp/review-sN`）查看代码，审完删除；
  - 门禁用本目录自己的环境（`harness/.venv`、`frontend/node_modules`），不借用其他目录的：
    Harness 的 editable 安装会让测试实际导入那个目录的源码；
  - 主目录 `insurancekb-weknora/` 只用来查看 `main`，不在上面开发；PR 合并后由 Claude 删除对应工作目录。
- **何时停下**：GitHub 上首行为 `**[by Claude Code]**` 的明确指示，以及总控会话里以 `[来自 Claude Code]` 开头的派工消息，
  等同于确认，不需要再找用户转述。
  Spec 范围内的步骤直接做，只有以下情况停下并在 Issue/PR 中说明：要改"改动范围"以外或受保护的路径；
  Spec、蓝图与代码事实冲突；超出 Issue 的真实调用预算；部署、迁移、环境或仓库设置变更；需要只有用户
  才有的材料。停下时如果还有其他已批准、未阻塞的 Issue，先去做它，不空等。
- **不再沿用的旧流程**：Mission Card、六维 DELIVERY 台账、构建预算、逐文件哈希清单、
  HANDOFF 状态块、向仓库提交大体量证据与日志。证据用 commit SHA 加测试/评测报告摘要；真实
  调用原始输出存仓库外的私有位置，PR 中只写摘要与位置。
- **署名**：Claude 与 Codex 共用 GitHub 账号时，每条 Issue/PR 评论、review、PR 描述的第一行
  写署名：Claude 写 `**[by Claude Code]**`，Codex 写 `**[by Codex]**`。没有署名的内容视为
  用户所写。
- **真实调用与环境**：每个 Issue 写明"场景数 + 发送上限 + 模型"，用户批准 Issue 即授权该预算；
  部署、迁移、环境变更单独开 Issue 并附回滚方式。第三方资产按各自许可证管理。

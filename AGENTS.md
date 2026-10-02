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

- 分工：用户决策；Claude 负责调研、架构、切片 Spec、验收测试、架构守卫与审计；Codex 负责
  实现。同一时间只有一个实现切片修改运行时代码。流程全文见蓝图 §9。
- 协作通道是 GitHub 公开仓库 `PA-ALG/InsuranceKB-WeKnora`：Claude 写 Spec 与验收测试，推到
  `slice/sN`，开 Issue → 用户批准 → Codex 收到"做 issue #N"后在 `slice/sN` 上实现 → Codex
  开 PR（`Closes #N`），按 `.github/pull_request_template.md` 交接 → Claude 本地重跑门禁并用
  `gh pr review` 审计 → 用户 Squash merge。
- **Codex 的职责**：按 Issue 与 Spec 写出高质量实现代码和配套测试。架构、方案、Spec、验收
  标准、任务拆分与排期不归 Codex；遇到这类问题在 Issue 或 PR 中提出，由 Claude 与用户决定。
- 收到"做 issue #N"时：
  1. `gh issue view N --repo PA-ALG/InsuranceKB-WeKnora` 读取任务；
  2. 读 Issue 指定的 Spec，以及蓝图、调研结论中与本切片相关的章节；
  3. 在 Issue 下回复一条评论，用自己的话复述目标、改动范围与完成标准，再列实施计划；
  4. 按 Issue 中"开工方式"执行：小切片发出计划即开工；大切片等 Claude 或用户确认。

  Issue 与仓库文档已包含全部背景，不需要其他转述。
- **给 Codex 的规则**：
  - 只做 Issue 指定的切片，只改 Spec"改动范围"列出的路径；
  - 不修改蓝图、`docs/design/`、`tests/acceptance/`、`tests/architecture/`、`contracts/`（守卫基线只在
    数字下降时用脚本更新；`contracts/` 只由 Spec 规定的导出命令生成）。唯一例外：切片 Spec 允许修改
    上游文件时，实现者在 `docs/design/upstream-patches.md` 追加对应登记行（不改已有行）；G10 基线仍由
    Claude 审查后更新；
  - 提审前本地过完验收、守卫与受影响组件门禁（相对 S0 失败清单不新增失败），rebase 到最新
    `main`；
  - 不 deselect、不加 xfail/skip、不改已有断言；
  - 不自行合并；不自行申请或扩大真实模型调用、构建、部署与数据库迁移；
  - Spec 有错或走不通时停下，在 PR 里写明，不自行换方案。
- **不再沿用的旧流程**：Mission Card、六维 DELIVERY 台账、构建预算、逐文件哈希清单、
  HANDOFF 状态块、向仓库提交大体量证据与日志。证据用 commit SHA 加测试/评测报告摘要；真实
  调用原始输出存仓库外的私有位置，PR 中只写摘要与位置。
- **署名**：Claude 与 Codex 共用 GitHub 账号时，每条 Issue/PR 评论、review、PR 描述的第一行
  写署名：Claude 写 `**[by Claude Code]**`，Codex 写 `**[by Codex]**`。没有署名的内容视为
  用户所写。
- **真实调用与环境**：每个 Issue 写明"场景数 + 发送上限 + 模型"，用户批准 Issue 即授权该预算；
  部署、迁移、环境变更单独开 Issue 并附回滚方式。第三方资产按各自许可证管理。

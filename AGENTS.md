# Enterprise LLM Wiki 项目指令

本仓库的产品本体是 **Enterprise LLM Wiki**。WeKnora 提供企业平台、权限、
上传、解析、检索和 Wiki 载体；Python Harness 负责编译、治理、Release 与
Active Query。应用知识权威是 PostgreSQL 中不可变 WikiRelease 及
`Space.active_release_id + activation_epoch`，WeKnora managed Wiki 是带
epoch fencing、可重建的投影。

任何任务开始前必须依次阅读：

1. `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
2. `docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`
3. `HANDOFF.md` 的当前状态块
4. 对应的 `openspec/changes/<NNN>/`

## MVP 主航道协作

任何新任务开工前，Owner 必须先向用户提交 **Mission Card** 并取得逐项批准。
Mission Card 至少包含：

- 业务目标与现在做的理由；
- 唯一写 Owner、执行模型与 reasoning effort；
- 依赖、预计 PR 数、预计周期；
- exact 验收条件、明确非目标；
- 阻断问题定义。

未获批准不得写实现、迁移或功能规格。GitHub 上已有分支、PR、旧测试或历史
现场不构成开工授权；W1、P1、G0a 等后续功能仍须各自取得 Mission Card 批准。

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
- `REJECTED`：不可复现、低概率假设、范围外重构，或 Tencent/WeKnora 上游
  通用问题。

普通 PR 最多一轮修复复审，高风险 PR 最多两轮。两轮后仍出现同域新的基础问题，
停止追加补丁，回到设计或拆分 PR。达到 Mission Card 验收且 CI 通过后及时合并，
不追求理论完美。一个 PR 只交付一个用户价值，默认应在 1–2 个工作日完成且
reviewer 可在 30 分钟内理解；超出时拆分，或重新取得用户批准。

硬门禁：

- 没有 OpenSpec 不写功能代码，先测试后实现；AI 会话不 commit/push。
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
- WeKnora 改动只允许 planned inventory 中的 W1/P11/P13/P14，在各自
  Contract Card 和预算内实施；不得产生未登记补丁。
- Wiki、Evidence、Conflict、版本、不可变 Release、回滚、当前 ACL 与
  PostgreSQL CAS/Outbox 是生产闭环不可省略的合同。
- 第一方 `LLM-wiki-black` 资产只作为迁移来源；保险领域生产逻辑统一收敛到
  Python 3.12 Harness。第三方资产继续按各自许可证管理。

实施采用小 PR、单一领域不变量、strict TDD、独立复审。样本数量、worker 数和
文件数只来自版本化 CapacityProfile 或具体验收画像，不得写成产品硬上限。
总体规划会话维护 Roadmap、控制板、任务卡与验收，不写功能代码；执行会话按
独占文件域实现；评审会话只报告发现，修复退回原 Owner。

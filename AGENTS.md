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

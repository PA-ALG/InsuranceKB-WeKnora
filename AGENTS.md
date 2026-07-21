# Enterprise LLM Wiki 项目指令

本仓库的产品本体是 **Enterprise LLM Wiki**：WeKnora 只提供企业平台、权限、解析、检索和页面载体；Harness 负责弱模型知识编译与治理；人和 Agent 只消费同一已批准 release snapshot。任何任务开始前必须先读：

1. `docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`
2. `HANDOFF.md` 的当前阻断与认领表
3. 对应的 `openspec/changes/<NNN>/`

硬门禁：

- 没有 OpenSpec 不写功能代码，先测试后实现；AI 会话不 commit/push。
- 生产只允许经批准、身份冻结的 MiniMax/Qwen/Qwen-VL 能力档弱模型。NS-0 完成前，现有 CLI/config 尚未形成硬门禁，所有真实生产编译、judge、merge、ChangeSet 与 release 操作一律禁止。
- 每个生产 `ReleaseSnapshot` 必须由该 Space 授权人对完整 content hash 最终批准；P-1 前不得逐页写普通用户可见的 WeKnora Wiki KB。
- 业务方/项目权利人已确认 `LLM-wiki-black` 为项目方完整著作权资产；可阅读、审计并迁移其第一方能力。每项迁移必须记录 source commit/path，经新 OpenSpec/TDD 重构到 Python Harness，并通过 MVP Golden Slice；历史代码不因权利已确认而自动获得生产准入。
- LLM-wiki-black 的 TypeScript 只作为迁移来源；保险领域生产逻辑必须收敛到 Python 3.12 Harness。禁止新增 Node/TS 领域服务、queue、事实库或 Python↔TS 双运行时；自有 TS 前端仅可展示和调用 API。
- `nashsu/llm_wiki`、Tencent WeKnora 与其他第三方资产继续按各自许可证管理；第一方声明不得覆盖第三方代码。详细边界见 `docs/insurance-kb/06-asset-migration.md`。
- OpenSpec 004/006/024/025 是历史实现记录，不得仅据已勾 checkbox 宣称当前 Enterprise LLM Wiki 能力完成；复用时以新的 MVP/企业 OpenSpec、弱模型门禁、Evidence/ChangeSet/Alert 与同快照验收为准。

会话分工：总体规划会话只维护 `23-mvp-control-board.md`、Roadmap、任务卡、状态与验收，不写功能代码、不跑重测试；执行会话按独占文件域写代码；评审会话只报告发现，修复退回原执行 Owner。

完整产品、发布、弱模型、许可证和验证规则以北极星设计与 `CLAUDE.md` 为准；冲突时先修订规格，不得自行放宽门禁。

# 项目约定（所有 AI 编码会话自动加载）

本仓库交付 **Enterprise LLM Wiki**：WeKnora 是企业平台底座，Python 3.12
Harness 是知识编译与治理运行时，PostgreSQL Active WikiRelease 是应用知识
权威，WeKnora managed Wiki 是 fenced、可重建投影。

## 开工前必读

1. `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
   及其修正案 `docs/superpowers/specs/2026-07-27-enterprise-llm-wiki-knowledge-compilation-amendment.md`
   （知识编译层交付项、human_batch-first 首发画像、subject_ref=product_version）
2. `docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`
3. `HANDOFF.md` 当前状态块
4. 对应 `openspec/changes/<NNN>/`
5. `docs/insurance-kb/00-project-overview.md`

## 产品与权威边界

- Active WikiRelease 同时服务人、API、MCP 和问答；请求开始时固定一个
  `release_id`，页面、Claim、Relation、Evidence 与引用不得混版。
- 原始 Source 是证据真相，不是应用答案旁路。知识未发布时返回
  `insufficient/needs_qualification`，或进入显式证据核查与补编流程。
- ReviewPolicy 按 Space 版本化，支持
  `machine_auto | human_batch | hybrid | trusted_import`。自动发布必须精确
  绑定仍有效的 QualityProfileApproval、AutomationScope、run fingerprint、
  covered capabilities 和 CompilationSecurityProfile；任一不匹配回落
  `human_batch`。
- 新建 Space 的安全默认值是 `human_batch`。
- 生产 `machine_auto` 只有在 G0b 批准后，才能通过显式、版本化的
  ReviewPolicy binding 在其 exact AutomationScope 与 covered capabilities
  内启用；环境、调用者标签或隐式默认均无效。
- superadmin 只可对 exact CandidateRelease 执行一次性 ReviewDecision 动作；
  不得直接改 active pointer，也不得绕过完整性、Space ACL、
  Provenance/Attestation 或恶意内容与其他安全检查。
- 发布只由 PostgreSQL 事务完成：重验 Candidate/Decision/base/policy，
  创建不可变 WikiRelease，CAS 更新 active pointer/epoch，并写 Outbox。
  Worker/Projector 是 at-least-once，通过幂等、fencing 和 reconciliation
  收敛。
- Harness 只通过版本化 WeKnora REST 与 Source lifecycle event 交互，不读取
  WeKnora DB、Redis/Asynq 或内部队列。MCP 仅映射 Active Query，不承担内部
  集成或发布控制。
- WeKnora patch 仅允许 machine-readable inventory 中的 W1/P11/P13/P14；
  新 patch 必须先修改 033 并独立批准。

## 模型、资产与实现边界

- 生产只使用经版本化策略批准的 MiniMax/Qwen/Qwen-VL 级弱模型；强模型不得
  成为生产 fallback、在线 judge、模板或发布前置。
- `LLM-wiki-black` 是项目方第一方迁移来源。保险领域逻辑必须重构到 Python
  Harness，不新增 Node/TS 领域服务、queue、事实库或双运行时。
- Tencent WeKnora、`nashsu/llm_wiki` 及其他第三方继续按各自许可证管理。
- 无 OpenSpec 不写功能代码；先写关键 RED，再实现 GREEN；每个 PR 只拥有一个
  领域不变量和明确路径预算。
- AI 会话不执行 git commit/push。

## 默认验证

功能 PR 按其 Contract Card 运行 focused、Ruff、mypy、OpenSpec、所需
PostgreSQL/WeKnora lane，并准确报告未运行项。完整 deterministic 只在 PR-ready
或 CI 阶段运行，不在每个小步骤重复。文档 PR 只运行其明确列出的文档门禁。

默认门禁是 deterministic lane：

```bash
uv run pytest -m "not live and not integration_postgres" -q
```

PostgreSQL `integration_postgres` lane 由 `.github/workflows/harness-ci.yml`
的 PostgreSQL 16 job 验证；WeKnora `live` lane 只在受控
`.github/workflows/harness-live.yml` 手工触发，未运行必须准确报告 `NOT RUN`。

## 高频不变量

- `unknown` 不等于 `absent_explicitly`。
- 所有对象、任务、缓存、幂等键和权限检查显式绑定 Space。
- Candidate、Decision、Release、projection 与 Query 都绑定 exact
  identity/digest/epoch；caller 标签不构成 authority。
- 失败必须成为 typed state、Alert、ReviewItem 或 dead letter；不得以空结果
  或隐式降级伪装成功。
- 微批文档数、worker/provider 并发和 Candidate 大小来自配置与
  CapacityProfile；示例数值不是产品上限。

收尾时更新对应 tasks/validation/HANDOFF 当前状态，报告推进的 Wiki 能力、
失败处理、同 Release 证据、验证结果和 NOT RUN。

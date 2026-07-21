# 08 · 技术选型（开源框架清单）

> 原则（业务方约定）：**能采用成熟开源方案的不自研**。本文逐组件给出选用方案、备选对比与选择理由。变更选型需修订本文并在 HANDOFF 登记。
>
> 关联：[02-architecture.md](02-architecture.md)（组件边界）· [04-extraction-harness.md](04-extraction-harness.md)（管道设计）

## 1. 选型总表

| 组件 | 选用 | 备选（未选原因） | 理由 |
|---|---|---|---|
| 企业平台底座 | **WeKnora**（MIT，官方 v0.6.3） | 自研 / RAGFlow / Dify（多租户治理与 Wiki 能力不及，或与"跟随上游"策略冲突） | 多租户 RBAC、解析/检索/Wiki/Agent/MCP/审计齐备；ADR-001 |
| Harness 语言/运行时 | **Python 3.12 + uv**（包管理）+ ruff + mypy | Poetry（uv 更快、锁定更简单） | 团队 Python 优先；工具链为当前社区主流 |
| 流程编排 | **LangGraph**（含 Postgres checkpointer） | Temporal（需独立 server 集群，运维重，LLM 场景无原生支持）；Prefect/Airflow（面向数据批处理，无 human-in-the-loop 中断恢复） | 可恢复状态图、持久化 checkpoint、人工审批中断/恢复原生支持，正是"环节断了能续"的需求（04 §编排） |
| Web/API 框架 | **FastAPI + Pydantic v2** | Flask/Django（异步与 schema 校验弱） | Pydantic 同时是抽取 schema 校验器，一套模型两用 |
| Harness 数据库 | **PostgreSQL 15+ + Alembic** 迁移 | MySQL（JSONB/行级锁/SKID LOCKED 生态弱） | 与 WeKnora 同栈（部署一套 PG 两个库），运维统一 |
| 任务队列 | 起步：**Postgres 队列（SELECT … FOR UPDATE SKIP LOCKED）**；上量后：**arq**（Redis） | Celery（重、配置面大）；直接上 Redis 队列（起步阶段多一个依赖） | 与 04 §限流分片配合；升级路径明确，接口先抽象 |
| 模型网关 | **百炼 DashScope OpenAI 兼容端点**（2026-07-12 定，复用 yingxiaoguihua 配置）；库内统一 model_client 抽象 | new-api 自建网关（暂无必要）；直连各厂商 SDK | 生产按 MiniMax M2.5 / Qwen 3.x / Qwen-VL 级弱模型能力设计；模型身份与参数冻结，推理型响应需只取 content 并处理截断 |
| 生产裁决 / 离线金标 | **生产裁决：确定性规则 + 多弱模型 Agent 建议 + 人工最终审核**；**离线金标：可选 Claude/其他最强模型或人工，独立版本化** | — | 强模型不可作为生产 fallback、在线 judge、模板生成前置或发布前置；离线金标不可直接发布 |
| 文档解析 | **复用 WeKnora docreader**（含 OCR/表格） | — | 平台已有，不重复建设 |
| 复杂 PDF 备选解析 | **MinerU 2.5**（对照/兜底解析器） | Marker/olmOCR（表格与中文条款效果不及） | 04 §解析质量抽检需要第二解析器做对照；仅在低质时启用（分层升级链见 11 §2） |
| 版面/表格结构识别 | **PaddleOCR 3.x / PP-StructureV3** | camelot（仅矢量表）、table-transformer（中文弱） | 费率表/利益演示表→markdown 结构化；OmniDocBench v1.6 中文综合领先（11 §2） |
| 图表理解 VLM | **经准入的 Qwen-VL 级生产弱模型** | DeepSeek-OCR-2 / 其他 VLM 只能进入隔离离线 A/B，达到弱模型能力档、完成合规/身份/预算/金标准入并经 OpenSpec 批准前不得成为生产备选或 fallback | caption-first：图表→结构化描述 JSON 进文本管道；高风险字段禁止仅图表证据（11 §3）；无批准模型时 Alert + 人工，不自动换强模型 |
| 结构化抽取输出 | **Pydantic schema + 自研对抗性解析器**（04 §对抗解析） | instructor/outlines（依赖 function-calling 质量，弱模型上不稳） | 弱模型 function-calling 不可靠，逐行状态机解析 + 重试更稳（llm_wiki 经验） |
| 向量/检索 | **复用 WeKnora**（向量+BM25+GraphRAG） | 自建 faiss/qdrant | Harness 不建向量库；语义检索需求走 WeKnora API |
| 可观测 | **Langfuse**（与 WeKnora 共用实例） | 自研日志 | 以 knowledge_id / harness_job_id / change_set_id 关联端到端链路 |
| 评估 | **自研 eval runner**（05）+ pytest 集成 | ragas/promptfoo（指标口径与字段级金标不匹配，可借鉴报告形式） | 字段级 P/R、三态混淆矩阵等口径是定制的（05 §5） |
| 测试 | **pytest + pytest-asyncio + respx**（HTTP mock）+ **金标回归**（契约测试打真实 WeKnora 测试实例） | — | TDD 约定见 10-development-guide.md |
| 审核工作台 UI | 起步：**FastAPI + Jinja2 + HTMX**；若交互复杂化：Vue3 独立 SPA | 改 WeKnora Vue 前端（违反 ADR-001 边界） | 审核队列/完整度矩阵以表单和表格为主，HTMX 成本最低；升级路径保留 |
| MCP server | **官方 python `mcp` SDK** | 自实现协议 | harness/mcp 暴露版本查询/证据链工具（02 §2） |
| 部署 | **Docker Compose**（开发/PoC）→ 复用 WeKnora Helm 加 harness chart（生产） | — | 与平台部署形态一致 |

## 2. 许可证核对

| 依赖 | 许可证 | 结论 |
|---|---|---|
| WeKnora | MIT | 可商用二开 |
| LangGraph / FastAPI / Pydantic / litellm / arq / HTMX | MIT | 可 |
| MinerU | AGPL-3.0 | **以独立服务进程隔离调用（HTTP），不做代码级链接**；上生产前法务确认 |
| LLM-wiki-black | 项目方第一方完整著作权 | 可按 06 provenance 选择性迁移进 Python Harness；旧生产入口仍须 027/028/030 重构验收 |
| nashsu/llm_wiki | 第三方 GPL-3.0 | 默认借鉴思想；复制或链接实现须另行确认许可证兼容 |

## 3. 版本锁定策略

- 所有 Python 依赖由 `uv.lock` 锁定；LangGraph/litellm 等快速演进库设上限版本，升级走 PR + 金标回归；
- WeKnora 版本锁定见 02 §8 版本列车；
- 模型身份（含可选离线金标模型）必须记录不可变 `provider/model_id/deployment_id/artifact_digest-or-provider-attestation/prompt_hash/params_hash`，并进入每次金标 release、AgentReceipt 与 ChangeSet 元数据；禁止 `latest`/rolling alias（05 §3），保证评估可复现。

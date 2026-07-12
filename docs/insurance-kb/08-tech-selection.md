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
| 模型网关 | **new-api**（团队已有使用经验）；库内调用统一走 **litellm** 客户端抽象 | 直连各厂商 SDK（切换模型/统计成本困难） | 统一接入 minimax/qwen/DeepSeek/Claude，限流、计费、故障切换集中处理；金标（Claude）与生产（弱模型）同一网关不同通道 |
| 文档解析 | **复用 WeKnora docreader**（含 OCR/表格） | — | 平台已有，不重复建设 |
| 复杂 PDF 备选解析 | **MinerU 2.5**（对照/兜底解析器） | Marker/olmOCR（表格与中文条款效果不及） | 04 §解析质量抽检需要第二解析器做对照；仅在低质时启用（分层升级链见 11 §2） |
| 版面/表格结构识别 | **PaddleOCR 3.x / PP-StructureV3** | camelot（仅矢量表）、table-transformer（中文弱） | 费率表/利益演示表→markdown 结构化；OmniDocBench v1.6 中文综合领先（11 §2） |
| 图表理解 VLM | **qwen-VL（生产已有）**；备选 DeepSeek-OCR-2 | GPT-4V 级云端（合规不确定） | caption-first：图表→结构化描述 JSON 进文本管道；高风险字段禁止仅图表证据（11 §3） |
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
| nashsu/llm_wiki 及 LLM-wiki-black | GPL-3.0 | 只借鉴思想与自研数据，不复制代码（06 §合规） |

## 3. 版本锁定策略

- 所有 Python 依赖由 `uv.lock` 锁定；LangGraph/litellm 等快速演进库设上限版本，升级走 PR + 金标回归；
- WeKnora 版本锁定见 02 §8 版本列车；
- 模型版本（含金标 Claude 版本）记录在每次金标 release 与 ChangeSet 元数据中（05 §4），保证评估可复现。

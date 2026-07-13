# 寿险知识平台文档集

初始版本产出于 2026-07-11 架构讨论定稿后。阅读顺序即编号顺序；新人从 00 开始。

| 文档 | 内容 | 状态 |
|---|---|---|
| [00-project-overview.md](00-project-overview.md) | 5 分钟项目入口：目标、架构一图、关键决策、术语表 | ✅ |
| [01-requirements-and-challenges.md](01-requirements-and-challenges.md) | 业务痛点、12 项技术难题、8 项需求、全局约束，及各自的设计落点映射 | ✅ |
| [02-architecture.md](02-architecture.md) | ADR-001 插件式架构、组件职责、三条硬边界、WeKnora 集成契约、3 个上游补丁、版本列车、master plan 落点映射 | ✅ |
| [03-knowledge-model.md](03-knowledge-model.md) | Claim/Evidence/ChangeSet/Review/QA 对象模型、三层页面、版本与回滚、权威序与冲突裁决、DB schema 草案 | ✅ |
| [04-extraction-harness.md](04-extraction-harness.md) | 弱模型抽取八步管道、LangGraph 编排、重试/限流/分片、成本估算 | ✅ |
| [05-golden-set-eval.md](05-golden-set-eval.md) | 金标注 Agent 子系统、三类任务金标、指标口径、eval runner 回归门禁 | ✅ |
| [06-asset-migration.md](06-asset-migration.md) | LLM-wiki-black 资产移植清单：字段字典详单、Q001-Q027 踩坑档案、不带走清单、GPL 合规 | ✅ |
| [07-schema-baseline.md](07-schema-baseline.md) | 业务方 schema 基线接入、元属性增强计划、扩展字段提案（已全部接受）、样本批次登记 | ✅ |
| [08-tech-selection.md](08-tech-selection.md) | 技术选型：逐组件的开源框架清单、备选对比、许可证核对、版本锁定策略 | ✅ |
| [09-llm-wiki-feature-migration.md](09-llm-wiki-feature-migration.md) | LLM Wiki 功能迁移对照表：27 项功能逐一标注承接方（WeKnora 已有/Harness 重写/不迁移）与排期 | ✅ |
| [10-development-guide.md](10-development-guide.md) | 开发规范：SDD/OpenSpec 流程、TDD 分层约定、代码边界纪律、HANDOFF 维护义务、示范项目质量清单 | ✅ |
| [11-parsing-templates-multimodal.md](11-parsing-templates-multimodal.md) | 解析组件分层升级链、模板抽取三层设计（族识别/模板归纳/fast path）、图表 caption-first 处理与证据风控 | ✅ |
| [12-dayu-borrowings.md](12-dayu-borrowings.md) | dayu-agent（财报）弱模型准确性机制的借鉴决策：缩小模型战场、data_quality 来源分级、断链硬门禁、可喂性评分、dry-run 治理、保险算术校验器 | ✅ |
| [13-blueprint-status.md](13-blueprint-status.md) | 整体蓝图现状：change 001~012 状态一张图、LLM Wiki 27 项引入状态复盘与缺口 G1~G8、下一批规划 | ✅ |
| [14-deployment-runbook.md](14-deployment-runbook.md) | 部署与联调 Runbook：WeKnora 双库初始化、Harness 启动、L1~L6 联调验收路径、live 契约测试约定、B10 完成定义 | ✅ |
| [15-solutions-traceability.md](15-solutions-traceability.md) | 业务九问对账：需求→方案→状态追踪矩阵（六问已实现、三问条款级待执行） | ✅ |
| [16-roadmap.md](16-roadmap.md) | Roadmap：M1 可演示闭环 / M2 形态完整 / M3 规模化提准 / M4 智能演进，含关键路径与完成定义 | ✅ |
| [17-team-collaboration.md](17-team-collaboration.md) | 三人协作规范：模块所有权分工、Git/PR 双查流程、HANDOFF 同步纪律、主航道守护清单、决策升级路径 | ✅ |
| [18-ai-collaboration.md](18-ai-collaboration.md) | AI Coding 协作机制：会话生命周期、文件域声明制、门禁等化器、token 预算纪律、反模式清单（001~007 实战验证） | ✅ |
| [19-weknora-utilization.md](19-weknora-utilization.md) | WeKnora 能力利用清单：三层利用率盘点、早期调研结论修订记录、选型结论复核 | ✅ |
| [schema-baseline/](schema-baseline/) | 机器可读字段基线（13 个 YAML + extensions-v1.1，转自业务方 2026-07-10 Excel） | ✅ |

上位文档：[../project-iterations/2026-07-insurance-knowledge-compiler-master-plan.md](../project-iterations/2026-07-insurance-knowledge-compiler-master-plan.md)（唯一主清单）· [/HANDOFF.md](../../HANDOFF.md)（交接文档）

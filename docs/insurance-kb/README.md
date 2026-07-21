# 寿险知识平台文档集

> **最高层设计基准**：[`Enterprise LLM Wiki 北极星设计`](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)。它定义产品本体、三层职责、知识权威、生产弱模型边界、七类核心问题与开发门禁；本目录任何内容与其冲突时，先以北极星设计为准并修正文档。

初始版本产出于 2026-07-11 架构讨论定稿后。新人先读北极星设计，再从 00 开始按编号阅读。

| 文档 | 内容 | 状态 |
|---|---|---|
| [00-project-overview.md](00-project-overview.md) | 5 分钟项目入口：目标、架构一图、关键决策、术语表 | ✅ |
| [01-requirements-and-challenges.md](01-requirements-and-challenges.md) | 业务痛点、12 项技术难题、8 项需求、全局约束，及各自的设计落点映射 | ✅ |
| [02-architecture.md](02-architecture.md) | ADR-001 插件式边界 + ADR-002 Enterprise LLM Wiki 产品本体、知识权威、生产弱模型边界、WeKnora 集成契约与版本列车 | ✅ |
| [03-knowledge-model.md](03-knowledge-model.md) | Claim/Evidence/ChangeSet/Review/QA 对象模型、三层页面、版本与回滚、权威序与冲突裁决、DB schema 草案 | ✅ |
| [04-extraction-harness.md](04-extraction-harness.md) | 弱模型 Harness 目标合同、TemplateApproval、lease fencing、重试/限流/分片 | ⚠️ 目标设计；旧 004 production-disabled |
| [05-golden-set-eval.md](05-golden-set-eval.md) | 金标注 Agent 子系统、三类任务金标、指标口径、eval runner 回归门禁 | ✅ |
| [06-asset-migration.md](06-asset-migration.md) | LLM-wiki-black 第一方资产迁移、provenance 与第三方许可证边界 | ✅ 第一方权利决定已记录 |
| [07-schema-baseline.md](07-schema-baseline.md) | 业务方 schema 基线接入、元属性增强计划、扩展字段提案（已全部接受）、样本批次登记 | ✅ |
| [08-tech-selection.md](08-tech-selection.md) | 技术选型：逐组件的开源框架清单、备选对比、许可证核对、版本锁定策略 | ✅ |
| [09-llm-wiki-feature-migration.md](09-llm-wiki-feature-migration.md) | Enterprise LLM Wiki 功能承接目标；第一方选择性迁移与第三方许可证边界 | ✅ 权利口径已校正 |
| [10-development-guide.md](10-development-guide.md) | 开发规范：SDD/OpenSpec 流程、TDD 分层约定、代码边界纪律、HANDOFF 维护义务、示范项目质量清单 | ✅ |
| [11-parsing-templates-multimodal.md](11-parsing-templates-multimodal.md) | 解析升级、四级模板专门化与多模态目标合同 | ⚠️ 004/006 资产 production-disabled |
| [12-dayu-borrowings.md](12-dayu-borrowings.md) | dayu-agent（财报）弱模型准确性机制的借鉴决策：缩小模型战场、data_quality 来源分级、断链硬门禁、可喂性评分、dry-run 治理、保险算术校验器 | ✅ |
| [13-blueprint-status.md](13-blueprint-status.md) | 整体蓝图现状：历史代码地基、NS-RIGHTS/NS-0～NS-F 差量、缺口与规划 | ✅ 2026-07-21 校正 |
| [14-deployment-runbook.md](14-deployment-runbook.md) | 部署与联调 Runbook：RAW/STAGING/target 分阶段拓扑、pre/post-P1 路径、live 契约与 B10 边界 | ✅ 已校正 |
| [15-solutions-traceability.md](15-solutions-traceability.md) | 七类北极星核心问题的能力闭环与当前落点；保留 2026-07-12 历史九问追溯 | ✅ |
| [16-roadmap.md](16-roadmap.md) | 完整 Roadmap：7–10 日真实 MVP → 企业生产核心 → 规模运营 → 持续演进 | ✅ 2026-07-21 批准 |
| [17-team-collaboration.md](17-team-collaboration.md) | 三人协作规范：模块所有权分工、Git/PR 双查流程、HANDOFF 同步纪律、主航道守护清单、决策升级路径 | ✅ |
| [18-ai-collaboration.md](18-ai-collaboration.md) | AI Coding 协作机制：会话生命周期、文件域声明制、门禁等化器、token 预算纪律、反模式清单（001~007 实战验证） | ✅ |
| [19-weknora-utilization.md](19-weknora-utilization.md) | WeKnora 平台能力利用清单；领域编译器当前门禁另行标注 | ✅ 平台结论；编译生产未放行 |
| [20-enterprise-runtime-foundation.md](20-enterprise-runtime-foundation.md) | 企业运行基础：KnowledgeSpace、Source Bridge、SnapshotFact 与 Golden 闸门 | 🚧 历史软件地基已合入；027/适用 admission 未齐，真实 baseline 未运行 |
| [21-selftest-before-submit.md](21-selftest-before-submit.md) | 复审前自测方法论：提交前 gauntlet、反复返工问题清单（身份绑可变标签/判定两处推导/构造期校验器可绕过/对称路径/冗余安全层…）、并行红队配方；源自 019 七轮返工教训固化 | ✅ |
| [22-parallel-execution-blueprint.md](22-parallel-execution-blueprint.md) | G/S/K/M/I 会话拓扑、依赖、文件域、PR 列车与风险分级 TDD | ✅ 2026-07-21 |
| [23-mvp-control-board.md](23-mvp-control-board.md) | 已批准 MVP 的冻结范围、23 来源样本、任务包、7–10 日节奏、验收与提效规则 | ✅ 当前 MVP 基准 |
| [schema-baseline/](schema-baseline/) | 机器可读字段基线（13 个 YAML + extensions-v1.1，转自业务方 2026-07-10 Excel） | ✅ |

权威分工：[北极星设计](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)（产品/架构）· [16-roadmap](16-roadmap.md)（完整阶段）· [23-mvp-control-board](23-mvp-control-board.md)（冻结 MVP）· [HANDOFF](../../HANDOFF.md)（唯一实时状态）· [master plan](../project-iterations/2026-07-insurance-knowledge-compiler-master-plan.md)（完整 backlog）。

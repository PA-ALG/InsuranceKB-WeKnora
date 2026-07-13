# 00 · 项目总览（5 分钟入口）

## 我们在做什么

为大型寿险企业建设 **AI 时代的知识基础设施**：把散落在产品说明书、条款、FAQ、培训材料里的知识，编译成**原子化、有版本、可溯源、可进化**的知识体系——既供 Agent 精准调用，也供人像维基百科一样阅读和审核。

一句话架构：**WeKnora 做企业平台骨架（原样跟随开源上游），寿险知识能力全部做成插件式的 Python Harness**。

```
原始文档 ──► WeKnora（解析/chunk/检索/权限）
                │ REST
                ▼
        harness/（Python 插件）
        分类 → 抽取 → 校验 → 合并/冲突裁决 → 审核 → 发布
                │ Wiki REST
                ▼
        WeKnora 寿险知识 Wiki ──► Agent / RAG / 业务用户
```

## 核心命题（三件难事）

1. **知识模型**：事实（Claim）+ 证据（Evidence）+ 变更集（ChangeSet）+ 三层页面（概念主页/产品限定页/义项），版本可回滚 → [03](03-knowledge-model.md)
2. **弱模型抽取工程**：生产只有 minimax 2.5 级弱模型，用 harness 的结构（短任务拆分、引文回验、投票、定向补漏）逼近强模型效果 → [04](04-extraction-harness.md)
3. **版本与冲突治理**：六级权威序裁决、全程留痕、库级快照回滚 → [03](03-knowledge-model.md) §4-5

## 关键决策（已拍板）

| 决策 | 结论 | 出处 |
|---|---|---|
| 架构路线 | 插件式（ADR-001）：WeKnora 零侵入，补丁≤3 且提 PR 回上游 | [02](02-architecture.md) |
| 唯一主清单 | `docs/project-iterations/2026-07-insurance-knowledge-compiler-master-plan.md`（条目落点按 02 §6 映射调整） | 02 §6 |
| QA 形态 | 一等知识对象（权威/派生），不做实体字段 | 03 §2 |
| 版本 SSOT | Harness 自有 PostgreSQL；WeKnora Wiki 是发布视图 | 03 §4 |
| 金标 | 最强模型直读标注，独立可维护的 Agent 子系统（S0，先于 S1 启动） | [05](05-golden-set-eval.md) |
| Schema | 业务方 Excel 为基线 + 旧项目字典元数据 + 扩展提案流程 | [07](07-schema-baseline.md) |
| 旧项目资产 | LLM-wiki-black 的字段字典/抽取经验/踩坑档案按清单移植；GPL 代码只借鉴思想 | [06](06-asset-migration.md) |

## 术语表

| 术语 | 含义 |
|---|---|
| Claim | 一条可验证的原子事实，绑定产品版本、有效期、置信度、三态 |
| Evidence | Claim 的原文证据：knowledge_id + chunk_id + 页码 + 权威等级 |
| 三态 | present / absent_explicitly / unknown——"没抽到"≠"不存在" |
| ChangeSet | 一批导入产生的 add/enrich/supersede/conflict/retract 候选及决策 |
| 产品限定页 | 承载具体事实的原子 wiki 页，如"在线问诊@某产品v2" |
| 金标（golden set） | 最强模型直读文档产出的标注，评估弱模型 harness 的标尺 |
| S0~S7 | 交付切片；S0=金标子系统（本项目新增），S1 起见 master plan §5 |

## 相关仓库与材料

- 本仓库（唯一总仓库）：`PA-ALG/InsuranceKB-WeKnora` = 官方 WeKnora v0.6.3（零分岔）+ 本文档集 + 未来的 harness/
- 参考（已 clone 于本仓库同级目录）：`LLM-wiki-black`（旧寿险定制，资产来源）、`llm_wiki`（范式思想来源，GPL 勿抄码）
- 业务材料：schema 基线 Excel（已转 [schema-baseline/](schema-baseline/)）、13 产品样本包（`../samples/`，不入 git）

## 我该读什么

- **新接手** → 本文 → [HANDOFF.md](../../HANDOFF.md) → 01 → 02
- **写抽取代码** → 04 → 03 → 06（移植清单）→ 07（schema）
- **做评估** → 05
- **排期/对齐业务** → master plan + 02 §6 映射表

# 00 · 项目总览（5 分钟入口）

## 我们在做什么

为大型寿险企业建设 **Enterprise LLM Wiki**：把散落在产品说明书、条款、FAQ、培训材料和结构化产品库里的知识，持续编译成**原子化、有版本、可溯源、可关联、可进化**的知识体系——既供 Agent 精准调用，也供人像维基百科一样阅读和审核。

它是本项目的产品本体，而不是普通 RAG 的附属页面：**WeKnora 做企业平台底座，Python Harness 做可恢复的弱模型知识编译与治理，已发布 Wiki active release 与同快照 MCP 做人和 Agent 的默认知识权威。** WeKnora 当前逐页 Wiki REST 不具备原子 release 语义，P-1 前只允许隔离 staging + Harness reader，不能宣称生产 Wiki UI 完成。完整基准见[北极星设计](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)。

> [!CAUTION]
> **目标和第一方权利边界已确认，当前运行门禁未解除。** `NS-RIGHTS=recorded`：LLM-wiki-black 是项目方第一方完整著作权资产，可按 provenance 迁移；第三方许可证另行管理。027 尚未在 CLI/config 硬封强/未知/rolling model，030 MVP admission 也未 READY，因此当前不得真实生产编译、merge 或 release。020 canonical admission 不能授权 030 slice。

```
文档 ──► WeKnora RAW（权限/解析/chunk/检索）── REST ──┐
JSON/JSONL/CSV/FAQ/API ──► Harness 结构化 normalizer ─┤（跳过 docreader）
                                                       ▼
        harness/（持久知识编译与统一治理运行时）
        来源冻结 → 模板/映射 → 证据/校验 → Claim/QA/ChangeSet → 人工门禁
                │ ReleaseSnapshot
                ▼
        Enterprise LLM Wiki（产品/概念/FAQ/关系/版本/change log）
                ├─► WeKnora 页面载体 ──► 业务用户
                └─► 同快照 MCP ──► Agent
```

## 核心命题

1. **持久知识编译**：事实（Claim）+ 证据（Evidence）+ 变更集（ChangeSet）+ Wiki 页面与关系，持续吸收更新而非一次性抽取 → [03](03-knowledge-model.md)
2. **弱模型 Harness**：生产只依赖 MiniMax/Qwen/Qwen-VL 级模型，通过模板、多 Agent、短任务、引文回验、定向补漏、共识与人工门禁获得高准确率和覆盖率 → [04](04-extraction-harness.md)
3. **融合、校验与多产品路由**：文档和结构化知识统一进入 Claim 治理；分类到文档、路由到事实，低置信隔离 → [09](09-llm-wiki-feature-migration.md)
4. **版本与冲突治理**：权威序与有效期裁决、全程留痕、删除收敛、库级快照回滚 → [03](03-knowledge-model.md) §5-6
5. **人/Agent 同一知识权威**：内部语义 SSOT 是 Claim/Evidence/ChangeSet/Snapshot；默认消费权威是其编译出的 Wiki + 同快照 MCP，RAW 只作证据和标注兜底。
6. **运营与规模化**：完整度、质量、Schema/Template 工作台、告警、批量补全与百千文档并发均围绕 Wiki 演进闭环建设。

## 关键决策（已拍板）

| 决策 | 结论 | 出处 |
|---|---|---|
| 架构路线 | 插件式（ADR-001）：WeKnora 零侵入，补丁≤3 且提 PR 回上游 | [02](02-architecture.md) |
| 需求主 backlog | `docs/project-iterations/2026-07-insurance-knowledge-compiler-master-plan.md`；北极星最高、OpenSpec 定验收、HANDOFF 记实时状态 | 02 §6 |
| QA 形态 | 一等知识对象（权威/派生），不做实体字段 | 03 §3 |
| 版本 SSOT | Harness 自有 PostgreSQL；WeKnora Wiki 是发布视图 | 03 §5 |
| 默认消费权威 | P-1 `active_release_id` 指向且经真人批准的 ReleaseSnapshot Wiki + 同快照 MCP；Harness CurrentRelease 只镜像 activation receipt，RAW 不覆盖已发布结论 | 北极星设计 §4/§9.2 |
| 生产模型边界 | 目标只依赖弱模型；当前运行时尚未硬封，NS-0 前所有真实生产任务禁止 | 北极星设计 §3.2 |
| 金标 | 独立离线评测子系统，可用最强模型或人工构建；不可直接发布且不构成生产依赖 | [05](05-golden-set-eval.md) |
| Schema | 业务方 Excel 是有权基线；第一方工程元数据可审计迁移，但必须经新 OpenSpec、provenance、Golden Slice 和人工批准 | [07](07-schema-baseline.md) |
| 旧项目能力 | LLM-wiki-black 为第一方资产，可选择性重构进 Python Harness；nashsu/llm_wiki 等第三方实现继续按许可证隔离 | [06](06-asset-migration.md) |

## 术语表

| 术语 | 含义 |
|---|---|
| Claim | 一条可验证的原子事实，绑定产品版本、有效期、置信度、三态 |
| Evidence | Claim 的原文证据：knowledge_id + chunk_id + 页码 + 权威等级 |
| 三态 | present / absent_explicitly / unknown——"没抽到"≠"不存在" |
| ChangeSet | 一批导入产生的 add/enrich/supersede/conflict/retract 候选及决策 |
| 产品限定页 | 承载具体事实的原子 wiki 页，如"在线问诊@某产品v2" |
| 金标（golden set） | 独立离线标注与评测制品，评估生产弱模型 Harness 的标尺，不是生产知识来源 |
| S0~S7 | 交付切片；S0=金标子系统（本项目新增），S1 起见 master plan §5 |

## 相关仓库与材料

- 本仓库（唯一总仓库）：`PA-ALG/InsuranceKB-WeKnora` = 官方 WeKnora v0.6.3（零分岔）+ Enterprise LLM Wiki 文档/规格 + 已落地的 `harness/`
- 第一方 LLM-wiki-black 迁移须在 PR 记录 source commit/path、接受/拒绝行为与新测试；第三方来源继续单独管理，未经兼容决定不复制实现表达。
- 业务材料：schema 基线 Excel（已转 [schema-baseline/](schema-baseline/)）、13 产品权威数据集（仓内 `dataset/shouxian_product/`；早期 `../samples/` 副本不再作为运行输入）

## 我该读什么

- **新接手** → [北极星设计](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md) → 本文 → [HANDOFF.md](../../HANDOFF.md) → 01 → 02
- **写抽取代码** → 先确认 027、适用 admission 与新 OpenSpec；第一方旧能力只按 06 provenance 选择性重构，不直接恢复旧生产入口
- **做评估** → 05
- **排期/对齐业务** → master plan + 02 §6 映射表

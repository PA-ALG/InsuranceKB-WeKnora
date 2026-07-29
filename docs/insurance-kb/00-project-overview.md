# 00 · 项目总览（5 分钟入口）

## 我们在做什么

为大型寿险企业建设 **Enterprise LLM Wiki**：把散落在产品说明书、条款、FAQ、培训材料和结构化产品库里的知识，持续编译成**原子化、有版本、可溯源、可关联、可进化**的知识体系——既供 Agent 精准调用，也供人像维基百科一样阅读和审核。

它是本项目的产品本体，而不是普通 RAG 的附属页面：**WeKnora 做企业平台底座和
条件接受的唯一 serving Active Release 载体；Python Harness 做弱模型寿险知识
编译、Candidate、审核与发布授权。** Harness 不保存第二个 serving Head。
Release Kernel 尚未实现，必须先经过 `80a5003` capability gap matrix 与 S0-R；
知识编译可行性由独立 S0-Q 验证。当前执行基准见
[Authority ADR](../superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md)
和
[Amendment 2](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)。

> [!CAUTION]
> **目标和第一方权利边界已确认，当前运行门禁未解除。**
> `NS-RIGHTS=recorded`：LLM-wiki-black 是项目方第一方完整著作权资产，可按
> provenance 迁移；第三方许可证另行管理。S0-R/S0-Q 尚未 PASS，Release
> Kernel 与 MVP 均未实现，因此当前不得把历史实现、镜像 digest 或演示路径
> 声明为生产 release。

```
文档 ──► WeKnora RAW（权限/解析/chunk/检索）── REST ──┐
JSON/JSONL/CSV/FAQ/API ──► Harness 结构化 normalizer ─┤（跳过 docreader）
                                                       ▼
        harness/（持久知识编译与统一治理运行时）
        来源冻结 → 模板/映射 → 证据/校验 → Candidate → Review/Authorization
                                                       │
                                                       ▼
        WeKnora preparation → atomic activation → sole serving Active Head
                ├─► pinned Wiki page/payload ──► 业务用户
                └─► pinned release-aware retrieval ──► Agent
```

## 核心命题

1. **持久知识编译**：事实（Claim）+ 证据（Evidence）+ 变更集（ChangeSet）+ Wiki 页面与关系，持续吸收更新而非一次性抽取 → [03](03-knowledge-model.md)
2. **弱模型 Harness**：生产只依赖 MiniMax/Qwen/Qwen-VL 级模型，通过模板、多 Agent、短任务、引文回验、定向补漏、共识与人工门禁获得高准确率和覆盖率 → [04](04-extraction-harness.md)
3. **融合、校验与多产品路由**：文档和结构化知识统一进入 Claim 治理；分类到文档、路由到事实，低置信隔离 → [09](09-llm-wiki-feature-migration.md)
4. **版本与冲突治理**：权威序与有效期裁决、全程留痕、删除收敛、库级快照回滚 → [03](03-knowledge-model.md) §5-6
5. **人/Agent 同一 serving 权威**：Harness 保存语义、Candidate、Decision 与
   Authorization；人和 Agent 都固定同一 WeKnora `release_id`，RAW 只作证据和
   标注输入。
6. **运营与规模化**：完整度、质量、Schema/Template 工作台、告警、批量补全与百千文档并发均围绕 Wiki 演进闭环建设。

## 关键决策（已拍板）

| 决策 | 结论 | 出处 |
|---|---|---|
| 架构路线 | 单一 serving Active Release；WeKnora 载体 `ACCEPTED_CONDITIONALLY`，不得恢复双 Active Projector | Authority ADR / Amendment 2 |
| 需求主 backlog | `docs/project-iterations/2026-07-insurance-knowledge-compiler-master-plan.md`；北极星最高、OpenSpec 定验收、HANDOFF 记实时状态 | 02 §6 |
| QA 形态 | 一等知识对象（权威/派生），不做实体字段 | 03 §3 |
| 版本 SSOT | 目标态由 WeKnora sole serving Active Head 决定；Harness 只保存 Candidate、Decision、Authorization 与 receipt | Authority ADR |
| 默认消费权威 | 人、API、MCP、问答固定同一 WeKnora `release_id`；RAW 只作 Evidence/补编，不能覆盖已发布结论 | Amendment 2 |
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

- 本仓库（唯一总仓库）：`PA-ALG/InsuranceKB-WeKnora` = 已采用
  `80a5003` 能力基线的 WeKnora + Enterprise LLM Wiki 文档/规格 + 已落地的
  `harness/`；运行镜像按固定 digest 识别，Full Artifact probes 仍 open。
- 第一方 LLM-wiki-black 迁移须在 PR 记录 source commit/path、接受/拒绝行为与新测试；第三方来源继续单独管理，未经兼容决定不复制实现表达。
- 业务材料：schema 基线 Excel（已转 [schema-baseline/](schema-baseline/)）、13 产品权威数据集（仓内 `dataset/shouxian_product/`；早期 `../samples/` 副本不再作为运行输入）

## 我该读什么

- **新接手** → [Authority ADR](../superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md)
  → [Amendment 2](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)
  → 本文 → [HANDOFF.md](../../HANDOFF.md)
- **写抽取代码** → 先确认 027、适用 admission 与新 OpenSpec；第一方旧能力只按 06 provenance 选择性重构，不直接恢复旧生产入口
- **做评估** → 05
- **排期/对齐业务** → master plan + 02 §6 映射表

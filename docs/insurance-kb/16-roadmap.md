# 16 · Enterprise LLM Wiki Roadmap

> 本文定义稳定的阶段、顺序和完成定义；实时状态只在 `HANDOFF.md` 的 MVP-0 控制板维护，冻结 MVP 范围和任务拓扑见 [23-mvp-control-board.md](23-mvp-control-board.md)，并行文件域见 [22-parallel-execution-blueprint.md](22-parallel-execution-blueprint.md)。
> 产品北极星：**Enterprise LLM Wiki 是产品本体；WeKnora 是企业底座；Python Harness 是弱模型知识编译与治理运行时。**

## 0. 现有基础与路线修正

现有 001～024 已形成可复用底座：KnowledgeSpace、WeKnora Source Bridge、产品注册/分类/路由、Claim/Evidence/ChangeSet/Review、ReleaseSnapshot/SnapshotReader、Source lifecycle、审核工作台核心、Golden Gate、run-admission 软件和本机 WeKnora 环境。

过去 Roadmap 把首次 MVP 与完整企业生产验收混在同一个 M1，导致 P-1、13 产品 baseline、完整结构化平台、分布式调度、预算结算和 GC 都被放在首个产品闭环之前。2026-07-21 业务方批准以下修正：

- 先交付真实多文档 MVP，而不是继续建设孤立组件；
- MVP 固定长期对象和接口，后续扩实现而不换主链；
- P-1、完整预算/调度和 13 产品全 baseline 后置，但企业路线不删除；
- LLM-wiki-black 是项目方第一方资产，可选择性迁移为 Python Harness 组件；第三方许可证单独管理。

## M1 · 真实多文档 MVP（当前，7–10 个工作日）

**目标**：用现有底座走通“资料进 → 知识编译 → 人审 → 人/Agent 同快照 → 更新/回滚”的真实闭环。

### 固定范围

- 23 份受控输入：15 份真实 PDF、5 份只进入产品注册且零 Claim/Evidence 的 `product_meta.json`，以及混合产品文档、后续修订/冲突来源、FAQ JSON；
- 5 个产品，覆盖医疗、终身寿险、年金；
- WeKnora 文档来源与已知 schema 结构化来源；
- 固定批准模板、弱模型多次短任务、Evidence 回验、ChangeSet/Conflict、人工审核；
- ReleaseManifest/完整 hash 批准、Harness Reader 与 MCP 同 SnapshotReader；
- 一次来源更新、一次失败告警、一次回滚。

### 工作包

| 包 | OpenSpec | 交付 |
|---|---|---|
| Model Gate | 027 | 所有生产入口只允许批准、身份冻结的 MiniMax/Qwen/Qwen-VL 级弱模型；旧强 judge/fallback fail closed |
| Template + Runtime | 028 | 最小 TemplatePackage、父 intake → 按产品/模板确定性子 compilation job、StageRun/Attempt/AgentReceipt/Alert、可恢复编排与现有主链接线 |
| Release Authority | 029 | ReleaseManifest、授权人批准完整 hash、CAS CurrentRelease、逻辑回滚；P-1 前不写生产 Wiki UI |
| Structured Thin Slice | 010 的 MVP 子集 | `product_meta.json` 只进产品注册且零 Claim/Evidence；已登记 FAQ `fact_assertions` → SourceRevision/结构化 Evidence → Claim 候选 → ChangeSet/Review，raw FAQ 只暂存 |
| Human/Agent Read | 013 core + 032 | 独立只读 Human Wiki Reader 与 MCP 消费同一 ApprovedSnapshotReader，返回相同 snapshot/hash；008 继续只做运营审核 |
| Real Slice/E2E | 030 | 23-entry manifest/fixtures、最小 parameterized admission core + 固定 MVP profile（实现 027 `AdmissionVerifier`、签发 opaque `VerifiedAdmission`，不复用 020 evaluator）、真实运行、更新/冲突/告警/回滚验收报告 |

### 完成定义

1. 23 份受控输入可校验且幂等，5 份 `product_meta` 不冒充 Claim 来源；
2. 5 个产品形成有 Evidence 的可读知识页；
3. 混合文档由父 intake job 按明确产品/模板扇出子 compilation job，不产生跨产品污染，歧义进入人工队列；
4. `product_meta` 只注册产品；已登记 FAQ fact assertions 可跳过 PDF 解析但不跳过来源、冲突、审核与版本；
5. 新 SourceRevision 形成 add/enrich/supersede/conflict，不静默覆盖；
6. 模板失配、无共识、证据断链或尝试耗尽产生持久 Alert 并停止推进；
7. 授权人批准完整 manifest hash 后才移动 CurrentRelease；
8. 人与 MCP 返回相同 snapshot/hash；
9. 回滚不重新调用模型；
10. 独立验收报告诚实区分 deterministic、PostgreSQL、WeKnora live 与真实 provider 证据。

MVP 不宣称 WeKnora 生产 Wiki UI 已完成；P-1 前只使用 ACL 隔离 staging + Harness Reader/MCP。

## M2 · 企业生产核心（MVP 后重新基线，参考 3–5 周）

**目标**：把 MVP 的同一合同扩展为正式生产发布和完整业务覆盖。

| 能力 | 主要范围 | 完成定义 |
|---|---|---|
| P-1 原子发布 | release namespace、seal、`active_release_id` CAS、MCP alias 核对、pin/GC、批准撤销/到期 | 人、MCP、页面、目录、关系和索引物理同快照；故障不移动 serving alias |
| 完整 Template Registry | global→险种→文档类型→产品族 scope、版本/hash/approval/retire、Golden Slice 准入 | 模板可评测、可回滚、失配告警；草案不自动生产化 |
| 完整 Runtime | durable job/checkpoint、worker lease/fencing、多模型计划、预算预留/结算 | 崩溃恢复、迟到 worker 拒绝、attempt/receipt 可审计 |
| 完整结构化知识 | 010 全量：未知 schema 映射、CSV/API、QA staging、mapping 演进 | 文档与结构化输入同走治理主链 |
| 完整 Human/Agent | 013 四工具、032 扩展、008 发布/回滚页、009 概念、012 QA | 产品页、概念、FAQ、比较和历史版本完整 |
| 完整质量基线 | 13 产品和跨险种 Golden Slice、020 D2～D4/D4b | 召回/准确率/Evidence/污染/冲突指标有真实 provider 证据 |

M2 完成后，Enterprise LLM Wiki 才可宣称企业生产核心就绪。

## M3 · 规模运营（M2 后滚动计划，参考 4–6 周）

**目标**：支持百千文档并发、知识运营和持续质量提升。

- 014/NS-F：按 Space/产品版本分片、限流、公平性、dead letter、批次控制台；
- 011：知识完整度、证据健康、过期/漂移/孤立/任务可靠性；
- NS-E：产品知识仪表盘、Schema/Template Workbench、缺口批量补全与审批；
- 完整预算与成本运营：provider/model/tenant/product 维度，不进入 M1 主叙事；
- 015 飞轮：查询缺口、审核反馈、错误样例 → 新任务/Golden Slice/模板版本；
- 更多险种和文档类型按 slice 准入，不一次性大爆炸上线。

完成定义：千份级批次可恢复运行；同一产品 finalize 串行且不丢更新；质量趋势和 Alert 有 Owner/SLA；模板/模型升级经过固定留出集非退化。

## M4 · 持续演进

- 基于业务背景生成 Schema/Template 草案，并经过留出集和人工批准；
- 关系/概念网络、差异分析、决策表与 Agent 规划接口；
- 扫描表格、图片、音视频等多模态扩展；
- 受控 Deep Research 与知识发现，只产生候选，不绕过 Evidence/ChangeSet/Review；
- 将高频问答、审核否决和冲突模式转为可版本化知识资产。

M4 是持续产品演进，不设置一次性“完成”日期。

## Architecture Runway：从 MVP 起冻结

M1～M4 共用以下对象和语义：

`KnowledgeSpace / SourceRevision / Claim / Evidence / ChangeSet / ReviewItem / ReleaseSnapshot / TemplatePackage / CompilationJob / StageRun / Attempt / AgentReceipt / Alert`

扩展规则：

- 单进程 executor → 分布式 worker，只换 runtime adapter；
- 固定模板实例 → 四级 registry，只扩 TemplatePackage repository/resolver；
- Harness CurrentRelease → WeKnora active alias，只扩 release adapter/seal receipt；
- 产品主数据注册 + 已登记 FAQ fact assertions → 通用结构化平台，只扩 mapping/source adapters，不改变双通道边界；
- MCP core → 完整工具集，继续只读 SnapshotReader；
- 5 产品 slice → 13 产品/全险种，继续使用相同 Golden/quality contracts。

任何后续方案若要求放弃这些身份或绕过 Claim/Evidence/ChangeSet/ReleaseSnapshot，必须回到北极星重新审批，不能在执行 PR 中自行重构。

## MVP 前明确不排

- P-1 全故障矩阵、GC/retention 全组合；
- 13 产品 canonical 020 完整运行；
- 完整预算 UI、退款 reconciliation、成本分摊；
- 千份并发、五级限流、公平性和批次控制台；
- 未知 schema 通用映射、10 万条结构化压力测试；
- PP-StructureV3、图谱洞察、Deep Research、多模态增强；
- 与当前 Wiki 闭环无直接关系的 WeKnora 平台优化。

“不排”只表示不进入 M1；上述能力均保留在 M2～M4，不得据此删除合同或扩展点。

## Roadmap 运营规则

- HANDOFF 只放实时状态、最多 3 个 blocker、下一动作和证据链接；
- 23 号文档只放冻结 MVP 范围、任务拓扑和效率规则；
- 本文只放稳定阶段与完成定义；
- 13 号文档只记录已交付能力和差量；
- OpenSpec 是单个功能包的条款级合同；
- master plan 是完整 backlog，不再作为当前 MVP 控制板。

每个里程碑收尾都更新 13/15/HANDOFF，并用实际 PR 七段时间重新估算下一阶段。

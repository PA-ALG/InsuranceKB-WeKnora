# 028 · TemplatePackage + Compilation Runtime MVP

> 状态：MVP S1，规格待独立复核；027 合入后实现。北极星 C1/C3/C4/C7。

## 为什么做

现有分类、抽取、attempt、merge、review、snapshot 各自可用，但缺少统一可恢复 Harness；旧 product fast-path 还可能绕过 identity/relation/audit/governance。MVP 需要把现有部件编排成不会“一环断、全链丢”的插件运行时。

LLM-wiki-black 的第一方 TypeScript 代码是能力迁移来源，不是待并排部署的第二套 runtime。本 change 同时完成语言收敛：生产领域逻辑只在 Python 3.12 Harness 运行。

## 做什么

- 最小但可扩展的 `TemplatePackage/TemplateVersion/TemplateApproval`；
- `CompilationJob/StageRun/Attempt/AgentReceipt/Alert` 稳定合同；
- 分别可 checkpoint 的固定阶段：materialize → classify_route → resolve_template → extract → verify → gap → consensus → knowledge_sink；
- 复用 WeKnora Source、KnowledgeScope、product routing、MergeEngine、ReviewItem、QualityGate；
- 2–4 worker 上限的单进程持久 executor、checkpoint、幂等重放、固定 attempt/time/token 上限；
- 多个批准弱模型角色做短任务和证据共识，失败停止并告警。

## 不做

不建设完整分布式 lease/fairness、成本分摊 UI、通用模板自动生成、P-1 发布或千份并发；不部署 Node/TS DomainSkill 服务，不建立 Python↔TS 运行时桥，不复制旧单体 extractor，不重写已有 knowledge/source/product 状态机。

## 文件域

包名冻结为新 `harness/src/insurance_harness/template_packages/` 与新 `runtime/`、相关 tests；旧 compiler 只允许小型 adapter，不在本 change 大改。028a 是不可部署的纯领域 PR，只含 immutable models、canonical hash、只读 catalog port 和纯 resolver，禁止 SQLAlchemy/table/DDL/production approval storage；028b 在一个 actual-head migration 中同时增加 TemplateVersion/Approval 与 runtime persistence，并提供生产 Python plugins/wiring/CLI，合入后才可部署。

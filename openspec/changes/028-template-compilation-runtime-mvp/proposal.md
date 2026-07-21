# 028 · TemplatePackage + Compilation Runtime MVP

> 状态：MVP S1，规格与实施计划已独立复核；027 合入后实现。北极星 C1/C3/C4/C7。

## 为什么做

现有分类、抽取、attempt、merge、review、snapshot 各自可用，但缺少统一可恢复 Harness；旧 product fast-path 还可能绕过 identity/relation/audit/governance。MVP 需要把现有部件编排成不会“一环断、全链丢”的插件运行时。

LLM-wiki-black 的第一方 TypeScript 代码是能力迁移来源，不是待并排部署的第二套 runtime。本 change 同时完成语言收敛：生产领域逻辑只在 Python 3.12 Harness 运行。

## 做什么

- 最小但可扩展的 `TemplatePackage/TemplateVersion/TemplateApproval`；
- `CompilationJob/StageRun/Attempt/AgentReceipt/Alert` 稳定合同；
- 唯一 manifest dispatcher 在全量 preflight 后分三路：exact-entry `product_meta` 只经 010/003 注册、registered FAQ 只经 010 structured governance、document 才创建父/子 job；前两路零模型/零伪 job；
- 两级可恢复 job：父 intake job 先 materialize → classify_route → resolve_template → fan_out，再按明确产品/模板确定性创建子 compilation job；
- 子 job 分别 checkpoint：extract → verify → gap → consensus → knowledge_sink；混合文档可扇出多个子 job，歧义 section 只进 unassigned + Alert/ReviewItem；
- 复用 WeKnora Source、KnowledgeScope、product routing、MergeEngine、ReviewItem、QualityGate；
- 2–4 worker 上限的单进程持久 executor、checkpoint、幂等重放、固定 attempt/time/token 上限；
- 多个批准弱模型角色做短任务和证据共识，失败停止并告警。
- 027 canonical verifier/opaque capability 在每个可推进进程重新核验；010 exact-entry ports 只由 concrete thin adapters 调用，三分支 receipt/count/hash 最后封入同一 compilation manifest。

## 不做

不建设完整分布式 lease/fairness、成本分摊 UI、通用模板自动生成、P-1 发布或千份并发；不部署 Node/TS DomainSkill 服务，不建立 Python↔TS 运行时桥，不复制旧单体 extractor，不重写已有 knowledge/source/product 状态机。

## 文件域

包名冻结为新 `harness/src/insurance_harness/template_packages/` 与新 `runtime/`、相关 tests；旧 compiler 只允许小型 adapter，不在本 change 大改。028a 是不可部署的纯领域 PR，只含 immutable models、canonical hash、只读 catalog port 和纯 resolver，禁止 SQLAlchemy/table/DDL/production approval storage；028b 在一个 actual-head migration 中同时增加 TemplateVersion/Approval 与 runtime persistence，并提供生产 Python plugins/wiring/CLI、manifest dispatcher，以及 `runtime/plugins/product_registration.py`/`structured_facts.py` 对 010 public exact-entry APIs 的 thin adapters，合入后才可部署。

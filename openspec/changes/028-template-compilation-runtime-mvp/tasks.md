# 028 任务（风险 B；建议拆 028a/028b 两个 PR）

- [ ] T0 冻结 TR0 语言边界：TS 仅作 provenance/characterization 输入，所有目标路径为 Python；审查 Harness/部署无 Node/TS 领域服务、queue、事实状态或运行时桥

## 028a TemplatePackage

- [ ] T1 冻结包名与 ports，写 TR1/TR2 RED：canonical hash、approval、scope stack、相似产品隔离
- [ ] T2 实现 immutable models、canonical hash、`TemplateCatalog` 只读 Protocol 与纯 resolver；028a 禁止 SQLAlchemy/table/persistent repository/DDL，不宣称可部署
- [ ] T3 记录 LLM-wiki-black TS source commit/path、接受/拒绝行为、Python target path 与 characterization tests；不整体搬运旧包，不建立双 runtime
- [ ] T4 focused + Golden Slice resolver tests；独立 review 后合小 PR

## 028b Compilation Runtime

- [ ] T5 写 TR3/TR4 RED：job 幂等、stage checkpoint、restart、attempt/receipt append、Alert 去重
- [ ] T6 在 028b 同一 actual-head `0014` migration 中创建 TemplateVersion/TemplateApproval 及 Job/StageRun/Attempt/AgentReceipt/Alert 全部表，实现 SQLAlchemy repositories 与单进程 2–4 worker executor；建表不是可选项
- [ ] T7 写 TR5 RED：弱模型多角色、证据回验、gap、无共识人工接管
- [ ] T8 实现 materialize/classify_route/resolve_template/extract/verify/gap/consensus 七个生产 Python stage adapters 与 orchestrator；统一使用 027 ModelGateway，不复制或执行旧 TS/pipeline
- [ ] T9 写 TR6 RED：用真实来源冻结 fixture 组合所有生产 adapters，经 Source lifecycle/KnowledgeSink 到 ChangeSet/Review；无第二套治理表、无直接 Wiki/CurrentRelease/TS runtime path
- [ ] T9a 写 TR8 RED/实现唯一 `python -m insurance_harness.runtime.cli run-manifest --request ... --output-dir ...`，冻结 exit code 与最后写入的 sealed compilation bundle；它不得产出 release proof/final artifact manifest 或移动 CurrentRelease，030 不得另写编译 runner
- [ ] T10 focused/领域 suite；PR ready 一次 full deterministic；真实 provider 只在 030 admission READY 后跑
- [ ] T11 独立 review、validation report、HANDOFF 一行与七段时间

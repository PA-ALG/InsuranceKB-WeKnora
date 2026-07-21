# 028 任务（028a 模板纯领域风险 B；028b 持久化/迁移风险 A、编排风险 B；建议拆两个 PR）

- [ ] T0 冻结 TR0 语言边界：TS 仅作 provenance/characterization 输入，所有目标路径为 Python；审查 Harness/部署无 Node/TS 领域服务、queue、事实状态或运行时桥

## 028a TemplatePackage

- [ ] T1 冻结包名与 ports，写 TR1/TR2 RED：canonical hash、approval、scope stack、相似产品隔离
- [ ] T2 实现 immutable models、canonical hash、`TemplateCatalog` 只读 Protocol 与纯 resolver；028a 禁止 SQLAlchemy/table/persistent repository/DDL，不宣称可部署
- [ ] T3 记录 LLM-wiki-black TS source commit/path、接受/拒绝行为、Python target path 与 characterization tests；不整体搬运旧包，不建立双 runtime
- [ ] T4 focused + Golden Slice resolver tests；独立 review 后合小 PR

## 028b Compilation Runtime

- [ ] T5 写 TR3/TR4 RED：父 intake identity 在分类前不含未知产品/模板但绑定 admission artifact/request/verified-binding digests；明确路由按产品/模板确定性扇出子 compilation identity并继承 binding digest；混合文档多子 job、unassigned 隔离、父/子重放、stage checkpoint；resume 每进程重新 canonical verify，过期/替换 request 或 admission B 不得复用 A checkpoint；attempt/receipt append、Alert 去重
- [ ] T6 在 028b 同一 actual-head `0014` migration 中创建 TemplateVersion/TemplateApproval 及 Job/StageRun/Attempt/AgentReceipt/Alert 全部表；Job 必须支持 `job_kind`、nullable `parent_job_id`、content-addressed request/admission refs 与 digests、verified-binding digest 及父/子唯一身份，实现 SQLAlchemy repositories 与单进程 2–4 worker executor；不得持久化 opaque capability，建表不是可选项
- [ ] T7 写 TR5 RED：弱模型多角色、证据回验、gap、无共识人工接管
- [ ] T8 实现 materialize/classify_route/resolve_template/extract/verify/gap/consensus 七个生产 Python stage adapters 与 orchestrator；orchestrator 将前三个用于父 job、把 `fan_out` 作为独立 checkpoint、将后四个与 knowledge_sink 用于子 job；实现 manifest dispatcher，并在 `runtime/plugins/product_registration.py`/`structured_facts.py` 分别以 thin adapter 实现 `ProductRegistrationPort.apply_exact_entries`→010 `bootstrap_manifest_entries`、`StructuredFactImportPort.apply_registered_records`→010 `import_known_schema_manifest_entries`；product_meta/FAQ 不建模型 job且 receipts 进同一 manifest；模型路径统一使用 027 canonical `GuardedModelClient`，不复制 003/010 或旧 TS/pipeline 领域逻辑
- [ ] T9 写 TR6 RED：用真实来源冻结 fixture 组合适用的父/子生产 adapters，经 Source lifecycle/KnowledgeSink 到 ChangeSet/Review；无第二套治理表、无直接 Wiki/CurrentRelease/TS runtime path
- [ ] T9a 写 TR8 RED/实现唯一 `python -m insurance_harness.runtime.cli run-manifest --request ... --output-dir ...`；submit/resume 同样要求 same frozen request，status 只读；只消费 027 canonical AdmissionVerifier/opaque capability，任一 purpose/schema/Space/manifest/eligibility/Golden/routing/template/structured-dispatch/model/caps/provenance/integration-SHA/expiry 漂移或 persisted digest mismatch 均 exit 2 且零 job/Attempt/provider；验证 exact 5 meta 不 root-scan、FAQ raw/assertion 双通道、三分支 receipt/count/hash 与零模型边界；冻结最后写入的 sealed compilation bundle；它不得产出 release proof/final artifact manifest 或移动 CurrentRelease，030 不得另写编译 runner
- [ ] T10 focused/领域 suite；PR ready 一次 full deterministic；真实 provider 只在 030 admission READY 后跑
- [ ] T11 独立 review、validation report、HANDOFF 一行与七段时间

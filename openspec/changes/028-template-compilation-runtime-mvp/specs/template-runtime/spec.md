# 028 Template/Runtime MVP 验收规格

## ADDED Requirements

### Requirement: TR0 单一 Python 领域运行时

LLM-wiki-black 的 TypeScript 实现 SHALL 只作为第一方能力迁移来源；保险领域的模板、路由、抽取、校验、融合、冲突与任务编排 SHALL 在 Python 3.12 Harness 内实现并执行。MVP SHALL NOT 引入 Node/TS 领域服务、TS queue/localStorage 事实状态或 Python↔TS 运行时桥。WeKnora 上游实现与纯展示/API client 前端不属于本限制，但不得拥有领域事实或发布权威。

#### Scenario: 迁移行为不产生第二套 runtime

- **WHEN** 执行会话迁移任一 LLM-wiki-black 能力
- **THEN** 迁移记录包含 TS source commit/path、Python target path 与 characterization/Golden Slice tests，生产部署和知识主链不启动或调用 Node/TS 领域进程

### Requirement: TR1 内容寻址 TemplatePackage

TemplateVersion SHALL 冻结 scope、schema、field groups、role prompts、validators、evidence policy、attempt limits、golden slice ref 和 rights/provenance receipt；content hash 从 canonical 全量内容计算。未批准、hash 不匹配、scope 不适用的模板不得用于 production job。028a 的 in-memory catalog 只用于 pure-domain tests；production resolution SHALL 使用 028b 持久、Space-scoped repository。

#### Scenario: 批准后内容改动失效

- **WHEN** 已批准模板任一内容被修改但沿用原 approval
- **THEN** resolver 拒绝，创建 template_mismatch Alert，零模型调用

### Requirement: TR2 稳定解析顺序

resolver SHALL 按 global → product-line → document-type → product-family 叠加，并返回最终内容 hash 与来源链。MVP 只需登记本 slice 的固定实例，但不得以 if/else 把产品名写死在 orchestrator。

#### Scenario: 相似产品不串模板

- **WHEN** 普通终身寿险与同名分红型同时编译
- **THEN** resolver 按 scope/版本返回适用模板链，不以模糊名称串用产品模板

### Requirement: TR3 可恢复 CompilationJob

CompilationJob SHALL 使用同一持久模型表达两级层次，避免在分类前伪造产品/模板身份：

- 父级 intake job identity 至少绑定 `space + source_revision + run_revision + admission_artifact_hash + strict_request_digest + verified_binding_digest + routing_policy_hash + template_lock_hash + structured_dispatch_lock_hash + model_plan_hash`；其固定且分别 checkpoint 的 StageRun 为 `materialize/classify_route/resolve_template/fan_out`；
- `resolve_template` SHALL 在分类结果上解析每个明确产品路由的批准模板；`fan_out` SHALL 为每个明确的 `product_version_id + routed_section_set_hash + schema_version + resolved_template_hash` 确定性创建一个子 compilation job；
- 子 job identity 至少绑定 `parent_intake_job_id + verified_binding_digest + product_version_id + routed_section_set_hash + schema_version + resolved_template_hash + model_plan_hash`；其固定且分别 checkpoint 的 StageRun 为 `extract/verify/gap/consensus/knowledge_sink`；
- 同 identity 重放 SHALL 复用原父/子 job，成功阶段在进程重启后不重做。`verify/gap/consensus` 不得合并成一个不可定位黑盒阶段。

混合文档 SHALL 可扇出到多个产品子 job。无法明确归属的 section SHALL 以稳定 section hash 持久化到既有 unassigned 路径并产生可追踪 Alert/ReviewItem；不得创建伪产品子 job，也不得把歧义内容送入任一产品的模型抽取。

opaque `VerifiedAdmission` SHALL NOT 持久化。所有可能创建 job/Attempt 或调用模型/工具的 submit/resume/run-manifest 进程 SHALL 用同一冻结 strict request 与仓外 content-addressed admission artifact 重新调用 canonical verifier，fresh 检查 expiry/current content，并把得到的 digest 与 job 持久化的 request/admission/binding digests 精确比较。不同 admission 即使沿用 run revision/template/model 也不得复用旧 checkpoint；只有相同 verified-binding digest 才可恢复。只读 status 可不持有 capability，但不得推进状态。

#### Scenario: 中间失败后恢复

- **WHEN** evidence verify 阶段失败后重启 executor
- **THEN** 父 job 的 materialize/classify_route/resolve_template/fan_out 与该子 job 的 extract 已成功 checkpoint 不重做，该子 job 从 verify 继续

#### Scenario: 重启重新验签且不洗白 checkpoint

- **WHEN** resume 使用过期/替换的 request 或 admission B 与原 job A 的 integration SHA、caps、authority 任一不同
- **THEN** canonical verifier 或 repository digest check 在 Attempt/provider 前拒绝，A 的 succeeded checkpoint 不被 B 复用；只有同 request/admission/verified-binding digest 的 fresh capability 可继续

#### Scenario: 混合文档确定性扇出且歧义隔离

- **WHEN** 一个 SourceRevision 含两个可明确归属产品的 sections 与一个歧义 section
- **THEN** 同一父 intake job 确定性复用两个产品子 job，歧义 section 只进入 unassigned + Alert/ReviewItem，重放不新增 job、unassigned 记录或 Alert

### Requirement: TR4 Attempt/Receipt/Alert

每次模型/工具尝试 SHALL 先创建 Attempt，结束后追加 AgentReceipt；receipt 包含 input/output hash、027 `ModelPermitView` 审计 identity（不构成 authority）、template/prompt version、verified-binding/call-scope digest、usage/latency/outcome 和 evidence refs，不保存 secret、process seal 或 opaque capability。失败达到上限 SHALL 产生可去重、认领、关闭的 Alert 并停止候选推进。

#### Scenario: 空结果不算成功

- **WHEN** 模型返回空正文或 Evidence 回验失败至上限
- **THEN** stage=blocked、Alert 存在、零 ProposedClaim 进入 merge

### Requirement: TR5 多弱模型与证据优先

runtime SHALL 让所有需要模型的 extract/gap/verify/consensus 路径只经 027 canonical `GuardedModelClient` 使用批准弱模型；caller 不得传 permit。高风险字段无共识、Evidence 不可回验或三态不明确时进入 ReviewItem/Alert，不得由 consensus 直接发布。

#### Scenario: 无共识转人工

- **WHEN** 两个弱模型对同字段给出互斥值且双方证据均存在
- **THEN** 产生 conflict proposal + ReviewItem，CurrentRelease 不变

### Requirement: TR6 复用现有治理主链

runtime SHALL 通过公开 ports 复用 Source lifecycle、Product routing、MergeEngine、QualityGate、ReviewItem；SHALL NOT 创建第二套 Claim/Review/Snapshot 表，也不得直接写 WeKnora Wiki。

#### Scenario: 运行时没有治理旁路

- **WHEN** 静态/契约测试枚举 runtime writes
- **THEN** 语义写入只经 knowledge sink → ChangeSet/Review，页面/CurrentRelease 零直接写

#### Scenario: 生产组合根贯通治理而无旁路

- **WHEN** 一个带真实来源 hash/lineage 的冻结 fixture 通过 production composition root 与全部生产 Python stage adapters 运行，外部 Source 与 guarded-client transport 用零网络 scripted fake，027 test-only verifier fixture 仍产生真实 opaque capability
- **THEN** Source lifecycle 与 MergeEngine 产生预期 ChangeSet/ReviewItem，适用的父/子 stage 各成功一次且重放幂等
- **AND** publisher、CurrentRelease、WeKnora writer、Node/TS runtime 调用均为零

### Requirement: TR7 MVP 规模边界

MVP executor SHALL 支持同进程 2–4 worker、固定 attempt/time/token 上限和 23-entry 受控输入 run；完整 lease/fencing/fairness 可以后置，但稳定 Job/Stage/Attempt identity 不得改变。

#### Scenario: 资源上限生效

- **WHEN** 同时提交超过 worker/attempt 上限的任务
- **THEN** 超出部分保持 queued/blocked，不产生无界并发或强模型 fallback

### Requirement: TR8 唯一可复现运行入口

runtime SHALL 提供唯一 `python -m insurance_harness.runtime.cli run-manifest --request <external-yaml> --output-dir <new-external-dir>` 编译入口；独立 `submit` 与任何可推进模型阶段的 `resume` 也 SHALL 要求 `--request <same-external-yaml>`，而 `status` 严格只读。request SHALL 使用 027 `StrictAdmissionRequestBinding`，绑定 independent expected purpose、run schema version、run identity/revision，以及 source manifest/eligibility、admission artifact、Space、Golden Slice、routing policy、schema/template lock、structured-dispatch lock、model plan/deployment roles、资源上限、rights/provenance 与 integration SHA 的 canonical hashes/identities，且不含 secret；CLI 不接受 caller-supplied binding/READY/verifier 或模型/模板/上限逃生参数。028 SHALL 只消费 027 `AdmissionVerifier` Protocol：production composition root 先用 request expected purpose/schema 从代码 registry 选择唯一 verifier，再解析/验签 artifact 并逐字段比较 actual；不得由 artifact 自选 profile/domain。每次进程启动成功返回 fresh opaque `VerifiedAdmission`，其 rich binding view/digest 与 job persisted digests 精确相等才可推进；任一 unknown/wrong/expired/substituted request/admission 或其他 mismatch 在 job/Attempt/provider 创建前 exit `2`，零模型/工具调用、零运行时写入。027 model policy 只消费此 capability发 permit，不重复验签。

`run-manifest` SHALL 以 manifest dispatcher 处理三种冻结 entry，所有 ports 均接收同一 `VerifiedAdmission`/structured-dispatch lock：document entry 才创建父/子 CompilationJob；registration-only product_meta 调用注入的 `ProductRegistrationPort.apply_exact_entries`，只处理 manifest 明列 path/hash（不得 root scan/额外注册），产生零 Claim/Evidence；registered FAQ fact assertions 调用注入的 `StructuredFactImportPort.apply_registered_records`，raw FAQ 只暂存、事实断言经 010 公共 service 进入治理，且不创建模型 job。registration/structured receipts 与 count/hash、零模型调用证明 SHALL 纳入同一 sealed compilation manifest。dispatcher/028 不得复制 003/010 领域逻辑，010 必须提供 exact-entry/public APIs。

exit `0` 只表示所有三类适用 entry 完成各自 sink 且最后写入、校验了 `compilation-manifest.json`；它不得生成 release proof、最终 artifact manifest 或移动 CurrentRelease。`2` 表示调用外部能力前的 gate/preflight blocked，`3` 表示启动后 terminal blocked/failed 并保留部分 receipts/Alerts；既有 output dir 必须拒绝。后续 029 人控治理 CLI 不是第二套编译 runtime，禁止导入 stage plugin 或调用模型。

#### Scenario: 030 使用同一 runner

- **WHEN** 以冻结 request 执行 23-entry run（registration-only 输入不创建编译 job）
- **THEN** 编译只调用本入口，生成 run summary、父/子 jobs、stages/attempts/receipts/alerts/unassigned/metrics/governance proposal identifiers，并最后写入 compilation manifest；CurrentRelease 不变
- **AND** compilation manifest 含每个编译制品的 count/hash，任何 secret/raw provider body 不进入 bundle；release proof 与最终 artifact manifest 只能在 029 真人审核/批准/CAS promote 后产生

#### Scenario: strict request 不得脱离签名 admission

- **WHEN** request 的 expected purpose/schema 未登记或与 artifact 不同，或 Space、manifest/eligibility、Golden Slice、routing/template/structured-dispatch locks、model plan、resource caps、rights/provenance、integration SHA 任一与已签 030 admission 不同
- **THEN** canonical AdmissionVerifier 返回 typed preflight blocked，exit=2，父/子 job、Attempt、provider/model/tool 调用均为 0

#### Scenario: 同一 runner 严格分派双通道

- **WHEN** 23-entry manifest 含 5 个 registration-only product_meta、document entries 与 registered FAQ fact assertions
- **THEN** 只精确注册 5 个 manifest 产品且零 Claim/Evidence；只有 document entries 创建 compilation jobs；FAQ raw 暂存且 explicit assertions 经 010 service；所有分支 receipt 被同一 compilation manifest 封存，structured/model calls 为各自预期且无额外目录扫描

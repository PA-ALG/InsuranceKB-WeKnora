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

Job identity SHALL 至少绑定 space、source revision、product/version、schema version、template hash、model plan hash；同 identity 重放复用原 job。StageRun 名称固定且分别 checkpoint：`materialize/classify_route/resolve_template/extract/verify/gap/consensus/knowledge_sink`；成功阶段在进程重启后不重做，不得把 verify/gap/consensus 合并成一个不可定位黑盒阶段。

#### Scenario: 中间失败后恢复

- **WHEN** evidence verify 阶段失败后重启 executor
- **THEN** materialize/classify/extract 的已成功 checkpoint 不重做，从 verify 继续

### Requirement: TR4 Attempt/Receipt/Alert

每次模型/工具尝试 SHALL 先创建 Attempt，结束后追加 AgentReceipt；receipt 包含 input/output hash、027 model permit identity、template/prompt version、usage/latency/outcome 和 evidence refs，不保存 secret。失败达到上限 SHALL 产生可去重、认领、关闭的 Alert 并停止候选推进。

#### Scenario: 空结果不算成功

- **WHEN** 模型返回空正文或 Evidence 回验失败至上限
- **THEN** stage=blocked、Alert 存在、零 ProposedClaim 进入 merge

### Requirement: TR5 多弱模型与证据优先

runtime SHALL 让 extract/gap/verify/consensus 只使用 027 permit 的弱模型；高风险字段无共识、Evidence 不可回验或三态不明确时进入 ReviewItem/Alert，不得由 consensus 直接发布。

#### Scenario: 无共识转人工

- **WHEN** 两个弱模型对同字段给出互斥值且双方证据均存在
- **THEN** 产生 conflict proposal + ReviewItem，CurrentRelease 不变

### Requirement: TR6 复用现有治理主链

runtime SHALL 通过公开 ports 复用 Source lifecycle、Product routing、MergeEngine、QualityGate、ReviewItem；SHALL NOT 创建第二套 Claim/Review/Snapshot 表，也不得直接写 WeKnora Wiki。

#### Scenario: 运行时没有治理旁路

- **WHEN** 静态/契约测试枚举 runtime writes
- **THEN** 语义写入只经 knowledge sink → ChangeSet/Review，页面/CurrentRelease 零直接写

#### Scenario: 生产组合根贯通治理而无旁路

- **WHEN** 一个带真实来源 hash/lineage 的冻结 fixture 通过 production composition root 与全部生产 Python stage adapters 运行，外部 Source/ModelGateway 端口用零网络 scripted fake
- **THEN** Source lifecycle 与 MergeEngine 产生预期 ChangeSet/ReviewItem，所有 stage 各成功一次且重放幂等
- **AND** publisher、CurrentRelease、WeKnora writer、Node/TS runtime 调用均为零

### Requirement: TR7 MVP 规模边界

MVP executor SHALL 支持同进程 2–4 worker、固定 attempt/time/token 上限和 23-source run；完整 lease/fencing/fairness 可以后置，但稳定 Job/Stage/Attempt identity 不得改变。

#### Scenario: 资源上限生效

- **WHEN** 同时提交超过 worker/attempt 上限的任务
- **THEN** 超出部分保持 queued/blocked，不产生无界并发或强模型 fallback

### Requirement: TR8 唯一可复现运行入口

runtime SHALL 提供唯一 `python -m insurance_harness.runtime.cli run-manifest --request <yaml> --output-dir <new-dir>` 编译入口。request SHALL 绑定 source manifest/admission/Space/template/model-plan hashes 与资源上限且不含 secret；CLI 不接受模型/模板/上限逃生参数。exit `0` 只表示编译已走到 `knowledge_sink` 且最后写入、校验了 `compilation-manifest.json`；它不得生成 release proof、最终 artifact manifest 或移动 CurrentRelease。`2` 表示调用外部能力前的 gate/preflight blocked，`3` 表示启动后 terminal blocked/failed 并保留部分 receipts/Alerts；既有 output dir 必须拒绝。后续 029 人控治理 CLI 不是第二套编译 runtime，禁止导入 stage plugin 或调用模型。

#### Scenario: 030 使用同一 runner

- **WHEN** 以冻结 request 执行 23-source run
- **THEN** 编译只调用本入口，生成 run summary、jobs/stages/attempts/receipts/alerts/metrics/governance proposal identifiers，并最后写入 compilation manifest；CurrentRelease 不变
- **AND** compilation manifest 含每个编译制品的 count/hash，任何 secret/raw provider body 不进入 bundle；release proof 与最终 artifact manifest 只能在 029 真人审核/批准/CAS promote 后产生

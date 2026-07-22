# 027 Production Weak-Model Boundary 验收规格

## ADDED Requirements

### Requirement: PWB1 不可变弱模型身份

生产模型身份 SHALL 由 `provider + deployment/model immutable id + family + capability role + policy version` 构成；只允许批准列表中的 MiniMax/Qwen/Qwen-VL 能力档。`family` SHALL 是完整 identity key 的一部分，不得作为可替换标签。production config 只声明独立期望身份，不得用该声明构造批准列表或自批准；具体 deployment 的批准权 SHALL 来自 canonical `VerifiedAdmission` 中的 exact full identities，且与 code-owned production profile、完整角色集合和 model-plan hash 精确一致。每次受保护调用 SHALL 从当前 opaque admission authority 重新核对完整 identity 集合和 model-plan，不得复用另一份 admission 的初次绑定结果。

当前 MVP deny-only 预检 SHALL 只接受原文即 canonical ASCII lowercase 的 `bailian` provider 和 deployment：原文必须为 ASCII、NFKC 后不变且 casefold 后仍与原文相同，Unicode confusable、combining mark 或大小写混写不得经归一化后放行。deployment SHALL 由互斥锚定根 `qwen<major>[.<minor>]`、`qwen-vl<major>[.<minor>]` 或 `minimax-m<major>[.<minor>]` 开始；根后只允许 code-owned capability token `{prod,instruct,thinking,coder,chat,plus,max,turbo,long,preview}`、size/arch token `\d+([.]\d+)?b`/`a\d+b`，并以 YYYYMMDD、严格 ISO `YYYY-MM-DD`、YYMM 或 `sha256-<8..64 lowercase hex>` 锚定，日期后可再带合法 sha256。未知字母 token、跨 family 根、任意尾串、短 digest、`latest`/rolling alias、Claude/DeepSeek/OpenAI/GPT/O-series 强模型、family/provider/deployment 伪装或批准记录不匹配 SHALL 在任何 provider/transport 构造前拒绝；强模型 marker 仅作纵深防御，不得代替 grammar。

#### Scenario: 未批准模型零网络调用

- **WHEN** production profile 请求未知、强模型或 rolling identity
- **THEN** 返回类型化拒绝，provider fake 记录零调用

#### Scenario: 配置不得自批准模型身份

- **WHEN** caller 在 production config 中把 GPT/O-series/custom deployment 标注为 Qwen，或让 provider/deployment/family/role/policy 任一字段与 canonical admission 的批准身份不一致
- **THEN** code-owned provider catalog 或 exact `VerifiedAdmission` 比较在 provider 构造前类型化拒绝，模型调用数为 0；config 声明本身不产生 allowlist

#### Scenario: 受控 deployment grammar 不接受标签伪装

- **WHEN** caller 使用 `qwen-gpt-04-*`、分隔符变体、`qwen-minimax-*`、跨 family 根、大小写/Unicode confusable、未知 token 或不足 8 位的 sha256 anchor
- **THEN** deny-only grammar 在 config/bind/use-time client 构造或 transport 之前返回类型化拒绝，provider、ALLOW receipt 与 transport 均为 0；只有 grammar 合法且与 opaque `VerifiedAdmission` exact identity 相等的 deployment 才可继续

#### Scenario: 调用时完整身份集合不可替换

- **WHEN** composition 绑定后收到同 model-plan 但增加或缺少角色身份的另一份 `VerifiedAdmission`
- **THEN** 调用时从 opaque authority snapshot 重算的完整集合不相等，类型化拒绝且 receipt/transport 均为 0

### Requirement: PWB2 所有生产入口共用单一策略

所有会调用模型的 extract、gap、judge/consensus 与 conflict-suggestion entrypoint SHALL 通过 composition root 注入的 canonical `GuardedModelClient`，不得各自复制 allowlist，也不得接收 caller-supplied permit/policy/guard。merge candidate promotion 与 release command SHALL 明确证明为零模型路径；它们不得为了满足形状而接收伪 permit。缺 canonical guard 或 verified admission 的 production 模型调用 SHALL fail closed。

#### Scenario: 旁路枚举测试

- **WHEN** 测试枚举所有公开 CLI/API/package entrypoint
- **THEN** 每个 production 模型 entrypoint 都调用同一 canonical `GuardedModelClient`，其余 entrypoint 有明确零模型证明；公开 permit view 从不作为调用参数

### Requirement: PWB3 禁止强模型 fallback

生产路径遇到模板失配、弱模型失败、无共识或截断 SHALL 重试批准弱模型、产生 Alert/ReviewItem 或停止；SHALL NOT 自动切换强模型或 offline judge。

#### Scenario: 弱模型失败不升级模型

- **WHEN** 批准弱模型达到 attempt 上限仍失败
- **THEN** 结果为 blocked/alert proposal，强模型 fake 零调用，零 ChangeSet 自动推进

### Requirement: PWB4 Admission 与审计绑定

027 SHALL 冻结唯一跨包 admission 边界：`StrictAdmissionRequestBinding`、只读 rich `AdmissionBinding` view、opaque `VerifiedAdmission` capability，以及 `AdmissionVerifier.verify(StrictAdmissionRequestBinding) -> VerifiedAdmission` Protocol。030 只实现 verifier，028 只消费该 Protocol；两者不得复制 DTO/port。

production request/config SHALL 显式携带独立、不可变且必填的 expected purpose、run schema version、run identity/revision；这些期望值不得从 admission artifact 的 actual 值反推、缺省或回填。production composition root SHALL 先用 expected purpose/schema 从代码 registry 选择唯一 verifier，再调用 verify；CLI/config/PolicyContext SHALL NOT 接受 caller-supplied `AdmissionBinding`、`state=READY` 或 verifier override。`VerifiedAdmission` SHALL 只能由 canonical verifier 的受控非公开 factory 签发，包含不可序列化的进程内 seal 与 verification receipt；公开构造 rich DTO 不得成为 policy capability，test fake 只能存在于显式 test-only helper 且不得作为 production export。

capability 的 binding view 至少携带 actual purpose/schema、run identity/revision、state、artifact hash/expiry、Space、manifest/eligibility、Golden Slice、routing policy、schema/template lock、structured-dispatch lock、model plan、resource caps、rights/provenance、integration SHA 与批准 model roles 的 canonical hashes/identities，并产生覆盖全 binding + strict request 的 `verified_binding_digest`。027 不得重复实现 030 验签/evaluator；其单一 model policy 只消费 `VerifiedAdmission`，在任何网络调用前比较 expected/actual purpose/schema/run、Space、调用角色、model plan 与 exact template 对批准 template lock 的成员证明。

production policy SHALL 通过非公开 issuer 签发 opaque `IssuedModelPermit` capability；公开/可序列化的 permit view 只用于 receipt，不构成调用权威。permit capability 至少绑定 purpose、run schema、Space、run identity/revision、admission artifact hash、`verified_binding_digest`、exact template hash、model plan hash、model identity/role、call-scope hash 与 expiry，并携带不可由 Pydantic 构造/copy/deserialize 伪造的进程 seal。

`GuardedModelClient` SHALL 由 production composition root 注入 canonical policy/transport；CLI/config/caller 不得传入自定义 policy、permit issuer、permit capability 或 guard override。每次调用接收 `VerifiedAdmission + ModelCallContext`，由 client 内部调用 canonical policy evaluate/issue，再逐字段比较 issued permit scope；手工 DTO、复制 view 或 test fake 均不得进入 production transport。permit 不得仅凭相同 run/template/model 在另一 Space、manifest、template lock、integration SHA 或 call scope 重放。每次允许/拒绝 receipt SHALL 包含 permit identity、Space、verified-binding/call-scope digests 且不含 secret。任一身份缺失/不匹配、过期或 run 非 READY 时零网络调用。

#### Scenario: 不能借用 020 canonical 状态

- **WHEN** 030 MVP run 请求使用 020 canonical admission 的 approval/permit
- **THEN** 因 run identity 不匹配被拒绝

#### Scenario: 期望身份不得从 admission 自证

- **WHEN** production request 未显式提供 expected purpose/schema/run identity/revision，或实现试图用 admission actual 值同时充当 expected 与 actual
- **THEN** 在 provider client 构造前 fail closed，模型调用数为 0

#### Scenario: 手工 READY DTO 不构成 verified capability

- **WHEN** production caller 手工构造 `AdmissionBinding(state=READY)`、传入自定义 verifier，或绕过 canonical registry 直接调用 model policy
- **THEN** production composition/PolicyContext 在 client 构造前拒绝；只有 canonical verifier 返回的 opaque capability 可继续，模型调用数为 0

#### Scenario: permit 不得跨 verified scope 重放

- **WHEN** 已签发 permit 被用于另一 Space，或使用相同 run/model/template 但不同 manifest、template lock、integration SHA、job/stage call scope 的 context
- **THEN** GuardedModelClient 在 transport 前拒绝，provider 调用数为 0，receipt 记录 scope/digest mismatch

#### Scenario: 手工 permit 或自定义 guard 不构成调用权威

- **WHEN** caller 构造/复制/反序列化 permit view，替换 identity/role/expiry，或向 production entrypoint 注入自定义 policy/guard
- **THEN** canonical GuardedModelClient 不接受该输入，transport 调用数为 0；只有内部 policy issuer 产生的 opaque permit 可调用 transport

### Requirement: PWB5 零模型验证

027 自身所有 deterministic tests SHALL 使用 fake transport，validation report SHALL 明确真实 provider 为 `NOT RUN`。

#### Scenario: 报告不虚报 provider

- **WHEN** 027 在无真实 provider 调用下完成
- **THEN** 只报告 policy/entrypoint contract PASS，provider 记 `NOT RUN`

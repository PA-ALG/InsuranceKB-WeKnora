# 031 真实运行准入解阻规格

## ADDED Requirements

### Requirement: O1 缺失输入必须内容保持地规范化并重新绑定 identity

系统 SHALL 将唯一的 JSON-content `.txt` meta 迁移为标准 `product_meta.json`，不得
改变业务字段；旧路径不得残留为 unconsumed input。所有受影响 digest 必须从 clean
revision 重算。

#### Scenario: meta 迁移不改变业务内容

- **WHEN** 比较 rename 前后的 canonical JSON
- **THEN** 两者语义相等，identity 不再报告 `missing_path` 或
  `unconsumed_product_file`

### Requirement: O2 legacy provenance 必须是逐产品、显式受限的签名联合

系统 SHALL 使用带 discriminator 的
`ObservedAnnotationProvenance | LegacyFrozenProvenance`，每个历史产品恰好一个
entry。legacy entry SHALL 绑定 product/WIP digest、有效 ancestor frozen commit、该
commit 中实际存在的 evidence blob/digest、从代码 allowlist 仓库证据派生的 recorded
agent ID、evidence-freeze time 与 `original_annotation_time_unavailable`；freeze time
SHALL NOT 被解释为 annotation time。整个 entry 必须由 provenance approver 签名。

#### Scenario: 未签 legacy provenance 仍阻塞

- **WHEN** 11 个 legacy entries 已生成但没有 provenance approval
- **THEN** admission 保持 `BLOCKED/approval_missing`

#### Scenario: 缺失、重复、调用者自报或证据漂移被拒绝

- **WHEN** 产品没有恰好一个 entry，或 commit/blob/digest/agent/limitation 任一无法从
  allowlisted evidence 证明
- **THEN** provenance 为 typed `BLOCKED`，不得接受 CLI 自报值或全局 default

### Requirement: O3 审批工具和信任根必须把 key 绑定真实身份

trust store SHALL 为每个 key 固定 approver identity、允许 domain/scope/roles，验证器
SHALL 与签名 payload 精确比较。keygen/sign 不得 self-enroll trust。私钥 SHALL 使用
安全父目录、nofollow/dirfd 等价打开、原子 O_EXCL、限长、fstat 与 0600 保护，key bytes
永不输出。公开 envelope 可进入权威 plan；私钥和临时材料不得入库。

production ledger/controller 的 mutation API SHALL 只从 root-owned 固定配置加载 trust
policy，不得接受 caller 提供的 trust store、authority mapping 或 override path。operator
ceremony SHALL 对 budget、provenance、canary review、provisioning、adoption、pricing、
provider cap 与 cleanup 的独立 domain/role/scope 提供 render→外部 sign→verify；offline
verify 只提供诊断，不能铸造 production capability。

production mutation/finalization API 也不得接受 caller 提供的 `authorized_roles` 或权威
`now`。允许 role 集合必须来自同一 root-owned policy；freshness 必须由受信 runtime clock 在
比较点读取。测试 clock 只能通过显式 private test seam 注入，不得出现在 production public API。

#### Scenario: 自称其他身份或不安全密钥失败

- **WHEN** payload identity/role/domain/scope 与 key policy 不符，或路径/owner/mode/
  symlink/size 任一不安全
- **THEN** 工具 fail closed 且不产生 envelope、不泄露 key bytes

#### Scenario: 调用者不能自带信任根授权生产 mutation

- **WHEN** 调用者向 reserve、provision、adopt、cleanup 或 final bind 注入自签 authority/
  trust path、放宽 authorized roles、回拨 now，或把一个 domain 的 envelope 重放到另一 domain
- **THEN** 在 ledger/provider mutation 前失败，reserve、artifact 与网络调用均为 0

### Requirement: O4 provider POST 前必须存在签名预授权与 durable 固定费用占用

未来创建 SHALL 在 POST 前验证 signed `ProvisioningAuthorization`，其绑定 operation、
workspace/project/credential、region、base model、request plan、quota、价格证据、最大
费用和 deadline；stable infrastructure reserve SHALL 在网络前 exact-once durable
占用。receipt/final contract 只能引用原 authorization/reserve，不能事后追认费用。

ProvisioningAuthorization SHALL 使用 versioned domain
`insurancekb.run-admission.provisioning.v1\0`，并由 key policy 中
`deployment-provisioner` 角色签署；canonical payload SHALL 绑定 exact run identity、
purpose、scope、operation/reserve、plan/evidence digest、issued/expires。

当前 preexisting deployment 只能走显式 adoption exception：从 provider 创建时间起保守
计算成本，声明未由 031 ledger 预授权，经预算审批后先占用再进入 final plan；该路径
不得用于创建新资源。ExistingDeploymentAdoptionAuthorization SHALL 使用独立 domain
`insurancekb.run-admission.deployment-adoption.v1\0`，由 `budget-approver` 签署，并
额外绑定 exact deployed model、receipt digest、workspace/project/credential ref、quota、
gmt_create、pricing/cap evidence、incurred+future max cost 与 cleanup deadline。

provider hard cap SHALL 按同一受信资源边界聚合所有 run/purpose/account 的 fixed 与
inference 占用；资源边界至少绑定 workspace/project/credential/currency、cap evidence
identity/coverage 与签名 approval。`account_id` 只是运行账本键，不能隔离或重置共享 cap。
合法不同的 provider account/cap 不得互相污染。cap evidence 轮换不得绕过同一资源的既有
占用；exact replay 不得二次 debit。

#### Scenario: 网络前崩溃不发送且保留授权状态

- **WHEN** reserve 前或 durable pre-send journal 前崩溃
- **THEN** provider POST 次数为 0；恢复不会重复 debit

#### Scenario: 无 provider 硬费用边界不能 READY

- **WHEN** 只有本机 TTL/watchdog/delete，而无覆盖基础设施与推理费的 provider cap
- **THEN** 报告显示持续费用暴露，canonical admission 保持 typed `BLOCKED`

#### Scenario: 授权不可跨 domain、run、operation 或 deployment 重放

- **WHEN** provisioning 签名被当作 adoption 使用，或任一签名被替换 run、operation、
  reserve、receipt 或 deployed model
- **THEN** 验证在 durable reserve/provider mutation 前失败，保持 typed `BLOCKED`

#### Scenario: 共享 provider cap 跨 run 与 purpose 聚合

- **WHEN** 两个不同 run/purpose/account 使用同一受信 workspace/project/credential/cap，
  且其 fixed+inference 总占用超过 hard cap
- **THEN** 第二次 reserve 在任何 provider mutation 前失败，事务无部分写；并发结果与串行
  结果一致

### Requirement: O5 部署控制器必须 crash-safe、幂等且只允许固定最小组合

控制器 SHALL 只允许 strong=`qwen3.7-plus-2026-05-26`、weak=
`deepseek-v4-flash`、request plan=`ptu_v2`、10,000 input + 1,000 output TPM、北京
endpoint 与确定性 suffix。它 SHALL 使用 run lock、durable pre-send journal、provider
marker/list reconciliation；timeout、409 或响应丢失后先 reconcile，禁止盲 POST。

provider transport SHALL 提供稳定且非 secret 的 credential/project identity attestation，
并在任何 POST/GET/DELETE 前与签名 authorization/cap 的 workspace/project/credential 精确
匹配；receipt 的 credential/project identity 必须从已验证 transport identity 派生，不得从
请求 DTO 自报，也不得写入 raw API key。verified reconciliation capability 只能由受信
provider ownership verifier 基于 fresh remote evidence 签发；两个内容相等的 caller DTO
不能自铸 capability。

new/adoption/cleanup SHALL 共用 operation/run 级 OS lock。adoption 获锁后必须重新验证
authorization、cap、receipt 与 remote freshness；若等待锁期间过期，provider GET 次数为 0。

#### Scenario: 漂移配置在网络前拒绝

- **WHEN** 请求未知 base、alias 替换、其他 plan/quota/endpoint 或无授权 operation
- **THEN** provider mutation 次数为 0

#### Scenario: provider 已接受但客户端丢响应

- **WHEN** POST 成功后客户端 timeout 或在 receipt 前崩溃
- **THEN** 恢复通过 marker/suffix 找回唯一 deployment，不重复创建或重复 reserve

#### Scenario: 并发、collision 或伪造 receipt 不转移 ownership

- **WHEN** 两个 operator 并发、provider 返回 409，或本地 receipt 与远端 manifest 不符
- **THEN** 最多一个 operation 可继续；未知资源不被采纳或删除

#### Scenario: transport identity 或 receipt issuer 不匹配时零网络

- **WHEN** authorization/cap 属于 credential A 而 transport attestation 属于 credential B，
  或调用者克隆两个相等 receipt 试图签发 verified reconciliation
- **THEN** 在 provider mutation 前失败，不产生 verified capability、ledger row 或 artifact

### Requirement: O6 receipt、模型身份与基础设施 reserve 必须一一可审计

provider request `ptu_v2` SHALL 只映射到实测 receipt `ptu`，request quota 字段 SHALL
只映射为 receipt 的 10,000/1,000 canonical 值。receipt SHALL 绑定 operation、base/deployed
model、plan mapping、quota、gmt times、workspace evidence、cleanup state 与 digest。
每个 unique deployed model 恰好一个 stable reserve，role 只引用 reserve ID；
`model_id == immutable_deployment_id == deployed_model`。

final bind SHALL 在与两条 reserve/receipt 绑定相同的 ledger 事务中写入 content-addressed
durable topology sidecar 与 strong/weak receipt annex；sidecar 绑定完整 plan/contract、budget
approval、provider-cap evidence/approval、annex digest、角色、scope 与静态 evidence expiry，
annex 必须逐字节匹配固定 operation-store 中独立生成的 immutable ownership receipt artifact
与 fresh provider reconciliation artifact；后者必须绑定前者、remote manifest、operation、
reserve、workspace/project/credential、provider-cap evidence/approval、受信 issuer/transport
identity 及 observation window，并使用独立 content address。只有 production ledger fresh
reload 并重验两份工件后才能签发 opaque `VerifiedFinalTopology`。legacy ledger 迁移不得虚构
缺失 sidecar/annex；重放必须幂等，任一工件篡改、缺失或半写必须 fail closed。

topology 内嵌的 reconciliation issuer、digest 或 transport identity 只是被验证数据，不能作为
自身 trust root。production fresh reload SHALL 将其与 root-owned issuer/transport policy、
独立 durable provider reconciliation/ownership evidence 逐字段精确比较；调用者即使构造一组
内部完全自洽且全部签名可验证的 topology payload，也不能替代独立 provider provenance。

初始 receipt reconciliation 的短期 freshness 不得永久裁剪静态 topology；每个 production
submit/resume/begin 边界 SHALL 在静态 topology 通过后，使用 canonical controller 对 strong/weak
deployment 各执行一次 fresh detail observation，并原子发布同时绑定 topology/plan/cap/transport/
完整 manifest/receipt/roles 的内容寻址 batch。旧 batch、单边成功或任一 drift 均不能进入
evaluator/model/write；READY `valid_until` SHALL 纳入本次 batch expiry。

#### Scenario: annotator 与 judge 共享费用但保持独立角色

- **WHEN** 两角色引用同一 verified strong receipt/reserve
- **THEN** 两角色各自通过 identity，基础设施固定费用只计一次

#### Scenario: mutable base 或 metadata 漂移保持阻塞

- **WHEN** provider 不能证明 unique deployed model 冻结 resolved base，或 receipt metadata
  后续漂移
- **THEN** identity 为 typed `BLOCKED`，不得因 base 字符串在 allowlist 而放行

#### Scenario: durable topology 重放与迁移保持 fail closed

- **WHEN** 相同 final bind 在稍后时间 exact replay，或 v5 ledger 迁移到 v6 但没有历史
  topology sidecar
- **THEN** exact replay 返回同一 topology digest 且不重复写；legacy row 仍可用于受控 cleanup，
  但不得据其签发 READY capability

#### Scenario: 自洽伪造 topology 不能铸造 production capability

- **WHEN** topology 的 issuer/transport/reconciliation digest 在自身 JSON 内彼此一致，但没有
  root-owned issuer/transport binding 或独立 durable remote evidence
- **THEN** fresh reload 拒绝签发 `VerifiedFinalTopology`，READY/probe/model/provider I/O 为 0

#### Scenario: 重写 observation window 不能替代独立 reconciliation 工件

- **WHEN** 调用者修改 strong 或 weak topology 的 observation window，并同步重算 reconciliation
  digest 与外层 topology digest，但固定 operation store 中没有该 digest 对应的受信工件
- **THEN** fresh reload 在签发 capability 前 fail closed，ledger 数据逐字节不变

### Requirement: O7 定价、审批与清理证据必须来自同一治理边界

价格 SHALL 使用 content-addressed 权威证据，绑定 region、plan mapping、base、quota、
币种、有效期、计费粒度与向上取整规则，并机械生成 fixed reserve/RoleRate。provider cap
attestation SHALL 绑定相同 workspace/project/credential 且覆盖固定费与推理费。删除前
必须远端复验 ownership/manifest；结果使用安全、脱敏、限长的 content-addressed receipt。

content digest 只证明完整性，不证明权威性。价格证据与 provider cap attestation SHALL
分别使用 `insurancekb.run-admission.pricing.v1\0` 与
`insurancekb.run-admission.provider-cap.v1\0` 的签名域，并由 trust policy 中固定的
`pricing-evidence-approver` 与 `provider-cap-attestor` 身份/角色签署。payload SHALL 绑定
evidence digest、issuer、currency/cap amount、observed/expiry 和 exact workspace/project/
credential；调用者自造或过期证据不得进入 reserve 或 READY。

删除属于独立外部 mutation，SHALL 使用
`insurancekb.run-admission.deployment-cleanup.v1\0` 的签名
`DeploymentCleanupAuthorization`，由 trust policy 中固定的
`deployment-cleanup-operator` 身份/角色签署，并绑定 exact run/purpose/scope、operation、
reserve、receipt/deployed model、workspace/project/credential、expected remote manifest、
cleanup reason、issued/expires/deadline。provisioning/adoption 签名或本地 ownership 证明
不得单独授权 DELETE。

verified adoption SHALL 通过 production 路径原子写入 cleanup 所需的 content-addressed
receipt artifact；测试不得手工 seed 来替代 adoption→artifact→cleanup 链。artifact 必须绑定
operation、ownership、verified remote receipt/manifest 与 transport identity，写入/replace/
file fsync/directory fsync 任一失败不得留下半工件；exact replay 幂等。

#### Scenario: 价格或 cap 只靠人工字符串不能准入

- **WHEN** 缺 evidence bytes/digest，成本由人工填写，或 attestation 不覆盖同一资源
- **THEN** admission 为 typed `BLOCKED`

#### Scenario: 自签或跨资源重放的价格/cap 证据不能准入

- **WHEN** evidence 只有 hash 而无受信签名，或签名 identity/role/domain/expiry/currency/
  workspace/project/credential/cap coverage 任一不匹配
- **THEN** 在 infrastructure reserve 前 typed `BLOCKED`，不得进入 READY

#### Scenario: RUNNING PTU 只走已证明的直接删除状态机

- **WHEN** 本 operation 的 verified PTU deployment 到达 cleanup 条件
- **THEN** 控制器直接 DELETE、不得调用 MU stop；删除不确定时不声称停止计费

#### Scenario: 缺少独立 cleanup 授权不得删除

- **WHEN** cleanup authorization 缺失、过期、跨 scope/resource 重放，或只提供
  provisioning/adoption 签名与 ownership receipt
- **THEN** DELETE 次数为 0，资源保持 typed `BLOCKED/cleanup_authorization_invalid`

#### Scenario: adoption 产物是 cleanup 的唯一生产来源

- **WHEN** preexisting adoption 成功并随后进入 cleanup，且测试未手工写 operation-store artifact
- **THEN** cleanup 从同一 production adoption 路径读取已验证、原子且内容寻址的 receipt；
  任一 ownership/manifest/transport drift 使 GET/DELETE 与 ledger mutation 保持 0

### Requirement: O8 READY 必须遵循唯一状态机并诚实限定零推理声明

未来创建 SHALL 按
`preauth→reserve→create/reconcile→final plan→sign→admit→probe→READY`；preexisting
采纳 SHALL 按 `receipt→adoption approval→reserve→final plan→sign→admit→probe→READY`。
probe 只允许三个角色 deployment metadata，controller-observed inference routes 必须为
0；不得据此声明共享账号全局零调用/零费用。任一阶段缺失或过期 SHALL typed BLOCKED。

production submit/resume/begin SHALL 只经 canonical 031 finalizer：每次进入产品执行前 fresh
读取 production ledger 签发的 opaque `VerifiedFinalTopology`，重验两条 reserve、完整
receipt、role topology、budget/provider-cap evidence 与所有 expiry，再进行 metadata probe。
remote observation 返回后、020 evaluator/probe 前 SHALL 再读取受信时钟与 durable topology/cap，
并与 observation exact bind；evaluator 返回后仍须复核，避免等待窗口把过期或漂移检测推迟到
provider I/O 之后。首个 canary 在 artifact/settlement 后进入 candidate evaluator/write 前也 SHALL
重新通过 canonical finalizer；candidate evaluator 返回后、candidate build/persist 前还 SHALL 从
production ledger 独立 fresh 重载同一 topology/cap authority。candidate evaluator 期间发生的
topology digest 漂移、cap 轮换/过期或 durable loader 失败不得被 evaluator 返回的旧 READY 掩盖，
且不得通过重复 evaluator 或重试循环绕过。
020 `BudgetAdmissionProof`、布尔字段、失败类型、fake/testing ledger 或
`OperationalRunResult` 均不是 capability，不得推导 `cap_verified` 或 READY。缺失、漂移、
过期时必须在 evaluator/model/provider I/O 与 durable write 前 fail closed；READY 的
`valid_until` 不得晚于任何独立证据的最早 expiry。

#### Scenario: metadata probe 不等于模型运行

- **WHEN** 两个 deployment RUNNING 且三个角色 probe 通过
- **THEN** probes=3、verified=3、controller inference requests=0；只有预算、审批、
  identity 与 ledger 同时通过时 canonical state 才可为 READY

#### Scenario: 020 入口不能绕过 canonical finalizer

- **WHEN** submit、resume 或 begin 只有 020 READY DTO/布尔值，但缺少 fresh production
  `VerifiedFinalTopology`，或 topology/cap 在等待期间漂移/过期
- **THEN** canonical state 为 typed `BLOCKED`，cost exposure 保守报告为 unbounded/unknown，
  evaluator/model/provider I/O 与 durable write 均为 0

# 031 设计：从 BLOCKED 到可审计 READY

## 1. 已验证事实与边界

PR #24 合入后，020 的软件门禁已完成，当前 admission 仍由输入、legacy
provenance、预算/审批与部署治理阻塞。2026-07-21 的百炼实测补充了以下事实：

- 无 quota 的 `ptu_v2` 请求在创建前以 `Miss ptu capacity info` 失败；
- 请求使用 `plan=ptu_v2`、`input_tpm_quota/output_tpm_quota`，provider receipt
  规范化为 `plan=ptu`、`input_tpm/output_tpm`；
- 最小 10,000 input TPM + 1,000 output TPM 的 qwen3.7-plus 与
  deepseek-v4-flash 目录价分别约 ¥6.72/h、¥4.32/h；
- RUNNING 的 PTU 后付费部署可直接 DELETE，实测经历
  `RUNNING→DELETING→404`，不得调用仅 MU 支持的 stop；
- 最终保留的唯一调用身份为
  `qwen3.7-plus-2026-05-26-031strng` 与
  `deepseek-v4-flash-031weak1`，二者均为最小 quota、`RUNNING`；
- 上述外部资源的存在不等于 020 READY，也不能倒推出审批、费用硬上限或零推理。

强模型供 annotator/judge 共用，弱模型供 weak_extractor 使用。DeepSeek 的
deployable ID 不带日期，因此不能把两个 base model 都描述成 dated；production 只接受
provider receipt 证明的唯一 deployed model，并在 base-model metadata 漂移时 BLOCKED。

## 2. 采用方案

不复用用途未知的 Qwen2.5 LoRA，也不放宽 020 接受公共 alias。采用“provider 唯一部署
身份 + 固定费用预算 + 人工签名治理”。控制面请求枚举与 provider 规范化 receipt 必须
分别验证，不得要求字符串 `ptu_v2 == ptu`，也不得接受其他映射。

当前两套资源是用户明确授权后由 operator 预先创建的外部资源。031 将其视为
`existing_external` 候选：只有采纳审批覆盖创建时间、已发生/最大未来费用、receipt 和
cleanup 风险后才能进入最终合同。该审批只决定是否继续使用资源，不把创建前费用伪装成
由 durable ledger 预授权。未来所有新建资源必须走下述 pre-provision 流程。

## 3. 输入与 legacy provenance

`product_meta.txt` 是合法 JSON 且与其他产品同 schema。使用 Git rename 迁移为
`product_meta.json`，不改变字节内容，并从 clean revision 重算全部 identity。

031 显式取代 020 D1.1c 的单一 provenance 结构，使用 discriminator 标记的联合：

- `ObservedAnnotationProvenance` 保留可证明 provider/model 与 annotation window；
- `LegacyFrozenProvenance` 逐产品绑定 product/WIP digest、有效 ancestor
  `frozen_commit`、该 commit 中实际存在的 evidence blob/digest、从 allowlisted 仓库
  证据派生的 `recorded_agent_id`、`evidence_frozen_at`，以及固定限制
  `original_annotation_time_unavailable`。

每个历史产品恰好一个 entry。`evidence_frozen_at` 是证据冻结时间，绝不是标注时间。
provenance approver 的签名表示接受该 legacy 基线及限制，不补写未知 provider model/time。

## 4. 审批信任根与文件安全

trust store 按 key 固定绑定 `approver_identity`、允许 domain、scope 与 roles；签名 payload
必须精确匹配，不能由持钥者在 CLI 中自称其他身份。keygen/sign 不得自行注册 trust。

operator CLI 分离 keygen、render、sign、verify。私钥创建使用安全父目录、dirfd/
`O_NOFOLLOW` 等价保护、原子 `O_EXCL`、限长与 open 后 `fstat`，最终 inode 为 0600，
key bytes 永不进入 stdout/stderr/log。production trust store 仍是 root-owned 固定路径。
公开 approval envelope 可进入权威 plan；只有私钥和临时待签材料 gitignore。

## 5. 预创建授权、预算与 provider cap

新增签名 `ProvisioningAuthorization`，在任何未来 provider POST 前绑定 run、workspace/
project、credential ref、region、base model、request plan、quota、官方价格证据 digest、
保守计费粒度、最大固定费用、cleanup deadline、确定性 operation ID 与 expiry。durable
ledger 在 POST 前以 stable `infrastructure_reserve_id` exact-once 占用最大费用。

两类授权使用不可互换的 canonical Ed25519 domain：
`insurancekb.run-admission.provisioning.v1\0` 与
`insurancekb.run-admission.deployment-adoption.v1\0`。provisioning key policy 只允许
`deployment-provisioner`，adoption 只允许 `budget-approver`。两者都绑定 exact run
identity、purpose、scope、operation/reserve ID、issued/expires 和 plan/evidence digest；
跨 domain/run/operation 重放失败。

provider timeout、客户端崩溃或重复 operator 不能释放该 debit。创建成功后 receipt 绑定
原 operation/reserve；final BudgetContract 引用同一 reserve，不能事后新增费用授权。
每个 unique deployed model 恰好一个 reserve，role 只保存 reserve reference，因此共享
strong deployment 不重复计费，重复或冲突 ID fail closed。

当前已存在的两套部署必须走单独 `ExistingDeploymentAdoptionAuthorization`：显式记录
它们是 preexisting、从 provider `gmt_create` 起按最坏计费粒度计算成本、尚未由 031
ledger 预授权这一限制，并由 budget approver 决定采纳或删除。采纳时先 durable 占用从
创建至批准窗口末端的保守费用，再生成 final plan；payload 还必须绑定 exact
deployed model、receipt digest、workspace/project/credential ref、quota、gmt_create、
pricing/cap evidence、incurred+future max cost 与 cleanup deadline。不得把该路径开放为
普通创建捷径。

价格证据必须是 content-addressed 的官方/控制台报价，绑定 region、request/response
plan mapping、base model、quota、币种、有效期和向上取整规则。RoleRate 由 evidence
机械计算，覆盖 tiers/thinking/cache/overflow；未知项取最坏或 BLOCKED。provider
spend-cap attestation 必须绑定同一 workspace/project/credential，并明确覆盖 PTU 固定费
与推理费。没有 provider 硬上限时，本地 TTL/delete watchdog 不能声称费用有硬上限，
canonical READY 保持 BLOCKED；报告仍展示当前持续费用暴露。

hash 只作为内容寻址，不能把 operator 自写 JSON 变成权威证据。价格证据和 provider cap
attestation 还必须分别由 trust policy 中的 `pricing-evidence-approver` 与
`provider-cap-attestor` 签名，使用独立 domain-separated canonical payload；验证 exact
issuer、currency/cap amount、observed/expiry 与 workspace/project/credential 绑定后，
才允许计算 reserve。自签、过期或跨资源重放在 durable mutation 前失败。

基础设施 reserve 不另建第二套预算数据库。现有 `BudgetLedger` schema 迁移并新增
infrastructure tables，使 account ceiling、fixed reserve、request/token reserve 与最终
budget approval 由同一个 SQLite 文件管理。部署前事务验证 provisioning authorization、
price/cap 并占用 stable reserve；部署 receipt 产生后，第二个事务验证最终 budget approval
并只绑定 deployed model/roles，不增加或追认费用。authorization digest 与 stable reserve
ID 是幂等键；恢复时从同一 ledger 判断是否已占用，避免双账不一致。

ownership 证明只回答“是不是本 operation 的资源”，不回答“现在是否获准删除”。cleanup
使用第三个独立签名域 `insurancekb.run-admission.deployment-cleanup.v1\0`，绑定 exact
receipt/deployed model/remote manifest 和 deadline；缺失、过期或跨资源重放时 DELETE
调用数必须为 0。生产 provider HTTP client 固定 `trust_env=False`，禁止代理环境变量改变
控制面路由。

## 6. Crash-safe 部署控制器

未来创建使用代码固定组合：strong base=`qwen3.7-plus-2026-05-26`，weak
base=`deepseek-v4-flash`，request plan=`ptu_v2`，每套 10,000/1,000 quota，北京
endpoint、后付费、确定性唯一 suffix。控制器在 provider mutation 前：

1. 验证 ProvisioningAuthorization、provider cap、价格和 durable reserve；
2. 取得 run 级独占锁，写 durable pre-send operation journal 并 fsync；
3. 按 operation marker/suffix list/reconcile，只有确无匹配项才 POST；
4. 对 timeout/409/响应丢失先 reconcile，禁止盲重试；
5. receipt 原子记录 allowlisted metadata 与 evidence digest；删除前重新查询并验证
   remote ownership/manifest，只能删除本 operation 创建的 deployment。

部分创建、并发 operator、伪造 receipt 或 cleanup 不确定均 typed BLOCKED。receipt 与
cleanup 工件采用与 admission artifact 相同的限长、脱敏、safe-path、content-addressed
写入。实测表明 PTU RUNNING 可直接 DELETE；状态机只允许该已证明路径，并在 provider
行为变化时停止自动操作。

## 7. 唯一状态机与验证

未来新建资源的唯一顺序是：

`pre-provision render/sign → durable infrastructure reserve → create/reconcile receipt →`
`final plan/contract → provenance+budget sign → ledger admit → metadata probe → READY`

当前 preexisting 资源使用：

`receipt verify → adoption render/sign → durable historical+future reserve → final plan/contract`
`→ provenance+budget sign → ledger admit → metadata probe → READY`

metadata probe 只访问 allowlisted deployment detail；“零推理”只声明本控制器受控且隔离
credential/project 的 outbound inference route 为 0，不能从本地计数推导账号全局费用。
最终需通过 Ruff、mypy strict、pytest not-live、OpenSpec strict；测试名引用 O1～O8，
覆盖创建前后各崩溃点、并发、timeout、409、伪造 receipt、共享 reserve 与审批重放。

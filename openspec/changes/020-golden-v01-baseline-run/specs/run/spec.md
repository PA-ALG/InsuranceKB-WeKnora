# 020 Golden 与 Baseline 真实运行规格

## ADDED Requirements

### Requirement: D1 真实调用前必须通过可执行、可追溯且不可绕过的运行准入

系统 SHALL 以单一类型化 admission plan 作为真实运行的准入源：

- **D1.1a 三模型角色**：plan SHALL 同时固定 annotator、weak extractor、judge 三角色的精确 provider/model ID、签名 `expected_model_revision` 或 immutable deployment ID、protocol、base URL、provider policy 与凭据环境变量名；该 provider-neutral union 只描述类型能力，不得覆盖 D1.2b 对 production Bailian 的更强限制。在取得 immutable identity 前只允许显式 typed `pending_immutable_identity`（revision/deployment 必为空）形成合法 `BLOCKED`，该变体不得进入 probe、费率身份或真实调用；policy SHALL 从 metadata 解析并精确比较 provider-specific revision/deployment，模糊 alias、伪造占位值、无稳定 revision/deployment、过期 observation 或缺任一角色均 `BLOCKED`；judge SHALL 是确切执行模型，`claude-session`/纯人工标签不得替代模型身份；
- **D1.1b 依赖与输入身份**：plan SHALL 绑定完整 identity request 的 domain-separated canonical SHA-256；该 request 包含 019/021 merge revision、schema/prompt/template/执行前 WIP Golden/execution-surface 指纹，以及恰好 13 个唯一产品的 line key、每份 PDF、`product_meta.json`、`fields.json` 和其他实际消费输入 digest，替换 request 与对应 digest 不得复用原 plan 审批。production identity policy SHALL 由代码固定唯一 designated merge mapping：019=`4d9c84e25bd53f3564631b8f8dc0b1f85e21e55f`、021=`cfefcc9b3a7d6af0503f3b76cf8ac5a1b6d44b35`；plan pin 必须先逐 key/value 精确等于该 mapping，随后才允许执行 ancestor 检查，故作为祖先的 feature head、cherry-picked equivalent 或 caller 自选 revision 均 `BLOCKED`。仅 private `_for_testing` policy 可为临时仓库指定另一组 exact revision，production constructor 不接受该配置。pre-run input snapshot 与 run-output snapshot SHALL 彻底分离；canary 的 cache/manifest/Golden candidate/review candidate 只能写入代码固定、受保护、content-addressed 的 run/checkpoint root，该 root 不属于本次 consumed-input 或 execution-surface digest，写出运行产物不得改变执行前 plan hash；只有它们在下一 admission revision 被提升为 immutable Golden release/输入时才进入新 identity 并重新审批。必需文件尚缺时只允许显式 `pending_required_input` 且对应 digest 必为空，由 evaluator 形成 `BLOCKED`，不得伪造摘要；revision 非当前祖先、绝对路径、缺失/额外/重复产品、dirty/untracked consumed file 或任一 digest 漂移均 `BLOCKED`。evaluated revision 记录在 result 而不嵌入 tracked plan，避免自引用；
- **D1.1c 历史 provenance（031 修订）**：现有 11 产品 SHALL 逐产品且恰好登记一个带 discriminator 的 provenance entry。`ObservedAnnotationProvenance` SHALL 登记可证明的 annotator provider/model、标注时间范围与 evidence basis；`LegacyFrozenProvenance` 只可绑定逐产品 product/WIP digest、当前 evaluated revision 的有效 ancestor frozen commit、该 commit 中实际存在的 evidence blob/digest、从代码 allowlist 仓库证据派生的 recorded agent ID、evidence-freeze time 与固定 `original_annotation_time_unavailable` limitation。freeze time 不得解释为 annotation time；legacy entry 只有在 provenance approval 签名覆盖整个 entry 时才可作为 gs-v0.1 基线 evidence。不得以全局 default、调用者自报、推测模型或伪造时间补齐；缺失、重复、未签或证据漂移均 `BLOCKED`；
- **D1.1d 受信审批**：plan payload SHALL 固定非空且受限长度/语法的唯一 `run_identity` 与非空 purpose，一个 admission 只授权该 run；canonical `plan_payload_hash` SHALL 排除 approval envelope、observation 与派生状态。provenance/budget/canary-review detached Ed25519 envelope SHALL 由部署侧受信公钥验证；信任根/授权角色只能从代码固定、root-owned、非 symlink、group/world 不可写的部署文件加载，run CLI 不得接受自选 trust store。provenance/budget envelope 仍属于执行前 plan document；运行后产生的 canary-review envelope SHALL 仅从代码固定的 repo 外 deployment-owned approval inbox 加载，inbox 及文件必须逐级拒绝 symlink、owner 非 root 或 group/world 可写，且严格限长/唯一 key；CLI 不得自选 inbox。加载该外部 envelope 不得改变 Git evaluated revision、plan hash 或 execution-plan hash，tracked plan/observation/result/candidate 中的 canary-review 不得进入授权路径。签名字节固定为版本化 domain label `insurancekb.run-admission.<budget|provenance|canary-review>.v1\0` + 禁 float/unknown field、key 排序、array 保序、compact、UTF-8 不转义的 canonical JSON；payload SHALL 绑定 plan hash、run identity、purpose、scope、授权 approver role、issued/expires 与相应 provenance/预算/canary 证据；未知 key、错误角色、过期、domain/scope/run/hash/signature 不匹配均 `BLOCKED`；
- **D1.2a 零推理 probe**：默认静态检查零网络且不能 `READY`；remote probe SHALL 强制 HTTPS、TLS certificate verification、`trust_env=False`、无 ambient HTTP(S)/SOCKS proxy，并仅选择代码内 allowlist 固定的 `(protocol, origin, GET|HEAD, normalized path)`，使用空 body、无 query/userinfo/fragment、禁自动 redirect；URL percent-decode 后不精确匹配、3xx、跨 origin/path 变化或 chat/completions/responses/embeddings/rerank/OCR 等推理路由均在后续请求前 `BLOCKED`。HTTP loopback 只允许无生产凭据且路径精确为代码所有 `/metadata/{deployed_model}` 的 test-only policy；
- **D1.2b 凭据脱敏与时效**：probe 只解析 provider policy allowlist 与 plan 同时声明的环境变量且 SHALL NOT 输出 key/response body；时钟、整体 monotonic deadline 与最大 observation age SHALL 为代码所有。请求及其嵌套 `ModelRolePlan` SHALL 在任何 static/remote 分支、凭据读取或网络 client 创建前从 plain field data 完整重验，`model_construct` 形成的 dual identity、非法字段类型、非法 mode/timestamp 均 typed `BLOCKED` 且零请求。请求 SHALL 强制 identity encoding，压缩响应须在 body iteration 前拒绝，identity body 须流式限长，malformed/duplicate-key/递归耗尽 metadata 均 typed `BLOCKED`。Bailian 生产身份只接受 provider 保证可直接调用且不可变的 `immutable_deployment_id`，并 SHALL 要求它逐字等于 runtime `POST /chat/completions` 实际发送的 `model_id`；仅签 `expected_model_revision` 的 plan、immutable ID 缺失/不等于 `model_id`，或 provider 无法提供这种保证时均保持 typed `BLOCKED`，不得创建 metadata/inference client。官方 dedicated deployment detail `GET /api/v1/deployments/{deployed_model}` 的精确 `deployed_model/base_model/gmt_modified/status` 仍用于状态、语法与审计，其中 `gmt_modified` 只作非授权 metadata，不能授权一个可变 alias。四字段须通过 provider-specific 安全语法；失败结果不得保留 response-derived identity，成功审计只可写精确匹配后的签名 plan 值。公开 alias 无稳定 metadata、凭据缺失、URL 内 secret、鉴权失败、超时、端点不可达、返回 deployment 与签名 immutable identity 不符、配置不安全或 probe/价格 observation 过期均 `BLOCKED`、零模型调用；
- **D1.3a 预算合同**：budget SHALL 记录币种/价格快照、三角色费率、provider project/key spend-cap attestation、总 input/output token 与费用硬上限、分阶段及逐产品 worst-case reserve。可预先枚举的调用 SHALL 签名精确 request reserve；retry/gap-fill/judge 等只能在运行时确定 prompt 的调用 SHALL 按产品/角色签名 dynamic request pool，绑定不可变的 model-role identity、RoleRate canonical digest、`max_attempts` 与逐次 input/output/cost 上限；精确 reserve 与 pool 的合并最坏情况必须同时受产品、总额及 provider cap 限制。合同由 D1.1d budget envelope 以 canonical full-contract SHA-256 与重复 ceiling 共同批准；revision 1 的 previous digest 必须为空，后续 revision 必须显式携带单调序号与 previous approval-envelope digest；数值非法、contract hash/chain 不匹配、provider cap 大于批准 cap 或批准不匹配均 `BLOCKED`；
- **D1.3b durable reserve**：系统 SHALL 以 domain-separated `run_identity+purpose` digest 建立稳定 run-level budget account，所有进程、恢复和同 run admission revision 共享该账户；换 run identity 会改变 plan hash 并须新账户/签名。ledger SHALL 以 `(budget account identity, stage, product)` 为产品唯一键并在事务锁内原子扣减；状态只允许 `reserved→settled|released`，恢复复用相同 reservation。每个逻辑请求 SHALL 以签名角色、完整 model-role plan 与精确 system/user prompt 的 domain-separated SHA-256 形成唯一 `request_unit`，再以 `(account, stage, product, request_unit,attempt_no)` 与 owner token 在同一锁内 insert/CAS。该 unit 须精确命中 signed request reserve，或在同角色 signed pool 的逐次上限和总 attempt 数内 claim；未走到的动态分支不需创建 attempt，但每个已创建 attempt 必须可对账为 terminal 或 uncertain。只有 claim winner 可执行网络 I/O，loser/observer 不得发送；lease 过期不得自动转移发送权，release 与 attempt claim 同锁。请求 SHALL 在网络前带 max-token/cost bound 落库；durable ledger schema 升级必须单事务、逐行验证且保留旧 exact attempt 的所有原有列，迁移失败必须 fail closed 且不破坏旧表。恢复时任何无 durable terminal response 的 attempt（含 pre-send/send 模糊崩溃边界及 legacy/tampered `no_usage` row）均标 `uncertain`、清除未受信 proof 字段、按 full reserve 结算且不得自动重放；若该 legacy row 所属 reservation 已为 `settled`，恢复须在同一事务按 conservative attempt charges 重算其 actual，若已为 `released` 则不得静默复活 reservation，而须锁存 account overage 并阻止后续 reserve、attempt claim 与 capability claim。当前 020 capability SHALL NOT 暴露 provider-no-usage/reconciliation mutation；产品 release 只允许从未创建任何 attempt 的 reservation，`no_usage` row 在 recovery 前不得 release 或 settle。provider reconciliation 的 trust root、key-to-role identity、持久化认证 provenance 与部署 loader 必须由未来单独 OpenSpec 设计复审，不能由本 change 或测试 seam 推断；实际 overage 阻止后续产品并受 provider spend cap 兜底；
- **D1.3c 停止/恢复/扩容**：余额不足 SHALL 在产品边界安全停止并保留 ledger/checkpoint；同 run 扩大预算必须形成绑定上一 approval digest 与新 plan payload hash 的单调 revision 签名，并在同一事务只提高原 run account ceiling，完整继承 settled/reserved/uncertain debit 与 attempts，新 ceiling 不得低于既有占用；revision 2 及以后除顶层 account ceiling 外，currency、pricing/attestation、role rate/model identity、product、exact request、dynamic pool 的集合、顺序与全部值 SHALL 与 revision 1 canonical contract 精确相等，不得添加、删除或修改任何 limit；换模型/费率或换 run 必须新账户/批准。runtime capability/version 未通过两进程竞争、各崩溃点和部分消费后扩容验收时 admission 不得 `READY`；
- **D1.4 审计工件**：checker SHALL 同源生成脱敏 canonical JSON 与 `run-admission.md`，逐项列出 blocker、checker/capability version 与 expiry；所有耗时检查完成后 SHALL 读取新的 decision time，并按该时刻重新派生全部 expiry，预算 expiry 取 envelope/价格/provider-attestation 的最早值；YAML 重复键、plan/result/report 路径别名均须在写入/删除前 exit 1，不能 last-key-wins 或误删输入；JSON 作为最后原子替换并 fsync 的 commit marker，Markdown 必须绑定其 canonical SHA-256 且声明脱离匹配 JSON 无效；仅全部通过返回 `READY`/exit 0，完整但不满足返回 `BLOCKED`/exit 2，输入或 checker 错误 exit 1；
- **D1.5 调用时重验与 canary 扩权**：T2/T4 SHALL 在每个产品调用前重跑同一 evaluator，不信任可编辑 result 的 state/blockers；重验 payload hash、签名/授权/expiry、probe/价格 expiry、依赖 exact designated merge pin+祖先、execution-surface/shared/本产品输入 digest 并重新派生 `READY` 与 execution authorization，再执行 D1.3 reserve；`begin_product` SHALL 在最后一跳检查 `(stage, product)` 仍在 fresh authorization 内并重验当前时间/账户 revision/证据 digest，不得存在 `--force` 绕过。production Bailian invoker SHALL 在其受信入口与实际 HTTP mutation 点各自从 plain fields 重验完整 `ModelRolePlan`，并在创建 `AsyncClient`/发送 inference 前再次要求 provider/protocol/base URL/provider policy/credential env 精确等于代码固定 Bailian policy，且 `immutable_deployment_id == model_id`；revision-only、policy mismatch、identity mismatch、dual identity 与 `model_construct` 绕过均 typed 暂停且零 inference call。无 canary-review envelope 时只允许代码固定的首个缺失产品 annotation canary，baseline 与其他产品为空集。canary-review payload SHALL 显式签名 `review_decision=approved|rejected`、唯一有序 `granted_targets[(stage,product)]`、执行前 plan hash/evaluated revision、runtime capability version、run/purpose、canary product/stage、budget account/revision/approval digest、settlement snapshot digest、checkpoint/manifest、Golden/quote/disputed 质量工件及阈值版本、provider 返回的实际 input/output token 与按签名 RoleRate 计算的费用；evaluator 只能返回该签名集合的子集，未签 target 绝不得由代码隐式扩大。首个 canary 复核最小权限只授予第二缺失产品 annotation；13 产品 baseline 须等 D2 immutable Golden release 进入新 admission 输入后另行明确授权，不得由本 canary review 隐式放行。settlement snapshot canonical preimage SHALL 按 request-unit/attempt 排序并覆盖 account/stage/product、budget revision/approval、reservation maximum/state、每个 role/limit-kind/status/maximum/actual/usage-verification/response digest 及 legacy `no_usage` metadata（recovery 后必须为空），且 canary 全部 attempt 必须 terminal 且 provider usage verified；prepared/sent/uncertain/no_usage 任一存在都不可扩权。envelope canonical digest SHALL 作为 capability identity；ledger 必须在同一事务内重验 snapshot 并原子 claim `(account,envelope,target)`+预留目标产品，同 target 恢复幂等，超出 grant/不同 target 重放拒绝。重复/过期/语义非法的 review、工件或 ledger 漂移、budget revision 改变、provider usage 缺失/非法均使全局 authorization 为空并 `BLOCKED`，不得降级为无复核 canary。`CanaryReviewCandidate` 只是从同一锁内 settled ledger 与 content-addressed artifacts 派生的 canonical 待签 payload 展示，不属于 approval union，evaluator 绝不读 candidate/result/observation 以扩权；写 candidate 不改变 authorization。语法/schema 非法输入 exit 1；已成功解析但语义非法的 review 为 `BLOCKED`/exit 2。生产入口 SHALL 以同 run 独占 session lock 覆盖 `recovery→begin→model/artifact→settle`，防止后启进程将正在发送的 attempt 误标 uncertain；

#### Scenario: 当前未合入依赖只生成 BLOCKED 工件

- **GIVEN** 019 已合入但 021 尚未合入当前 revision
- **WHEN** 操作者执行静态 admission check
- **THEN** checker 以 exit 2 生成列明 021 与未 probe 等 blocker 的 canonical JSON 和 `run-admission.md`
- **AND** 不访问网络、不调用任何模型、不输出任何凭据

#### Scenario: 三角色任一模糊或缺失即拒绝

- **WHEN** annotator、weak extractor、judge 任一角色缺失，或 model ID 使用 `latest`/`best`/占位值
- **THEN** admission 为 `BLOCKED`，不得由另外两个角色或本机 WeKnora 配置推断补齐

#### Scenario: judge 标签或可漂移模型身份不得视为精确角色

- **WHEN** judge 只写 `claude-session`/`manual`，或 provider policy 无法证明 model ID/revision 且 observation 已过期
- **THEN** judge 角色保持 `BLOCKED`，人工最终审核不能冒充模型裁决身份

#### Scenario: Bailian revision-only 或不可调用 identity 不得授权

- **GIVEN** signed plan 只有 `expected_model_revision`，或 immutable deployment ID 与实际发送的 `model_id` 不同
- **WHEN** metadata probe 的 `gmt_modified` 相同或漂移，或 provider 无法保证该 immutable ID 可直接调用且不可变
- **THEN** admission 为 `BLOCKED` 且零 metadata/inference client call；不得以新鲜 revision observation 或同名 model ID 覆盖该缺口

#### Scenario: 依赖祖先或等价代码不得代替 designated merge

- **GIVEN** 019/021 feature head 或 cherry-picked equivalent 已是 evaluated revision 的祖先
- **WHEN** plan pin 不是代码固定的对应 designated merge SHA
- **THEN** checker 在 ancestor 检查前以 `dependency_revision_mismatch` 拒绝；只有 exact designated merge pin 且其为祖先才通过

#### Scenario: 历史 WIP 不得由全局默认 provenance 洗白

- **GIVEN** 11 个现有产品的行内 `annotator_model`/`created_at` 缺失
- **WHEN** plan 只提供一个全局 default annotator 或推测时间
- **THEN** 11 个产品逐项保持 provenance blocker，WIP 文件不被修改

#### Scenario: 伪造或篡改批准不能产生 READY

- **WHEN** approval reference 不带签名、签名 key 未受信、approver role 无权批准该 scope、envelope 过期，或 plan/state/blocker 被编辑
- **THEN** runtime 重跑 evaluator 后仍为 `BLOCKED`；修改 result 的 `state=READY` 不改变判定

#### Scenario: 签名编码与 domain 阻止拼接及跨 scope 重放

- **WHEN** 攻击者改变字段类型/顺序/拼接边界，或把有效 provenance envelope 当作 budget envelope、把另一 run 的 envelope 用于当前 run
- **THEN** versioned domain-separated canonical signed bytes 校验失败，admission 保持 `BLOCKED`

#### Scenario: probe 永不触发推理

- **WHEN** probe 配置指向 chat/completions、responses、embeddings、rerank、OCR 或其他推理路由
- **THEN** checker 在请求前拒绝并返回 `BLOCKED`
- **AND** 日志、异常、JSON、Markdown 均不包含 API key 或 provider response body

#### Scenario: 编码路径、POST 与 redirect 绕过均在第二请求前拒绝

- **WHEN** probe 使用 POST、query/userinfo/fragment、编码后的推理路径、尾随子路径，或 allowlisted URL 返回 3xx
- **THEN** checker 不跟随 redirect、不发送 body、不访问变化后的 origin/path，并返回 `BLOCKED`

#### Scenario: ambient proxy 与非 TLS 远端不得改变探测路径

- **GIVEN** 进程环境含 HTTP(S)/SOCKS proxy 或 CA 相关变量
- **WHEN** 执行 remote provider probe
- **THEN** client 以 `trust_env=False` 忽略 ambient proxy，强制 HTTPS 与 TLS verify；非 HTTPS 远端在请求前 `BLOCKED`

#### Scenario: 预算不足在下一个产品之前停止

- **GIVEN** 当前 ledger 剩余额度小于下一个产品的 worst-case token 或费用 reserve
- **WHEN** runtime 尝试开始该产品
- **THEN** runtime 不发起该产品任何模型请求，持久化 ledger/checkpoint 并要求新 admission revision

#### Scenario: 两进程竞争只产生一份产品 reserve

- **GIVEN** 两个进程以相同 admission/run/stage/product 并发申请 reserve
- **WHEN** 两者通过 durable ledger 事务竞争
- **THEN** 总余额只扣减一次，只有 attempt owner-CAS winner 发出恰好一个 outbound request，loser 仅观察/复用结果，且状态等价某一串行顺序

#### Scenario: release 与 attempt claim 竞争不得释放已可能发送的额度

- **WHEN** 一个进程申请 release、另一进程并发 claim request attempt
- **THEN** 两者经同一 ledger 锁串行；若 attempt 已创建或可能已发送则 release 失败，且 lease 过期不授予第二发送者

#### Scenario: 换 run identity 不得重放同一预算批准

- **GIVEN** budget envelope 已批准 run A 的 plan payload hash
- **WHEN** 操作者用相同 envelope 启动 run B 或为 run B 新建 reservation
- **THEN** run/hash/signature 校验失败；run B 不能访问 run A 的预算账户，须取得新批准

#### Scenario: 部分消费后扩容不得重置预算账户

- **GIVEN** run A 已有 settled、reserved 与 uncertain debit，原 ceiling 不足以开始下一产品
- **WHEN** 授权主体签发绑定上一 approval digest 的更高 ceiling revision
- **THEN** 系统在同一 run-level account 原子提高 ceiling，完整保留全部既有 debit/attempt；不得创建满额空账户或降低 ceiling

#### Scenario: 任一无 terminal response 的崩溃边界不得自动重放或 release

- **GIVEN** request attempt 已持久化，但进程可能在 send 前、send 中或响应落盘前崩溃
- **WHEN** 相同 run 恢复
- **THEN** 因本地无法证明 provider 未接收，attempt 标为 `uncertain` 并按全 reserve 结算，不自动重发或 release；当前 020 不实现 provider reconciliation，只有从未创建任何 attempt 的 reservation 可 release

#### Scenario: READY 结果发生漂移后不可复用

- **GIVEN** 先前 admission 结果为 `READY`
- **WHEN** Git revision、模型、schema、prompt、template、Golden、产品输入或预算任一身份改变
- **THEN** 调用前重验判旧结果 stale 并阻止模型调用，且无 `--force` 旁路

#### Scenario: 未复核 canary 不得扩展到第二产品或 baseline

- **GIVEN** admission 完整 `READY` 但不存在有效 canary-review envelope
- **WHEN** 入口尝试启动第二缺失产品或任一 baseline 产品
- **THEN** fresh execution authorization 不包含该 `(stage, product)`，`begin_product` 在 reserve 和模型调用前 `BLOCKED`

#### Scenario: canary review 不得授予未签名目标

- **GIVEN** 有效 review 只在 `granted_targets` 签名第二缺失产品 annotation
- **WHEN** 代码、CLI 或第二进程尝试以该 capability 启动 baseline 或其他产品
- **THEN** evaluator 不得隐式扩大签名集，ledger 在原子 claim/reserve 前拒绝，零新预留且零模型调用

#### Scenario: canary 输出与待签 candidate 不得改变执行前身份或自行授权

- **WHEN** canary 写入固定 run-output root 并生成未签 `CanaryReviewCandidate`
- **THEN** 执行前 plan hash 不变，evaluator 不读 candidate 扩权，即使 candidate/result/observation 被改为 `approved:true` 也不改变 authorization
- **AND** 修改 content-addressed 输出字节使后续 envelope 验证失败；将输出提升为新 Golden release 输入必须形成新 admission revision/审批

#### Scenario: 生产入口不得以占位字节冒充真实运行工件

- **GIVEN** 单产品 annotation 或 baseline 已获 fresh execution authorization
- **WHEN** 入口生成 checkpoint/manifest/Golden/quote/disputed 或 baseline run artifact
- **THEN** annotation executor SHALL 通过版本化 `execution_artifacts_020` renderer，由本次实际 `GoldenRecord`、逐文件原始 cache 字节及对身份中每份 PDF 的逐条 quote 回验确定性生成同一个 typed bundle，并将该 bundle 原样交给 committer；checkpoint/manifest/Golden/quote/disputed 各自 SHALL 携带固定 schema version，manifest 同时绑定 admission 产品名、`product_meta.planCode`、line/schema/model、execution plan hash 及 PDF/meta/fields/其他 consumed-input digest；不得以非空占位字节、空 JSON、重建后的 cache 字节或仅由 `disputed=false` 反推 quote 通过
- **AND** baseline `DirectoryDocumentSource.parser_fingerprint` SHALL 为 `SHA-256("insurancekb.directory-parser-fingerprint.v1\\0" + canonical_json)`；canonical JSON SHALL 固定 policy version、已重验的解析算法相对路径与 digest、已重验的 `uv.lock` 相对路径与 digest，以及本轮唯一直接 parser dependency `pdfplumber` 的精确 locked/installed version；不得在本轮宣称绑定未实际验证的传递依赖闭包，运行文件或 installed version 与已签 execution-surface identity 不符则在 source/pipeline/model I/O 前 fail closed
- **AND** 任一记录/身份 PDF/cache 缺失或额外、双身份/line/schema/model/doc 漂移、逐 PDF quote coverage 不完整，或 baseline 的 pred/judge-queue/manifest/checkpoint 路径、manifest 声明或 symlink 逃离固定 run root 时，不得 commit、settle 或生成 candidate；empty/cache/quote/identity/parser/path blocker SHALL 使用可区分的稳定 code
- **AND** baseline pred/judge-queue/dead-letter/manifest 的精确内容 SHALL 在 replace 前逐文件 fsync，manifest 作为最后 commit marker 安装后 SHALL fsync 固定 run directory 并按期望字节 read-back；任一步失败须清理 commit marker 并在 settle 前中止

#### Scenario: canary 实际用量不可用最坏 reserve 冒充

- **GIVEN** canary 模型响应缺失、超界或伪造 provider usage
- **WHEN** 系统可以按 full reserve 安全结算预算，但无法证明实际 token/费用
- **THEN** canary continuation 保持 `BLOCKED` 并报 `canary_actual_usage_unverified`，不得签发或接受扩权 capability

#### Scenario: 竞争入口不得把活跃请求当崩溃恢复

- **GIVEN** 进程 A 已持有同 run session lock 并处于 provider send/artifact 窗口
- **WHEN** 进程 B 尝试启动同 run 入口
- **THEN** B 在 recovery 前 fail closed，不得将 A 的 prepared/sent attempt 改为 uncertain，不得执行模型 I/O

### Requirement: D2 gs-v0.1 只补齐两个缺失产品并以 019 工具发布

020 SHALL 按以下原子条款完成 `gs-v0.1`：

- **D2.1** SHALL 不改现有 11 产品，只完成平安爱满分（2026）两全保险和平安附加（2026）意外伤害保险；新增每条记录 SHALL 含真实 annotator model/time；
- **D2.2** present/absent SHALL 有逐字可回验 Evidence，每产品 disputed rate SHALL ≤ 0.05；
- **D2.3** SHALL 使用 019 validator 发布 13/13 immutable `gs-v0.1`，所有 extractable 字段有三态且 self-eval 全 1.0；
- **D2.4** 发布成功后 SHALL 更新并勾选 002 T8/T9，且保留 WIP 原始输出。

#### Scenario: 单产品 canary 通过后才继续第二产品

- **GIVEN** D1 admission 为 `READY`
- **WHEN** 运行第一个缺失产品 canary
- **THEN** 系统在产品边界停止并报告 quote 回验、disputed rate、实际 token/费用和 checkpoint
- **AND** 仅当该复核通过才允许第二产品开始

#### Scenario: 发布前任一产品不完整则拒绝 release

- **WHEN** 13 产品任一缺 Golden、extractable 字段缺三态、Evidence 回验失败或 disputed rate 超标
- **THEN** validator 拒绝创建 immutable `gs-v0.1`，002 T8/T9 不得勾选

### Requirement: D3 十三产品基线必须可恢复且裁决后重新出分

13 产品基线 SHALL 满足：

- **D3.1** 13 产品均有完整 run manifest、pred、dead-letter、judge artifacts 和 eval；
- **D3.2** judge queue 全部 resolved 或逐条登记 pending 原因；dead letter 重跑后仍失败 SHALL 保留最终原因；
- **D3.3** judge 回写后 SHALL 重新出分，不得以回写前分数作为批准基线。

#### Scenario: 中断后从已验证 checkpoint 恢复

- **GIVEN** 某产品在模型调用或 artifact 写入之间中断
- **WHEN** 以相同 admission/run identity 恢复
- **THEN** 有 durable terminal response 的单元继续落 artifact；所有无 terminal response 的已创建 attempt 均转为 uncertain、保持暂停待裁决并按 full reserve 计费，当前 020 不接受 provider no-usage 证明或自动重试
- **AND** 已完成单元不重复收费，manifest、checkpoint 与 ledger 对账一致

#### Scenario: 未决 judge 或 dead letter 不得静默批准

- **WHEN** judge queue 尚有未登记 pending 项，或 dead letter 最终失败原因缺失
- **THEN** baseline artifact 明确不可批准，并在 unresolved 清单中逐项报告

### Requirement: D4 长字段要点与 before/after 回归必须进入批准证据

Keypoints 与回归 SHALL 满足：

- **D4.1** 全部 present 且归一化值长度 ≥30 字的字段有 keypoints 或明确 pending 工单；
- **D4.2** 完成 005 路由修复与 006 template fast path 的 before/after 对比；
- **D4.3** 使用 019 生成 baseline artifact、approval 与 QualityProfile；未满足自动资格的字段不得人工修改指标绕过。

#### Scenario: 长字段缺 keypoints 阻止批准

- **WHEN** 任一符合条件的长字段既无 keypoints 也无明确 pending 工单
- **THEN** baseline artifact 保持不可批准并列出对应产品/字段

#### Scenario: 回归或 unresolved 失败不得人工改分

- **WHEN** before/after 指标退化或 019 approval blocker 非空
- **THEN** 系统拒绝批准，操作者只能修复产物或记录正式 pending，不能直接修改指标

### Requirement: D5 收尾报告必须完整、脱敏并与项目账本对账

收尾 SHALL 满足：

- **D5.1** `validation-report.md` 记录实际 token/费用、运行时间、模型指纹、13 产品指标和 unresolved 清单；
- **D5.2** 更新并对账 HANDOFF B1/B2/B3/B4/B6/B7、002 tasks、05/13/16/20；
- **D5.3** 数据 release 不含绝对路径、凭据或未脱敏客户数据。

#### Scenario: 完整运行收尾

- **WHEN** D2～D4 全部完成
- **THEN** validation report 与各账本引用同一 artifact/approval identity，并列出实际成本、运行时间和所有 unresolved 项

#### Scenario: 敏感或不可移植内容阻止交付

- **WHEN** release/report 含绝对路径、凭据模式或未脱敏客户数据
- **THEN** 收尾门禁失败，相关工件不得进入 immutable release 或提交

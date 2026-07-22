# 031 实施任务：真实运行准入解阻

> 执行边界：遵循 SDD → TDD；每项测试名引用 O1～O8。AI session 不执行
> `git commit`/`git push`，不调用推理端点，不在缺少签名授权时创建、采纳或删除部署。

## T1 — O1 输入规范化与 clean identity

- [x] T1.1 先写失败测试，证明唯一 `product_meta.txt` 会造成 typed identity blocker。
- [x] T1.2 将该文件 byte-preserving rename 为 `product_meta.json`，验证 canonical JSON
  语义和原始 bytes 均不变。
- [x] T1.3 从 clean revision 重算产品、共享输入与 execution-surface identity；不得忽略旧路径。
  AI worktree 未 commit 时只能验证重算算法与生成 pending evidence；权威 production digest
  必须在人工 commit 后以该 clean SHA 重新生成，旧 SHA 证据不得复用。

## T2 — O2 legacy provenance 联合与证据验证

- [x] T2.1 用 discriminator 替换单一 `HistoricalProvenance`，兼容 observed 事实并新增
  `LegacyFrozenProvenance` 的强类型限制。
- [x] T2.2 新增只读 Git evidence inspector：逐产品验证 ancestor commit、blob、digest、
  WIP/product digest、allowlisted recorded agent 与 freeze time。
- [ ] T2.3 生成恰好 11 条 provenance 候选；缺失、重复、自报或证据漂移均 typed BLOCKED。
- [x] T2.4 更新 provenance approval payload/identity contract 绑定完整联合内容；未签名仍
  `BLOCKED/approval_missing`。

## T3 — O3 离线密钥仪式与信任策略

- [x] T3.1 扩展 trust-store key policy，固定 identity、domain、scope、role，并保持 production
  trust path 不可由 run CLI 覆盖。
- [x] T3.2 实现 keygen/render/sign/verify 分离命令；私钥安全目录、nofollow、O_EXCL、
  fstat、限长与 0600，任何输出不含 key bytes。
- [x] T3.3 覆盖自注册、identity/role/domain/scope 冒充、symlink、宽权限、超限文件和
  TOCTOU 失败场景。

## T4 — O4/O6 授权模型与 durable infrastructure reserve

> Core implemented and deterministically verified. Production reserve/adoption/bind permits are
> intentionally fail-closed until T5 provider reconciliation and T6 trusted pricing/cap verifiers
> are installed; test capabilities can reach only explicit private transaction helpers.

- [x] T4.1 新增独立 canonical domain 的 `ProvisioningAuthorization` 与
  `ExistingDeploymentAdoptionAuthorization`，绑定 exact run/operation/reserve/receipt/
  deployment；adoption 还绑定 purpose、preexisting/not-preauthorized limitation、
  gmt_create、incurred/future max cost、base/region/plan mapping，并不得授权 create。
- [x] T4.2 将 budget ledger 迁移到新 schema，新增每个 unique deployed model 恰好一个的
  infrastructure reserve；网络前事务 exact-once 占用，receipt 后事务只绑定最终审批、
  deployed model 与 roles 且不得新增费用；强模型的 annotator/judge 共享 reserve。
- [x] T4.3 验证 `ptu_v2 → ptu` 唯一映射、10,000/1,000 quota 映射和
  `model_id == immutable_deployment_id == deployed_model`。

## T5 — O5 crash-safe provider 控制器

- [x] T5.1 建立固定 allowlist 的百炼 deployment request/receipt models，漂移配置在网络前失败。
- [x] T5.2 实现 run lock、durable pre-send journal、确定性 suffix/marker 和原子 receipt。
- [x] T5.3 实现 timeout/409/响应丢失后的 list/reconcile；恢复不得重复 POST 或重复 reserve。
- [x] T5.4 receipt/remote manifest 不一致、并发 collision 或未知资源保持 BLOCKED，不采纳、
  不删除。
- [x] T5.5 新 HTTP client 固定 `trust_env=False`；代理环境变量不得改变 provider 控制面路由。

## T6 — O7 价格、cap 与 cleanup 证据

- [x] T6.1 实现 content-addressed price evidence，机械计算固定费用 reserve/RoleRate；人工
  字符串或未知计价项不得准入；digest 之外必须验证受信 pricing issuer 的独立域签名。
- [x] T6.2 provider cap 必须覆盖同 workspace/project/credential 的固定费和推理费；缺失时
  canonical state 保持 typed BLOCKED 并报告持续费用暴露；cap issuer/domain/currency/
  amount/expiry/resource binding 均须签名验证。
- [x] T6.3 实现仅针对 verified-owned RUNNING PTU 的直接 DELETE 状态机；禁止 MU stop，
  不确定结果不得声称停止计费；DELETE 还需独立 domain-separated cleanup 授权，缺失或
  重放时 delete_calls=0。

裁决记录：production provisioning/adoption 均只接收独立验签后的 price/cap evidence；
adoption 对 `gmt_create→issued_at` 与 `issued_at→cleanup_deadline` 分段向上取整，禁止用
总时长一次取整掩盖历史费用。`RoleRate` 只能由 sealed pricing capability 与 exact
`ModelRolePlan` identity 派生。receipt digest、ledger reserve、artifact、签名 expected 与
当前 GET 共同绑定 remote manifest；cleanup 在入口、获锁后及 DELETE 前重验相同 gate 与
固定 endpoint。terminal 404 仅证明 billing stop，不释放或复用 budget reserve，预算释放
留待独立签名预算修订/spec。

## T7 — O8 状态机与 production wiring

- [x] T7.1 实现 new/adoption 两条唯一状态机，并验证前置顺序、过期、崩溃恢复及反重放。
- [x] T7.2 接入最终 plan/contract/admission/probe；probes=3、verified=3、controller inference
  requests=0 才满足软件条件，但不外推账号全局零使用。
- [x] T7.3 当前外部部署仅生成 adoption 候选/报告；缺真实签名或 provider hard cap 时保持
  BLOCKED，不进行外部 mutation。

## T8 — 回归、证据与交接

> T1～T7 的软件实现已完成；T2.3 因仓库证据无法唯一证明历史 session-agent ID 而继续
> `BLOCKED`，不得伪造候选。以下三项必须由主代理在 fresh 门禁、diff/secret 复核和文档
> 占位符替换完成后再勾选；本文档更新本身不构成 READY 或外部准入。

- [x] T8.1 运行所有 031 focused tests、020 admission 回归、Ruff、mypy strict、pytest
  not-live/not-integration_postgres 和 OpenSpec strict。
- [x] T8.2 更新 031 proposal 状态、validation report、根 HANDOFF；明确软件完成项、外部
  签名/cap 阻塞与两套 RUNNING PTU 的费用风险。
- [x] T8.3 复核无 secret/private-key/完整 provider response/本机绝对密钥路径进入 Git diff。
  私钥和临时待签材料必须位于 repository 外；`.gitignore` 与测试共同拒绝约定的本地目录。

## T9 — PR #26 对抗性复审 hardening

> T8 记录的是首轮软件收口。PR 复审随后暴露共享 cap、caller trust、receipt/transport、
> adoption→cleanup 与 020 production wiring 的 Critical 缺口，因此旧 T8 全量数字不再代表
> 当前最终 diff。以下实现均先取得可复现 RED，再做最小 GREEN；PR 保持 Draft，最终 fresh
> gate 与独立复审完成前不得转 Ready，更不代表 020 READY。

- [x] T9.1 按同一受信 workspace/project/credential/currency/cap evidence/coverage 聚合跨
  run/purpose/account 的 fixed+inference 占用；并发、轮换 cap、exact replay、不同合法资源
  隔离均 fail-closed/exact-once，第二个超额 reserve 无部分写、provider mutation=0。
- [x] T9.2 删除 BudgetLedger 与 DeploymentController production mutation API 的 caller trust
  override；production 只加载 root-owned 固定 trust policy，测试能力仅通过显式 private seam。
- [x] T9.3 将 reconciliation capability 限制为受信 provider ownership issuer 在 fresh remote
  evidence 下签发，并把 signed authorization/cap 与非 secret transport credential/project
  identity 精确绑定；clone-forgery 与 A 授权+B transport key 均在网络前拒绝。
- [x] T9.4 让 verified adoption 通过 production 路径原子、内容寻址地写 cleanup receipt
  artifact；new/adoption/cleanup 共用 OS run lock，获锁后重验 freshness，排队期间过期 GET=0；
  replace/file fsync/directory fsync 故障不留半工件且重放幂等。
- [x] T9.5 将失败路径的费用报告改为保守语义：不得根据
  `final_topology_invalid/final_bind_blocked/admission_evaluation_failed` 或 020 DTO/布尔值推断
  cap 已验证；无 production capability 时报告 unbounded/typed blocker。
- [x] T9.6 为 provisioning/adoption/pricing/provider-cap/cleanup 补齐与既有 domain 一致的
  operator render→外部 sign→verify ceremony；保持 domain/role/scope 隔离、禁止 self-enroll、
  跨域重放与私钥输出。
- [x] T9.7 BudgetLedger schema v6 原子持久化完整 final topology sidecar，并只在 fresh
  production reload/reverify 后签发 opaque `VerifiedFinalTopology`；sidecar 篡改、缺失、v5
  legacy 迁移与稍后 exact replay 保持 fail closed/幂等。`run_020` 的 submit/resume/begin
  每次只经 canonical 031 finalizer，任何缺失/漂移/过期在 evaluator/model/provider I/O 与写入前
  阻塞。
- [x] T9.8 删除 production ledger/finalizer public API 的 caller `authorized_roles` 与权威
  `now`；角色只来自 root-owned policy，freshness 只来自受信 runtime clock，测试时间仅通过
  private seam 注入。补 self-authorized role 与 time rollback 的 RED→GREEN，零写/零网络。
- [x] T9.9 topology 内嵌 reconciliation issuer/transport/digest 不得自证 provenance；fresh
  production reload 必须与 root-owned issuer/transport policy 和独立 durable remote evidence
  精确比对。补内部完全自洽、签名也可验证但 provider provenance 伪造的 RED→GREEN。
- [x] T9.10 v5→v6 迁移对真实已 bind legacy rows 不回填或虚构 topology sidecar：受控 cleanup
  查询继续可用，但 production READY capability 必须 fail closed；迁移 focused 3 文件
  **72 passed**。
- [x] T9.11 在最终工作树运行合并后的 020/031 focused、Ruff、mypy strict、deterministic、
  OpenSpec strict、diff/secret audit，并由总控回填 fresh 数字；真实 provider/live 继续
  `NOT RUN`，T2.3、外部签名、root-owned trust store 与 provider 条件继续 `BLOCKED`。
  当前 D 提交前证据：affected **1274 passed**；冻结 main + 当前 031 聚合树的 027/030
  compatibility **375 passed**；Ruff、D 3 source strict mypy、031/020 OpenSpec strict 与
  `git diff --check` PASS；两路独立终审 C0/I0/M0 后，唯一一次 deterministic 为
  **3280 passed / 30 deselected / 495 warnings（509.75s）**。报告回填后重新冻结 exact
  26-path/blob/mode/secret tree；外部准入条件仍按上文保持 BLOCKED。
- [x] T9.12 删除 `run_020.main` 在 canonical 031 finalizer 前的旧 020 evaluator/probe 调用；
  topology/cap 缺失、伪造、漂移或过期时，首次 evaluator/provider probe/ledger/runtime write 必须
  全为 0。首次 evaluation 只允许在 session lock 内由 `finalize_durable` 发起，补顺序 RED→GREEN。
- [x] T9.13 隔离 production/test capability issuer 与 seal；所有 `_for_testing` pricing/cap/transport/
  receipt capability 必须被 production require/reserve/bind 拒绝，production public topology 测试不得
  用 test issuer 伪造 provider reconciliation。
- [x] T9.14 production `DeploymentController` 只能由 canonical factory 从固定 ledger/run-root/真实
  transport 构造；caller fake reader/transport 仅允许 private testing seam，生产入口在 provider I/O
  前拒绝替换依赖。
- [x] T9.15 将不可变 ownership receipt 与可续期 remote reconciliation observation 分层；sidecar
  只引用独立、内容寻址 observation。bind commit 后必须丢弃内存 capability并 fresh reload；5 分钟
  observation 过期后未刷新保持 BLOCKED，受信 refresh 以 append-only/versioned 方式恢复。
- [x] T9.16 将 `workspace_ref` 纳入 signed budget/provider-cap attestation 与 inference shared-cap
  resource identity；不同 workspace 不互相污染，相同 workspace/project/credential/cap evidence 仍
  全局聚合并发占用。
- [x] T9.17 receipt capability 与 authorization/reserve 的 provider-cap approval digest 必须 exact
  join；legacy 单部署 production bind 还须把 signed cap evidence `observed_at` 与 budget contract
  exact join。strong/weak approval 漂移与 observed-at 漂移均在事务前零写拒绝。
- [x] T9.18 remote observation 后、020 evaluator 前重新读取受信时钟与 durable topology/cap，
  并保留 evaluator 后复核；首个 canary 的 post-settlement candidate evaluator/write 前增加第四次
  canonical finalizer，并将 normal/resume 的 candidate evaluator 置于两次独立 durable
  topology/cap reload 之间。evaluator 返回后发生 expiry/digest drift/cap rotation 或 loader
  SQLite/OSError 时 candidate build/persist 为 0；进程控制异常原样透传，不重复 evaluator。
- [x] T9.19 cleanup 使用独立减费 authority，不因 READY/budget/provider spend cap 过期而锁死；
  ambiguous DELETE 后允许新 root-signed 授权对同一 immutable resource 安全恢复，跨资源仍零 I/O。
  adoption 获 OS lock 后须 fresh 重读固定 cap approval；controller-issued capability 必须直接进入
  canonical v7 dual bind→cleanup E2E，不得测试另铸或手工 seed。A 的 DELETE 结果不确定后由 B
  接管时，terminal receipt 必须绑定实际 causal DELETE attempt；v1/v2、provider 已不存在/仍存在的
  首次结果与精确重放均一致，foreign receipt exact join 不得放松。
- [x] T9.20 shared single/dual infrastructure transaction 必须绑定 ledger mode：testing ledger
  拒绝 production evidence，production ledger 强制完整 root-verified evidence/requests 并覆盖 caller
  policy/time/bindings；production 直接调用不得进入 testing receipt verifier 或产生任何写入。

裁决记录：使用 stacked review：`main ← A authority/cap ← B receipt/transport ←`
`C adoption/cleanup/CLI ← D finalizer/wiring`。A 只含固定 trust/shared cap；durable topology
依赖 B 的 trusted receipt/transport facts，故 sidecar 在 B 闭合。budget/deployment/cost tests
跨层，必须按条款/hunk 拆而不能按整文件拆。各 head 必须可独立审查、编译且 fail-closed；A～D
全部通过后反向聚合，完整栈一次进入 main，禁止逐层合入半成品并宣称可运行。真实 provider
mutation、020 T2～T7 与 002 内容均不属于本轮提交。

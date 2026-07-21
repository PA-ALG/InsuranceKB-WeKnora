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

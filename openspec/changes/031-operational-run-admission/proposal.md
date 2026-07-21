# 031 · 020 真实运行准入解阻

> 状态：**软件完成；外部准入条件 BLOCKED，待人工提交后重算 production identity**。
> 依赖：020 T1（PR #24，已合入 main）。本 change 只解除 T2～T7 的真实运行前置，
> 不执行金标标注、13 产品 baseline 或 judge 推理。

当前实现已交付 O1～O8 的 fail-closed 软件路径，但这不等于真实运行已经准入。仓库历史
没有可唯一证明的 legacy session-agent ID，因此 T2.3 不能由工具代填；当前工作树也尚未
形成可作为 production identity 根的人工 clean commit。provenance、预算、provisioning、
adoption、pricing、shared provider cap 与 cleanup 的真实签名，以及 root-owned trust store /
provider cap，均仍须由相应外部责任人提供或安装。在这些条件满足前，canonical admission
必须保持 `BLOCKED`，不得执行 provider mutation 或模型推理。

## 为什么做

020 已交付 fail-closed 的准入与 durable budget 软件，但当前权威工件仍为
`BLOCKED`：一个产品输入路径不规范、11 个历史产品无逐产品 provenance、三个
运行角色未绑定百炼唯一部署 ID、预算合同/台账与两类审批为空。继续把这些事实
手工写进 YAML 会把审计门禁退化成形式检查；直接创建按时计费的模型部署，又会在
开发与审批期间产生无边界费用。

## 做什么

1. 将 `平安福满分（2026）养老年金保险/product_meta.txt` 内容保持不变地迁移为
   统一的 `product_meta.json`，重新生成完整输入 identity。
2. 从现有仓库证据生成 11 个历史产品的逐产品 provenance **候选**；候选明确记录
   legacy session-agent 标识和证据边界，必须由真实 provenance 审批人签名，工具
   不得替审批人断言未知事实。
3. 增加离线 Ed25519 key ceremony、待签 payload、签名和 trust-store 安装工具；
   私钥永不入库、永不输出，production 仍只信任 root-owned 固定路径。
4. 增加创建前签名授权与 durable infrastructure reserve；价格证据、provider cap、
   固定费用和 token/request reserve 共同进入预算治理，禁止事后追认创建费用。
5. 增加 crash-safe 百炼部署控制器：代码固定 deployable ID、最小 `ptu_v2` 请求、
   durable pre-send journal、确定性 marker、模糊结果 reconciliation、ownership 复验与
   content-addressed receipt。创建/删除不触发推理。
6. 采纳或清理由用户已授权创建的两个唯一部署；采纳必须显式记录其 preexisting 成本
   边界并经审批，不能仅凭 RUNNING 状态更新 020 plan 或声称 READY。

## 不做什么

- 不调用 chat/completions、responses 或任何推理端点；
- 不自动接受历史来源，不生成伪造的审批身份/签名；
- 不创建 MU 或扩大 quota；provider 将 `ptu_v2` 请求规范化为 `ptu` receipt 时只接受
  代码固定映射；
- 不修改 020 的金标、baseline、judge 或质量门槛语义；
- 不把 API Key、私钥、完整 provider response 或本机绝对密钥路径写入仓库。

## 成功标准

- 所有确定性门禁全绿；
- 输入和模型 identity/probe 阻塞清零；
- 预算合同能覆盖部署固定费用与三个角色的 token 上限，台账已准入；
- 真实审批人签名存在且由 root-owned trust store 验证；
- canonical `run-admission.json` 为 `READY`，probe 为 3/3 verified，受控推理路由调用数为 0；
- 任一审批、provider cap、cleanup ownership 或成本事实不可信时仍为 typed `BLOCKED`。

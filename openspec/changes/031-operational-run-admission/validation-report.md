# 031 验收报告 — Operational run admission

> 当前状态（2026-07-21）：**T1～T7 软件完成；外部准入条件 `BLOCKED`；待人工 clean
> commit 后重算 production identity。** 本报告不声称 canonical admission `READY`，不声称
> 已取得真实签名、provider hard cap 或远端最终状态，也不把旧测试计数冒充 T8 fresh 全量证据。

## 1. 结论与证明力边界

031 已实现从输入规范化、legacy provenance 证据回验、离线 Ed25519 authority、部署前授权与
durable infrastructure reserve、crash-safe provider 控制器、可信价格/cap/cleanup，到最终
new/adoption 状态机及 020 production wiring 的 fail-closed 软件路径。

本次没有执行 provider 创建、采纳、删除或推理调用。软件通过只能证明：当完整、匹配且受信的
外部证据到位时，系统有可验证的准入路径；当任一身份、签名、价格、cap、ownership、receipt
或预算事实缺失/漂移时，系统会拒绝放行。它不能证明外部审批已经完成，也不能证明当前远端
资源状态或费用已经变化。

## 2. 软件完成项

- **O1 输入 identity**：将唯一错误扩展名 byte-preserving 迁移为 `product_meta.json`，并验证
  canonical JSON、原始 bytes、Git blob 与 SHA-256 identity；权威 production identity 必须在
  人工 clean commit 后重新生成。
- **O2 provenance**：实现 observed/legacy 联合模型与只读 Git evidence inspector，回验 ancestor、
  literal path、blob、digest、freeze time 和 recorded agent allowlist。仓库只保留批次/模型标签，
  没有唯一历史 session-agent ID，因此 T2.3 合法地保持 `BLOCKED`，未生成伪候选。
- **O3 authority**：实现 identity/domain/scope/role 绑定的离线 key ceremony、签名/验签与
  production 固定 trust path；私钥不入库、不输出。
- **O4/O6 durable reserve**：BudgetLedger v5 在 provider POST 前 exact-once 占用固定最大费用，
  receipt 后事务只绑定最终审批、部署与角色，不增加费用；强 annotator/judge 共享 reserve，弱模型
  独立 reserve。
- **O5 provider 控制器**：实现固定 request/receipt 合同、durable pre-send journal、确定性 marker、
  timeout/409/响应丢失 reconciliation、ownership 复验、原子 receipt 与 `trust_env=False`。
- **O7 价格、cap、cleanup**：实现 content-addressed price evidence、独立签名 pricing/provider-cap
  能力与只允许 verified-owned RUNNING PTU 的授权 cleanup；不确定结果不声称停止计费。
- **O8 编排**：new/adoption 两条唯一状态机接入最终 plan/contract/admission/probe；控制器推理调用
  必须为 0，当前缺外部条件时只产出 typed blocker/adoption 候选，不执行外部 mutation。

## 3. 本地门禁证据

以下为实施阶段和最终收口取得的 focused / affected 证据。各组存在重叠，**不得相加**。

| 门禁 | 阶段结果 | 证明范围 |
|---|---:|---|
| O1/O2 identity + provenance | 110 passed | clean identity 算法、legacy Git evidence、受影响 020 identity |
| O3 authority + affected 020 | 103 passed | trust policy、key ceremony、签名安全边界 |
| O4 authorization / BudgetLedger v5 | 146 passed | pre-POST reserve、post-receipt binding、迁移与回滚 |
| O5 provider controller | 23 passed | journal、reconcile、collision、receipt、代理隔离 |
| O6/O7 pricing/cap/cleanup | 56 passed | signed price/cap、成本计算、cleanup gate |
| T7 coordinator / production wiring | 21 passed | new/adoption 状态机、最终准入顺序 |
| 031 affected regression | 160 passed | 031 与受影响 020 合同组合 |
| T8 fresh 031 focused | **248 passed** | `tests/test_operational_*_031.py`；随后只调整了 020 会话锁测试的 macOS `spawn` 调度等待，031/生产代码未变 |
| T8 fresh 020 admission | **711 passed** | `tests/test_run_admission_*_020.py`，最终工作树独占复跑；其中会话锁文件另有 **15 passed** |
| T8 fresh deterministic | **2965 passed / 30 deselected** | `pytest -m "not live and not integration_postgres" -q`；证据产生后仅收紧上述测试调度容差，改动文件已由最终 020 全量覆盖，未无意义重复整套 |
| T8 fresh Ruff | **All checks passed** | `ruff check .` |
| T8 fresh mypy strict | **309 source files，无问题** | `mypy src tests` |
| T8 fresh OpenSpec strict | **031 valid；020 valid** | 两条命令均 exit 0；离线 PostHog telemetry DNS 噪音不影响校验 |
| T8 diff/secret/private-material audit | **PASS，无 P0/P1** | 未发现 secret、private key、完整 provider response 或本机 credential path；无真实 provider/inference 调用 |

## 4. 外部未满足条件

1. **人工 clean commit 与 identity 重算**：当前 AI 工作树不能提供 production clean SHA。人工提交
   后必须从该 clean revision 重算产品、共享输入与 execution-surface identity；旧 SHA 的派生工件
   不得复用。
2. **legacy provenance T2.3**：仓库没有唯一历史 session-agent ID。需要真实 provenance 责任人
   提供可审计的唯一身份/裁决并签名；工具不得把 `claude-fable-5 (session agents, gs-v0.1)` 等批次
   标签伪装成唯一 agent ID。
3. **外部签名**：仍需 provenance、budget、provisioning、adoption、pricing、shared provider cap、
   cleanup 各自 domain-separated 的真实签名；签名必须精确绑定 031 规定的 identity、scope、金额、
   deployment、receipt、时限与角色。
4. **受保护的运行时信任材料**：仍需安装 root-owned production trust store 与 provider cap；CLI
   不得用本地覆盖路径绕过固定生产策略。
5. **provider 条件**：pricing 与 provider cap 必须覆盖相同 workspace/project/credential、区域、
   currency、固定部署费和推理费，并在有效期内；deployment ownership/manifest/receipt 必须 fresh
   重验。条件缺失时 canonical admission 继续 typed `BLOCKED`。

## 5. 已知持续费用风险与外部变更声明

以下只记录 **2026-07-21 最后一次观测**，本次 T8 文档收口没有刷新远端状态：

- `qwen3.7-plus-2026-05-26-031strng`：last observed `RUNNING`；
- `deepseek-v4-flash-031weak1`：last observed `RUNNING`；
- 两者合计持续费用风险约 **¥11.04/小时**。

该历史观测不能证明它们此刻仍在运行，也不能证明计费已停止。本次没有创建、采纳、删除、停止、
扩容或调用任何外部模型；在真实 adoption/cleanup 授权、provider cap、ownership 与 fresh GET 证据
到位前，不得更新为“已采纳”“已清理”或“已停止计费”。

## 6. 合并与后续顺序

1. T8 本地软件门禁已完成；人工提交前仍需按最终 staged diff 再确认 rename 识别与敏感材料边界；
2. 人工复核、commit 031，基于 clean SHA 重算 production identity；
3. 在真实外部签名、root-owned trust store/provider cap 到位后重新生成 canonical admission；仍有
   blocker 就保持 `BLOCKED`，不得运行 020 T2～T7；
4. 031 独立合并后，再 rebase 002 并重新计算其依赖 identity；不得把 002 与 031 混入同一提交。

## 7. 本轮执行教训

- 每个高风险闭环先取得分段 RED，再做最小实现与 focused GREEN，避免大批改动后才发现合同偏差；
- 任何 agent/tool 60 秒无新输出即轮询并向业务方报告可验证进度；
- focused 绿色不能替代全量回归：本轮全量组合会揭示旧迁移 fixture 与新 BudgetLedger schema 的
  交互，必须在最终 diff 上 fresh 运行后才能收口。

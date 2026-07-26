# 23 · Enterprise LLM Wiki 生产架构控制板

> 当前唯一状态口径：D0 governance rewrite 正在实施。用户已于 2026-07-26
> 书面批准生产架构设计；本控制板不把 planned 项写成已交付。

## 1. 当前状态

| 项目 | 状态 | 当前允许动作 |
|---|---|---|
| D0 Production Architecture Reset | `IN PROGRESS` | 治理文档、OpenSpec、patch inventory |
| C0 Canonical Envelope | `PLANNED / NOT IMPLEMENTED` | 等 D0 |
| W0 Revision Contract Spike | `PLANNED / NOT IMPLEMENTED` | 等 D0 |
| CAP0 Capacity Contract | `PLANNED / NOT IMPLEMENTED` | 等 C0 |
| Milestone A | `PLANNED / NOT IMPLEMENTED` | 等 foundation |
| Milestone B | `PLANNED / NOT IMPLEMENTED` | 等 Semantic Core |
| Milestone C | `PLANNED / NOT IMPLEMENTED` | 等 Governed Active Release |

启动顺序：

```text
D0 → {C0, W0}
C0 → CAP0
then Milestone A → Milestone B → Milestone C
```

## 2. D0 完成定义

- 已批准生产设计完整进入仓库，除状态元数据外语义字节一致；
- AGENTS、CLAUDE、北极星、Runbook、Roadmap 和控制板使用同一生产权威；
- PostgreSQL Active WikiRelease 是 serving authority；
- WeKnora managed Wiki 是 fenced、可重建投影；
- `machine_auto | human_batch | hybrid | trusted_import` 均为合法 ReviewPolicy；
- 原始资料只用于证据、审核和补编；
- Harness 与 WeKnora 只通过版本化 REST + Source lifecycle event；
- planned WeKnora patch 仅 W1/P11/P13/P14；
- 旧路线只保留历史审计价值，不再提供实现授权；
- 文档门禁、独立复审和 exact tree custody 完整。

## 3. 下一批任务卡

### C0

- 单一职责：CanonicalEnvelopeV1、expected bytes/hash vectors、Python reference。
- 不包含：领域表、Candidate/Release、Go patch。
- 退出：跨语言规范、非法输入 fail closed、独立 Spec/Quality C/I=0。

### W0

- 单一职责：只读证明 WeKnora Source lifecycle 与 revision manifest 合同。
- 不包含：功能 patch、共享数据库、补偿平台。
- 退出：现有 API 充分，或以可复现证据触发条件 W1。

### CAP0

- 单一职责：CapacityProfile、launch/contracted_forecast/stress_breakpoint。
- 前置：C0。
- 不包含：压测平台、分片或第二数据库。

## 4. Milestone Gate

### Milestone A — Semantic Core

证明 exact revision、Evidence/Provenance、Schema、entity/applicability、Conflict、
security profile 和 Golden dev check。完成后仍不能宣称生产 Wiki 已发布。

### Milestone B — Governed Active Release

证明 Candidate、四种 ReviewPolicy、不可变 Decision/Release、PostgreSQL
active CAS/epoch/Outbox、固定 Release Query、rollback 与 G0b acceptance。

### Milestone C — WeKnora Production Experience

证明 managed-page fencing、Projector reconciliation、Evidence/Review/Proposal
UX、ACL、恢复演练、容量和最终生产切换。

## 5. 永久边界

- 生产模型只使用经批准、不可变身份的弱模型。
- Active Query 不读取 Candidate 或原始资料生成应用答案。
- MCP 只映射 Active Query，不复制权限、语义或发布逻辑。
- WeKnora 与 LLM Wiki 不共享 DB、Redis/Asynq 或内部队列。
- publication 只由 PostgreSQL transaction + CAS + Outbox 提交。
- 同一 Space 的最终状态转换串行，不同 Space 可并行。
- Worker/Projector at-least-once；幂等、fencing、reconciliation 收敛。
- 未登记 WeKnora patch、跨 Space、stale identity 和 caller 自报 authority
  一律 fail closed。

## 6. 容量与样本

Golden Product、产品/文档数量、Worker 数、attempt 数和并发都属于某次 fixture、
EvaluationProtocol 或 CapacityProfile。它们是验收输入或部署配置，不是产品硬
上限。没有真实 launch 证据时状态是 `INSUFFICIENT_CAPACITY_EVIDENCE`。

## 7. 本轮非目标

D0 不实现功能代码、migration、API/Worker、provider、WeKnora patch、真实
PostgreSQL/live/load，也不宣称任何 Milestone 完成。

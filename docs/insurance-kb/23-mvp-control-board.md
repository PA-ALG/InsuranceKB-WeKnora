# 23 · Enterprise LLM Wiki 生产架构控制板

> 当前唯一状态口径：D0 governance rewrite 正在实施。用户已于 2026-07-26
> 书面批准生产架构设计；本控制板不把 planned 项写成已交付。

## 1. 当前状态

| 项目 | 状态 | 当前允许动作 |
|---|---|---|
| D0 Production Architecture Reset | `GOVERNANCE MERGED`（PR #34）；本 docs PR 为治理补丁收口 | 归档 033、维护决策记录 |
| C0 Canonical Envelope | `IN PROGRESS`（Owner：总控窗口；worktree `ikb-c0`；OpenSpec 034） | 规格 → RED → GREEN → 双独立评审 → PR |
| W0 Revision Contract Spike | `AUTHORIZED / NEXT`（本机 live 六服务 healthy 已核验 2026-07-26） | C0 提交后本窗口执行只读 spike |
| CAP0 Capacity Contract | `PLANNED`（等 C0；launch 八项申报问卷待发业务方） | 等 C0 |
| P1 Job Store + Outbox | `SPEC DRAFTING`（033 §16 DAG：仅依赖 D0，与 C0 并行） | 规格起草；实现待规格评审 |
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

## 8. 决策记录

> 本节按 22 号蓝图约定记录执行裁决。裁决只澄清执行口径，不修改已批准的
> 033 设计正文；需要改正文时走下一次设计修订。

### D-2026-07-26-1 · CAP0 对 P2a/P2b 的门禁语义澄清

033 §5.1 要求"P2a/P2b 表和索引合同获批前冻结版本化 CapacityProfile"，同节
三档证据语义又规定 `launch` 是生产切换阻断门禁。按如下口径执行：

1. P2a/P2b 的放行前置 = CAP0 合同（schema 与档位语义）已冻结，且存在一个
   已冻结的 CapacityProfile 版本，其 `launch` 档由业务方**申报**的首上线
   环境规模填写（记录输入来源与时间；申报即可，不要求实测）；
2. `launch` 档的实测验证与 `INSUFFICIENT_CAPACITY_EVIDENCE` 阻断只作用于
   P15 生产切换，不作用于 P2a/P2b；
3. 业务方申报输入未取得时，CAP0 不得用无工作负载假设代填，此时 P2a/P2b
   不放行。因此 033 §5.1 的 launch 输入清单（八项）必须在 C0/W0 窗口期内
   向业务方发出并回收，这是 CAP0 的显式交付物之一。

依据：避免业务侧数据收集变成 DAG 头部串行阻塞；业务方 2026-07-26 批准
架构评估后落地。

### D-2026-07-26-2 · 评审深度分级

- 双独立 Spec/Quality 评审为默认，必须保留的高风险项：C0、W1、P1、P2a、
  P2b、P2c、P2d、P4a、P4b、P4c、P5a0、P5a1、P5a2、P5b1、P5b2、P6b、P7、
  P8、P9a、G0a/G0b custody；
- 单独立评审 + 自动门禁即可：P3、P9b、P13、P14、G0s 运行性检查、纯文档/
  治理 PR；
- "连续两轮独立评审仍出现同域新基础不变量即停止补丁循环、回到边界设计"
  规则对所有层级不变。

### D-2026-07-26-3 · 存量资产处置清单立项

[24 · 存量资产处置清单](24-legacy-asset-disposition.md) 是旧代码、旧迁移与
旧 OpenSpec 的唯一处置权威。每个 Pn 实现窗口的 Contract Card 必须引用其
对应行，声明本 PR 取代哪些旧表/旧模块及读写切换方式；不得在实现窗口内
临场重新裁决存量资产归属。

### D-2026-07-26-4 · G0a 标注并行启动与 W1 预案

- 平安 e 生保（尊享版）金标标注草稿（dev 集优先）即刻并行启动；正式冻结
  仍按 033 等待 P4c/P5a2 合同；
- W0 spike 的问题清单按"直接产出 W1 API 规格草案"的形状设计；W1 按大概率
  触发做预案，提前确认 Go 侧实现人力与窗口。

### D-2026-07-26-5 · 主线开发执行模式

业务方指示：Wave 1（C0/W0/P1）由总控窗口（Claude 会话）直接实施，
SDD/TDD，允许该窗口执行 commit/push 与创建 PR；合入主干前仍必须通过
按 D-2 分级的独立 Spec/Quality 评审与 CI 绿。CLAUDE.md 中"AI 会话不执行
git commit/push"在本指示范围内由业务方授权覆盖；主线目标锁定 033 MVP
（Milestone A → B → C），不开旁线。

## 9. 重置后基线排期（业务方 2026-07-26 已确认）

旧"7–10 工作日"MVP 口径随 033 重置作废。本节为当前基线排期；区间估计
仍非逐日承诺，偏离超出区间时按 §8 决策记录流程重新裁决并更新本节。

- **关键路径**（串行链，约 14 个 PR）：

  ```text
  W0(→条件 W1) → P4a → P4c → G0a 冻结 → P5b1 → P5b2 → G0s
    → P6a → P6b → P7 → P8 → P9a → G0b
  ```

- **喂入关键路径的并行道**（启动后前两周铺开）：C0 → CAP0 → P2a → P5a2
  → P2b/P2c（P2b/P2c 在 P2a 后、是 P6a/P6b/P7/P8 硬前置）；P4b（依赖
  CAP0+P4a，是 P5b1 硬前置——CAP0 输入回收风险因此直接压在关键路径上）；
  P1、P2d、P3、P5a0、P5a1 并行；G0a 标注草稿与 launch 容量输入回收同步
  启动。
- **吞吐假设**：参照 021/023 历史，单个中大 PR（Contract Card + RED→GREEN
  + 双独立评审 + PG 并发测试）约 1–3 个窗口日。
- **里程碑区间估计**（自 C0/W0 启动日起）：Milestone A（至 G0s）约 2–4
  周；Milestone B（至 G0b）约 4–8 周；Milestone C 依赖 W1/P11 Go 侧人力，
  待 W0 裁决后另估。
- 排期最大风险项：W1 是否触发及其 Go 侧人力、G0a 人工标注时长、launch
  容量输入回收时长。三者都已有并行化预案（见 §8）。

# 23 · Enterprise LLM Wiki 生产架构控制板

> 当前唯一状态口径：D0 governance rewrite 正在实施。用户已于 2026-07-26
> 书面批准生产架构设计；本控制板不把 planned 项写成已交付。

## 1. 当前状态

| 项目 | 状态 | 当前允许动作 |
|---|---|---|
| D0 + 治理补丁 | ✅ `MERGED`（PR #34/#35/#37） | 维护决策记录 |
| 知识编译层修正案（Amendment 1） | 🚧 本 PR 落地（业务方 2026-07-27 批准） | 见修正案 §2–§7 |
| C0 Canonical Envelope | ✅ `MERGED`（PR #36，双独立评审 4 Important 闭合，向量 40+19） | 消费方引用 |
| P1 Job Store + Outbox | 规格 ✅ `MERGED`（PR #38）；实现 🚧 `IN PROGRESS`（worktree `ikb-p1-impl`，迁移占号 **0015**） | TDD 实现 → 双独立评审 → PR |
| W0 Revision Contract Spike | ✅ `EXECUTED`（2026-07-27，OpenSpec 037）：**两份合同均 `insufficient` → 条件 W1 正式触发**；证据与 W1 API 草案在 spike PR | 评审合入证据 PR；P4a/P4c 保持 blocked 至 W1 |
| W1 WeKnora Revision Manifest | 🚧 `TRIGGERED / SPEC DRAFTING`（Go patch，预算内 W1 项；~600 行估计） | OpenSpec 起草 → 双独立评审 → Go 实现 |
| CAP0 Capacity Contract | 🚧 `IN PROGRESS`（OpenSpec 036；含 stock_backfill 档位与 declared/measured 语义） | TDD 实现中 |
| G0-probe 弱模型探针 | 🚧 `IN PROGRESS`（校准专用，非验收证据） | 出数后校准 G0a 阈值 |
| 038 G0a 金标资产化内核 | 🚧 规格 ✅ 冻结（PR #42 draft）；实现 `NOT STARTED` | RED → GREEN → 双独立评审 → PR |
| Schema 切片 + 词表 seed 草稿 | 🚧 `IN PROGRESS`（Golden Product 医疗险；专家收口于 G0a） | 草稿 → 专家评审 |
| Milestone A | `IN PROGRESS`（首批地基推进中） | 按修正案 §7 DAG |
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

### D-2026-07-27-6 · 外部诊断裁决与知识编译层修正案

Opus 诊断（enterprise-llm-wiki-gap-analysis）经独立对抗性裁决后由业务方
批准落地为
[知识编译层修正案](../superpowers/specs/2026-07-27-enterprise-llm-wiki-knowledge-compilation-amendment.md)。
采纳：G0-probe、P5b0、P5a1+ 内容化（Golden Product 切片）、P5b1+ 抽取
质量机制与反向补抽、P5b2+ SourcePrecedencePolicy（确定性①–④，弱模型
共识建议后置）、P5a0+ 合同澄清、G0a+ 标注 Agent 子系统、CAP0+
stock_backfill、human_batch-first 首发画像。拒绝（记录于修正案 §6）：
recall 数学不可能论、无主动撤回入口论、machine_auto 吞吐死锁论、
O(片段) 人工论。后续版本项见修正案 §5。

### D-2026-07-27-7 · subject_ref = product_version

Claim/Relation 的 `subject_ref` 绑定 `product_version`（修正案 §4.1）。
P5a2 据此建模，不可逆；文档→ProductVersion 归属判定（P5a0/003）是版本
编译的真实前置。

### D-2026-07-27-8 · 首发画像 human_batch-first

machine_auto 整链（P2c approval registry、P7 exact verifier、
AutomationScope 重验、shadow/canary）移为 `P15[auto-profile]`，依赖 G0b。
G0b 保持为知识质量门禁不变。P2c 拆分：ReviewPolicyVersion 存储/指针/
epoch 留主线。

### D-2026-07-27-9 · 金标标注模式（修订 033 §14.1 落地形态）

模型标注 + 确定性验证 + ≥2 强模型交叉；人工只审分歧 + 全部高风险字段 +
5% 抽样。高风险字段（precision=1.00 门槛）的裁判必须是人。holdout
custody 等防刷红线不变。

### D-2026-07-27-10 · 迁移台账清理

0007–0011 预分配随 009/010/011/012/025 撤号作废，永不复用；0013/0014
（superseded 028b 计划）同样作废。P1 实现使用 **0015**。台账修订随 P1
实现 PR 提交（该 PR 是 0015 的占号 Owner）。

### D-2026-07-27-11 · W0 裁决：两份合同 insufficient，W1 触发

live 实测证据（OpenSpec 037 artifacts）：公开 API 无单调 parse
generation；删除无 tombstone（404 与 never-existed 不可区分）；服务端
digest 仅 MD5；chunk 无 attempt 字段、无服务端 manifest digest、
`content_hash` 全空；metadata/chunk 替换非原子（3/3 观察到中间窗口）；
分页期间重解析 3/3 出现新旧混排且静默丢块、全程 HTTP 200——"同 attempt
完整快照"被证明不可获得。`SourceLifecycleContract` 与
`RevisionManifestContract` 均 `insufficient`。**条件 W1 正式触发**（patch
预算内），P4a/P4c 保持 blocked 至 W1 合入；W1 API 草案见 037
`artifacts/w1-api-draft.md`。

### D-2026-07-27-12 · 待业务方动作

① 关闭 superseded DRAFT PR #26/#28/#33（会话权限受限）；② 确认是否存在
Golden Product 真实第二版本资料（决定 G0v 可行性）；③ CAP0 八项 launch
容量问卷（036 交付后转发业务方填报）。

### D-2026-07-27-13 · G0-probe 结果与阈值校准（校准专用，非验收证据）

真实弱模型 dev 粗测（301 次调用）：micro F1 0.15–0.31（合计 0.231），与
历史 0.216 同量级——**G0b 0.95/0.90 是结构性差距**。分解：引文回验
1.000、present 检测精度 0.948（deepseek）、幻觉 0.052；塌方在值一致性
0.273；qwen-flash 幻觉 0.22（4 倍差）→ 模型身份门有判别力；确定性
fastpath 2/2 exact。G0a 冻结口径：可即冻 evidence ≥0.99 / 幻觉 ≤0.10
（按模型身份）/ present-P ≥0.90；值精度与召回待 P5b0/P5b1+ 后分档
（v2 P≥0.60 起步）；高风险 1.00 只经确定性路线 + 人审；每维最小支持
≥30 键；**冻结前必须修"值承载 absent 计为幻觉"的度量约定 bug**。完整
报告：`docs/insurance-kb/probes/2026-07-27-g0-probe-report.md`。

### D-2026-07-27-14 · 真实版本资料已获取，G0v 走真资料

平安官网信息披露渠道获取 14 份官方 PDF（备案号齐全，manifest 含
sha256/来源 URL，见 `dataset/version-materials/`）。G0v 采用
**e生保长期医疗（费率可调）1072-1（2020-168号）vs 1072-4（2021-155号
重发）**真实版本对（033 §14.1 允许以具备真实版本资料的产品验收版本
能力）；Golden 尊享版本体仅一个备案版本，保持单版本。**不构造合成
版本**。同名不同产品"平安附加e生保（尊享版）长期医疗"一并收录，作
P5a0 实体消歧测试数据。D8 关闭。

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

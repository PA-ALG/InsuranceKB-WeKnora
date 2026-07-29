# 23 · Enterprise LLM Wiki 生产架构控制板

> 当前代码事实截止点（截至 2026-07-29）：
> `main=529d72c994369750b26e352a70fd6284e8b0fd9d`。
> 用户已批准 728 V3、Sole Serving Active Release Authority ADR 与 Amendment
> 2；本控制板严格区分
> `MERGED`、规格完成、draft、校准证据与生产上线，不把 planned 项写成已交付。
>
> PR #53/#55/#56/#57/#58/#59/#63/#64/#65/#66 均已合入；Mission 0 开工前
> GitHub open PR 为 `0`。PR #44 仍为 `CLOSED / ARCHIVED / NOT MERGED`，
> 其经批准的 P1 实现由 PR #53 重落地后合入，不改变归档分支的历史身份。

## 1. 当前状态

| 项目 | 状态 | 当前允许动作 |
|---|---|---|
| V3 serving authority | ✅ 原则 `ACCEPTED`；WeKnora carrier `ACCEPTED_CONDITIONALLY` | Mission 0；不得恢复双 Active Projector |
| Mission 0 | 🚧 docs-only 治理纠偏 | ADR/Amendment/状态同步；零功能代码、零 migration |
| S0-Q | `APPROVED TO START AFTER OPENSPEC/MISSION CARD` | 使用 WeKnora/W1 冻结解析制品；禁止人工清洗文本 |
| S0-R | `BLOCKED ON 80a5003 CAPABILITY GAP + OWN OPENSPEC` | 输入就绪后两工作日证伪；非生产 Kernel 交付 |
| D0 + 治理补丁 | ✅ `MERGED`（PR #34/#35/#37） | 维护决策记录 |
| 知识编译层修正案（Amendment 1） | ✅ `MERGED`（PR #39；业务方 2026-07-27 批准） | 见修正案 §2–§7 |
| C0 Canonical Envelope | ✅ `MERGED`（PR #36，双独立评审 4 Important 闭合，向量 40+19） | 消费方引用 |
| P1 Job Store + Outbox | ✅ `IMPLEMENTED / MERGED`（规格 PR #38；实现 PR #53） | 迁移 **0015**；5 条非阻断 follow-up 归 042 |
| W0 Revision Contract Spike | ✅ `EXECUTED / MERGED`（PR #40，OpenSpec 037）：两份合同均 `insufficient`，W1 正式触发 | 触发结果已由 W1 PR #55 闭合 |
| W1 WeKnora Revision Manifest | ✅ 源码 `IMPLEMENTED / MERGED`（规格 PR #41；实现 PR #55，OpenSpec 038） | `80a5003` adoption 与 legacy `000066` bridge 已完成；Full Artifact/W1 runtime probes 仍 OPEN |
| CAP0 Capacity Contract | ✅ `IMPLEMENTED / MERGED`（PR #46；含 stock_backfill 与 declared/measured） | 八项 launch 问卷仍待业务确认 |
| P3 API/Worker Shell | ✅ `IMPLEMENTED / MERGED`（规格 PR #48；实现 PR #58，OpenSpec 039） | 双角色、principal fail-closed、readiness truth、lease/drain 已交付 |
| P1 Active Fence Verifier | ✅ `IMPLEMENTED / MERGED`（PR #59，OpenSpec 044） | 只读 DB-clock fence；零状态/Outbox 写 |
| P5a0 ProductVersion Resolver | ✅ `IMPLEMENTED / MERGED`（PR #56，OpenSpec 041） | 后续 P5a2/G0a 消费 |
| P2d Space Security Boundary | 规格 ✅ `MERGED`（PR #57，OpenSpec 043）；`SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R` | 保留 Space/principal/epoch/ACL/跨 Space/零写；不得按旧 `wiki_projector` 语义实现或创建 0016 |
| WeKnora `80a5003` adoption | ✅ source/bridge/images/digest pin complete | upstream=`80a5003`；build source=`a8bf55ae...`；Full Artifact probes OPEN，source_reader BLOCKED |
| G0-probe 弱模型探针 | ✅ `COMPLETED`（PR #45 证据；校准专用） | 只校准 G0a，不构成 G0a/G0b 验收证据 |
| Schema 切片 + 词表 seed | ⚠️ `DRAFT / NON-AUTHORITY`（PR #43 已合入） | 等领域专家与后续 Contract Card 正式冻结 |
| 金标标注 v0 | ⚠️ `DRAFT / NON-ACCEPTANCE-AUTHORITY`（PR #49 已合入） | 等 G0a 正式 custody、协议和验收冻结 |
| G0a 金标资产化内核 | 规格 ✅ `MERGED`（PR #42，OpenSpec 040）；`SPEC-ONLY / IMPLEMENTATION NOT STARTED` | 后续实现须独立 TDD/复审；不得称 G0a 已验收或产品已完成 |
| Repository operational cleanup A1/A2 | ✅ 历史收口已完成；同步 worktree 建立后为 32 records / 31 usable / 18 clean / 13 dirty / 1 prunable | 历史现场保留；未经新授权不清理、不 reset |
| 旧 Milestone A/B/C | `SUPERSEDED AS EXECUTION DAG / HISTORY-ONLY` | 只作能力盘点；当前按 S0 双门与 MVP 纵切推进 |

当前唯一启动顺序：

```text
Mission 0
├── 80a5003 capability gap matrix → S0-R
└── S0-Q 立即并行
           ↓
S0-R PASS AND S0-Q PASS
           ↓
MVP 纵向闭环；legacy 按需改接、物理清理后置
```

## 2. 旧 D0/Milestone 账本（history-only）

> [!WARNING]
> 本节至第 7 节保留 2026-07-28 前的依赖、能力与验收盘点，不再构成开工顺序、
> serving authority 或 patch 授权。凡与第 1 节和
> `D-2026-07-29-1` 冲突，均以 Mission 0 / S0 双门路线为准。

### 历史 D0 完成定义

- 已批准生产设计完整进入仓库，除状态元数据外语义字节一致；
- AGENTS、CLAUDE、北极星、Runbook、Roadmap 和控制板使用同一生产权威；
- 正式线上知识只有一个 serving Active Release authority；
- WeKnora 作为 authority carrier 为 `ACCEPTED_CONDITIONALLY`；
- Harness 不保存第二个 serving Head；
- `machine_auto | human_batch | hybrid | trusted_import` 均为合法 ReviewPolicy；
- 原始资料只用于证据、审核和补编；
- Harness 与 WeKnora 只通过版本化 REST + Source lifecycle event；
- planned WeKnora patch 仅 W1/P11/P13/P14；
- 旧路线只保留历史审计价值，不再提供实现授权；
- 文档门禁、独立复审和 exact tree custody 完整。

## 3. 当前推进卡

### 已完成地基

- C0：CanonicalEnvelopeV1 已由 PR #36 实现并合入。
- CAP0：CapacityProfile 合同已由 PR #46 实现并合入；launch 问卷仍待业务确认。
- W0：PR #40 已证明两份合同均 `insufficient`，其退出结果是触发 W1，不是
  WeKnora revision 能力已满足。

### W1

- OpenSpec 038 规格由 PR #41 合入，Go 源码实现由 PR #55 合入；W1 源码实现
  已完成，runtime adoption 尚未完成。
- 源码合同已完成，但 trusted local-live workflow 仍从 `5eefa70e` 构建且只
  应用 model-debug redaction patch，当前运行制品不含 W1。采用 v0.7.1 时还
  必须解决项目与上游同时占用 migration `000066` 的直接冲突。
- P4a/P4c 的 W1 代码前置已经解除；生产运行采用仍受 v0.7.1 upgrade
  Mission 阻断，它们还分别受 P2d、P2a/P4a 等 DAG 前置约束。
- PR #42 已把 G0a 规格以 OpenSpec 040 合入；这只关闭编号冲突，不改变
  W1/038 的已完成事实，也不表示 G0a 实现或验收完成。

### P1 → P3

- P1 规格由 PR #38 合入，实现由 PR #53 合入；旧 PR #44 继续保持
  `CLOSED / ARCHIVED / NOT MERGED`，不得混淆两个 Git 身份。
- P3 规格由 PR #48 合入，实现由 PR #58 合入；PR #59 另交付只读 active
  fence verifier。下一项 P3-owned 工作只有为 043 提供最小权限 ACL
  inspection authority，不得扩成通用服务框架。

### 下一轮两开发 + 一审查

- Lane A：WeKnora v0.7.1 adoption + 000066 migration bridge + W1 replay；
  再基于新 scoped/platform key API 裁剪 P3 ACL-inspection authority，
  随后串行接 043 P2d。
- Lane B：P5a1 SchemaVersion + Golden Product slice。P2a 等八项 launch
  业务输入回收后再启动，不得以假设补齐 D-2026-07-26-1。
- Lane C：动态只读 review/integration；所有修复退回唯一写 Owner。
- P2c 技术依赖已满足但属于 Milestone B；G0a 仍受 P2d/P4c/P5a2 阻断。

### human_batch-first

- 机器审核结果可以成为批量决策输入；生产发布动作是授权人对 **exact
  CandidateRelease** 的一次性批准或拒绝，不是逐页审批。
- 完全无人值守 `machine_auto` 属 `P15[auto-profile]`，依赖 G0b，并要求
  显式、版本化的 policy binding。
- superadmin 不得绕过完整性、Space ACL、Provenance/security 或
  PostgreSQL CAS/epoch。

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

### D-2026-07-29-1 · V3 sole serving authority 与 Mission 0

1. 正式线上知识只有一个 serving Active Release authority；WeKnora 作为当前
   carrier 为 `ACCEPTED_CONDITIONALLY`，Harness 无第二 serving Head。
2. PostgreSQL Active → Outbox → WeKnora Projector 路线
   `superseded / history-only`；旧 018 代码、表和 migration 冻结审计，不立即
   删除。
3. OpenSpec 043 保留通用安全合同，但必须在 S0-R 后 amendment；预留 migration
   0016 不得提前创建。
4. MVP profile 固定 `1 RAW KB + 1 release-managed Wiki KB`，不是永久企业
   cardinality。
5. S0-R 是输入就绪后的两工作日二元证伪窗口；S0-Q 必须使用 WeKnora/W1 冻结
   解析制品。
6. 045 exact identities 分离：upstream `80a5003...`、image build source
   `a8bf55ae...`、current main `529d72c...`；digest pin 不等于 Full Artifact
   closure。
7. S0 双 PASS 后只按首个纵切真实调用改接，legacy 物理清理留到 MVP 后。

### D-2026-07-28-20 · #53/#55–#59 集成完成与下一轮主航道

1. `d1c1b3ac` 是本轮代码事实截止点；P1、W1、P5a0、P1 active fence、
   P3 shell 已实现合入，P2d 规格已合入，禁止重复排期；W1 的 local-live
   runtime adoption 尚未闭合。
2. WeKnora 官方 `v0.7.1@c64a4864` 已发布，项目仍锁 v0.6.3/`5eefa70e`。
   直接升级被上游/项目同号 migration `000066` 与 W1 14-path overlap 阻断。
3. migration 修复不得静默改写历史，也不得把 legacy W1 `000066` 改名或
   删档：必须覆盖现有 `5eefa` DB 尚未执行任一 000066、上游 000066 已执行、
   项目 W1 000066 已执行、fresh v0.7.1 DB 四种状态，并保留两侧 schema；
   采用独立 project migration state/namespace 或经审查兼容桥，并以
   upstream-tag collision CI 阻断未来碰号。在此之前不新增 project-owned
   WeKnora migration。
4. 下一轮固定为两个开发 lane：Lane A 先做 v0.7.1 adoption/迁移桥/W1
   replay，再裁剪 P3 ACL authority 并进入 P2d；Lane B 做 P5a1；第三 lane
   动态审查/集成。
5. P2a 的软件依赖已满足，但 D-2026-07-26-1 要求的八项 launch 业务输入
   未回收前仍 blocked；P2c 不抢占当前 Milestone A lane。
6. 状态文档同步不授权任何上述功能开工；每项仍须独立 Mission Card。
7. 历史 worktree 不等于当前 main，dirty/prunable 现场未经授权不处理。

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
（superseded 028b 计划）同样作废。当前 main 唯一 Alembic head 是 **0006**；
**0015** 仍为 P1 实现预留但未合入，未来新小 PR 必须从当时最新 main 重新
确认 `down_revision`。

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

### D-2026-07-27-12 · 业务方动作状态

① superseded PR #26/#28/#33 已关闭，完成；② Golden Product 真实第二版本
资料已取得，见 D-2026-07-27-14，完成；③ CAP0 八项 launch 容量问卷仍待
业务确认，未完成。

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

### D-2026-07-27-15 · P1 旧 PR 关闭但实现同内容重落地（取代 #52 的"不得重放"条款）

业务方 2026-07-27 裁决：**关闭 PR #44 成立，从零重做 P1 不成立。**

- **背景**：#44（P1 实现）经规格评审 Approved-with-findings（minor）+
  对抗评审 REJECTED（2 Critical / 10 Important / 7 Minor），19 条全部
  RED-first 闭环后转为 `DIRTY / CONFLICTING`，2026-07-27 06:40 由 codex
  关闭并归档为 tag `archive/pr44-p1-job-outbox-20260727-a6cdc9ae`。
  随后 PR #52 在 HANDOFF/注册表写入"P1 实现回到 `NOT STARTED`；后续只能
  从最新 main 以新小 PR 提取仍需的能力，**不得恢复或重放 #44**"。
- **裁决**：该条款由本决策**取代**。P1 实现由 **PR #53** 从最新 main 的
  干净 worktree **同内容重落地**：代码对归档 tag 逐字节一致（`git diff`
  在 P1 全部代码路径为空；main 侧自 merge-base `dedbbafb` 起从未触碰这些
  文件），只按最新 main 重写 `HANDOFF.md`、`openspec/changes/README.md`
  与 `validation-report.md`。#44 的 `CONFLICTING` 仅来自这两个治理文档，
  代码零冲突。
- **理由**：#44 的 19 条 findings 已沉淀为 16 个以 finding 编号命名的
  测试节点（`test_c1_*`/`test_c2_*`/`test_i3..i10_*`/`test_m14..m19_*`）。
  两个 Critical（C1 = scope 外过期 lease 永久占死全局限额；C2 = 回收不
  递增 generation 致被逐出 worker 仍可写）是该领域固有陷阱,换分支从零
  重做几乎必然重新踩一遍并再挨一轮对抗评审——循环变长而非变短。033 §18
  的停线规则要求"外审发现真实缺陷时**保留测试场景**"，与本裁决一致；其
  "连续两轮独立评审仍出现同域新基础不变量即停止补丁循环"的触发条件在
  #44 不成立（规格评审只有 minor，实质 findings 只有对抗评审一轮）。
- **约束**：这 16 个测试节点是 #53 验收清单的**强制项**，后续重构不得
  删除。#53 不继承 #44 的任何门禁证据，全部在自己 head 重跑。两项已知
  边界仍待 reviewer 裁决：生产代码 1300 有效行 > 033 §16.2 的 ~900
  重新切分警报线（作者主张 P1 是单一原子不变量不拆，§16 交付表亦把
  Job+Outbox 列为一个交付项）；`DomainWriteHandle` 可执行任意 SQL，以
  文档合同约束、交 P3 接线时按权限模型收紧。
- **一般规则**：未合入的 PR 被关闭时，若其代码已通过评审 findings 闭环，
  归档 tag 的内容可在最新 main 重落地；**关闭 PR ≠ 作废其已闭环的
  findings**。治理文档写"不得重放"需要业务方裁决，执行会话不得单方面
  把关闭动作升级为能力作废。

### D-2026-07-27-16 · P1 §18 停线与 lease 写权威边界冻结

PR #53 的双独立评审（Spec / Quality，互不知晓对方结论、各自独立 worktree +
独立 PostgreSQL）双双给出 **not compliant / not approved**，并**独立复现了
同一个破口**：过期未回收的 lease 既不计入并发限额、又保有完整写权威。

**§18 停线判定成立。** 触发条件是"连续两轮独立评审仍出现同域新基础
不变量"：#44 已过两轮（规格评审 minor + 对抗评审 REJECTED 19 条），本轮
是同一份代码的第三、四轮，而两支新评审各自独立落在 **lease 过期语义 ×
写权威 × 限额会计**这同一个域——C1 修了"过期行不占额度"、M14 修了"过期行
不能被 heartbeat 续命"，两轮都没回答"过期行的持有者还有没有写权威"。
按 §18"若根因是错误架构边界，替换边界而不是把补丁堆叠到旧实现"，本决策
**先冻结边界规格再实现**，不接受继续在旧实现上追加条件分支。

**三条 Critical**（均有 live 复现）：

1. 过期未回收 lease 保有写权威 + per-Space/全局限额被无界超越（两侧共同；
   Spec 侧"限额 1 实际 2 行"、Quality 侧"限额 2 实际 6 租约 + 6 份领域
   结果"，且单 Space 即可触发）。计数侧被 C1 收窄为 `lease_expires_at >
   now`，写权威侧只校验 generation ⇒ "被计数的集合" ≠ "能写的集合"，
   全局上限恰在其设计要抵御的失效模式（worker stall）下静默 fail-open。
2. `claim` 与 `start` 之间崩溃 ⇒ 毒任务无界重排队（Quality 独有；实测 25
   次租约后 `attempt` 仍 0、永不 `dead_letter`）。DLQ 的界被押在"worker
   有没有来得及自报 `start`"这一可缺失标签上，而数据库已知投递次数。
3. 领域写句柄可结束完成事务 ⇒ 两份领域结果 + 跨 Space 伪造（Quality
   独有）。此前 #44 与总控窗口均把它当作"已声明的可接受残余（SQL 沙箱
   不属 P1）"，该定性被 live 证据推翻：一条 raw `COMMIT` 即可使领域行落库
   而任务留在 `running`、outbox 为空，重放产生第二份领域结果；同一通道
   还可复活其他 Space 的终态行、伪造 `lease_generation`、插入越域 outbox
   行。I8 只收紧了属性面，未收紧语句面。

**冻结的边界条款**（已随本 PR 写入 035 spec，属澄清不属扩域——不新增状态、
不新增异常分支，四项修法均为收敛）：

- P1.3 写权威 = 当前 generation ∧ lease 未过期；四条写路径对称执法；
  `lease_seconds` 必须 `> heartbeat_interval_seconds` 且严格为正；
- P1.8 限额计入全部 `leased | running` 行；饱和且存在过期行时先做一次受
  `maintenance_batch_size` 约束、**无 Space 过滤**的回收再重算（消除 C1
  的饥饿动机，同时不再过度准入）；
- P1.1 第 10 条：回收 `leased` 行时先递增 `attempt` 再路由；
  storage-only 转换必须有可执行的执法点，失败上报要求源状态 `running`；
- P1.10 必须提供显式命名的跨 Space 回收入口（与 P1.9 全局聚合同形）；
- P1.6 投递不得因失败计数永久移出扫描窗口，让位机制改**持久化退避**
  （`next_dispatch_at` + 配置化退避序列）；事件只能在完成事务内追加；
- P1.7 duplicate 判据改为不可被覆写的持久事实；
- P1.5 领域写句柄受语句面约束（事务身份不变式 + 禁写 P1 自有表）；
- P1.9 新增过期 lease 计数与最老过期 lease 年龄为必需指标。

**评审方法论记录**：两支评审各自漏了对方抓到的东西——Spec 侧把
`STORAGE_ONLY_TRANSITIONS` 判为满足（核了 backoff 提升无公共入口，但漏查
失败上报缺源状态守卫）、把领域写句柄判为 Minor；Quality 侧不覆盖 Contract
Card 义务与迁移台账合规。**有 live 复现的一侧优先。** 这印证 D-2026-07-26-2
的双独立评审设置有效，且"红队也会错、双向都不轻信"。

### D-2026-07-27-19 · 035 收口：BACKLOG 转 042，P1 可合入

035（P1 Job Store + 事务性 Outbox）在 PR #53 经**四轮**独立评审收口：
规格评审 1 轮 + 对抗评审 3 轮，另有总控窗口 2 次自攻。

**最终裁决**：零 BLOCKER，P1 满足合入条件（双独立评审无阻断项 + CI 三项绿 +
与 main 零冲突）。

第四轮定向评审覆盖此前从未被独立验证的五个面，结论：

- `attempt` 计数精确性 → **no finding**（循环内严格 +1，恰在 `max_attempts`
  处 `dead_letter`，既不无界也不提前）；
- `human_decision_resumed_at` 不可变判据 → **no finding，攻不动**（含"唤醒后
  经回收致 `error_class` 被覆写"的关键回归、8 线程并发恰好 1 resumed/7
  duplicate、7 种表标识变体伪造该列全被拒）；
- `_reclaim_saturated` scope-free 有界回收 → 越限/饥饿/跨 Space 泄漏**全部
  攻不动**（15 秒 6 并发压测 2310 次采样零越限；被外部锁持有的行只在锁存续
  期间让位，锁一放立刻收敛）；
- 多 spec 领域写原子性 → **成立**（四种失败模式 live 复现均为领域表零行 +
  任务仍 `running`，"部分落库但任务未 succeeded"构造不出来）；
- `next_dispatch_at` 持久退避 → 3 条 BACKLOG，**已在 035 内修完**（详见下）。

**在 035 内修掉的 B 面三条**：① `dispatch_backoff_seconds` 只校验 `>= 0`，
`inf`/`nan`/`1e12` 通过配置门却在写入时抛裸 `OverflowError`——异常在 cursor
推进前逃出，每轮重撞同一队头事件使整个 Space 的 outbox 卡死（I10 队头阻塞
回归），且 `dispatch_attempts += 1` 随回滚丢失。修为有限性 + 30 天上界，
**护栏只接受自己能履行的值**（与表标识那条同一族教训）；② 模型层默认
`(0.0,)` 是热循环（实测约 180 次/秒空转），与 `config.py` 自身声明矛盾，
改 `(1.0,)`；③ 退避基准在 `deliver()` **之前**读取，超时（生产主要失败形态）
时退避退化为空操作，改为失败分支按数据库时钟重读。

**转出到 042 的 5 条 BACKLOG**（号已占、目录未开，比照 026 惯例；本节即其
权威清单）。五条均 live 证明不损坏数据、不越 Space、不产生第二份领域结果，
符合 `AGENTS.md`「真实但不阻断当前用户价值」：

1. **领域写失败的驱动异常穿透 typed 面**。`_execute_domain_writes` 的数据库层
   失败把裸 `IntegrityError`（约束冲突）/`DataError`（类型错误）抛给调用方，
   而 `store.py` 自身声明"越界在存储层前置 typed 拒绝，不泄漏 `DataError`"。
   泄漏的是调用方**自己**领域表的表名/约束名，不越 Space。影响：调用方无法按
   P1.4 的封闭分类路由领域写失败。建议：为领域写失败定义 typed 载体（区分
   "调用方数据不合法"与"目标 schema 不兼容"）并明确其在 P1.4 中的映射。
2. **反射占用第二条连接，与完成事务争抢连接池**。`autoload_with=session.get_bind()`
   的 bind 是 Engine，反射另取一条连接，而当前事务的连接仍持着任务行的
   `FOR UPDATE` 锁。live（`pool_size=1, max_overflow=0, pool_timeout=3`）：
   有领域写的完成事务 `TimeoutError in 3.01s`，领域行零写入、任务仍 `running`
   （原子性成立，只是完成不了）。出货默认池 15 对默认并发 8 有余量，但该上限
   "只是环境默认而非产品上限"（P1.8 明文）——调到 ≥ 15 即**完成路径自我死锁**
   （每个反射等 30s 后抛 Timeout）。建议：反射改用当前事务连接
   （`session.connection()`），或由第 3 条的缓存彻底消除运行期反射。
3. **反射无缓存**。同一目标表连续两次完成事务，各 14 条语句中 10 条是相同的
   `pg_catalog` 反射查询。领域写在热路径上，每次多 10 个 catalog 往返且发生在
   **持有任务行锁的事务期间**（放大第 2 条的窗口）。建议：进程级 `MetaData`
   缓存（按 bind + 表名），或要求装配期注册可写领域表——后者同时收紧可写表
   白名单，与 P1.5 的 `OWNED_TABLES` 精确枚举同形。
4. **有界回收触发条件宽于 spec**。P1.8 要求"上限已饱和 **且饱和集合中存在**
   过期行"才触发，实现在饱和时**无条件**调用 `_reclaim_saturated()`。live
   （`per_space=1, global=8`）：调用方 Space 无过期行、全局未饱和 → claim 返回
   typed `per_space_concurrency_limit`（调用方一无所获），但**另一 Space** 的
   过期行被当作副作用回收。代价：① 每次 per-Space 饱和的 claim 都在全局
   advisory 锁串行段内多做最多 `maintenance_batch_size`（默认 128）行的加锁 +
   更新；② 另一 Space 的过期行按**调用方实例**的 `policy_for`/`max_attempts`
   被推进乃至 `dead_letter`，**review M18 的多实例配置分歧在此被放大**。
   建议二选一并写入决策记录：(a) 收窄实现以匹配 spec；(b) 修订 spec 承认无条件
   维护并明确其 M18 影响。
5. **docstring 与实现的先后次序不符**。`_execute_domain_writes` 声称"全部规格
   先校验、后执行"，实测表/列存在性检查在**执行循环内**（只有表名/列名/列值
   形状在前置循环），第一条 INSERT 可能已执行才拒绝第二条。行为正确——原子性
   靠事务回滚成立（四种失败模式 live 复现均为领域表零行 + 任务仍 `running`）；
   问题是声明不准，会误导后续实现者以为存在前置全量校验保证。建议：把表/列
   存在性检查移入前置循环（与第 3 条缓存同一处改动），或改写 docstring 为
   "原子性由事务回滚保证"。

042 的**非目标**（写死，防范围漂移）：不改 035 已冻结的领域不变量与 8 条边界
合同；**不得恢复 D-18 否决的可执行回调形态**；不扩展到 P3/P6a/P8 的消费方
接线。预期零迁移；若最终方案需建表，须先在注册表占号。

**042 开工前须取 Mission Card 批准**；不得在其中恢复 D-18 否决的可执行回调
形态，也不得改动 035 已冻结的领域不变量与 8 条边界合同。

**注册表漂移一并补记**：main 上目录 `041-p5a0-product-version-resolver`
（PR #56）先于注册表行创建，占号规则被绕过；已事后补记该行，042 取下一个
真实空闲号。后续窗口一律先占号再开目录。

### D-2026-07-27-18 · P1.5 领域写通道换为声明式（完成事务收数据不收代码）

第二轮双独立评审在 lease 过期/写权威/限额会计域确认闭合（13 条上轮 findings
12 条 CLOSED），但在 **P1.5 领域写通道**判定 §18 停线并给出两个边界裁决；
业务方 2026-07-27 选 **方案 A**。

**为什么换边界而不是再补一轮**：第一版修法是"可执行回调 + 进程内沙箱"
（句柄语句面拒绝事务控制语句与 `wiki_` 目标表 + 完成事务提交点校验 SAVEPOINT/
外层事务身份）。评审以**公共属性一行**击破：

```text
handle.execute(text("INSERT ...")).connection.execute(text("COMMIT"))
→ 领域行落库、任务仍 running、outbox 空、抛裸 OperationalError
⇒ 过期回收后重放产生第二份领域结果
```

同一套 SQL 文本扫描还**误杀合法负载**：P6a 的 `wiki_page_revisions`、P2b 的
`wiki_releases`、含 `do`/`begin`/`call` 的字符串字面量全被拒。既可绕过又会
误杀 ⇒ 方法错误而非补得不够（024 教训：半个护栏比没有更危险）。根因：**进程内
沙箱化一个持有 DB 句柄的可执行回调不可完成**，句柄逐层可达（Session →
Connection → 语句结果 → …），包一层只把泄漏点推深一层。

**裁决内容**：完成事务 SHALL 收数据、不收代码。`report_success` 的
`domain_write: Callable[[DomainWriteHandle], None]` 改为
`domain_writes: Sequence[DomainWriteSpec]`（表标识 + 列值），由存储层自己执行；
`DomainWriteHandle` 与全部 SQL 文本扫描删除。调用方不再持有任何 DB 句柄，
"提交外层事务"在**接口层面无法构造**——非法状态不可构造，而非构造后检测。
换边界的时点是唯一的：`domain_write` 当时**在生产代码里零消费者**（P3 未实现），
再晚就要连带改 P3/P6a/P8。

**已声明的功能收窄**：声明式通道不支持完成事务内先读后写。需要该形态的领域
逻辑把读与计算移到事务外，或由后续 PR 以显式合同新开入口，**不得恢复可执行
回调**。

**三轮才收敛的账（教训保留，不得删除）**：① 第一版沙箱可绕过（独立评审发现）；
② 换边界后表名用**原样字符串**比对，而 `autoload_with` 在 SQLite 上大小写不
敏感 ⇒ `table="WIKI_JOBS"` 过校验却真的伪造写入 `wiki_jobs`（总控窗口**自攻**
发现，3/3 成功；同一输入在 PostgreSQL 上是 `NoSuchTableError`，即护栏正确性
取决于方言）；③ `values` 仍接受 SQL 表达式对象，`scalar_subquery` 能把自有表
行 ID **读出来写进领域表**（独立评审发现，跨边界信息泄漏）。

**固化规则**：涉身份/授权/表名/列名的**安全比较点必须先规范化再比**
（`strip().casefold()`）并把形状收窄到裸标识符；"数据"必须真的是数据——列值
只接受纯标量，任何可编译成 SQL 的对象一律拒绝。同一条教训在本 PR 内栽了两次，
后续 Pn 实现窗口不得重犯。现三处比较点均有独立攻击集验证（17 个表名变体 +
6 类表达式对象，全部 typed 拒绝、零泄漏、零自有表触碰）。

### D-2026-07-27-17 · 035 实现的 §16.2 行数触发线豁免

035 实现的生产代码为 raw 1781 行 / 有效 1300 行（唯一迁移 200、`__init__`
导出面 89、store 445、outbox 196、models 169、tables 86、metrics 77、
errors 38），超过 033 §16.2 的 ~900 行重新切分警报线。该裁决自 #44 起
一直悬置，本决策予以闭合：**不拆分**。

依据（Spec 侧独立评审给出的算术论证，总控窗口采纳）：

1. §16.2 自带反向约束"不能为了数字把一个原子不变量拆成跨 PR 半成品"。
   P1.1–P1.8/P1.10 是一个不可分事务边界不变量（单领 → lease/fencing →
   attempt/路由 → 完成事务 + outbox 同事务），该部分本身已约 750 有效行；
2. **拆分在算术上不能带来预算合规**：唯一真正可分离的是 metrics（77）与
   dispatcher（约 148），共约 225 行；拆掉后仍约 1075 > 900，只换来两个
   PR 和一段"`wiki_outbox_events` 无人 drain"的空窗；
3. §16.2 明确 900 是**评审触发线**而非正确性门禁，其正确出口是 reviewer
   裁决而非强制拆分；
4. 超出部分构成可审计且多不属 P1 领域逻辑：`__init__` 89 行纯 re-export、
   迁移中约 76 行是为满足仓库既有"被拒绝的降级零 DDL"不变量而重放 0006
   preflight 的机械代码、输入校验约 25 行。

**豁免仅限本窗口，不构成后续 Pn 先例**；后续 Pn 的 Contract Card 仍按
§16.2 的 300–700 目标与 ~900 触发线约束，超线仍须逐案裁决。tasks.md 的
路径预算行同步改为实测值并引用本决策，不得留 TBD。

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
  W1 → P4a → P4c → G0a 冻结 → P5b1 → P5b2 → G0s
    → P6a → P6b → P7 → P8 → P9a → G0b
  ```

- **喂入关键路径的并行道**（启动后前两周铺开）：C0✅ → CAP0✅ → P2a → P5a2
  → P2b/P2c（P2b/P2c 在 P2a 后、是 P6a/P6b/P7/P8 硬前置）；P4b（依赖
  CAP0+P4a，是 P5b1 硬前置——CAP0 输入回收风险因此直接压在关键路径上）；
  P1 规格✅、实现 NOT STARTED（须从最新 main 以新小 PR 提取），P3
  规格✅但实现等 P1；P2d、P5a0、P5a1 并行；G0a 标注草稿与 launch
  容量输入回收同步推进。
- **吞吐假设**：参照 021/023 历史，单个中大 PR（Contract Card + RED→GREEN
  + 双独立评审 + PG 并发测试）约 1–3 个窗口日。
- **里程碑区间估计**（自 C0/W0 启动日起）：Milestone A（至 G0s）约 2–4
  周；Milestone B（至 G0b）约 4–8 周；Milestone C 依赖 W1/P11 Go 侧
  实现人力与实际交付证据，待 W1 实现窗口确认后另估。
- 排期最大风险项：W1 Go 实现人力与周期、G0a 人工标注时长、launch 容量
  输入回收时长。三者都已有并行化预案（见 §8）。

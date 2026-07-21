# 18 · AI Coding 协作机制（人×AI 会话的并行开发规范）

> 与 17 配套：17 讲三个人怎么协作，本文讲**每个人手里的 AI 编码会话**怎么高效并行、互不冲突、不偏离 SDD/TDD 主航道。以下机制全部在本项目 001~007 的多 AI 会话交付中实战验证过（包括踩过的坑）。

## 0. 第一性原理：北极星定方向，仓库留记忆，spec 定合同

AI 会话是无状态的——聊天记录会丢、额度会断（本项目发生过 3 次会话中断）。因此：**每个会话先以 Enterprise LLM Wiki 北极星校准方向**，**一切状态必须落仓库**（代码/文档/HANDOFF/裁决记录），**一切任务必须有 spec**（openspec change 的条款）。做到这三条，任何会话中断都可被任何新会话无损接管，同时不会把项目带回普通 RAG/一次性 pipeline。

## 1. AI 会话生命周期（每次开工照此执行）

```
开工：新会话固定读 CLAUDE.md（自动）→ 北极星设计 → HANDOFF ⓪ → 认领 change 的 specs → 相关权威文档
过程：TDD（spec 条款→测试名引用条款号→实现）；实现中的自主判断写 tasks.md「裁决记录」
收尾：门禁全绿 → 验证 Wiki 核心能力/同快照/告警 → 勾 tasks → validation-report → 更新 HANDOFF → 【人】验收后 commit/push
```

三条硬规则：
- **AI 不碰 git 提交**：commit/push 由人执行——人是合并闸门，这是人对 AI 产出负责的落点（本项目全程如此）；
- **裁决记录强制**：AI 在实现中做的任何设计判断（阈值标定、测试与实现谁对、接口取舍）必须写进 tasks.md——否则决策锁死在会话里，接手者只能猜；涉及受限来源的历史裁决只能留在隔离台账，不能作为新实现输入；
- **中断即固化**：会话断掉（额度/网络），人做的第一件事是把现场提交为 `wip:` commit + HANDOFF 记录进度，再开新会话接管（范例：wip 固化金标现场 `bc1c8db`）。

每个 AI 任务单还必须显式给出：推进的 C1–C7 能力、允许/禁止文件域、生产弱模型边界、输入/输出权威层、失败告警与候选推进停止条件、release 批准不变量、P-1 active alias/过渡可见性、第一方迁移 provenance 与第三方许可证边界。Agent 无权用强模型 fallback；无权绕过 SourceRevision→Claim/Evidence→ChangeSet/Revision→ReleaseSnapshot 直接改生产 Wiki；无权在 P-1 前写普通用户可见 Wiki KB；无权把低置信候选伪装为成功；无权替代 Space 授权人批准生产 snapshot。

## 2. 并发控制：文件域声明制（AI 大 diff 的冲突预防）

AI 产出 diff 大、速度快，事后解冲突代价极高，必须**事前隔离**：

1. 每个 change 的 proposal/specs 必须声明**触碰文件域**（哪些目录/文件会改）；
2. **两个在途 change 文件域相交 → 不并行**：要么串行，要么先拆出共享接口的小 change；复用第一方旧资产必须记录 provenance 并按新 OpenSpec/TDD/Golden 验收，不能把“旧 change 已合入”当作生产质量证明；第三方资产仍须许可证兼容；
3. 共享文件（pyproject.toml / config.py / prompts/ / 迁移编号）：只允许**追加不重排**，PR 描述点名声明；Alembic 迁移编号由 A（平台 Owner）统一发号避免撞号；
4. 给 AI 的任务单里**显式写"不要动 X 目录"**（负面清单和正面清单同样重要——本项目每个开发任务单都带）。

## 3. 质量等化器：门禁而非信任

AI 产出质量有方差，靠门禁拉齐而不是靠"这个模型强"：

- 机器门禁按风险分级：RED/GREEN 只跑精确测试（目标 ≤90 秒）；任务收口跑领域套件（目标 ≤3 分钟）；完整 deterministic 只在 PR ready 与 CI 跑。A 级权限/迁移/发布再加 PG/故障矩阵，B 级模板/抽取/融合加 Golden Slice，C 级 UI/文档/接线只跑契约/smoke；
- 人工验收固定三查：specs 条款是否都有对应测试、边界纪律（17 §4 清单）、裁决记录是否完整；
- **验收者必须独立复跑门禁**，不采信 AI 自报的"全绿"（本项目验收惯例）。

## 4. 任务粒度与合并节奏

- 一个 AI 会话 = 一个 change（或 change 的一段）；**change 设计时就按"一个会话一口气能做完"拆段**（007 四段可拆 PR 是范例）——太大的任务撞额度上限，中断成本高；
- 小步合并：每段全绿即合，主干始终绿；禁止长命分支囤积 AI 大 diff；
- **token 与运行门禁前置**：预估 >10 万 token 的执行任务动工前在 HANDOFF 登记并获业务方确认，且 `NS-RIGHTS=recorded ∧ NS-0=verified ∧ applicable admission=READY`；签名、输入/provenance、不可变 schema/template/model identity、provider probe 与适用预算硬上限/账本还须齐全并运行时复验。之后才可用可恢复 worker/nohup；nohup 绝不是授权。

Reviewer 第一轮必须一次性汇总完整 finding，第二轮只验证关闭；第三轮停止反应式补丁，由总体规划会话裁决拆 PR、改接口或驳回。每个 PR 记录 design/coding/focused-test/review-wait/rework/full-CI/live 七段时间。

## 5. 三人 × AI 的日常形态

| 时机 | 动作 |
|---|---|
| 早（开工前） | 拉主干 → 看 HANDOFF ⓪ 与认领表 → 确认自己 change 的文件域无新冲突 |
| 启动 AI 会话 | 用 §1 生命周期开工；一人可并行多个 AI 会话，但**文件域互斥**（等价于自己和自己也不许冲突） |
| AI 交付 | 人验收（§3 三查）→ commit → PR → 双查合并（17 §2） |
| 收工 | HANDOFF 当天更新（进度/卡点/新坑）；未完成现场 wip 固化 |
| 里程碑 | 16 号文档的收尾三件事 |

## 6. 反模式清单（已付过学费的）

- ❌ 口头/聊天记录里描述需求就让 AI 开写（→ 必须先有 specs）；
- ❌ 两个 AI 会话同时改同一目录"应该没事"（→ 文件域声明制）；
- ❌ 采信 AI 自报测试通过不复跑（→ 独立复跑）；
- ❌ AI 会话里做了关键取舍没写裁决记录（→ tasks.md 强制）；
- ❌ 大批量模型调用不做预算和断点设计（→ token 事故 ×2）；
- ❌ 为追求效果给生产链偷偷接强模型、或模板失败后静默回退为自由生成（→ 必须弱模型 Harness + 显式告警/人工接管）；
- ❌ 把模型/AI 会话的“批准”当作生产 ReleaseApproval，或只批准部分页面就移动 current pointer（→ 每个完整 snapshot hash 必须由 Space 授权人最终批准）；
- ❌ 把第一方与第三方混为一谈（→ LLM-wiki-black 可按 provenance 迁移；nashsu/WeKnora/其他第三方仍按许可证，第一方声明不覆盖第三方代码）；
- ❌ 只完成 WeKnora/基础设施组件，却不能说明它如何推进可消费的 Wiki 闭环（→ 任务暂停并重新对齐北极星）；
- ❌ 让 AI 直接 commit/push 主干（→ 人是闸门）；
- ❌ 按 review 条目补 `if` 就当修完、送复审前不自派红队（→ 同类 bug 反复返工，019 栽了 7 轮；复审前自测 gauntlet + 反复返工问题清单见 [21-selftest-before-submit](21-selftest-before-submit.md)）。

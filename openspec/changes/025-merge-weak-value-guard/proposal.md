# 025 · 合并前置弱值门槛（可证明弱值不开冲突 + informationScore 仅作排序信号）

> 状态：**提案二版（2026-07-18，按 codex PR #17 复审收口重构：抑制=有资格前提的裁决，非中性过滤）**。轨道 L6 治理（见 docs/insurance-kb/22）。
> 依赖：007 主链（合并/冲突语义）、018（PR #9 已合入 main，2026-07-17）、**021（规格已提出、尚未实现）——实现排在 021 之后**（合并策略接线点在 `knowledge/merge.py`，且 G8 锁序依赖 021 的 per-source lock 语义定稿）；提案与规格即刻定稿。
> 设计权威：007 mainchain（K2/K3 合并与裁决序）、docs 03（§6.2 高风险清单、§8 表清单权威）、LLM-wiki-black PROJECT_HISTORY Q026、024 的弱值/兼容性护栏（抽取侧对称防线）、21（复审前自测）。

## 为什么做

007 K2 已规定「低权威新值只进 conflict 记录，不 supersede」，但它按**权威序**裁决，未处理**信息量**维度：一个与已发布值**同权威、但更粗略**的新候选（如已发布「犹豫期为 15 天」，新抽到「有犹豫期」）仍会开 conflict → 生成 ReviewItem。真实弱模型批量重抽会持续产出这类"更粗略"的同权威值，**审核队列（008）被垃圾冲突淹没**——这正是 LLM-wiki-black 的 Q026 历史踩坑。

**第一性原理（二版修正）**：不开 conflict、不落 Claim、直接 drop **本身就是一次裁决**——它判定"旧值胜、候选永不进入裁决链"。因此抑制的前提是：①候选在更高优先级裁决维度（权威、生效时间、高风险强审、三态语义）**不可能胜出**；②"更弱"是**可证明的偏序关系**，不是启发式分数比大小；③被抑制的观察在基线失效后**可恢复**；④审计与丢弃**原子**。任何一条做不到 → fail-open 回 007（宁可多开一次审，绝不静默吞可能有效的值）。

## 做什么

1. **抑制资格前提（G1 E1~E5）**：双方 value_state 均 present；非高风险、无 pending_judge；候选权威不高于基线；同权威时生效区间完整且相等（否则生效时间裁决权还给 007 K3.2 ②）；基线为当前 published 且提交前锁内复核同 revision。任一不满足 → 不抑制。
2. **可证明弱化偏序（G2）**：`SpecificityRelation = strictly_weaker | equivalent | stronger | incomparable`，由 schema/value-type/predicate 级**版本化比较器**给出（附 rule_id）；自由文本默认 incomparable，仅白名单可证明关系（存在性=量化投影、枚举父子、严格子集投影）可判弱。与 informationScore（仅 008 排序信号）**彻底分离**——标量全序表达不了"不可比"，不得当语义证明用。
3. **SuppressedObservation + append-only 审计（G5，迁移 0011）**：抑制不丢观察——保存候选完整快照 + Evidence/来源身份 + 基线 claim/revision + 双方权威/生效区间 + 判定依据（特征向量/两分/comparator_version/rule_id）；唯一约束 exact-once；服务层与 DB 权限双层 append-only。
4. **可恢复生命周期（G7）**：基线 supersede/retract/stale → active 观察重新进入裁决；观察自身来源删除 → invalidation，不复活。防"强值来源删除后，仍有效的弱观察随之丢失"。
5. **事务与并发（G8）**：claim business key advisory/row lock（021 per-source lock 不覆盖跨来源同键并发）；锁内复核基线；审计写入与 drop 决定同一事务，写失败整体回滚或 fail-open；PostgreSQL 双会话验收（suppress-vs-supersede/retract、重试、审计故障注入）。
6. **008 消费合同（G9）**：informationScore + comparator_version 持久化（被抑制→observation；进 007→decision_basis 附加），008 W1.1 排序读持久化值不重算；抑制计数只读 API（Space 强制）。

## 不做什么

- 不改 007 的权威序/裁决/supersede 语义（除 G1 资格内枚举的抑制情形外，K2/K3 一字不改）；
- 不用 informationScore 做替换/supersede/抑制判据（G6：防其成为绕过权威序的后门）；
- 不碰抽取侧弱值/兼容性护栏（归 024，已交付）；
- 不做 `data_quality` 字段持久化（归 026）；
- 不静默丢值——任何抑制都留可恢复的 SuppressedObservation + append-only 审计（可计数、可复盘、可重评）。

## 影响

文件域（二版按 codex 复审扩展至自洽）：`harness/src/insurance_harness/knowledge/merge.py`（资格校验+比较器接线，K2 判定前）+ `knowledge/tables.py`（suppressed_observations ORM，docs 03 先行）+ `knowledge/models.py`（SpecificityRelation/observation 领域模型）+ `knowledge/` 只读查询 API（抑制计数/明细）+ 迁移 **0011**（含迁移测试）+ `docs/insurance-kb/03-knowledge-model.md` §8 表清单修订（**本 PR 已先行完成**，遵守 tables.py"文档先改"合同）+ 008 W1.1 消费口径（经 decision_basis 持久化分数，008 侧无表变更）。**实现排在 021 之后**（021 规格已提出、尚未实现；018 已随 PR #9 合入）；与 024（`compiler/`）文件域不相交。迁移号 0011 已在 `openspec/changes/README.md` 占号。

# 025 · 合并前置弱值门槛（更粗略新值不开冲突 + informationScore 仅作排序信号）

> 状态：**提案（2026-07-17，已条款化，可认领）**。轨道 L6 治理（见 docs/insurance-kb/22）。
> 依赖：007 主链（合并/冲突语义）、018/021 的 knowledge 域基线——**实现排在 021 之后**（合并策略接线点在 `knowledge/merge.py`，PR #9 合入后开工）；提案与规格即刻可写。
> 设计权威：007 mainchain（K2 合并语义）、LLM-wiki-black PROJECT_HISTORY Q026、024 的弱值/兼容性护栏（抽取侧对称防线）、21（复审前自测）。

## 为什么做

007 K2 已规定「低权威新值只进 conflict 记录，不 supersede」，但它按**权威序**裁决，未处理**信息量**维度：一个与已发布值**同权威、但更粗略/信息量更低**的新候选（如已发布「等待期为 90 天」，新抽到「有等待期」）仍会开 conflict → 生成 ReviewItem。真实弱模型批量重抽会持续产出这类"更粗略"的同权威值，**审核队列（008）被垃圾冲突淹没**——这正是 LLM-wiki-black 的 Q026 历史踩坑。

024 在**抽取侧**建立了弱值/兼容性护栏（垃圾值不入 pred）。025 是**合并侧的对称防线**：即便一个更粗略的值入了 pred，合并时也不得用它开冲突骚扰人审。两侧同一第一性原理——**护栏必须 fail-safe，只拦明确的垃圾，绝不误伤更优值**（024 gauntlet 教训：只测拒绝侧、不测接受侧的半个护栏比没有更危险）。

## 做什么

1. **informationScore 确定性判据**：对同 `(product_version_id, predicate)` 的两个值给出确定性、零模型的信息量比较（长度、数值/枚举/单位等具体性信号、结构完整度）；比较结果**可审计**（两值 + 两分 + 判定入事件）。
2. **弱值不开冲突门槛**：新候选相对当前 published Claim **严格更弱**时，合并 SHALL NOT 开 conflict、SHALL NOT 生成 ReviewItem、SHALL NOT 落新 Claim——记一条 append-only **抑制事件**（含两值/两分/原因）后丢弃。
3. **fail-safe 边界（核心）**：只抑制**明确更弱**；信息量**相等或不可比或不确定** → **不抑制**，照 007 走原冲突/合并（宁可多开一次审也不静默吞掉可能更优的值）；缺 published 基线、informationScore 不可计算 → **不抑制**（fail-open 到既有合并，绝不因门槛计算失败丢值）。
4. **与权威序正交**：门槛只作用于**同权威或更低权威**候选；**更高权威**新值照 007 K2 走 supersede（权威胜过信息量——高权威的更正即便更粗略也是合法修订），门槛 SHALL NOT 抑制它。
5. **informationScore 仅作排序信号，非替换判据**：informationScore SHALL NOT 触发 auto-supersede（替换仍 100% 权威/裁决驱动，007 K2 不变）；仅作为 008 工作台的**排序/优先级**信号暴露（W1.1 可选信号），且抑制计数可在 008 展示（"本批抑制 N 条更粗略值"）。

## 不做什么

- 不改 007 的权威序/裁决/supersede 语义（门槛是**冲突前置过滤**，不是新的替换路径）；
- 不用 informationScore 做替换/supersede 判据（防其成为绕过权威序的后门）；
- 不碰抽取侧弱值/兼容性护栏（归 024，已交付）；
- 不做 `data_quality` 字段持久化（归 026）；
- 不静默丢值——任何抑制都留 append-only 审计事件（可计数、可复盘）。

## 影响

文件域：`harness/src/insurance_harness/knowledge/merge.py`（合并策略接线点，K2 冲突判定前插入门槛）+ 新迁移 **0011**（抑制事件表，append-only）+ `knowledge/` 只读查询暴露抑制计数给 008。**实现排在 021 之后**（依赖 018/021 的 source/snapshot 基线）；与 024（`compiler/`）文件域不相交。迁移号 0011 已在 `openspec/changes/README.md` 占号。

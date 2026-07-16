# 024 · 抽取召回提升（extract_empty 主攻 + 值粒度对齐）

> 状态：**提案（2026-07-16，已条款化，可认领）**。轨道 L5（见 docs/insurance-kb/22），零真实模型调用，即刻可从 main 开工。
> 设计权威：005 validation-report（归因清单=本 change 的工单来源）、04（管道结构）、11（模板/表格）、21（复审前自测）。

## 为什么做

004+005 建立的真实弱模型基线（deepseek-v4-flash，micro F1 0.216@v2）已把失分归因到两大主因：**extract_empty 漏抽**（约 24 条，005 归因工单有全量明细）与**值粒度/表述差异**（约 54 条，尺子 v2 修正后凸显的真实抽取缺口）。这是产品质量的主战场，且 005 已给出逐条工单——改进空间明确、可回放验证，不需要等真实模型预算。

## 做什么

1. **归因工单 → RED 回放用例**：把 005 归因清单逐条固化为 fixture 驱动的失败用例，改进使其转绿（回放既有模型响应，零新调用）；
2. **prompt 变体机制**：字段组级 prompt 变体注册（配置化、确定性选择、变体标识入 pred 元数据供审计）；
3. **定向补漏增强**：针对 extract_empty 字段的第二轮定向提问模板，复用既有 gapfill 链与 evidence 回验（反幻觉门槛不降）；
4. **值粒度对齐指引**：按金标粒度惯例的字段级抽取指引并入 prompt 变体（不改 pred schema、不动尺子）；
5. **fixture 回归合同**：3 基线产品 replay 分数不降，纳入 deterministic 门禁；
6. **抽取侧弱值/兼容性护栏**（LLM-wiki-black A10 承接，2026-07-16 代码级审计确认为唯一未迁移真空）：`WEAK_UNACTIONABLE`/`REFERENCE_ONLY` 两族清洗模式 + 字段-值语义兼容性校验（Q012/Q026 历史 bug 固化为回放用例）。

## 不做什么

- 不调真实模型（真实 13 产品 before/after 回归由 **020 D4** 承接，本 change 交付改进与回放证据）；
- 不动 cleaning 白名单（005 已证 cleaning_kill=0）、不碰 goldenset/ 尺子、不碰 knowledge/；
- 不做 PP-StructureV3 接入（B9 部署型任务独立）；
- 不做合并侧"更粗略新值不开冲突"门槛与 informationScore 审核排序信号（前者归 025，后者归 008 W1.1 可选信号——文件域边界）。

## 影响

文件域：仅 `harness/src/insurance_harness/compiler/`（extract/gapfill/prompts/pipeline 接线点；routing 关键词表允许按 005 先例补充）。无迁移。与轨道 L1–L4 文件域不相交。

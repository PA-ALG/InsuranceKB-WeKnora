# 024 · 抽取召回提升（extract_empty 主攻 + 值粒度对齐）

> [!CAUTION]
> **“软件完成”仅是历史测试状态；当前 production-disabled。** 本 change 继承的 004 路径属于可审计第一方资产，但必须按 provenance 迁移到 028；027 完成运行时硬封且 030 MVP 或 020 canonical 的适用 admission READY 前，不得运行或宣称真实提准。

> 状态：**软件实现完成（2026-07-21，PR #13 为集成载体）**。轨道 L5（见 docs/insurance-kb/22）；本 change 的软件验证零真实模型调用，真实效果结论仍由 020 D4 承接。
> 设计权威：005 validation-report（归因清单=本 change 的工单来源）、04（管道结构）、11（模板/表格）、21（复审前自测）。

## 为什么做

004+005 建立的真实弱模型基线（deepseek-v4-flash，micro F1 0.216@v2）已把失分归因到两大主因：**extract_empty 漏抽**（约 24 条，005 归因工单有全量明细）与**值粒度/表述差异**（约 54 条，尺子 v2 修正后凸显的真实抽取缺口）。这是产品质量的主战场，且 005 已给出逐条工单——改进空间明确、可回放验证，不需要等真实模型预算。

## 做什么（零调用交付 = 机制 + 版本化 + 护栏 + 确定性回归框架）

> **证明力边界（2026-07-16 二版，按 PR #11 复审收紧）**：`ReplayClient` 以 prompt 哈希为 fixture key，prompt 一变旧录制即失效——因此本 change 的零调用测试只证明**编排/解析/护栏合同**，不证明模型因新 prompt 抽得更好；真实召回改善只能由 **020 D4** 固定模型/样本/预算 A/B 证明。金标只作测试评分，不进任何生产触发条件。

1. **归因工单 → 机制合同回放用例**：005 归因清单逐条固化为 fixture 用例，断言"该场景触发定向补漏、产出经回验候选或显式 unknown"的机制行为（RED→GREEN；人工构造的新响应只证编排合同）；
2. **prompt 变体机制**：字段组级变体注册（配置化、确定性选择、**版本化标识**入 pred 元数据——020 A/B 以此对账）；
3. **定向补漏增强**：触发条件 **schema 驱动**（必填/期望字段 + 空/unknown/source_pointer + 候选章节 + 预算），复用既有 gapfill 链与 evidence 回验（反幻觉门槛不降）；
4. **值粒度对齐指引**：字段级抽取指引并入变体机制（不改 pred schema、不动尺子；效果由 020 D4 评分）；
5. **后处理机制合同**：冻结 synthetic fixture 的清洗/兼容性/解析/编排行为并钉住 request key；它不构成真实非退化证据。真实同录制集 differential replay 明确留在未完成的 **020 D4b**；禁止用人工新 fixture 分数暗示提升；
6. **抽取侧弱值/兼容性护栏**（LLM-wiki-black A10 承接，2026-07-16 代码级审计确认为唯一未迁移真空）：`WEAK_UNACTIONABLE`/`REFERENCE_ONLY` 两族清洗模式 + 字段-值语义兼容性校验（Q012/Q026 历史 bug 固化为回放用例）。

## 不做什么

- 不调真实模型（真实 13 产品 before/after 回归由 **020 D4** 承接，本 change 交付改进与回放证据）；
- 不动 cleaning 白名单（005 已证 cleaning_kill=0）、不碰 goldenset/ 尺子、不碰 knowledge/；
- 不做 PP-StructureV3 接入（B9 部署型任务独立）；
- 不做合并侧"更粗略新值不开冲突"门槛与 informationScore 审核排序信号（前者归 025，后者归 008 W1.1 可选信号——文件域边界）。

## 影响

文件域：`harness/src/insurance_harness/compiler/`、`harness/src/insurance_harness/schemas/`、对应测试与本 change 文档。每个 run 新增本地 `llm-attempts.sqlite` 事实账本；无 Alembic/业务数据库迁移。与轨道 L1–L4 文件域不相交。

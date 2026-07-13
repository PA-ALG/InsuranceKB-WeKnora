# 002 附录 · gs-v0.1 标注执行方案（T8 Runbook）

> 金标 = 最强模型（Claude）直读文档。本次执行不经 API 网关（生产网关里暂无 Claude 通道），而是由 Claude Code 会话内的 agent 直接标注：**每个产品一个标注 agent**，读原始 PDF → 按 schema 逐字段产出 GoldenRecord JSONL → 交给 002 子系统的确定性管线（引文回验 → meta 比对 → disputed 标记 → release 打包）。子系统的 LiteLLM 通道保留，未来网关接入 Claude 后可无人化重跑。

## 流程

1. 主会话用 002 的 CLI 导出每个产品的"标注工单"：险种 schema 字段清单（含 field_id/说明/取值示例/allowed_sources）+ 三份 PDF 的分页文本；
2. 并行启动 13 个标注 agent（每产品一个），指令要点：
   - 只依据文档内容，逐字段给出 value / tri_state / evidence(page+quote)；
   - quote 必须逐字摘自原文（供字符串回验）；找不到线索 = unknown，明确排除 = absent_explicitly + 依据；
   - 禁止用常识补值；费率表数字只抽"典型示例"字段要求的内容；
   - 输出严格 JSONL（GoldenRecord 字段）；
3. 主会话汇总 → 跑 `verify`（回验 + product_meta 比对）→ disputed 清单 → `build_release gs-v0.1`；
4. 回验失败率 > 5% 的产品退回重标（agent 会拿到失败明细）；
5. manifest 记录 annotator_model = 会话模型标识；gs-v0.1 目录不可变。

## 质量护栏

- 三态判定是重点审查项：**"文档没写"与"文档写了不含"必须区分**；
- 与 product_meta.json 冲突一律 disputed，不由标注方自行裁决；
- disputed 清单随 release 交付，等待人工复核通道（本阶段仅留存）。

## 产出

`dataset/goldenset/gs-v0.1/`：13 个 per-product JSONL + manifest.json + disputed.jsonl + eval 自洽性报告（金标 vs 金标 = 满分）。

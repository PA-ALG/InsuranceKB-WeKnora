# 002 · 金标与评估子系统（S0）

## 为什么做

一切抽取质量的衡量都依赖金标（05-golden-set-eval.md）：没有金标，弱模型 harness 的迭代就没有方向盘。业务方已拍板：金标 = Claude（最强模型）直读文档产出，独立可持续维护的 Agent 子系统。样本语料已就位（`dataset/shouxian_product/`，13 产品 × 条款/说明书/费率表 + product_meta.json）。

## 做什么

1. `insurance_harness/goldenset/`：金标注 Agent——
   - 直读原始 PDF（**不走 chunk**，避免切片失真；PDF→文本用 docreader 或本地解析，页码保留）；
   - 按 schema 注册表（07 基线 v1 + v1.1 扩展）逐字段产出：值 + 三态判定 + 证据（页码+原文摘录）；
   - 自检 pass：引文回原文字符串校验、schema 校验、置信标注（sure/disputed）；
   - `product_meta.json` 作为产品主数据字段（planCode/versionNo/备案文号/销售状态/生效日期）的 ground truth，标注结果与之比对，冲突项标 disputed；
2. 金标数据管理：`dataset/goldenset/gs-v0.1/` 版本化存储（JSONL，每条含 product/doc/field/value/tri-state/evidence/annotator-model/时间）；
3. eval runner（`goldenset/eval.py` + CLI）：输入任意抽取结果（同 schema 的 JSONL），输出字段级 P/R/F1、三态混淆矩阵、evidence 准确率、幻觉率，指标口径按 05 §5；产出 markdown 报告；
4. schema 注册表首个可执行形态：`src/insurance_harness/schemas/` 加载器——读取 docs/insurance-kb/schema-baseline/*.yaml + extensions-v1.1.yaml，合成带元属性的运行时 schema（Pydantic）。

## 不做什么

- 不做人工复核 UI（接口预留 disputed 队列即可）；不做合并/冲突类金标（S3 前补）；不做端到端问答金标（依赖发布链路，S3 后）。

## 影响面

- 新增 `goldenset/`、`schemas/` 两个包的实现（001 里是占位）；新增 `dataset/goldenset/`；
- 模型调用：Claude 经模型网关（08 选型）；金标 release 记录模型版本（08 §3）；
- 硬边界不受影响（纯 harness 内）。

## 验收（细则见 specs/）

- 13 产品全部产出 gs-v0.1；每个字段标注都带证据且引文回验通过率 100%（回验失败的必须标 disputed 而非静默保留）；
- 与 product_meta.json 可比对的字段（≥5 个）一致率报告产出；
- eval runner 对"金标 vs 金标"自评得满分（口径自洽性检查）。

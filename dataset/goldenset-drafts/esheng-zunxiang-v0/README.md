# esheng-zunxiang-v0 — Golden Product 金标标注 DRAFT

**状态：DRAFT，非权威，非验收基准。** 仅供 schema 内容评审校准与标注子系统（G0a+）开发自用。

- 产品：平安e生保（尊享版）医疗保险（planCode 596 / 596-1，Golden Product，033 §14.1）
- Schema：golden-product-medical-schema-v0 (DRAFT; branch draft/golden-product-schema-content, PR #43) —— 71 字段全量标注（base 35 + medical 24 + extensions 12），含三态，无选择性标注
- 决策锚：
  - **D-2026-07-26-4**：金标标注起草立即启动；**正式冻结待 P4c/P5a2**。本目录一切内容在冻结前不得作为验收 holdout、发布依据或 SchemaVersion 内容。
  - **D-2026-07-27-9（G0a+ 标注子系统形态）**：最强可用模型标注 + 确定性校验（引文逐字回验/类型/覆盖），人工只复核 分歧+高风险+抽样。本 bundle 即该形态的第一次产出：模型侧与确定性校验已完成，人工复核队列见 verification-report.md §5/§6。
- 取代关系：在本产品上 **supersede** dataset/goldenset/wip-gs-v0.1/平安e生保（尊享版）医疗保险/（旧 60 字段种子）；旧种子保留仅作对比。
- 标注模型：claude-fable-5（claude-session 形态；HARNESS_JUDGE_MODE=claude-session。仓内 API-key 模型仅 deepseek-v4-flash/pro，非最强档，未用于标注）
- 校验：harness goldenset.normalize.quote_in_page 逐条回验；报告见 verification-report.md

## 文件

- `annotations.jsonl` — 71 行，每字段一条：value / tri_state / evidence（doc+page+逐字引文）/ confidence / reasoning / flags / schema 元数据
- `verification-report.md` — 覆盖 71/71、引文回验率、类型/枚举一致性、meta 对账、与旧种子分歧清单（=人工复核队列）、高风险字段清单

## 使用纪律

1. 三态：unknown ≠ absent_explicitly；absent_explicitly 一律自带证据（含结构性负证据者已标 flag 待裁决）；unknown 一律空证据，绝不伪造引文。
2. 本 DRAFT 的分歧/低置信/高风险条目是人工评审输入，不是结论；专家裁决后回写并留痕。
3. 禁止将本目录用于生产写入、发布或对外口径；禁止作为验收 holdout（防评估泄漏）。

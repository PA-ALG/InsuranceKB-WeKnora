# 产品知识 Schema 业务权威

本目录保存业务方提供并批准公开入库的原始字段工作簿：

- 文件：[`产品知识库字段标签维度-20240205.xlsx`](产品知识库字段标签维度-20240205.xlsx)
- SHA-256：`5cd0ed8af0bc10fec488d0d83e8e28c7c0d64408c4fc25cca92b2a365355fdb6`
- 入库方式：保持原始 bytes，不重建、不清理截图、不改写水印
- 公开披露确认：业务方已明确批准原始文件整体公开入库；因此原文件内嵌截图、
  水印及文档属性（包括 `lastModifiedBy=DAIWENWEN003`）均未做脱敏改写

它是字段名称、字段含义、取值来源以及截图所示抽取语义的业务权威。截图用于说明
字段应从产品说明书或条款的哪些区域、表格列、条件和计划层级中抽取；截图中的
示例值不是任何具体产品的 Golden 答案。

## 与现有 YAML 的关系

工作簿的八张结构化字段表已逐行核对；字段顺序与规范化后的五列内容均一一对应
（原始工作簿中的空白/换行仍以本目录 exact XLSX 为准）：

| 工作表 | 字段数 | 对应机器可读基线 |
|---|---:|---|
| 基础字段 | 35 | `../schema-baseline/base.yaml` |
| 医疗险 | 24 | `../schema-baseline/medical.yaml` |
| 重疾险 | 18 | `../schema-baseline/critical-illness.yaml` |
| 意外医疗险 | 22 | `../schema-baseline/accident-medical.yaml` |
| 意外险 | 14 | `../schema-baseline/accident.yaml` |
| 寿险 | 23 | `../schema-baseline/term-life.yaml`、`whole-life.yaml` |
| 年金险 | 22 | `../schema-baseline/annuity.yaml` |
| 专业术语目录 | 3 | `../schema-baseline/glossary.yaml` |

现有医疗险注册表中有 60 个可抽取字段：49 个直接来自本工作簿（基础字段 33 个、
医疗险字段 16 个），另 11 个来自后续已登记的 v1.1 扩展。两者必须在 Golden
制品中保持可区分；后续扩展不会因为被抽取或标注而变成本工作簿的字段。

`endowment.yaml`、`long-term-care.yaml`、`supplementary-pension.yaml`、
`disability-income.yaml` 以及 `extensions-v1.1.yaml` 不在本工作簿中。它们作为
后续已登记内容原样保留，权威来源和后续对账另行治理；本次不删除、不重写，也不
修改运行时 registry 的内容哈希。

## 与 Golden Set 的关系

Golden Set 始终按完整产品字段集维护。S0-Q 只从冻结且获批的完整 Golden 中投影
四条诊断记录，不得创建或维护一套独立的“四字段 Golden”。

当前 `dataset/goldenset/wip-gs-v0.1` 中目标医疗产品已经覆盖 60/60 个当前可抽取
字段，但它仍是历史 WIP 覆盖证据，不自动等于当前获批 Golden。后续独立 Golden
Mission 应使用 `gpt-5.6-sol` 对全部 60 个字段进行统一候选生成或复核，完成
Evidence 回验与既定人工批准，并形成不可变 artifact identity/digest。强模型输出
是候选，不替代证据和人工批准。

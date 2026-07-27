# Schema 内容草案（Golden Product 医疗险）— DRAFT，非权威

> **状态：DRAFT。本目录一切内容均无权威性**：不是 SchemaVersion、不是抽取模板、不是发布依据；
> 未经保险领域专家评审并按 G0a 流程冻结前，任何管道、模板、金标不得引用。
> 基线文件（`../schema-baseline/*.yaml`）本次**未做任何改动**。

- 决策锚点：**D2=B + D11=A（2026-07-27 裁决）** —— 仅做内容起草供专家评审；不写代码、不做迁移。
- Golden Product：**平安 e 生保（尊享版）医疗保险**（033 §14.1；`dataset/shouxian_product/平安e生保（尊享版）医疗保险/`，含 保险条款.pdf / 产品说明书.pdf / 费率表.pdf / product_meta.json）。

## 文件

| 文件 | 内容 |
|---|---|
| `golden-product-medical-schema-v0.yaml` | 医疗险切片全部 71 字段的逐字段语义合同草案（基础 35 + 医疗 24 + 适用扩展 12）：field_id、类型、枚举草案、三态口径、风险等级、required qualifiers、comparator、provenance 映射、可发布性、抽取定位、专家问题 |
| `golden-product-glossary-seed-v0.yaml` | 本产品相关概念词表种子 57 条（含吸收 `glossary.yaml` 旧 3 条：就医绿通、费用垫付，其他增值服务拆为 在线问诊/优惠体检/药品补贴）；定义全部为通用领域草案，未对本产品作事实断言 |

## Owner 工作流（冻结路径）

1. **专家评审**：保险领域专家 + 业务方逐字段/逐概念评审——重点是每条 `expert_questions`、
   高风险族边界、枚举闭集、required qualifier 集合、三态 `absent_explicitly` 判据。
2. **修订留痕**：接受/修改/降级/移除均需留痕（v1.1 纪律：降级或移除需留痕；金标修订需独立业务 reviewer receipt，033 §14.1 防刷规则）。
3. **冻结**：G0a 检查点将评审通过的内容物化为 **P5a1 SchemaVersion registry** 内容
   （SchemaVersion content hash、逐字段 comparator/canonicalizer version、required qualifier 集），
   同时冻结全字段三态标注与 evaluator（033 §14.1 G0a 冻结清单）。冻结之前本目录始终是 DRAFT。

## MVP 可发布性与覆盖率（诚实口径）

**`provenance_class` 为 `derived` / `external_sync` / `human_attestation` / `undefined` 的字段一律
`mvp_publishable: false`**，依据 033：

- §8.1：可发布事实只允许三种封闭 provenance kind（`source_evidence` / `human_attestation` / `external_attestation`）。
  基线「人工填充」列**不是**带不可变 receipt 的 HumanAttestation，「官网同步/口袋E/产品芯/核保数据」列**不是**
  受控 connector 的 ExternalAttestation——在相应基建与流程建立之前，这些字段没有合法的发布通道。
- §10.5：计算/推导结论本轮不升级为可查询事实（需要另立 `DerivationEdge + transformation_version` 设计），
  因此 `derived` 字段整体出局，只能作带引用的页面表现。

**对本产品的覆盖率影响（诚实数字）**：71 个字段中仅 **29 个（40.8%）** 今天能从文档证据发布；
23 个高风险字段中有 **4 个不可发布**（`waiting_period` 取值来源空白、`zero_deductible` /
`social_security_unrestricted` / `indemnity_principle` 卡在人工填充）——而 G0a 要求**全字段**闭合三态标注，
这 4 个口子不解决，G0a 无法冻结。费率表.pdf 目前没有任何字段锚定（见 `fees` 字段问题）。

## 取值来源映射是机械草案

`取值来源 → provenance_class` 按固定规则机械映射（规则见 schema YAML 头部 `conventions.provenance_mapping`），
**不构成业务判断**。共 **18 个 `undefined` 行，每一行都需要业务给出答案**（字段清单见下）：
险种简称、险种名称、开始使用时间、结束使用时间、产品类别、产品类型、销售渠道、发布外网、销售状态、
主附加险、**等待期**、宽限期、费用、退保率、理赔件数、理赔金额、犹豫期及合同解除（退保）、投保范围。
其中多数几乎可确定应锚定条款/说明书（改锚提案已写入相应字段的 `expert_questions`，采纳需留痕）。
另有多字段（不限社保、补偿原则、增值服务、高端医疗等）提出了「人工填充 → 条款证据」的改锚问题，
采纳与否直接改变上表覆盖率。

## 统计

```text
字段总数:            71（base.yaml 35 + medical.yaml 24 + extensions-v1.1 适用 12）
  其中 1 个（reduced_paid_up）预判不适用于本产品（短期形态），待专家确认留痕

provenance_class 分布:
  source_evidence     29  (40.8%)   → mvp_publishable=true
  undefined           18  (25.4%)   → 全部需业务答复
  human_attestation   10  (14.1%)
  external_sync        7   (9.9%)
  derived              7   (9.9%)

高风险字段 (high_risk=true):  23（其中可发布 19；不可发布 4：waiting_period /
                              zero_deductible / social_security_unrestricted / indemnity_principle）
枚举草案字段:                 20（enum_status 区分 closed_draft_from_baseline / open_draft；
                              另有 3 个 enum_status=undefined 需受控目录）
required_qualifiers 非空字段: 11（等待期/免赔额/给付限额/报销比例 等）
expert_questions 总数:        71 条（66/71 个字段至少 1 条）

词表种子: 57 条（high 22 / medium 26 / low 9），全部 definition_draft 待专家确认
```

## 起草约定（评审时请对照）

- 类型→comparator 规则、三态口径、风险族草案边界、qualifier 语义均写在 schema YAML 头部 `conventions` 块。
- 高风险族按任务口径起草：豁免/等待期/除外(免责)/理赔限制/给付比例，并将「责任存在性」（癌症医疗、
  津贴、保什么）草案性并入给付族——**族边界本身是待专家裁决的问题**；extensions-v1.1 已带业务确认
  risk_level 的字段按原值保留。
- `text_long` 一律 `comparator_class: text_keypoints_unknown`：运行时 comparator 恒返回 `unknown` → 人工复核
  （033 §8.2 comparator 三态）。
- 所有枚举草案只来自基线取值列或明确标注的推断（`enum_status: open_draft`），未对本产品的具体取值作任何断言。
- 定义类内容（词表）为通用保险领域知识，逐条标注应锚定的权威位置（条款定义节/监管定义/行业通识）。

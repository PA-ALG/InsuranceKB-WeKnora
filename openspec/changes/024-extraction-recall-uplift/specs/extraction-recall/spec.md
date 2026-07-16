# 024 抽取召回提升验收规格

## ADDED Requirements

### Requirement: E1 改进必须由归因工单的回放用例驱动且零真实模型调用

005 归因清单中每条 extract_empty 工单 SHALL 固化为一个 fixture 驱动的 RED 回放用例（用例名引用工单标识）；本 change 全部测试 SHALL 进 deterministic lane，零真实模型调用；真实 13 产品回归 SHALL 显式让渡给 020 D4。

#### Scenario: 归因工单固化为回放用例

- **WHEN** 005 validation-report 归因清单中的一条 extract_empty 工单被纳入本 change
- **THEN** 存在一个以该工单标识命名的回放用例（fixture 化模型响应 + 期望字段）
- **AND** 改进落地前该用例为 RED，落地后转绿

#### Scenario: 未解决工单不得静默跳过

- **WHEN** 某条工单在本 change 结束时仍未转绿
- **THEN** validation-report 逐条列出该工单与未解决原因
- **AND** 对应用例以显式标记保留（不删除、不伪绿）

### Requirement: E2 prompt 变体机制必须确定性且可审计

字段组级 prompt 变体 SHALL 有单一权威注册表（配置化）；同一输入的变体选择 SHALL 确定性（无随机）；每次抽取的 pred 元数据 SHALL 记录所用变体标识（版本化）；变体 SHALL NOT 改变 pred 输出 schema。

#### Scenario: 变体选择确定性与审计标识

- **WHEN** 同一文档段与字段组重复运行抽取
- **THEN** 两次选中同一 prompt 变体
- **AND** pred 元数据含该变体的版本化标识

#### Scenario: 未注册字段组回落默认 prompt 零漂移

- **WHEN** 字段组未在变体注册表登记
- **THEN** 使用既有默认 prompt，既有回放用例输出逐字不变

### Requirement: E3 定向补漏不得降低反幻觉门槛

针对 extract_empty 字段的第二轮定向提问 SHALL 走既有 gapfill 链路与预算控制；补漏结果 SHALL 过 evidence 回验（引文对不上原文即打回），置信分级沿既有语义。

#### Scenario: extract_empty 字段二轮定向提问

- **WHEN** 首轮抽取对某字段返回空且该字段在金标为 present
- **THEN** gapfill 以定向模板（判断题/短答）发起第二轮提问（回放 fixture 驱动）
- **AND** 命中结果带 evidence 且通过回验后才计入 pred

#### Scenario: 回验打回不放宽

- **WHEN** 补漏返回的引文与原文对不上
- **THEN** 该值被打回不入 pred（004 反幻觉回归用例保持全绿）

### Requirement: E4 值粒度指引只经变体机制注入且不改数据契约

对 005 归因的值粒度缺口字段，SHALL 提供字段级"按条款原文粒度抽取"指引文本并入 E2 变体机制；SHALL NOT 修改 pred 值格式、goldenset/eval 尺子与 keypoints。

#### Scenario: 值粒度指引生效且契约不变

- **WHEN** 值粒度缺口字段经带指引的变体重新回放
- **THEN** 对应值粒度工单用例转绿
- **AND** pred schema 与 eval 尺子文件无任何改动（diff 为零）

### Requirement: E6 抽取侧弱值与字段-值兼容性护栏（LLM-wiki-black A10 承接）

cleaning SHALL 增补 `WEAK_UNACTIONABLE`（"以合同为准/按合同约定/需核对条款"类）与 `REFERENCE_ONLY`（"见第X条/详见附表"类）两族模式，命中即按既有三态语义转 `unknown`/`source_pointer`，不作为值入 pred；pred 侧 SHALL 增加字段-值语义兼容性校验（同名/近名字段辨析），不兼容的值 SHALL NOT 入 pred（转 unknown 并记录拒绝原因）；旧项目 Q012/Q026 历史 bug SHALL 固化为 RED 回放用例。合并侧的"更粗略新值不开冲突"门槛 SHALL NOT 在本 change 实现（归 025，文件域边界）。

#### Scenario: 弱值文案不冒充事实

- **WHEN** 抽取返回"以合同为准"或"按合同约定"类文案
- **THEN** 该字段按 `unknown` 处理、不入 pred
- **AND** 既有约 30 条占位清洗模式的回放输出零漂移

#### Scenario: 引用型文案转来源指针

- **WHEN** 抽取返回"见第 X 条 / 详见附表"类文案
- **THEN** 按 `source_pointer` 语义处理（供补漏 pass 定向追抽），不作为值入 pred

#### Scenario: 同名近名字段辨析（Q012 历史 bug）

- **WHEN** 返回值与目标字段语义不兼容（夹具复现旧项目 bug：如"退保费用"说明文案回填"费用"类字段、"投保年龄"混入职业类别、"保证续保"填了年限）
- **THEN** 该值拒入 pred、字段转 unknown 且拒绝原因可审计

### Requirement: E5 回归合同必须诚实且边界受限

3 基线产品的 replay 评分回归 SHALL 纳入 deterministic 门禁且分数不得低于改进前基线；SHALL NOT 修改 cleaning 白名单、knowledge/、goldenset/、adapters/；routing 关键词补充须附压缩比不退化证据；validation-report SHALL NOT 宣称真实分数提升。

#### Scenario: replay 回归下界断言

- **WHEN** 本 change 全部改进落地后运行 3 基线产品 replay 评分
- **THEN** 每产品分数 ≥ 改进前基线（下界断言用例失败即门禁失败）

#### Scenario: 报告诚实性

- **WHEN** 出具 validation-report
- **THEN** 含工单总数/转绿数/未解决数及原因、fixture 回归 before/after 分数表
- **AND** 真实分数提升的结论字段留空并指向 020 D4

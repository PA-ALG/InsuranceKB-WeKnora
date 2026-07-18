# 024 抽取召回提升验收规格

> 二版（2026-07-16，按 PR #11 复审修订）：**证明力边界收紧**——`ReplayClient` 的 fixture key 是 system+user prompt 的哈希（`llm.py:request_key`），prompt 一变旧录制即失效；因此本 change 的零调用测试只能证明**编排/解析/护栏合同**，不能证明模型因新 prompt 抽得更好。真实召回改善只能由 020 D4 在固定模型/样本/预算下 A/B 证明。金标只作测试预言机（评分），SHALL NOT 出现在任何生产触发条件中。

## ADDED Requirements

### Requirement: E1 改进必须由归因工单的回放用例驱动且零真实模型调用

005 归因清单中每条 extract_empty 工单 SHALL 固化为一个 fixture 驱动的回放用例（用例名引用工单标识）：用例断言**机制合同**——该工单场景下路由命中、变体选择、补漏触发、解析与护栏行为符合本规格；改进落地前用例为 RED、落地后转绿。为新 prompt 人工构造的录制响应 SHALL 仅用于证明编排合同，SHALL NOT 被表述为召回提升证据。本 change 全部测试进 deterministic lane，零真实模型调用；真实回归显式让渡给 020 D4。

#### Scenario: 归因工单固化为机制合同用例

- **WHEN** 005 validation-report 归因清单中的一条 extract_empty 工单被纳入本 change
- **THEN** 存在以该工单标识命名的回放用例，断言"该场景触发定向补漏、产出经回验的候选或显式 unknown"的机制行为
- **AND** 用例文档字符串注明其证明力为编排/护栏合同、非模型能力

#### Scenario: 未解决工单不得静默跳过

- **WHEN** 某条工单在本 change 结束时机制上仍无法覆盖
- **THEN** validation-report 逐条列出该工单与原因，对应用例以显式标记保留（不删除、不伪绿）

### Requirement: E2 prompt 变体机制必须确定性、版本化且可审计

字段组级 prompt 变体 SHALL 有单一权威注册表（配置化）；同一输入的变体选择 SHALL 确定性（无随机）；每次抽取的 pred 元数据 SHALL 记录所用变体的**版本化标识**（020 D4 的 A/B 以此对账）；变体 SHALL NOT 改变 pred 输出 schema；未注册字段组回落默认 prompt，既有回放用例输出零漂移。

#### Scenario: 变体选择确定性与审计标识

- **WHEN** 同一文档段与字段组重复运行抽取
- **THEN** 两次选中同一 prompt 变体，pred 元数据含该变体的版本化标识

#### Scenario: 未注册字段组回落默认 prompt 零漂移

- **WHEN** 字段组未在变体注册表登记
- **THEN** 使用既有默认 prompt，既有回放用例输出逐字不变

### Requirement: E3 定向补漏的触发必须 schema 驱动且不降低反幻觉门槛

第二轮定向提问的触发条件 SHALL 完全由运行时可得信息构成：字段属当前产品适用 schema 且标记为必填/期望（`FieldSpec.requiredness ∈ {required, expected}`——基线 Excel 无显式必填列时默认 expected，YAML 提供『必填』/requiredness 列时按列解析），首轮结果为空、`unknown` 或 `source_pointer`，存在候选章节（检索无候选=零 LLM 调用），且预算允许（运行级补漏调用上限，配置注入，并发下原子扣减）。首轮 `source_pointer` 的解析词条 SHALL 参与补漏检索（被指向正文不含字段名也能命中）并入审计。金标 SHALL NOT 参与触发判定（仅测试评分用）。补漏走既有 gapfill 链路与预算控制；结果仍过 evidence 回验（引文对不上原文即打回），置信分级沿既有语义，反幻觉门槛不得降低。

#### Scenario: schema 驱动触发（无金标参与）

- **WHEN** 某必填字段首轮返回空且存在候选章节、预算允许
- **THEN** gapfill 以定向模板发起第二轮提问（回放 fixture 驱动）
- **AND** 触发判定的输入不含任何金标数据（用例断言触发器签名/依赖）

#### Scenario: 回验打回不放宽

- **WHEN** 补漏返回的引文与原文对不上
- **THEN** 该值被打回不入 pred（004 反幻觉回归用例保持全绿）

### Requirement: E4 值粒度对齐指引只经变体机制注入且不改数据契约

对 005 归因的值粒度缺口字段，SHALL 提供字段级"按条款原文粒度抽取"指引文本并入 E2 变体机制（非全局 prompt 改写）；SHALL NOT 修改 pred 值格式、goldenset/eval 尺子与 keypoints。其效果验证同 E1 边界：零调用侧只验证指引被正确注入与解析链无回归，粒度改善由 020 D4 评分。

#### Scenario: 指引注入且契约不变

- **WHEN** 值粒度缺口字段经带指引的变体组装 prompt
- **THEN** prompt 快照含该指引与变体版本标识，pred schema 与 eval 尺子文件零改动

### Requirement: E5 回归合同——同录制集后处理非退化，禁止暗示真实提升

在**未变更的既有录制响应集**上，清洗/兼容性/解析/编排的任何改动 SHALL 不使产出退化（3 基线产品既有回放评分不下降，作为后处理非退化断言进 deterministic 门禁）；prompt 变更导致 request_key 变化时，SHALL NOT 以人工新 fixture 的分数与旧分数对比作为改善证据。SHALL NOT 修改 cleaning 白名单既有语义、knowledge/、goldenset/、adapters/；routing 关键词补充须附压缩比不退化证据。validation-report SHALL 给出工单总数/机制覆盖数/未覆盖原因、非退化断言结果与 prompt 变体版本清单，SHALL NOT 宣称或暗示真实分数提升（真实提升由 020 D4 数据说话）。

#### Scenario: 同录制集非退化

- **WHEN** 本 change 全部改动落地后，在未变更的既有录制集上重跑回放评分
- **THEN** 每产品分数 ≥ 改动前（下界断言失败即门禁失败）
- **AND** 该探针钉住两个前置并在用例内断言：使用 control/default prompt 变体（非新变体）+ fixture manifest 内容哈希与基线一致（manifest 变化即探针失效并 fail，不得静默换基线）

#### Scenario: 报告不得暗示提升

- **WHEN** 出具 validation-report
- **THEN** 含工单状态表、非退化结果、变体版本清单与"真实召回结论留待 020 D4"的显式声明
- **AND** 不含任何用人工构造 fixture 得出的 before/after 提升表述

### Requirement: E6 抽取侧弱值与字段-值兼容性护栏（LLM-wiki-black A10 承接）

cleaning SHALL 增补 `WEAK_UNACTIONABLE`（"以合同为准/按合同约定/需核对条款"类）与 `REFERENCE_ONLY`（"见第X条/详见附表"类）两族模式，命中即按既有三态语义转 `unknown`/`source_pointer`，不作为值入 pred；pred 侧 SHALL 增加字段-值语义兼容性校验（同名/近名字段辨析），不兼容的值 SHALL NOT 入 pred（转 unknown 并记录拒绝原因）；旧项目 Q012/Q026 历史 bug SHALL 固化为回放用例。合并侧的"更粗略新值不开冲突"门槛 SHALL NOT 在本 change 实现（归 025，文件域边界）。

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

### Requirement: E7 实验归属、实际使用与审计必须进入最终 pred 产物（codex PR#13 裁决）

三个概念 SHALL 分离且全部持久化：**variant_assignment**（运行前基于 experiment_id+seed+product+field 对同一 eligible population 确定性分桶 control/treatment；实验关闭为空；control 臂强制默认补漏模板）、**prompt_variant_used**（每条 pred 实际经过的模板标识——baseline/fastpath/default@v1/targeted@vN；注册表 membership SHALL NOT 冒充实际使用）、**winning_origin**（产生最终值的路径）。pred SHALL 携带类型化 `extraction_audit`（含上述三项 + 兼容性拒绝原因 + 指针词条）且经 pred.jsonl 序列化/反序列化不丢失（pred 值契约不变、eval 忽略未知字段、历史 JSONL 向后兼容）。变体注册表与 assignment policy SHALL 由管道配置注入（节点不得各取全局默认），其内容摘要 SHALL 进入 RunManifest 与 checkpoint 身份，resume 时不一致 SHALL fail-closed。

#### Scenario: 审计穿过交付边界

- **WHEN** 完整管道运行落盘 pred.jsonl 并反序列化
- **THEN** 每条 pred 的 extraction_audit 完整可读，首轮抽取路径归因 baseline，targeted 标识只出自真实经过定向模板的调用

#### Scenario: 分桶确定性且两臂同人群

- **WHEN** 同一 (experiment_id, seed, product, field) 重复分桶
- **THEN** 结果恒定；同一 eligible population 内 control 与 treatment 均可达；实验关闭时不分臂

#### Scenario: 注册表变化后 resume 被拒

- **WHEN** checkpoint 产生后变体注册表/assignment policy 内容变化（或旧 checkpoint 缺摘要）
- **THEN** resume 身份校验 fail-closed（不得同 run 混用两套 prompt）

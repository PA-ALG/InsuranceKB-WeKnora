# Native pdfplumber ParsedDocument Adapter Specification

## ADDED Requirements

### Requirement: NPPA1 exact bytes and parser identity

056 SHALL 只解析调用方已验证的 exact PDF bytes，并在任何解析前重算 source
SHA-256。native facts SHALL 绑定 `pdfplumber` engine、显式 build identity 与 config
hash；path、filename、caller hint 或缓存 SHALL NOT 替代 bytes identity。

#### Scenario: source digest drift

- **WHEN** supplied source SHA-256 与 exact bytes 不一致
- **THEN** 在 `pdfplumber.open` 前 typed fail closed，零 native facts

### Requirement: NPPA2 only native structural facts

056 SHALL 只保留 pdfplumber 原生返回的 ordered page、word bbox、table bbox、cell
bbox 与 row/column index。文本 SHALL 只形成 content SHA-256 与长度，不进入 native
facts。page/word/table/cell identity SHALL 由当前 parse 内的确定性 order 构造。

空 cell、缺 bbox、Markdown、相邻页、表名相似或内容相同 SHALL NOT 用于补造 cell、
span、header hierarchy 或 cross-page continuation。

#### Scenario: empty merged slot

- **WHEN** native table row 的某一位置没有 cell bbox
- **THEN** formal ParsedDocument 保留该 table 的 identity/shape，但不输出该表任何
  不可证明的 cell/span，且 `table_grid` 与 `merged_cells` 保持 unsupported，由 053
  quality gate 保守返回 `ESCALATE` 或 `BLOCK`

#### Scenario: complete native grid

- **WHEN** native table 每一个 row/column 位置都有 exact cell bbox
- **THEN** formal ParsedDocument 可以输出这些原生 cells，并将其 locator 明确绑定为
  `row_span=1`、`column_span=1`

### Requirement: NPPA3 explicit capability partition

native facts SHALL 对其可证明 capabilities 给出当前 element Evidence，并对
`header_hierarchy`、`merged_cells`、`cross_page_sections` 与 `cross_page_tables`
显式 unsupported。一个 capability 不得同时 supported 与 unsupported。

#### Scenario: MaterialProfile requires unsupported structure

- **WHEN** 052 profile 要求任一 native unsupported capability
- **THEN** 未来 bridge 把真实 facts 交给 053 quality gate；056 不自己 ADMIT，亦不
  静默调用 OCR/VLM/第二 parser

### Requirement: NPPA4 053 remains the sole ParsedDocument contract

056 SHALL 消费 053 的正式 DTO、manifest builder 与 quality evaluator，不得复制其
模型、canonical hash、quality reason 或 ReviewItem 形成第二合同。053 exact commit
未进入 branch 时，正式 bridge SHALL 保持可复现 RED，且当前状态不得报告完成。

#### Scenario: formal bridge consumes exact 053 authority

- **WHEN** exact native facts 与 caller 提供的 subject/parser/attempt/snapshot、052
  MaterialProfileResolution 一致
- **THEN** 056 直接构造 053 DTO、调用 053 manifest builder 与 quality evaluator；
  任一身份漂移 typed fail closed，不复制合同或自行批准

### Requirement: NPPA5 bounded task-local implementation

056 SHALL 保持一个 task-local adapter，不修改 parser router/queue/migration，不读取
Golden，不调用 LLM/provider/live/DB/WeKnora，不新增动态 fallback 或通用 adapter
registry。

#### Scenario: native parse is insufficient

- **WHEN** exact native facts 无法满足 profile
- **THEN** 返回 053 typed `ESCALATE` 或 `BLOCK + ReviewItem`；parser call count 不由
  056 增加

# 053 · Parsed document contract

## 状态

`IMPLEMENTATION IN PROGRESS / STACKED ON DRAFT PR #80`

053 是 051 的 Child B。它从 PR #80 exact head
`46b7e6b16e2bf2afb7ce1e450d63cca81e849951` 开始；现已 fast-forward 到 052
successor `67483ab7d769fc4a2c01736d638c34bf9ee0e66f`，只消费其冻结的 default
parser、至多一个 bounded upgrade、触发条件、attempt 与隐私/输出策略；质量入口
只接受该 052 validated `MaterialProfileResolution`，不接受脱离 binding/catalog 的裸
receipt。
PR #80 合入前，本 change 不得 Ready 或 merge。

## 本 Change 做什么

- 定义 vendor-neutral `ParsedDocumentV1`、`ParseManifestV1` 与
  `ParseQualityDecisionV1`；
- 绑定 Space、Source、SourceRevision、ProductVersion、052 MaterialProfile、
  source/raw/canonical hash、parser/profile/build/config 与 exact attempt；
- 表达有序 page/block/table/cell、稳定 locator、bbox、表格 row/column/span、
  content/structure digest、warnings 与 unsupported facts；
- 从 document 确定性生成 complete manifest，并用 C0 canonical hash 绑定；
- 只消费 052 已批准 required capabilities 与完整 resolution binding；capability
  Evidence 必须符合 page/block/table/cell 的当前结构形状，调用方不得用 page ref
  冒充 table/cell，也不得自报 parser role、upgrade eligibility、阈值或输出策略；
- 只允许 default attempt 与至多一个 approved upgrade。缺少上游 policy、身份漂移、
  manifest 不完整、required structure 缺失或隐私策略不满足均 fail closed，形成 typed
  `BLOCK`/ReviewItem；第二次不足后不得第三次 parser attempt。

## 非目标

- 不实现或选择 parser/OCR/VLM，不读取 Markdown 猜原生结构；
- 不调用 provider/model/live/DB/PostgreSQL，不写 WeKnora；
- 不新增 migration、API、worker、queue、registry 或 parser 平台；
- 不实现 ExtractionTask、Claim/ChangeSet、Candidate、ReviewDecision 或 Release；
- 不宣称三份真实 PDF 已 admitted，不读取 049 Golden 答案。

## 路径预算

严格七路径：OpenSpec registry、proposal/tasks/validation/spec 四件、一个纯领域模块、
一个 focused test。若需要第八路径必须停机重划；不得为导出便利修改 package
`__init__.py`。

# 061 · 596-1 Vertical Falsification

## 状态

`DETERMINISTIC SCORER GREEN / EXECUTION BLOCKED ON 3 PARSE ARTIFACTS`

061 是 051 最小真实纵切证伪。它只验证 ProductVersion `596-1` 的条款、
说明书、费率表三份 exact PDF 能否在已批准知识编译合同下形成完整 60 字段、
Evidence 闭合、具名人工批准并可发布的 Release。它不扩大到第二产品、动态
路由、评测平台或 production rollout。

当前工作分支精确基于已合入 059 PR #89 与 060 PR #88 的 authoritative main
`e388e8326ab20e134b82d532799b15cfc18e2387`（tree
`6bdf418c206c673b7391130fd2ebf36c02b3e804`）。该基线已提供真实的
`insurance_harness.compiler.native_mineru_cloud` 公共桥接合同，因此当前执行
缺口只有条款、说明书、费率表三份 exact PDF 各自一个经 060 质量门 ADMIT 的
typed immutable intake receipt。每件必须绑定 exact role/source SHA、
ParsedDocument/ParseManifest/decision hash 与完整身份链，并携带 sanitized 060
structure bytes、raw/sanitized hashes 与获批 052 MaterialProfileResolution。061
必须调用真实 060 builder 重放并逐对象相等，调用方手工构造的自洽 ADMIT 或任意三个
SHA 声明都不能开门。

因此本 checkpoint 仍只交付可执行 dependency gate。三份 admitted parse
artifact 缺失，或 060 真实公共模块/所需公共符号缺失或漂移时，061 必须返回 typed
`BLOCKED_ON_REQUIRED_CONTRACTS`，并在任何 Provider 调用或 049 Golden 读取前
停止。060 模块只能在 admission 内惰性解析；缺失、导入失败或符号漂移不得阻止
061 模块加载。所有嵌套 052/053/060 DTO 在解引用和 builder 重放前重新验证，
`model_construct` 等绕过不得泄漏原异常、绝对路径或 traceback。

059 已合入的发布权威位于 Go 服务层：`HumanBatchDecisionReceiptV1`、
`ActivateReviewed` / `Revert`、opaque pinned read 与 HTTP handler。061 不探测或
复制不存在的 Python Release 模块，也不接受 caller 自报的 Release/Head/receipt。
质量门全部通过时，纯 scorer 只返回
`QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE`；最终 `MVP_VERTICAL_SLICE_GO` 只能由
总控在真实 Go 059 激活 endpoint 返回 immutable receipt/Head，并完成 pinned
read/revert 证明后作出。

本 checkpoint 还交付不依赖 Go 059 运行调用、Provider 或 Golden 文件的
纯确定性后半段：6+8+4 调用预算账本、绑定三 PDF/Schema/parser/model/prompt/
budget/normalizer/comparator identity 的 C0 arm-output envelope，以及只接受 exact
049 `596.jsonl` bytes 的 60 字段/critical18/Evidence/费率结构 scorer。公共评分入口
必须先在内部重放三份 060 admission，绑定由三份 intake receipt 重算的 custody
digest，并在两臂 hash 冻结后才校验 Golden bytes SHA、严格解析 Schema60；调用方
不能注入可自行声明 authority 的 Golden 对象。critical18
绑定获批 exact ordered field tuple 与 canonical SHA256
`12b648d509c53b7ce1659abbf95811d437c3d22f729d46a58545f47e09bee344`；两臂绑定
获批 arm profile SHA256
`c64ce6227b714fb9a47fe2c15cd51349df4fccc8770fb95442aed86061f39fe3`。它们不打开
真实执行门，也不生成或伪造 Candidate/Release。scorer 还绑定 exact ProductVersion
`596-1`、按 terms/brochure/rate_table 排序的三份 source SHA、Schema
`v1.1+b31a411c621c`/registry SHA256
`5d222c68f228d57c9061fc329f85a26191f6c847f7122f221e6aff92147b9db5` 与由获批
DeepSeek facts 重算的 semantic-model identity；两臂仅相互一致但偏离这些权威值时
必须 NO-GO。Schema authority 还冻结 exact ordered 60 field IDs；费率语义只由
Schema 的 exact `zh_7fe8603c08`、`zh_c588207763` 集合派生，调用方不能用布尔值
降级。Golden bytes 必须精确匹配 SHA256
`562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`，并绑定
049 release `fca06f98...`、artifact `83032da0...`、approval subject
`6feb2acf...`、exact 三 source 与 Schema60。最终确定性 decision receipt 绑定两臂
output hash、Golden bytes/content digest、三份 admission receipt digest 与 evaluator
identity，任一字节漂移都会重算为不同 receipt。

## 最终运行合同

- 输入固定为 `596-1` 的 exact 三 PDF 与 Schema60；
- 任务固定为 10 个：8 个 weak-model 窄任务、2 个费率确定性任务；
- baseline 最多 6 次 Provider 调用；candidate 8 次，targeted repair 最多 4 次；
  总 hard cap 为 18；
- 两臂的完整输出必须先内容寻址冻结并记录 hash，随后才能读取 049 Golden；
- 公共 scorer 必须先重放 exact 三份 060 intake admission；非 READY 时 Golden
  bytes 零读取，且调用方不得用 status token 或自造 Golden 绕过；
- critical18 silent error 与 exact semantic error 必须为 0；hallucination 必须为 0；
- candidate tri-state correctness 至少 57/60，Golden-known/present normalized
  value correctness 至少 95%；critical known Evidence 必须为 100%，overall known
  Evidence 必须至少为 95%；
- 费率 Evidence 必须同时绑定 exact page/table/cell 与 row/column/header/span；
- exact ordered Schema60 与 exact rate-field subset 必须匹配；caller 的 rate 标签
  不具有 authority；
- Golden 必须由 exact `596.jsonl` bytes 严格解析并绑定已批准 049
  release/artifact/approval subject；score receipt 必须绑定两臂输出、Golden bytes/
  content digest、admission custody 与 evaluator identity；
- baseline 只报告同一套 tri-state/value/abstention/missing/hallucination/error/
  Evidence 指标，不承担 candidate GO 阈值；
- baseline 固定 `pdfplumber/default` attempt 1，candidate 固定
  `mineru-cloud-pipeline/bounded_upgrade` attempt 2；两臂语义抽取均为 exact
  `DeepSeek V4 Flash` / `https://api.deepseek.com/v1`，Qwen 不进入语义臂、judge
  或 fallback；
- 解析与质量计算只消费 060 canonical structure；纯 scorer 成功终态只能是
  `QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE`，失败为 typed NO-GO；
- `MVP_VERTICAL_SLICE_GO` 由总控在真实 Go 059 named-human activation、immutable
  receipt/Head、pinned read/revert 全部证明后给出，不能由 Python scorer 自行生成；
- 禁止 fallback、模型 judge、看 Golden 调 prompt、动态路由或评测平台。

## 非目标

- 本 checkpoint 不调用 provider/model/live/DB/PostgreSQL/WeKnora，不把 049 Golden
  值送入模型或用于调 prompt，不生成 Candidate/Release，也不声明纵切通过；focused
  custody test 只读取 exact approved `596.jsonl` bytes 以验证严格 parser/hash 门；
- 不复制或猜测 Go 059、060 的 DTO、hash 或 authority；
- 不修改 059/060、OpenSpec registry、Golden、Schema、README 或 CI inventory；
- 不实现重试、队列、缓存、实验管理、排行榜或 parser/model winner。

## 路径预算

当前严格六路径：proposal/tasks/validation/spec 四件、一个 task-local runner、
一个 focused test。本 checkpoint 不修改 README registry，也不增加第七路径。

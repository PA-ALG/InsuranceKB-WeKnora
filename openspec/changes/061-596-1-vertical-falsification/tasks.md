# 061 · Implementation Plan

## Task 1 · Exact identity and dependency inventory

- [x] 从 authoritative main `bfa6fe233d08f84b368b51570c1c0302d22ae002`
  创建 isolated worktree/branch，并确认 `.worktrees` 被忽略、基线 clean。
- [x] fresh 核验 059 的发布权威实际为 Go service contract，且不存在 Python
  `candidate_releases` 模块；060 MinerU adapter 为 Python public seam。
- [x] 安全保存 strict6 WIP，核验 `bfa6fe2..87eb36c` 仅含 060 strict11，
  ff-only 到已双审批准的 PR #88 exact head `87eb36cb...` 后无冲突恢复 WIP。
- [x] 060 合入后再次安全保存 WIP，确认 merge commit `1a8e36e0...` 与
  approved head tree 完全相同，并 ff-only 到 authoritative main 后恢复 strict6。
- [x] 冻结当前六路径预算；不修改 README registry。

## Task 2 · Executable dependency RED seam

- [x] 先写 focused RED：061 runner 尚不存在，测试不得 xfail。
- [x] 最小 GREEN：在导入缺失的 060 合同前返回 typed
  `BLOCKED_ON_REQUIRED_CONTRACTS`；`provider_calls=0`、`golden_reads=0`。
- [x] 证明 gate 只探测 exact public module/symbol，不定义本地 Release、MinerU
  或 canonical-structure DTO。
- [x] 先写 focused mutation RED，再直接消费 060 的真实
  `native_mineru_cloud` 公共模块；exact 060 存在时只剩三份 admitted artifact
  阻断，任一所需 060 公共符号漂移时重新 fail closed。

## Task 3 · Pure deterministic back half

- [x] TDD 交付 baseline≤6、candidate main≤8、repair≤4、total≤18 的预算账本；
  fallback、额外 retry 或任何上限越界均为 typed NO-GO。
- [x] TDD 交付两臂 C0 frozen output envelope，绑定 exact product/三 source SHA/
  Schema/parser/model/prompt/budget identity；hash 重算稳定且任一字节变化敏感。
- [x] TDD 交付 exact-049-bytes scorer：固定 60/critical18、tri-state/value、
  critical/overall Evidence coverage、critical silent error 与费率完整 locator gate。
- [x] TDD 绑定获批 critical18 exact ordered tuple/hash 与 exact arm-profile hash；
  拒绝 critical substitution/order drift、parser role 交换/复用、Qwen/alternate
  endpoint、自报 profile 以及 normalizer/comparator 漂移。
- [x] TDD 报告每臂 tri-state/value exact、abstention、missing、hallucination、
  wrong-value、Evidence counts/rates；candidate 执行 0 critical semantic error、0
  hallucination、tri-state ≥57/60、known-present normalized value ≥95% 与
  overall known Evidence >=95%，baseline 仅诊断。
- [x] TDD 拒绝空 table/cell/header、负 row/column、零 span，并保持费率完整结构门。
- [x] mutation 覆盖未冻结/改 hash、少/重/额外字段、unknown 冒充 known Evidence、
  critical/Evidence/费率/预算失败，并证明 admission 未 READY 或 arm 未冻结时
  scorer 不查看 Golden bytes；
  全部满足时只返回 `QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE`。
- [x] TDD 证明 fake Python 059 module 不改变 quality readiness，且 scorer 没有
  Release/Head/receipt 输入，也不能自行生成最终 `MVP_VERTICAL_SLICE_GO`。
- [x] TDD 将两臂与 Golden 绑定 exact 596-1、三 source 有序 SHA、Schema version/
  registry SHA、arm-profile 与 DeepSeek semantic identity；两臂共同伪造同一 identity
  仍为 typed NO-GO。
- [x] TDD 冻结 exact ordered Schema60 与 exact rate-field subset；foreign field、
  顺序漂移与 caller rate 降级均为 typed NO-GO。
- [x] TDD 从 canonical component preimage 重算 arm-profile/model/prompt/budget/
  normalizer/comparator/parser identities；两臂共同篡改组件也不能沿用获批 profile。
- [x] TDD 绑定 exact 049 release/artifact/approval subject、三 source 与 Schema60，
  公共入口只接受 exact `596.jsonl` bytes 并严格校验文件 SHA/内容；由两臂 output
  hash、Golden bytes/content digest、admission custody、evaluator identity 重算
  score receipt。
- [x] TDD 证明 060 exports 在同一无详情边界内一次性捕获；异常 `__getattr__`、
  二次读取陷阱或符号漂移均 typed fail closed，不泄漏 exception context、secret
  或绝对路径。
- [x] TDD 证明公共 scorer 内部重放 exact 三份 admission；non-READY 或 receipt
  digest 漂移时 Golden 零读取，调用方不能传 status token/Golden DTO 绕过。
- [x] TDD 预算计数只接受非负 runtime `int`；`bool`、float、NaN 均 fail closed。

## Task 4 · Runtime continuation — blocked

- [x] 059 已合入的 named-human activation 权威确认为 Go service；061 不复制
  Python DTO/signature，不把 caller opaque ref 作为质量或 GO 权威。
- [x] 从 merged 060 exact main 直接消费 MinerU native
  ParsedDocument/manifest/quality bridge 公共合同。
- [x] admission 已要求 terms/brochure/rate_table exact typed intake receipts，绑定
  596-1 source/profile、sanitized 060 bytes、raw/sanitized hashes、获批 052
  resolution 与完整身份链；真实 060 builder 必须重放出逐对象相等的
  ParsedDocument/manifest/terminal ADMIT decision。任意三个 SHA、手工 ADMIT、错
  role/source/hash/resolution 或非 ADMIT 均 fail closed。
- [x] 060 合同改为 admission 内惰性解析；缺失/导入失败 typed block。嵌套
  resolution/document/manifest/decision 在解引用前递归 revalidate，畸形 DTO 不泄漏
  raw exception/traceback。
- [ ] 条款、说明书、费率表各实际冻结一个满足上述合同的 060 ADMIT artifact receipt。
- [ ] 三份 admitted artifact 均满足后，才按 Spec 的 10-task/18-call 合同继续
  Provider execution 与真实 Golden loader；质量通过后仍停在 pending human release。
- [ ] 总控通过真实 Go 059 activation endpoint、immutable receipt/Head、pinned
  read/revert 独立完成最终 `MVP_VERTICAL_SLICE_GO` 证明。

## Task 5 · Current checkpoint verification

- [x] focused test、Ruff、strict mypy、OpenSpec strict、diff/scope、privacy/
  credential scan。
- [x] 重冻 exact six-path temp-index candidate；不 commit/push/PR。

# 059 · Fixture Candidate and Human Batch Envelope

## 状态

`PR1 MERGED / PR2 RELEASE-CAS-PINNED-REVERT AWAITING EXTERNAL REVIEW`

059 PR1 已合入。PR2 是同一 Mission 的第二个小 PR；它基于已合入 main 的 057 verified
Evidence/repair receipts，并直接消费已合入 PR #86 的 058 immutable ChangeSet
public contract。059 不复制 058 的 DTO、canonical hash 或 action logic。

## 本 Change 做什么

- 从一个 exact immutable 058 ChangeSet 与其 verified 057 receipt references
  确定性构建 `FixtureCandidateV1`；
- 嵌入 exact 054 ReceiptChain；从其 ExtractionTask 派生并校验 Space、
  ProductVersion 与 schema-contract artifact，绑定全部 source revision、
  ChangeSet 与 057 receipt identities，不接受 caller 自报 schema authority；
- 确定性生成 `HumanBatchV1`，只聚合 conflict、high-risk 和 repair-needed
  review items，同时绑定完整 Candidate；
- conflict item 保留所有竞争事实及各自 Evidence，不选择或隐藏 winner；
- 使用 C0 canonical envelope/hash，证明重排稳定、byte mutation 敏感；
- missing、ambiguous、cross-scope、invalid receipt 或 ChangeSet/hash drift 均
  fail closed，且不产生 Candidate/human_batch。
- exported aggregate validator 重算完整 Candidate/source/receipt 与
  conflict/high-risk/repair-needed membership；直接 DTO 构造或 `model_copy`
  不能绕过 builder 的约束。

## 058 exact public seam

059 从 accepted 058 merge head `07c4cd31d729c57d19f3de1118354e05b4092b0d`
的公开模块直接消费以下能力，不自行定义替身：

1. immutable ChangeSet aggregate 与 immutable item/action values；
2. 058 拥有的 canonical identity/digest 验证入口；
3. item 的 exact Space/ProductVersion/schema/source scope、action、before/after
   或 competing fact hashes、Evidence references；
4. conflict 的 deterministic action。057 verification/repair receipts 由 059
   以 content-addressed fact link 接入；high-risk 来自 exact fixture review policy，
   不伪装成 058 自带字段。

059 只建立 content-addressed fact↔057 verification join，并把 imported 058
objects 原样放入 Candidate；不得在本模块补造第二套 ChangeSet authority。

## 非目标

- 不实现 ReviewDecision、auto-approve、machine_auto、Release、serving Head、
  CAS activate、pinned read 或 revert；这些属于后续 PR2；
- 不实现 DB/migration、queue/workflow/review platform、API/UI、provider/live、
  WeKnora I/O 或 filesystem artifact store；
- 不读取 049 Golden，不调用模型，不修改 057/058 合同；
- 不把 Candidate 或 human_batch 伪装成批准、发布或线上读取 authority。

## PR2 bounded release boundary

PR2 只把 PR1 exact Candidate/human-batch hash 接入现有五张 WeKnora Release
表和既有事务边界：具名人工整批 decision receipt、单事务 Head CAS、请求起点
一次 pin、每次读取双 ACL、以及指向同 scope 不可变历史 Release 的 CAS revert。
WeKnora Head 仍是唯一 serving authority；Harness 不增加第二 Head。

PR2 不增加 migration、router、新 API、队列、provider、live 或通用审核平台。
既有 S0-R `PublishAuthorizationV0` 与五表只做窄幅复用，PR2 不改变表结构。
安全纠偏仅收紧既有 release handler：激活入口必须同时消费具名人工 receipt
与 publish authorization，serving 入口必须在请求起点 pin 当前 Head；URL 中的
历史 `release_id` 不能铸造读取 authority。

## 路径预算

PR1 严格七路径。PR2 安全纠偏后相对已合入 PR1 最多十一条路径：本 OpenSpec
四件、既有 `internal/types/wiki_release.go`、service、repository、两个既有域内
handler/service focused test、既有 release handler 与一个 immutable
cross-language fixture/vector；不修改 router 或 README。

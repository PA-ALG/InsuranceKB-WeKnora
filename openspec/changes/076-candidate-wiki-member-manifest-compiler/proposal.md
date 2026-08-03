# 076 · Candidate Wiki Member Manifest Compiler

## 状态

`IMPLEMENTATION IN PROGRESS / DRAFT-ONLY`

## 目标

把已合入 059 的完整 `CandidateAssemblyV1`、其逐 Fact 精确绑定的 057
`FieldCandidateV1`，以及由 Release read authority port 独立解析的 base membership binding，确定性编译为
现有 Go `WikiReleaseService.Prepare` 可消费的完整 member 集合、变更日志 member 和
canonical manifest bytes。

076 只产生不可变草稿。它不创建审核决定、ReadyReceipt、Release、Active Head 或
serving authority，也不调用 Prepare/activate/revert。

## 边界

- 直接消费 057/058/059 已合入 DTO、hash 与 custody，不复制其 authority；
- 每个 059 Fact link 必须与重算后的 057 Candidate snapshot hash 一一对应；value 与完整
  Evidence locator 从 exact Candidate 派生，并与 VerificationBatch/receipt 的 source revision、
  parse attempt、document 和 manifest custody 精确相等，不接受缩减版并行 preimage；
- 初始编译需要显式空 base；增量编译需要完整且 identity 精确的 base manifest，并以独立
  `ReleaseBaseAuthorityPort` 解析 base release/epoch/digest/member-count；不接受调用方自建 raw
  binding，防止自洽截断或伪造；
- 支持 `add/enrich/supersede/conflict/retract`，冲突保留全部竞争事实与 Evidence，
  不选择 winner；
- 使用 ProductVersion 与 scope hash 派生稳定 slug，不用标题或值寻址；
- 输出字段与 Go `WikiReleaseMemberSnapshot` byte-compatible；
- closed payload 必须能重算 Markdown/member；NFC、常见 assignment/header 形式的
  secret-shaped value/Evidence 或任意
  validation 漂移均 typed fail closed；
- 不新增 parser/provider/Golden/DB/WeKnora/queue/workflow/page-template 平台。

## 路径预算

严格八路径：OpenSpec 四件、一个 Python module、一个 focused test、一个 JSON
vector、一个只读调用既有 Go canonicalizer 的 focused test。不得修改 registry 或
生产 Go 代码。

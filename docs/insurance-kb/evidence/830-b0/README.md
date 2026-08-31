# B0 · 815 证据基线与资产裁决 Evidence Pack

> 状态：`EVIDENCE_FROZEN_PENDING_CONTROLLER_REVIEW`
> 当前 Goal：`B0`
> CURRENT_RED：`BASELINE_815_NOT_FROZEN_FOR_830`
> NEXT_PHYSICAL_RESULT：可重算的 815 FLOW PASS baseline、有限候选四态台账、
> D0–D3/镜像影响基线和 branch/worktree 机械索引
> VALIDATION_LEVEL：`D0`
> DOCKER_ACTION：`SKIP`

本目录只冻结既有 815 证据和 830 资产裁决，不重跑 815、不调用 Provider、不重抽
Schema67、不启动服务、不构建镜像、不修改产品代码或运行数据，也不启动 G1。
`815_FLOW=PASS` 不得改写为 `SCHEMA67_QUALITY=PASS`；质量状态保持 `DEFERRED`。

## 索引

- `baseline/815-flow-baseline.json`：815 commit/tree/release/runtime/current/pinned/
  7 sections/67 fields/17 citations/PDF page+quote 的冻结身份；
- `baseline/hash-recalculation.json`：receipt/runtime/workbook 的 expected/actual hash
  重算输出；
- `inputs/workbook-audit.json` 与 `inputs/*.xlsx`：11 类 Schema v5 工作簿持续审计副本；
- `receipts/`：既有只读 receipt 的 exact 副本；
- `runtime/c7-server-reopen-index.json`：67 字段与 17 citation page/quote/file 绑定；
- `assets/finite-candidate-disposition.json`：有限候选集四态裁决；
- `validation/validation-baseline.json`：当前 D0–D3 入口和既有 CI 样本 p50/p95；
- `image-impact/image-change-impact.json`：service→构建输入和 artifact identity；
- `branch-worktree/branch-worktree-manifest.json`：全量当前 refs/worktrees 机械索引；
- `branch-worktree/symbolic-alias-accounting.json`：392 个具体 branch 与
  `refs/remotes/origin/HEAD` symbolic alias 的非重复计数口径；
- `integration/origin-main-diff.json`：正式 base、选择性 authority 导入与 B0 写域差异；
- `closure/worktree-closure.json`：B0 写域、diff/status 与未集成提交闭环；
- `review/independent-review.json`：独立只读复核任务、exact candidate identity 与结论；
- `review/controller-review.md`：独立复核结果与总控最终裁决边界；
- `tools/verify_b0_evidence.py`：仅重算本包 hash/identity/穷尽性，不启动环境。

## Receipt 身份说明

用户冻结输入 `c7-ui-visible-terminal.json` 当前 external SHA-256 是 `20575de1…`，
canonical self-hash 是 `1d57527f…`。Handoff 中记录的 `0e24db1…` 实际对应后续
`c7-ui-cache-corrected-terminal-20260831.json`；后者修正产品入口/UI cache，绑定同一
`9fcf3386`、tree、backend binary 与 epoch2 release。两份 receipt 分开登记，互不替代。

## 裁决边界

本包可证明 B0 所需证据已经冻结并可机械重算，但执行窗口不会自行宣布最终路线 PASS。
独立只读任务 `B0-独立复核`（`01a057ef-b006-7362-9ac1-b1ddf4e5f851`）对
`1c752133afd204cc9fb93d1948d78e6490fb1c7b` / tree
`b8d503233128ac21607ef86dd39d9f8eb5311af9` 给出 `INDEPENDENT_REVIEW=PASS`，
`unresolved=0`。这不替代总控最终裁决；`CONTROLLER_FINAL_ADJUDICATION=PENDING`，
G1 及后续 Goal 全部保持 `LOCKED`。

## Branch 计数口径

机械索引的 392 个 branch 恰好等于 `310 local + 82 concrete remote-tracking`。
`refs/remotes/origin/HEAD` 是指向 `refs/remotes/origin/main` 的 symbolic alias，
不是独立 branch history，因此不计入 392；含该 alias 的 live ref 枚举为 393。
此口径单独冻结，不重新生成或改写 392 项历史清单。

## 非自指 Git 身份合同

包含 manifest 的 commit SHA 由 manifest 内容决定，因此文件不能诚实地内嵌自己的
最终 SHA。branch/worktree manifest 记录生成时的 `observed_head_before_evidence_commit`
和时间；最终 verifier 实时读取 exact `HEAD`，要求 observed head 是它的祖先，并要求
`observed..HEAD` 的全部 changed paths 都在授权 B0 写域、每个 commit message 都含
`B0` 与 `NEXT_PHYSICAL_RESULT=`。closure 同样记录 evidence candidate head；最终 exact
SHA 只由 verifier 输出、总控冻结复核与终态报告绑定。禁止循环 amend 或伪造 final SHA。

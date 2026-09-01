# 126 · Validation Report

## Current identity

```text
GOAL_ID=G1
BASE=d2ce44cb2107575f7624b3735c653078ae2a98b6
BRANCH=codex/830-g1-field-assertion-pages
CURRENT_RED=M2_COMPLETE_76_PAGE_GRAPH_EVIDENCE_AND_M3_ATOMIC_ISOLATED_RELEASE_NOT_YET_CLOSED
FLOW=M1_PASS
QUALITY=DEFERRED
DOCKER_ACTION=SKIP
G2_AND_LATER=LOCKED
M0_INITIAL_REVIEW=FAIL
M0_INITIAL_UNRESOLVED_COUNT=3
M0_CORRECTION=PASS
M0_REVIEWED_HEAD=bc93bbef19e24877f0a8816dc49395bc662d703f
M0_REVIEWED_TREE=71601455e486fe7b21b358032939b0799cafbc8f
M0_REVIEW_UNRESOLVED_COUNT=0
WIN1_CONTRACT_HEAD=8fa27956c6368502f21d52245d2cea905f0e2ce1
WIN1_CONTRACT_TREE=82e490ef47da775aed0d8176c7f31a27f6d537e9
WIN1_REVIEW=PASS
WIN1_REVIEW_UNRESOLVED_COUNT=0
WIN2_CONDITION=PASS
WIN2_WRITE_DOMAIN_DISJOINT=true
WIN1_ACTUAL_EVIDENCE_LANE=OPEN
NEXT_PHYSICAL_RESULT=M2_COMPLETE_76_PAGE_GRAPH_EVIDENCE
M1_DEADLINE=2026-09-02T23:42:03+08:00
M1_RUNTIME_HEAD=740d9b7c55f047e30c59c087dc29b943e3849726
M1_RUNTIME_TREE=bb29b5d6cf9533f69bd14728736e916513f3119c
M1_PREPARATION_ID=g1-m1-740d9b7c-preview
M1_MANIFEST_SHA256=3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c
M1_PREVIEW=PASS
G2_AND_LATER=LOCKED
```

## Requirement matrix

| Requirement | RED | Implementation | Focused test | Commit | Live evidence | Status |
|---|---|---|---|---|---|---|
| G1-R1 | PASS | Harness + Go + entity UI | focused PASS | `740d9b7c` | stable entity URLs/UI PASS | M1 PASS |
| G1-R2 | PASS | 76-member manifest + Draft snapshots | focused PASS | `740d9b7c` | Draft 76/76 PASS | M1 PASS |
| G1-R3 | PASS | tri-state FieldAssertion | focused PASS | `740d9b7c` | present/absent/unknown UI PASS | M1 PASS |
| G1-R4 | PASS | server-verified source bridge | focused PASS | `740d9b7c` | exact PDF page/bbox PASS | M1 PASS |
| G1-R5 | PASS | payload Profile + namespace metadata | focused PASS | `740d9b7c` | short title + full namespace PASS | M1 PASS |
| G1-R6 | PASS | existing preparation writer accepts atomic 76 snapshots | focused PASS | `740d9b7c` | Draft 76/76 PASS; Release NOT RUN | M1 PREPARATION PASS / M3 RELEASE NOT RUN |
| G1-R7 | PASS | current/pinned/preparation no-fallback reads | focused PASS | `740d9b7c` | preparation Preview PASS; successor current/pinned NOT RUN | M1 PARTIAL / M3 NOT RUN |
| G1-R8 | PASS | no second authority; existing C6 source viewer | focused PASS | `740d9b7c` | exact source bridge PASS | M1 PASS |
| G1-R9 | PASS | Profile-driven compiler/renderer | focused PASS | `740d9b7c` | seven-section actual UI PASS | M1 PASS |

M0 文档/规格变更采用 D0；当时功能 RED、实现、Docker 和 live 均未运行。只有实际命令与
不可变回执可改变本表状态，fixture/code GREEN 不得改变 FLOW 或 BUSINESS 状态。

初次独立复核在 commit `0f1cbe1840774aca6e1a3eb74bbc65687d97680b`、tree
`447dcbde22641136effc6d612134caeb7348fc4f` 上报告 3 个 BLOCKER。总控在
`bc93bbef19e24877f0a8816dc49395bc662d703f` / `71601455e486fe7b21b358032939b0799cafbc8f`
完成唯一 M0 纠偏；同一只读 Review 复核为 PASS、`UNRESOLVED_COUNT=0` 后才启动 Win1。

## Harness contract freeze

- Win1 可见任务：`01a058c0-1937-7d93-8bb3-92ee7f19dbf0`。
- 首个合同 commit `b33c7f8be0e9c41dbed194b94725a2a208db5c4b` 经独立 Review 报告 3 个
  跨对象语义闭包 BLOCKER；总控没有放行 Win2。
- 最小修正 commit `8fa27956c6368502f21d52245d2cea905f0e2ce1`、tree
  `82e490ef47da775aed0d8176c7f31a27f6d537e9` 关闭 overview→section、
  reference→citation/evidence receipt、citation→source authority 三类完整重哈希漂移。
- 独立只读 Review `01a05917-a8e7-7b00-bf36-82bef310c2a5` 复验 PASS，
  `UNRESOLVED_COUNT=0`；R1-R5/R8/R9 的跨语言合同可以供 Win2 消费。
- 合法 vector file SHA-256 为
  `cffb39e5a7214e2720b54a80acacab6923afa8e00e6174befc88b3cd44e069d1`，manifest
  SHA-256 为 `3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c`。
- 总控独立验证：actual focused `14 passed`；hermetic `11 passed, 3 skipped`；既有
  regression `43 passed`；Ruff、format、py_compile、strict mypy、diff-check 全部通过。

这些证据只冻结 Harness 离线合同。G1-R6/R7、真实 WeKnora Preview、current/pinned、
UI 与 source-click 仍为 NOT RUN；FLOW 继续为 NOT_RUN，不能报告 M1 或 G1 PASS。

Win2 条件成立：Win1 三条 Harness 写域已经冻结；Win2 的 Go/Frontend 路径与其完全互斥；
共享 vector 经独立 Review PASS；Win1 继续负责 actual 815 编译重放/证据支持，Win2 负责
WeKnora validation/read/UI，两者直接汇合到同一个 M1 Preview。最多仍为两个可写 lane，
不得扩大到 G2 或新增服务/表/authority。

## M1 real Candidate Preview

- Runtime source: `740d9b7c55f047e30c59c087dc29b943e3849726` / tree
  `bb29b5d6cf9533f69bd14728736e916513f3119c`; isolated backend `18094`, frontend
  `18085`, Draft `g1-m1-740d9b7c-preview`.
- Exact manifest: `3ae19c3254df73d9ed678a440404c9c2ec67319709c33c9bb8000c0a15da6a3c`;
  source release `release-42a3dd0c-ec76-4017-a288-37f1b13519a0`, epoch `2`; 76 members,
  67 fields, `present=2 / absent_explicitly=1 / unknown=64`, empty free_wiki.
- UI evidence: `docs/insurance-kb/evidence/830-g1/m1/entity-page-preview.json` and seven
  screenshots under `docs/insurance-kb/evidence/830-g1/m1/ui/`.
- Source evidence: `docs/insurance-kb/evidence/830-g1/m1/source-click.json`; real click opened
  the frozen source PDF on page 2 with exact bbox. Page/locator mutation tests return typed
  unavailable before snapshot fetch; UI emits `PDF_PREVIEW_UNAVAILABLE` and makes no
  current/latest/content/page-1 fallback.
- Runtime/effects: `docs/insurance-kb/evidence/830-g1/m1/runtime-identity.json`; Preview read
  window counts stayed `3/2/150/1/2`, Head stayed on the source release/epoch, Provider/model
  calls were zero, and production `8081` container/image/start identity stayed unchanged.
- Independent read-only Review of the implementation candidate at the same head/tree reported
  `REVIEW=PASS`, `UNRESOLVED_COUNT=0`. M1 evidence itself remains controller-owned and must be
  committed/re-reviewed before advancing to M2.
- The first evidence-commit review at `cf05e8af372aed8336bf3f6945b2be27ca54d70f` /
  `4b1b20d799b940fb312bb8cb75cdb5c7c74d2fa9` reported `REVIEW=FAIL`,
  `UNRESOLVED_COUNT=2`: the NEXT pointer still named completed M1, and controller-created M2
  evidence appeared in the shared worktree before the M1 gate closed. The M2 files were preserved
  outside the worktree and the NEXT pointer was corrected; the correction still requires the same
  independent read-only re-review.

M1 是真实 Candidate Preview PASS，不是 G1 最终 PASS：没有 Review/Release/activation，
也尚未形成 M3 successor current/pinned/no-mix 物理证据。G2 继续锁定。

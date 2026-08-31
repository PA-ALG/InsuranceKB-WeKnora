# 126 · Validation Report

## Current identity

```text
GOAL_ID=G1
BASE=d2ce44cb2107575f7624b3735c653078ae2a98b6
BRANCH=codex/830-g1-field-assertion-pages
CURRENT_RED=NO_ENTITY_SCOPED_INDEPENDENT_FIELD_PAGES
FLOW=NOT_RUN
QUALITY=DEFERRED
DOCKER_ACTION=SKIP
G2_AND_LATER=LOCKED
M0_INITIAL_REVIEW=FAIL
M0_INITIAL_UNRESOLVED_COUNT=3
M0_CORRECTION=CONTROLLER_D0_PASS_PENDING_EXACT_HEAD_TREE_REREVIEW
NEXT_PHYSICAL_RESULT=M1_REAL_815_CANDIDATE_WEKNORA_PREVIEW
M1_DEADLINE=2026-09-02T23:42:03+08:00
```

## Requirement matrix

| Requirement | RED | Implementation | Focused test | Commit | Live evidence | Status |
|---|---|---|---|---|---|---|
| G1-R1 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R2 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R3 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R4 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R5 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R6 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R7 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R8 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| G1-R9 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

M0 文档/规格变更采用 D0；功能 RED、实现、Docker 和 live 均未运行。只有实际命令与
不可变回执可改变本表状态，fixture/code GREEN 不得改变 FLOW 或 BUSINESS 状态。

初次独立复核在 commit `0f1cbe1840774aca6e1a3eb74bbc65687d97680b`、tree
`447dcbde22641136effc6d612134caeb7348fc4f` 上报告 3 个 BLOCKER：最高权威状态指针、
exact 窗口写域/单一 M1 结果、实际 Candidate/Claim/Evidence 与 PresentationProfile
身份。总控只做 M0 纠偏；新 exact head/tree 必须由同一只读 Review 任务复核为
`UNRESOLVED_COUNT=0`，此前不写功能代码、不创建 Win1。

# 062 implementation plan

## Task 1: Freeze authority and scope

- [x] Verify exact main, OpenSpec number, fixed two PDF identities and 051/052/060/061 boundaries.
- [x] Pin official MinerU `3.4.4` middle-output and `cross_page/lines_deleted` semantics.
- [x] Record that content-list/Markdown inference and real provider capture are prohibited.

## Task 2: RED

- [x] Prove content-list-only ZIP is typed `NOT_AVAILABLE`.
- [x] Add synthetic middle ZIP cases proving both vendor booleans remain AMBIGUOUS, clean
  middle is ABSENT, and missing middle is NOT_AVAILABLE; current relation count stays zero.
- [x] Add hostile ZIP, privacy, determinism, member order/path, marker-change, adjacency/header/
  HTML non-inference and exact-source negatives.
- [x] Prove symlink/special-mode members are rejected even when named as the native middle
  member, and prove capture HTTP reads stop at compressed-budget plus one byte.
- [x] Prove projection failure publishes no final and existing 061 no-replace/deadline behavior remains.

## Task 3: Minimal GREEN

- [x] Add one task-local projector over the unique compatible middle member.
- [x] Accept only regular files/directories and enforce the compressed-body limit in the
  capture projection branch without changing ordinary MinerU download behavior.
- [x] Thread only hashed ambiguous observations through capture-only reader state into the
  private 061 evidence; do not synthesize endpoints.
- [x] Preserve ordinary MinerU reader and 060 native sidecar behavior exactly.

## Task 4: Verification and freeze

- [x] Run focused Go tests/vet, OpenSpec 062 strict, diff-check, exact scope, private/secret scan.
- [x] Freeze exact candidate tree/temp-index with no commit/push/PR.
- [x] Record provider/live/DB/WeKnora/Golden/full as `NOT RUN`.

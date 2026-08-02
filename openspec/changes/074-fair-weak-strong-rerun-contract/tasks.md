# 074 · Implementation Plan

> Execute with TDD and verification-before-completion. Provider execution is forbidden.

## Task 1 · Contract and RED

- [x] Freeze the stacked PR #105/073 dependency and strict-seven path budget.
- [x] RED: missing or drifted 073 receipt blocks before either arm callback.
- [x] RED: parser/source/Schema60/task/prompt/budget/normalizer drift blocks before calls.
- [x] RED: incomplete or malformed 60-row output blocks before the scoring boundary.
- [x] RED: weak failure prevents strong; strong failure prevents scoring; no retry/fallback.

## Task 2 · Minimal GREEN

- [x] Reuse 073 authority evaluation, 069/072 composition, and existing arm freeze/hash.
- [x] Invoke fixed weak then strong task-local seams once each.
- [x] Emit one immutable pair receipt only after both complete outputs verify.
- [x] Bind weak scoring authority to 071 and strong authority to `UNADMITTED_RAW`.

## Task 3 · Verification and freeze

- [x] Run focused 074 and bounded 073/072/069/071/066 compatibility.
- [x] Run Ruff, strict mypy, OpenSpec strict, diff-check, exact-seven scope and
  private/secret scans.
- [x] Freeze an exact candidate tree/index; do not commit, push, create PR, or run provider.

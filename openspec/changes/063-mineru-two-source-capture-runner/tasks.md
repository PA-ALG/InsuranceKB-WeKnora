# 063 implementation plan

## Task 1: Identity and contract

- [x] Fresh-verify base `23f460d0f910c5e5ea229793ffce17b9db0f7d20`, number063 and strict7.
- [x] Freeze exact terms/rate paths, SHA-256 values, order and provider-not-run boundary.

## Task 2: RED

- [x] Add focused tests for complete preflight, fixed order/count, first-failure stop, second-failure
  partial custody, no retry, secret/path redaction and existing-output rejection.
- [x] Run focused test and record expected compile/behavior failure before implementation.

## Task 3: Minimal GREEN

- [x] Add one task-local command using a package-private capture seam over the existing public API.
- [x] Keep CLI to one output-root flag and keep credentials exclusively in process environment.

## Task 4: Verification and freeze

- [x] Run focused Go tests, vet, OpenSpec063 strict, diff-check and exact scope/privacy gates.
- [x] Freeze a temp-index candidate without commit, push, PR or real provider invocation.

# 079 · Implementation Plan

> Execute inline with strict TDD and verification-before-completion. Provider/model,
> real Golden values, live, PG, WeKnora and full-suite execution are forbidden.

## Task 1 · OpenSpec and RED

- [x] Register 079/080/081 atomically and freeze the exact-seven path budget.
- [x] Specify the public production transport port, opaque authorization and two-stage API.
- [x] RED: successor focused test fails on missing executable composition submission.
- [x] RED: missing authorization, shared identity drift and incomplete output fail closed.
- [x] RED: private-validator use, public-066 exception, malformed external receipt scalar,
  receipt drift, one-arm failure and sealed pair mutation keep Golden reads zero.

## Task 2 · Minimal GREEN

- [x] Implement `execute_and_freeze(...)` by composing 074 through the task-local port.
- [x] Carry the exact composition in each submission and replay both transport receipts.
- [x] Canonically re-freeze only weak as `candidate`; preserve strong candidate output.
- [x] Retain the externally issued 066 strong receipt unchanged; retain and replay the
  public 074 inputs/result without reconstructing either upstream receipt preimage.
- [x] Implement `score_frozen_experiment(...)` so its loader is invoked only after the
  complete sealed receipt replays and public 066 returns exact synthetic-Golden preflight,
  then call 066 normally with real caller-supplied Golden bytes.

## Task 3 · Verification and freeze

- [x] Run focused 079; bounded 067/066/074+079; Ruff; strict mypy; OpenSpec strict.
- [x] Run exact-seven scope, diff, private/secret and real-index-empty checks.
- [x] Record exact RED/GREEN counts and candidate identity; do not commit/push/PR.

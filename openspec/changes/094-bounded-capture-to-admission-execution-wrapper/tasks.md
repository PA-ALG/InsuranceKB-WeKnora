# Tasks

## T1 · Contract and RED

- [x] Freeze exact terms/brochure/rate PDF SHA-256 values and fixed role order.
- [x] Freeze capture executable/module, capture, intake and admission contract hashes.
- [x] Add genuine RED tests for one capture then one 087 call, zero retry/fallback/parallelism.
- [x] Add RED tests for credential secrecy, private modes, no symlink/extra file and safe errors.

## T2 · Minimal implementation

- [x] Add one task-local module/CLI with injected capture executor and 087 adapter.
- [x] Validate the relation receipt before/after capture and the capture tree before 087.
- [x] Preserve allowlisted 087 blocked statuses; never claim Golden or Release.
- [x] Add the concrete no-shell Go executable adapter with credential only in child environment.

## T3 · Verification

- [x] Focused RED → GREEN.
- [x] Run bounded capture/087 contract tests, Ruff and strict mypy.
- [x] Run OpenSpec strict, diff-check, exact scope/mode and private/secret scans.
- [x] Freeze an exact candidate through an independent temp index; no commit/push/PR.

## Stop

- [x] Stop rather than add an eighth path, public framework, provider call or shared child edit.

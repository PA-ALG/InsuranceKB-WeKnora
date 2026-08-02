# 064 · Validation Report

## Identity

- Base/HEAD: `f45b751bf2f88e941e3281f8fb67f863b96f24b9`
- Branch: `codex/064-freeform-arm-evidence-binding`
- Exact scope: seven paths maximum; no 061 path

## Current status

- OpenSpec/contract frozen from the approved Mission.
- RED: focused collection failed because the wished-for freeform DTO/binder/replay
  symbols did not exist.
- Corrective RED: 11 arm-locator scenarios failed because the initial Evidence DTO
  rejected the required 061 locator fields and could not bind them.
- Corrective GREEN: all 11 source/page/block/table/cell/row/column/header/span cases
  pass with exact ParsedDocument replay.
- GREEN: focused 057+064 `62 passed`; bounded 053+057+064 `75 passed`.
- Ruff on the two changed Python paths: `PASS`.
- strict mypy on the two changed Python paths: `PASS`.
- OpenSpec064 strict: `PASS` (telemetry DNS warning only; exit 0).
- diff-check and exact seven-path scope: `PASS`.
- Final candidate is frozen through an isolated temp index; exact tree/index digest is
  reported out-of-band to avoid a self-referential artifact hash.

## NOT RUN

Golden, semantic judge, model, provider, live, parser execution, database, PostgreSQL,
WeKnora, full suite, commit, push, PR, Ready, merge.

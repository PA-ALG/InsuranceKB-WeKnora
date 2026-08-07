# 091 validation report

## Status

`STABLE INTEGRATION CANDIDATE / PROVIDER NOT RUN`

## Identity

- base main: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`
- PR115: `836151c8de5407cebef674780de93d822654e5da`
- PR116: `96d7e02c08f89d4fcaad629b2e8cc8e41dcf7e37`
- 089 candidate tree: `70d32f09069571a8bc8cb9fa8774ea700e2134ad`
- 091 candidate tree: frozen out-of-band in the owner handoff after all gates

## TDD evidence

- baseline 062 focused Go tests: `PASS`.
- Go RED: the same-ZIP custody test failed to compile because the custody bridge
  did not exist; the self-consistent facts/marker count drift test then failed
  against the first implementation.
- Python RED: the closed 083 model rejected the absent marker seam (`5 failed,
  58 passed`); the independently resealed marker-count drift then incorrectly
  passed before pair validation was added.
- Go focused 089/091 tests: `PASS`.
- bounded MinerU 062/082/089/091 regression: `PASS`.
- capture command regression: `PASS`.
- Python 083 focused intake: `66 passed`.
- Ruff and strict mypy for the 083 module/test: `PASS`.
- `go vet` for docparser and capture command: `PASS`.
- OpenSpec 082/083/089/091 strict validation: `PASS` (telemetry flush was
  unavailable and non-gating).
- candidate diff-check and bounded high-signal private/secret review: `PASS`;
  only deliberate negative-test literals were present.

## Not run

Provider/model, Golden, database/PostgreSQL, WeKnora, live and full lanes are not
authorized and were not run.

# 070 · Validation Report

## Identity

- Base/HEAD: `4cfdfd208c5bf94248eaaca8bca7b399871f0558`
- Branch: `codex/070-golden18-human-gate`
- Scope budget: exact seven paths

## Evidence

- Initial RED: test collection failed because the task-local module did not exist.
- Contract RED after the first implementation: `6 failed, 1 passed` exposed invalid C0
  object-type/domain handling; the next run `2 failed, 5 passed` exposed an overly strict
  concrete Ed25519 backend type check. Both were corrected without expanding scope.
- Focused GREEN: `8 passed in 4.87s`.
- Bounded 066 + 070 regression: `31 passed in 76.18s`.
- Ruff exact source/test: `PASS`.
- Strict mypy exact source/test: `Success: no issues found in 2 source files`.
- OpenSpec 070 strict: `valid`.
- Diff-check, exact seven-path scope, private/secret and UTF-8/LF checks: `PASS`.
- The contract freezes authority SHA
  `23816ccdfa9258bb4785ed0d1032c8281c1eda047c7801543b2032649b567dc2`,
  exact P0-seven/P1-eleven order, decision/subject hashes, external named-human Ed25519
  receipt, caller-observed freshness and exact conversation provenance.
- Missing decisions/receipt return typed pending; service/self-report, placeholder,
  stale, foreign signer, output/score/decision/subject/signature/hash drift and explicit
  rejection return typed block. Every result records Release/WeKnora actions as zero.
- Total-control corrective RED reproduced an exact all-strong, validly signed `approve`
  receipt returning `HUMAN_GATE_VERIFIED` (`1 failed`). The successor keeps `strong` as
  a diagnostic choice but returns `WEAK_ARM_NOT_APPROVED` for any strong field and
  `HUMAN_DECISION_REJECTED` for any `reject_both`; only exact eighteen-of-eighteen weak
  decisions plus `approve` may verify.
- Corrective focused GREEN: `9 passed in 0.42s`.
- Corrective bounded 066 + 070: `32 passed in 4.55s`.
- Corrective Ruff and strict mypy: `PASS` / `Success: no issues found in 2 source files`.
- Corrective OpenSpec strict, diff-check, exact seven-path scope, private/secret and
  UTF-8/LF: `PASS`.
- The independently approved corrective tree `72785c9c97ce670dff267f05998ba8e752e3635e`
  was mechanically replayed onto authoritative main `4cfdfd208c5bf94248eaaca8bca7b399871f0558`.
  Main changed only the MinerU converter/test and 061 validation paths; all non-validation
  070 task blobs remained byte-for-byte identical.
- Provider, model, Golden values, DB, PostgreSQL, WeKnora, Release, live and full:
  `NOT RUN`.

This report records a pre-review local checkpoint only. It does not claim approval,
publication authority, production readiness, commit, push or PR delivery.

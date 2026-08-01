# 057 · Validation Report

## Identity

- Base/HEAD: `b3c4a7c661e5c7a61c82b5bc55e79ad580f928df`
- Base tree: reported out of band with the frozen candidate
- Branch: `codex/057-extraction-evidence-verifier-repair`
- Dependency: OpenSpec053/054/056 merged; exact contracts retained
- 054 integration: direct exact DTO binding is GREEN and non-authoritative.
- Frozen temp index:
  `/private/tmp/057-extraction-evidence-verifier-signed-054-final-20260802.index`
- Exact candidate tree/index SHA are reported out of band after this report is
  staged, avoiding a self-referential document hash.

## RED / GREEN evidence

- Module RED: focused collection failed with
  `ModuleNotFoundError: insurance_harness.compiler.evidence_verifier`.
- Value-binding RED: an exact-locator quote containing `90day` incorrectly
  passed a `10000/CNY` candidate; the assertion expected `FAIL` and observed
  `PASS`.
- Corrective RED: five independent focused tests failed for numeric substring,
  range bounds, explicit absence semantics, repair input custody, and manual
  repair-plan completeness/locator scope.
- Signed-boundary RED: positive number, number+unit, and range candidates each
  incorrectly passed a negative quote; the three exact negative-candidate
  controls remained GREEN.
- Signed-boundary GREEN: `6 passed, 26 deselected in 4.60s`.
- 054 exact DTO seam RED: `bind_054_attempt_receipt` was absent after 054 merged;
  the focused assertion failed before the exact adapter was implemented.
- 057 focused GREEN: `32 passed in 8.62s`; no xfail remains.
- 054 + 057 bounded regression: `50 passed in 14.68s`.
- 053 + 054 + 057 bounded regression: `63 passed in 17.96s`.
- Ruff focused: `PASS`.
- strict mypy on the two changed Python files: `PASS`.
- OpenSpec 057 strict: `PASS`.
- `git diff --check`: `PASS`.
- Production import boundary: only standard library, Pydantic, C0 canonical
  hashing and merged 053/054 pure contract imports; no Golden/provider/network/
  DB/filesystem/environment/WeKnora import.
- High-signal secret/private scan: no secret or private path in 057 production
  or test paths; registry/task wording matches only documentation terms.
- Exact scope: seven paths, all `100644`; real index empty and working bytes
  equal the temp-index candidate.

This report does not infer provider, live, DB, PostgreSQL, WeKnora, Golden, or
end-to-end evidence.

## NOT RUN

049 Golden, model/LLM judge, provider, live, database, PostgreSQL, WeKnora,
parser/OCR/VLM, full suite, commit, push, PR, Ready, merge.

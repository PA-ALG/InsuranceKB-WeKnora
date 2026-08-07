# 106 Validation Report

Status: `STABLE LOCAL CANDIDATE / DELIVERY NOT STARTED`

- Base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`.
- Combined 101/103 predecessor tree: `f162939153f8e6dbb95698368cfec17caac4ee18`.
- Genuine RED: focused collection failed with `ModuleNotFoundError` before the
  task-local 106 module existed.
- GREEN: 7 focused tests pass. The future-complete native `text_level` fixture
  produces `SECTION_ANCHOR_EVIDENCE_VERIFIED` and replays through the frozen
  103 authority request. The pinned current 101-shaped terms fixture without a
  native hierarchy fact remains precisely `SECTION_ANCHOR_NOT_AVAILABLE`.
- The focused negatives cover a next-page target, an intervening heading,
  nested levels, header exclusion, missing anchor, page gap, `lines_deleted`,
  request drift and envelope/hash drift. No title or body value is emitted.
- Bounded 053/083/101/103/106 regression: 106 tests pass.
- Ruff: pass. Strict mypy over the module and focused test: pass. OpenSpec 106
  strict: valid. Diff/scope/private/secret gates: pass.
- OpenSpec attempted to flush optional PostHog telemetry after validation and
  logged a sandbox DNS warning; the validator itself returned exit 0 and
  reported the change valid.
- Provider/model/Golden/DB/PG/WeKnora/live/full: NOT RUN / FORBIDDEN.

The candidate emits neither a NATIVE relation nor ADMIT/READY authority. It is
not committed, pushed or published as a PR.

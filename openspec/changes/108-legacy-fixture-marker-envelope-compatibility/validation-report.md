# 108 Validation Report

Status: `STABLE STACKED CANDIDATE`

- Base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`.
- Stacked predecessor tree: `860b3499d4c42a0262b2d732749f0ab55d0a75ff`.
- Real index: empty; provider/model/Golden/DB/PG/WeKnora/live/full/capture:
  NOT RUN / FORBIDDEN.
- RED command: the exact 086 and 092 test modules with the current task-local
  Python source first on `PYTHONPATH`.
- RED result: `22 failed, 1 passed`. Every failure is
  `CaptureIntakeError: CAPTURE_MARKER_ENVELOPE_INVALID`; no test reached and
  changed its original relation/admission assertion.
- GREEN: the two fixture factories now build explicit canonical 091 marker
  envelopes and each 086/092 relation call selects the frozen 102
  marker-preserving replay mode. Brochure remains marker-free; zero-marker and
  invalid-marker cases retain their original typed behavior.
- Focused 086+092: `23 passed`.
- Bounded 083/086/087/092/095/096/098/100/101/102/105: `196 passed`; this is the
  former `174 passed, 22 failed` stack with no new production blocker.
- Ruff on the helper and two modified tests: PASS.
- Strict mypy on the same three files: PASS.
- OpenSpec108 strict: valid.
- Production source changes: none. Every original assertion and expected typed
  reason is unchanged.

Exact candidate tree/index identity, candidate-vs-predecessor diff-check, scope,
privacy and secret scans are recorded by the final frozen checkpoint.

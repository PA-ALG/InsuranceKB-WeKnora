# 067 · Validation Report

## Identity

- Base/HEAD: `414e0384e9ca8cfb74a8f254d144af45c228c192`
- Base tree: `efd98b8428bccc3f8da4d2a69f998ff8cbe72c70`
- Branch: `codex/067-public-single-arm-golden-score`
- Exact scope: seven paths maximum

## Current status

- Fresh registry/open-PR/branch preflight: 067 was unoccupied; open PR count was zero.
- Clean baseline focused 061: `107 passed`.
- TDD API RED: `score_admitted_frozen_arm` and `AdmittedFrozenArmScoreV1` absent.
- TDD behavior RED: `4 failed, 7 passed` before the admission/authority/Golden/
  metrics implementation.
- Corrective RED: `7 failed, 13 passed` for answer-free field serialization,
  admission short-circuit and malformed nested DTOs.
- Corrective focused GREEN: `20 passed`.
- Exact four-file bounded command:
  `uv run --project harness pytest -q harness/tests/test_fixture_candidate_human_batch_059.py harness/tests/test_native_mineru_cloud_adapter_060.py harness/tests/test_596_1_vertical_falsification_061.py harness/tests/test_061_public_single_arm_golden_score_067.py`
- Exact four-file bounded result after corrective: `156 passed` (`149` was the
  pre-corrective count; the earlier `166` came from a five-file command and is not
  used as the four-file gate).
- Ruff on the changed source/test: PASS.
- Strict mypy on the changed source/test: PASS (`2 source files`).
- OpenSpec067 strict validation: PASS (telemetry DNS noise only, exit zero).
- Diff/scope/private/secret/UTF-8-LF and exact temp-index identity: PASS; exact
  values are recorded in the frozen checkpoint report.

## NOT RUN

Golden values, model, provider, live, parser execution, database, PostgreSQL, WeKnora,
full suite, commit, push, PR, Ready, merge.

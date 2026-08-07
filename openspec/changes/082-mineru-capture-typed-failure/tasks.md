# 082 · Implementation Tasks

## T1 · Contract and RED

- [x] Freeze the closed failure-code set and the three-layer propagation boundary.
- [x] Add stage-specific fake-seam REDs before production changes.
- [x] Add runner REDs for fixed prefix/code output and privacy.

## T2 · Converter stage sentinels

- [x] Emit allocation/upload/status/provider-task/budget/download-URL/ZIP/native/
  cross-page sentinels only where the failing stage is mechanically known.
- [x] Preserve ordinary-reader retry and extraction behavior.

## T3 · Capture custody and runner surface

- [x] Preserve recognized converter sentinels; map unrecognized reader failures to
  `CAPTURE_STAGE_UNDETERMINED` without raw detail.
- [x] Distinguish artifact and content custody failures and leave zero final artifact.
- [x] Emit only fixed terms/partial prefix plus a fixed reason code.

## T4 · Verification

- [x] Focused converter/capture/runner tests and bounded MinerU regression.
- [x] Go vet, OpenSpec strict, diff/scope/private/secret and stable exact-tree custody.

## T5 · Real-failure diagnostic corrective

- [x] Add REDs proving the exact projection subreason and downloaded raw ZIP are lost.
- [x] Retain them only as a private, closed, non-admission failure-custody pair while
  keeping the public runner error unchanged.
- [x] Run fresh focused and complete no-provider integration verification.

## Stop conditions

- A provider rerun, retry/fallback, timing/call-sequence change or general error
  framework is required.
- A change outside MinerU converter/capture/runner, their tests, OpenSpec082 and the
  registry is required.

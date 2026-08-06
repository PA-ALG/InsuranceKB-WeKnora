# 082 · Validation Report

## Identity

- Base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`.
- Base tree: `4dac593a13dd9fb26bd2e08f99bc7c544f16b8cb`.
- Branch: `codex/082-mineru-capture-typed-failure`.
- Provider/live/DB/PG/WeKnora/Golden/full: `NOT RUN / FORBIDDEN`.

## Root-cause evidence

- The authorized one-shot reached terms allocation/upload/status, then the runner
  returned only its generic exit-2 error; brochure and rate had zero calls.
- `MinerUCloudReader` currently carries raw stage detail, artifact capture collapses
  reader/result/native failures into `ErrMinerUArtifactCaptureFailed`, and the runner
  collapses that error again into terms/partial generic text.
- `LOG_FORMAT=json` is treated as a literal custom formatter template, but logger
  formatting must not influence the fixed terminal reason surface.

## TDD and verification evidence

- RED: the stage-seam suite reproduced six raw/generic converter failures, three
  artifact-capture collapses and both runner prefix collapses before production
  changes. A bounded regression then reproduced loss of
  `errors.Is(context.DeadlineExceeded)` at the ZIP stage.
- GREEN: the converter/capture/runner focused suite passed after introducing the
  closed reason set. The ZIP deadline regression passed after retaining only the
  fixed system deadline sentinel alongside `ZIP_DOWNLOAD_FAILED`; no arbitrary raw
  cause is retained.
- Focused and bounded MinerU regression:
  `go test ./cmd/mineru-capture-596-1 ./internal/infrastructure/docparser -run
  'Test.*MinerU|TestCaptureMinerU|TestRunThreeSourceCapture|TestStableRunnerError|TestValidateMinerUCapture|TestPublishMinerUCapture' -count=1`
  → both packages `PASS`.
- Targeted deadline/stage regression:
  `go test ./internal/infrastructure/docparser -run
  'TestMinerUArtifactCaptureDeadlineCancelsBlockedZIP|TestMinerUCapturePolicyReturnsFixedStageReasonsWithoutRawDetail' -count=1`
  → `PASS`.
- Final-review delta: the capture boundary now table-tests all nine recognized reader
  sentinels plus unknown fallback, legacy `ErrMinerUArtifactCaptureFailed`, privacy
  and zero-output custody. The ZIP deadline path proves both
  `errors.Is(ErrMinerUZIPDownloadFailed)` and
  `errors.Is(context.DeadlineExceeded)` survive poll and capture normalization while
  runner text remains exactly `ZIP_DOWNLOAD_FAILED`. Only those two fixed sentinels
  are retained; arbitrary raw causes remain stripped. The proposal EOF blank line was
  removed mechanically.
- Final-review targeted command:
  `go test ./internal/infrastructure/docparser ./cmd/mineru-capture-596-1 -run
  'TestMinerUArtifactCaptureDeadlineCancelsBlockedZIP|TestCaptureMinerUNativeStructurePreservesSafeTypedReasonAndCustodyClasses|TestStableRunnerErrorHidesSafeZIPDeadlineSentinel' -count=1`
  → both packages `PASS`.
- `go vet ./cmd/mineru-capture-596-1 ./internal/infrastructure/docparser` → `PASS`.
- `DO_NOT_TRACK=1 openspec validate 082-mineru-capture-typed-failure --strict`
  → `PASS`.
- `git diff --check`, exact-path scope, real-index-empty and high-signal
  private/secret scans → `PASS` at freeze.
- A package-wide diagnostic also showed the runner package passing and only the two
  known local-environment `ResolveRemoteImages` SSRF/127.0.0.1 failures in the
  docparser package; they are outside 082 and were not modified.
- Provider/live/DB/PG/WeKnora/Golden/full calls: `0 / NOT RUN`.

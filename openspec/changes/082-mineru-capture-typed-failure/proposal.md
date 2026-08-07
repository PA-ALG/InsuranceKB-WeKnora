# 082 · MinerU Capture Safe Typed Failure Surface

## Goal

Preserve a deterministic, privacy-safe failure reason from the MinerU Cloud reader
through artifact capture and the exact 596-1 runner. A failed one-shot must say which
mechanically proven stage failed without exposing provider bodies, messages, URLs,
credentials, document content or local paths.

## Scope

- Add a closed set of stable `errors.Is` sentinels for allocation, upload, status,
  provider task, bounded polling, download URL, ZIP download, native structure,
  cross-page projection, structure custody and content custody failures.
- Map capture-policy failures at the boundary where their stage is known. Unknown
  injected or future failures remain typed `CAPTURE_STAGE_UNDETERMINED` rather than
  receiving a guessed stage.
- Preserve the typed sentinel through `CaptureMinerUNativeStructure` with zero success
  artifact on failure.
- For the exact post-download cross-page projection failure only, retain one private
  task-local diagnostic pair: the exact raw ZIP and a metadata file containing only a
  closed subreason plus content identities. This pair is not an admission artifact and
  cannot be consumed by 083/087.
- Make the task-local runner print only the fixed terms/partial prefix and reason
  code, independent of `LOG_FORMAT` and raw error text.
- Prove call counts, fail-fast/no-retry behavior, ordinary-reader compatibility and
  privacy with fake transports and existing seams. Provider calls remain zero.

## Non-goals

No provider rerun, retry/fallback, timeout/poll/call-sequence change, log framework
redesign, general error platform, parser/Schema/Golden/fair-experiment change,
credential/config work, DB/migration, WeKnora deployment or production action.

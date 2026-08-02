# 068 validation report

## Identity and scope

- Base: `414e0384e9ca8cfb74a8f254d144af45c228c192`
- Base tree: `efd98b8428bccc3f8da4d2a69f998ff8cbe72c70`
- Scope ceiling: exactly eight paths; README unchanged
- Real provider/live/PG/full/WeKnora/Golden: `NOT RUN`

## TDD evidence

- RED: runner tests failed to compile because the three-source boundary did not exist; capture tests
  showed v1 omitted content/hash and accepted empty, secret-bearing, and path-bearing text.
- GREEN: the bounded affected MinerU/capture set passes 29 top-level tests / 123 leaf scenarios.
  The evidence contains exact same-read text plus recomputed hash; all three frozen PDFs preflight
  before terms → brochure → rate calls.
- Corrective RED: request/artifact omitted the approved ParseAttempt generation, and content guards
  admitted `/home`, `/var`, `/Volumes`, Windows-drive, and UNC absolute paths.
- Corrective GREEN: exact `2/bounded_upgrade/generation=0` is mandatory before reader construction
  and is bound into the artifact and independently recomputable capture-identity hash; adversarial
  cross-platform paths fail before publication while ordinary slash/URL text remains admitted.
- Final RED/GREEN: a sanitized JSON string value containing an escaped UNC path was accepted by the
  encoded-byte scan; recursively checking decoded JSON string values now rejects it before publish,
  while the detector itself continues to admit ordinary slash and HTTP(S) string values.

## Gates

- Focused Go tests: `PASS` (two affected packages; provider fake only)
- General affected-package run: the task-local command package passed; the broader docparser package
  was environment-blocked by the existing `httptest` IPv6 listener prohibition at
  `TestResolveRemoteImages_NormalDownload` before completing. The bounded affected set above is
  green and no network workaround was introduced.
- Go vet: `PASS` (two affected packages)
- OpenSpec068 strict: `PASS`
- Diff/scope/private/secret: `PASS`
- Commit/push/PR: `NOT RUN`

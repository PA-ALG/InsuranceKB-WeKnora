# 089 validation report

Status: `STABLE CANDIDATE / PROVIDER NOT RUN`

## Identity

- Base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`
- Base tree: `4dac593a13dd9fb26bd2e08f99bc7c544f16b8cb`
- Branch: `codex/089-mineru-typed-cross-page-marker-provenance`
- Open PRs at preflight: #115/#116; no production-file overlap, README mechanical only.

## Baseline

- Existing affected 062 projection/capture tests: `PASS`.
- provider/Golden/DB/WeKnora/live/full: `NOT RUN / FORBIDDEN`.

## RED/GREEN evidence

- Initial RED: focused build failed because the companion contract, projector and replay
  functions did not exist.
- Privacy RED: without bounded node-type privacy, a private-shaped node type entered the
  companion. Duplicate caller marker membership is covered by the exact replay mutation set.
- GREEN: one nested node carrying both `cross_page=true` and `lines_deleted=true` produces
  two non-colliding typed items bound to exact page/type/local-index/path hash.
- GREEN: source/parser/version/raw ZIP/native member and self-consistently re-sealed
  kind/type/page/path/local-index mutations all fail exact raw replay.
- GREEN: companion JSON contains no body, HTML/Markdown, bbox, URL, member name/path,
  endpoint, relation or admission claim.

## Gates

- Focused 089: `PASS`.
- Bounded 062/089 projection and capture regressions: `PASS`.
- 083 compatibility: `PASS` by unchanged capture envelope and unchanged 062 v1 DTO/seal;
  PR #116 files are not modified or imported by 089.
- Go vet (`internal/infrastructure/docparser`): `PASS`.
- OpenSpec089 strict: `VALID`; telemetry flush was unavailable and non-gating.
- candidate diff-check/exact seven-path scope/private/secret: `PASS`.
- provider/Golden/DB/WeKnora/live/full: `NOT RUN / FORBIDDEN`.

## Authority boundary

The companion proves only a typed native marker and its exact artifact/path custody. It does
not supply or claim a source/target endpoint or relation. Unique endpoint selection and any
derived relation remain owned by 086.

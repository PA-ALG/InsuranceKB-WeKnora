# Change 104: Marker authority readiness wiring

## Why

OpenSpec 101 exposes reviewed marker custody as an immutable public `UNBOUND`
authority. OpenSpec 098 derives the rate-table endpoint pair, while OpenSpec 099
owns the pre-capture readiness decision. Those public contracts are not yet
mechanically composed, so 099 still reports the obsolete 091-authority gap.

## What changes

- Replay and cross-bind the actual 101 authority before using marker facts.
- Invoke the actual 098 endpoint-pair builder for rate-table evidence.
- Translate actual 101/098 identities into 099 dependency evidence.
- Report `TERMS_SECTION_BINDING_UNAVAILABLE` first until 103 provides the
  missing terms-section authority.
- Keep future-complete composition explicitly `TEST_ONLY` and never authorize
  capture.

## Non-goals

No relation inference, parser, capture, credential access, private artifact
read, provider/model/Golden/DB/PG/WeKnora call, workflow platform, or edits to
the frozen 101/098/099 implementations.

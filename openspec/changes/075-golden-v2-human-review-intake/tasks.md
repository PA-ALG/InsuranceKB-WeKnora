# 075 · Implementation Tasks

## T1 · OpenSpec and RED

- [x] Freeze exact v1/workbook/source identities, ordered P0-seven/P1-eleven tuple,
  excluded fields, named-human authority and zero-write boundary.
- [x] Confirm strict OpenSpec validation fails while the normative delta is incomplete.
- [x] Add the focused test and confirm collection fails because the task-local module does
  not exist.

## T2 · Decision intake

- [x] Validate exact identity, order, cardinality, priority and record digest bindings.
- [x] Implement explicit five-choice decisions with no inference or default.
- [x] Keep `needs_expert` and every `not_applicable` pending with zero successor; no
  mapping is implemented in 075.
- [x] Validate complete replayable custom GoldenRecord semantics.

## T3 · External named-human receipt

- [x] Bind exact decisions, identities, actor, freshness and conversation provenance.
- [x] Expose canonical signing bytes and Ed25519 verification only.
- [x] Reject service/self, placeholder, foreign, stale, future and drifted receipts.

## T4 · Pure materialization

- [x] Hash actual formal v1 JSONL bytes and derive the sixty records before formal
  materialization.
- [x] Materialize only after internally replaying the original receipt, authority, time
  and actual request decisions; never trust a supplied verification DTO.
- [x] Preserve sixty-record ordering and the forty-two non-review record hashes.
- [x] Emit only an in-memory tuple and domain-separated successor receipt.

## T5 · Bounded verification

- [x] Focused 075 tests, bounded GoldenRecord/build-release and 070 tuple regressions.
- [x] Ruff, strict mypy, OpenSpec strict and diff-check.
- [x] Exact-six-path, absolute/private-path, secret and forbidden-surface scans.
- [x] Record all provider/model/Golden write/DB/WeKnora/live/Release actions as
  `NOT RUN / FORBIDDEN`.

## T6 · Final-review blockers

- [x] Reproduce forged verification DTO and post-signature decision replacement bypasses.
- [x] Remove verification DTO authority and replay the original receipt inside
  materialization.
- [x] Reject arbitrary synthetic bytes on the formal path and label the private fixture
  path `SYNTHETIC_TEST_ONLY`.
- [x] Reject bounded placeholder reasons and make `not_applicable` always pending.
- [x] Rerun every bounded/static/OpenSpec/scope/privacy gate and freeze a successor tree.

## T7 · Punctuation-variant final-review blocker

- [x] Reproduce `TODO!`, `TBD???`, `待定。` and `未知！` reaching ready state.
- [x] Normalize Unicode/whitespace and strip only surrounding common Chinese/ASCII
  punctuation before exact placeholder comparison.
- [x] Preserve substantive reasons that merely contain placeholder vocabulary.
- [x] Rerun focused/bounded/static/OpenSpec/scope/privacy gates and freeze a fresh
  successor temp index.

## Stop conditions

- A real business decision, signer, completed workbook or Golden v2 write is required.
- A provider, model, score gate, DB, migration, WeKnora, live or production action is
  required.
- A seventh owner path or a change to Golden v1 is required.

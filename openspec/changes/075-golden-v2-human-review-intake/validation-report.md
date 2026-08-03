# 075 · Validation Report

## Identity

- Coordination base/HEAD:
  `dc80a143ed4f6d315fe775f70eb52c448c95816d`
- Branch: `codex/075-golden-v2-human-review-intake`
- Scope budget: exact six owner paths

## Evidence

- Final review of candidate tree
  `573f587ca5b95f18ed43a358b23cd40eef76e3b3`: `NOT APPROVED`;
  classification `BLOCKER=3 / MAINLINE DRIFT=0 / DETAIL TRAP=unmapped
  not_applicable wording`.

- Initial OpenSpec RED: strict validation exited 1 because the intentionally incomplete
  normative file had no delta section or scenario.
- Initial implementation RED: focused test collection exited 2 because the task-local
  module did not exist.
- Subsequent receipt and materialization REDs exposed their missing APIs; a focused
  mutation RED then proved that a recommendation could be changed after receipt without
  blocking. The minimal implementation now rechecks the selected record digest at the
  materialization boundary.
- The rejected tree's prior focused/static evidence is superseded and is not approval.
- Corrective RED: a publicly constructed `HUMAN_DECISIONS_VERIFIED` result materialized,
  and replacing actual decisions after signature while retaining the declared hash also
  materialized.
- Corrective RED: arbitrary synthetic bytes reached only a generic record-set rejection;
  the public interface had no formal artifact-byte identity proof.
- Corrective RED: seven bounded placeholder reasons were accepted, and
  `not_applicable` did not expose its always-pending Mission semantics.
- Corrective focused 075: 38 passed.
- Corrective bounded 075 + GoldenRecord/build-release + 070 authority-tuple regression:
  53 passed.
- Corrective Ruff exact source/test and strict mypy exact source/test: PASS.
- Corrective OpenSpec 075 strict, diff-check, exact-six-path, private/absolute-path,
  secret and forbidden-surface scans: PASS.
- The formal public entry now hashes actual supplied v1 bytes before parsing; arbitrary
  synthetic bytes produce `V1_ARTIFACT_SHA256_MISMATCH`. The private fixture path is
  bound as `SYNTHETIC_TEST_ONLY` and cannot accept a verification DTO as authority.
- Independent review of successor tree
  `6bbcb4c2a26123c5f2121fe6a7d8f53588415067`: `NOT APPROVED`; one mechanical
  placeholder punctuation blocker remained.
- Corrective RED: `TODO!`, `TBD???`, `待定。` and `未知！` all reached
  `READY_FOR_EXTERNAL_APPROVAL`, while the substantive-reason positive fixture passed.
- Punctuation successor focused 075: 43 passed.
- Punctuation successor bounded 075 + GoldenRecord/build-release + 070 authority-tuple
  regression: 58 passed.
- Punctuation successor Ruff, strict mypy and OpenSpec 075 strict: PASS.
- Exact-six diff/scope, private/absolute-path, secret and forbidden-surface scans: PASS.
- Provider, model, scoring, Golden write, DB, migration, WeKnora, live, Release activation
  and production: `NOT RUN / FORBIDDEN`.

This report records an unapproved local implementation checkpoint only. It does not claim
business approval, Golden v2 creation, commit, push, PR or production readiness.

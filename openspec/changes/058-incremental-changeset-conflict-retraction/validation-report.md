# 058 validation report

## Candidate identity

- Base/HEAD/origin-main: `8f2f933c0c23e8f1dcc2d9073b463c62240ba54e`
- Base tree: `345763ffdbba873436ba0fa417c42facba64aeb4`
- Branch: `codex/058-incremental-changeset-conflict-retraction`
- Delivery: Draft PR `#86`; this report records the final pre-push successor.

## Pre-implementation gates

- Initial GitHub open PRs were #84 (054) and #83 (056); neither owned 058 paths.
- Registry: 058 was free before this change.
- Worktree/index: clean and isolated at creation.
- Bounded baseline:
  `uv run pytest tests/test_canonical_envelope_034.py
  tests/test_material_profile_template_binding_052.py
  tests/test_parsed_document_contract_053.py -q` → `79 passed in 5.35s`.

## TDD and implementation evidence

- Predecessor tree `3153f7648ecb29dd19434ddb0cb946e82a18eddc`
  was independently rejected and is historical only.
- Initial focused RED failed during collection with `ModuleNotFoundError` for
  the 058 incremental compiler module.
- A separate scope RED proved that an empty normalized conditions tuple was
  incorrectly rejected; the minimal validator correction made it GREEN.
- Corrective RED reproduced caller-self-authority, cross-registration,
  malformed digest/identity, mixed baseline, model-copy bypass, empty-root hash,
  and eager SQLAlchemy import failures (`18 failed / 1 passed`).
- Corrective focused 058: `19 passed`.
- Bounded C0/052/053/058 compatibility: `98 passed`.
- Reviewer-fresh predecessor bounded 052/053/058 compatibility: `61 passed`
  (correcting the earlier recorded `51`).
- Final semantic-token RED: `19 failed / 3 passed`; the independent unknown
  support RED: `1 failed`.
- Final focused 058 after minimal GREEN: `42 passed`.
- Final bounded 052/053/058 after minimal GREEN: `84 passed`.
- Final bounded C0/052/053/058 after minimal GREEN: `121 passed`.
- Ruff and strict mypy on all four changed production modules plus the focused
  test: PASS; no unused ignore remains.
- The first PR head exposed two full-CI-only regressions in the attempted lazy
  rewrite of the legacy knowledge facade: strict mypy treated historic exports
  as `object`, and the deterministic API-contract test required all 107
  `__all__` members to remain initialized. Both REDs are closed by restoring the
  legacy package initializer byte-for-byte and placing 058 in the dedicated
  `knowledge_compiler` package.
- Final isolated 058 import loads no SQLAlchemy, legacy knowledge models, or
  publisher, while the historic 107-name knowledge API contract remains intact.
- Final focused plus historic API-contract corrective: `43 passed`.
- Final bounded C0/052/053/058 plus historic API-contract corrective:
  `122 passed`.
- Full strict mypy: `384 source files` PASS.
- OpenSpec058 strict, `git diff --check`, exact10 scope, private/secret scans:
  PASS.
- WIP was stashed with untracked files, the branch was fast-forwarded from
  `16ae691d...` to `b3c4a7c...` and then to `8f2f933c...`, then restored. The
  only final replay conflict was README and it was resolved mechanically to
  preserve merged 056/057 status plus the 058 registry entry; the 058
  source/test files import none of the merged 054/056/057 implementation.
- Earlier approved content was committed and pushed to Draft PR `#86`. The
  final corrective successor is frozen in the real index; its tree identity is
  intentionally recorded by the external delivery checkpoint rather than
  self-referenced from this report. It is not yet committed or pushed.
- MAINLINE DRIFT: 0 after the authorized ff-only replay to `8f2f933c...`.

## Explicitly not run

- full, provider/model, live, PostgreSQL/DB, migration, WeKnora;
- final corrective successor commit/push, Ready, or merge.

# 076 · Validation Report

## Identity

- Base/HEAD: `dc80a143ed4f6d315fe775f70eb52c448c95816d`
- Branch: `codex/076-candidate-wiki-member-manifest-compiler`
- State: `IMPLEMENTATION COMPLETE / FROZEN DRAFT-ONLY CANDIDATE`
- Exact path ceiling: 8; registry is reserved by the coordination base and is not owner-writable.

## TDD evidence

- OpenSpec RED: strict validation failed because CWM1 had no required `#### Scenario`.
- Focused implementation RED: test collection failed with `ModuleNotFoundError` for the absent
  `candidate_wiki_manifest` module.
- Cross-language vector RED: focused Python test failed because the frozen JSON vector did not yet
  exist.
- Corrective REDs reproduced: arbitrary 059 candidate snapshot hash; truncated/forged base and
  attacker-created raw binding; VerificationBatch/receipt custody drift; assignment-shaped secret
  value/Evidence; decomposed Unicode escaping the typed boundary.
- Corrective GREEN: exact 057 Candidate bijection/full locator plus VerificationBatch/receipt
  custody, task-local independent base authority port/closed payload, bounded assignment/header
  secret rejection and NFC typed failure.
- Focused GREEN: `23 passed`.
- Bounded 057/058/059/076 GREEN: `141 passed`.
- Unchanged-Go vector: `TestCandidateWikiManifest076PythonVectorMatchesUnchangedGoCanonicalizer`
  passed on an incremental non-ASCII fixture and reproduced the exact Python manifest bytes and
  digest.

## Gates

- Ruff on the new Python module/test: `PASS`.
- strict mypy on the new Python module/test: `PASS`.
- OpenSpec 076 strict: `PASS`.
- `git diff --check`, exact-eight-path scope, private/secret scan and JSON parse: `PASS`.
- Exact candidate tree and independent temp-index SHA are reported out of band after final freeze
  to avoid self-referential document identity.

## NOT RUN

provider, model, Golden scoring, DB, PostgreSQL, WeKnora, live, production actions, full suite,
commit, push, PR, Ready and merge.

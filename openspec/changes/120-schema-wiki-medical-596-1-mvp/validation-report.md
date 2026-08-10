# 120 · Validation Report

Status: `IMPLEMENTATION-IN-PROGRESS / LANE-B-GREEN`

## Identity and scope

- Coordination base: `db6fd60bbf9cf4529db43ded24934c7bbdd422f9`
- Plan commit: `db0e52320e461a13863d8c803cd80d255c25b815`
- OpenSpec Task 0 commit: `a865c1066c15d7bb67ace3ed261d0ee0875663c7`
- Lane A A1 corrective authority: commit
  `acc2ccd36c1aec877dc0749ee3db91a6978f09b0`, tree
  `39bbcd2c594f2508bdc7aa56ffd84ab4c50d632c`.
- Branch: `codex/schema-wiki-compiler`
- Lane B implementation scope: medical pack/compiler, their two focused tests and one
  immutable release vector; this report and task checklist are mechanically synchronized.
- Provider/model, Golden scoring, DB, WeKnora, migration, activation and live:
  `NOT RUN`.

## RED evidence

Before these files existed, strict validation was run as:

`openspec validate 120-schema-wiki-medical-596-1-mvp --strict`

It exited `1` with `Unknown item '120-schema-wiki-medical-596-1-mvp'`. Subsequent telemetry
DNS noise did not alter that load-bearing missing-change RED.

## GREEN gates

- Strict OpenSpec: `PASS` (`Change '120-schema-wiki-medical-596-1-mvp' is valid`).
- `git diff --check`: `PASS`.
- A1 corrective delta: Python control/C0/vector gates `36 PASS`; Go control/unknown/
  typed-roundtrip/vector gates `PASS`.
- Lane B bounded pytest (`medical pack`, `release compiler`, existing Candidate report):
  `57 PASS`.
- Lane B Ruff: `PASS`.
- Lane B strict mypy over two production modules and two focused tests: `PASS`.
- Immutable release vector: `69,648` bytes; SHA-256
  `bc947b728f69596a56b1c5a64ab3a68ed27150db3995c35175088c05e7c17e2a`.
- Task 0 exact five-path scope and README status: `PASS`.

Lane B fixture acceptance uses a real public-factory-sealed Candidate and a synthetic trusted
citation-authority port. It does not claim that a real Candidate, the production exact-revision
join, preparation, activation, release tables, deployment or the end-to-end MVP exists.

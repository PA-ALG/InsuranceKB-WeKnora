# 077 · Validation Report

Status: `SECOND CORRECTIVE SUCCESSOR / DISPLAY ONLY`

## Identity

- Coordination base/HEAD: `dc80a143ed4f6d315fe775f70eb52c448c95816d`
- Parent `origin/main`: `d7e8c524bc81c4ff1cc5ff6e009565d0c4730a89`
- Branch: `codex/077-release-human-review-dossier`
- Scope budget: exact seven paths; registry unchanged

## Evidence

- Clean relevant baseline: 057/058/059/070 = `127 passed`.
- Incomplete OpenSpec RED: strict validation rejected the proposal because no capability
  delta/spec existed.
- Complete OpenSpec strict: `PASS` (`077-release-human-review-dossier` valid).
- Focused RED: collection failed with `ModuleNotFoundError` for the absent dossier module.
- Predecessor tree `bbbedd57816ae4ea25eff0e2490aeb42bae5b81f` was not approved:
  fact/value and Evidence/verification parse edges were incomplete, and HTML omitted
  load-bearing Evidence and repair/gap custody.
- Corrective RED: five focused cases reproduced acceptance of a recomputed foreign fact
  value, three independently foreign parse identities, and incomplete HTML custody.
- Successor `aa0f8e909c7cfab7e8258a1ba9318695d91b6704` was not approved because
  Evidence source revision only needed support membership and support-scope ProductVersion
  was not compared with the fact/Candidate scope.
- Second corrective RED: two fully recomputed 059 fixtures were accepted with a foreign
  Evidence source revision or foreign support-scope ProductVersion.
- Focused GREEN: `19 passed` covering complete categories, locator/hash custody,
  deterministic JSON, escaped static HTML and pure display-only imports.
- Bounded 057/058/059/070 plus 077: `146 passed`.
- Ruff: `All checks passed!`; strict mypy: no issues in the two production modules and
  focused test.
- `git diff --check`, exact-seven-path scope and high-signal private/secret scans: `PASS`.
- Provider/model, Golden scoring, DB, PostgreSQL, WeKnora, Release, live and full:
  `NOT RUN / FORBIDDEN`.

This file records a local pre-review checkpoint only. It does not claim approval,
publication authority, commit, push or PR delivery.

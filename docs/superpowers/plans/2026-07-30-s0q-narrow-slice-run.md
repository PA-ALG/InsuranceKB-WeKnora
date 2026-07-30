# S0-Q Narrow-Slice Falsification Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine, on exactly two real WeKnora-parsed PDFs, one ProductVersion, and four fields, whether the current weak-model knowledge-compilation path is feasible without manual text cleanup or strong-model assistance.

**Architecture:** Extend the existing WeKnora admin adapter only enough to read the approved W1 revision descriptor and exact-attempt chunks. Freeze those responses into canonical, digest-verified bundles, expose them through one narrow `DocumentSource`, and run one bounded A–D diagnostic from a thin S0-Q runner. Every phase fails closed: no provider call before input and model-profile admission, no Wiki mutation, and no new platform, migration, workflow, principal, or generic model router.

**Tech Stack:** Python 3.12, Pydantic v2, httpx, existing Insurance Harness compiler/source contracts, pytest, Ruff, mypy, OpenSpec CLI, pinned local WeKnora `80a5003`-capability images.

---

## Fixed limits

- Source PDFs:
  - `dataset/shouxian_product/平安e生保（尊享版）医疗保险/保险条款.pdf`
  - `dataset/shouxian_product/平安e生保（尊享版）医疗保险/产品说明书.pdf`
- ProductVersion: `596-1`.
- Fields: `产品特色`, `免赔额`, `保证续保`, `宽限期`.
- Formal weak chain strong-model call limit: zero.
- Live operations: one scratch RAW KB capture and one bounded provider run, each only after its preceding admission gate.
- Explicitly excluded: Wiki publication, Release/S0-R changes, database migration, full suite, PostgreSQL, load testing, provider fallback, legacy cleanup, second corpus, prompt-search loop.

## Task 1: Freeze the run authorization

**Files:**

- Create: `docs/superpowers/plans/2026-07-30-s0q-narrow-slice-run-mission-card.md`
- Modify: `openspec/changes/047-s0q-quality-feasibility/tasks.md`

- [ ] Write the Mission Card with exact owner branch/base, two source paths and SHA-256 values, ProductVersion, four fields, fixed phase gates, allowed live calls, cleanup rule, stop conditions, and non-goals.
- [ ] Mark R4 authorized while leaving R1–R3 and R5–R6 unchecked until evidence exists. Do not rewrite the already approved 047 contract.
- [ ] Verify the authorization is documentation-only and internally consistent:

```bash
openspec validate 047-s0q-quality-feasibility --strict
git diff --check
```

Expected: both commands exit 0; no README, registry, migration, workflow, Release, or Wiki path appears.

- [ ] Commit:

```bash
git add docs/superpowers/plans/2026-07-30-s0q-narrow-slice-run-mission-card.md \
  openspec/changes/047-s0q-quality-feasibility/tasks.md
git commit -m "docs(047): authorize narrow-slice quality run"
```

## Task 2: Add exact W1 reads and scratch cleanup to the existing admin adapter

**Files:**

- Modify: `harness/src/insurance_harness/adapters/weknora/admin_client.py`
- Create: `harness/tests/test_s0q_047.py`

- [ ] Add failing tests for:
  - `GET /api/v1/knowledge/:id/revision`;
  - `GET /api/v1/knowledge/:id/revisions/:attempt/chunks`;
  - `DELETE /api/v1/knowledge-bases/:id` for the exact scratch KB only;
  - exact knowledge/attempt matching;
  - malformed or incomplete W1 identity rejected rather than defaulted;
  - response pagination cannot silently mix attempts.

Run:

```bash
cd harness
uv run pytest -q tests/test_s0q_047.py
```

Expected: FAIL because the W1 DTOs/methods do not exist.

- [ ] Add the smallest typed DTOs, two read-only methods, and one exact-ID
  `delete_knowledge_base` cleanup method to `WeKnoraAdminClient`. Reuse its
  authentication, request, error, and pagination behavior. The runner, not
  this client, owns the fixed scratch-name/ID safety check. Do not add upload
  orchestration or a second HTTP client.
- [ ] Rerun the test. Expected: PASS.
- [ ] Run focused compatibility checks:

```bash
cd harness
uv run pytest -q tests/test_s0q_047.py tests/test_local_live_provisioning_023.py
uv run ruff check src/insurance_harness/adapters/weknora/admin_client.py tests/test_s0q_047.py
uv run mypy src/insurance_harness/adapters/weknora/admin_client.py
```

Expected: PASS. If a pre-existing unrelated failure occurs, record it and narrow to the affected adapter tests; do not start a cleanup.

- [ ] Commit:

```bash
git add harness/src/insurance_harness/adapters/weknora/admin_client.py \
  harness/tests/test_s0q_047.py
git commit -m "feat(047): read exact WeKnora W1 revisions"
```

## Task 3: Freeze and validate canonical input bundles

**Files:**

- Create: `harness/src/insurance_harness/s0q_047.py`
- Modify: `harness/tests/test_s0q_047.py`

- [ ] Add failing tests for:
  - canonical JSON and stable SHA-256 independent of mapping insertion order;
  - source path, byte length, source SHA-256, knowledge ID, parse attempt, parser/build/chunker identity, page order, chunk IDs, and W1 manifest are mandatory;
  - one missing identity or mismatched digest returns `BLOCKED_ON_INPUT`;
  - duplicate/missing/out-of-order pages and chunks are rejected;
  - page/table anchors must point into the frozen exact-attempt content;
  - no draft, local PDF parse, or manually cleaned text can satisfy admission.

Expected initial result:

```bash
cd harness
uv run pytest -q tests/test_s0q_047.py
```

FAIL because the bundle model and validator do not exist.

- [ ] Implement one narrow module containing immutable Pydantic models, canonical serialization/digest helpers, fixed error buckets, and input admission. Do not introduce a database, registry, plugin protocol, or general experiment framework.
- [ ] Rerun the focused test. Expected: PASS.
- [ ] Commit:

```bash
git add harness/src/insurance_harness/s0q_047.py harness/tests/test_s0q_047.py
git commit -m "feat(047): admit immutable W1 quality bundles"
```

## Task 4: Expose only the frozen bundle through `DocumentSource`

**Files:**

- Modify: `harness/src/insurance_harness/s0q_047.py`
- Modify: `harness/tests/test_s0q_047.py`

- [ ] Add failing tests proving:
  - the adapter yields only the frozen revision and exact-attempt chunks;
  - page and Evidence identities are deterministic;
  - terms page 31 preserves the complex-table anchor;
  - an absent table/page anchor fails as `input_integrity` or `candidate_region`;
  - no source reread or live WeKnora call occurs after bundle freeze.

- [ ] Implement the minimal existing-`DocumentSource` adapter in `s0q_047.py`, mapping bundle data into existing immutable source models.
- [ ] Run:

```bash
cd harness
uv run pytest -q tests/test_s0q_047.py tests/test_source_weknora_017.py
uv run ruff check src/insurance_harness/s0q_047.py tests/test_s0q_047.py
uv run mypy src/insurance_harness/s0q_047.py
```

Expected: PASS.

- [ ] Commit:

```bash
git add harness/src/insurance_harness/s0q_047.py harness/tests/test_s0q_047.py
git commit -m "feat(047): expose frozen W1 source"
```

## Task 5: Capture the two real W1 bundles

**Files:**

- Create: `harness/scripts/run_s0q_047.py`
- Modify: `harness/tests/test_s0q_047.py`
- Create after successful capture only:
  - `openspec/changes/047-s0q-quality-feasibility/artifacts/input-manifest.json`
  - `openspec/changes/047-s0q-quality-feasibility/artifacts/terms-w1.json`
  - `openspec/changes/047-s0q-quality-feasibility/artifacts/brochure-w1.json`
- Create on every capture attempt:
  - `openspec/changes/047-s0q-quality-feasibility/artifacts/input-capture-report.json`

- [ ] Add failing command-level tests proving `capture`:
  - accepts only the two fixed repository inputs;
  - creates/reuses only a dedicated scratch RAW KB;
  - waits for exactly one completed current parse attempt;
  - recomputes source and W1 manifest digests before writing;
  - writes atomically only after both bundles pass admission;
  - deletes only the exact scratch KB ID on success or failure;
  - always writes a non-secret capture report containing the verdict, exact
    failure bucket/reason, and cleanup state;
  - never initializes a model/provider client.

- [ ] Implement only the `capture` subcommand, reusing current local-live provisioning/admin helpers. Keep later diagnostic orchestration behind a separate subcommand.
- [ ] Run deterministic tests and static checks:

```bash
cd harness
uv run pytest -q tests/test_s0q_047.py
uv run ruff check scripts/run_s0q_047.py src/insurance_harness/s0q_047.py tests/test_s0q_047.py
uv run mypy scripts/run_s0q_047.py src/insurance_harness/s0q_047.py
```

Expected: PASS.

- [ ] Preflight the pinned runtime without printing credentials: confirm exact app/docreader image digests, authenticated admin configuration presence, scratch KB target, and that both repository PDF digests match the Mission Card.
- [ ] Run one bounded live capture:

```bash
cd harness
uv run python scripts/run_s0q_047.py capture \
  --output ../openspec/changes/047-s0q-quality-feasibility/artifacts
```

Expected success: two admitted bundles and one top-level manifest, with source/W1 digest checks PASS and the terms-page-31 table anchor present.

Expected fail-closed result: emit `BLOCKED_ON_INPUT` plus the exact missing
identity/structure and cleanup state. Skip Tasks 6–7, then execute the
blocked-only path in Task 8 so the valid falsification result is reviewed and
delivered. Do not access the provider, synthesize replacement input, tune a
prompt, or widen implementation.

- [ ] Independently recompute all three JSON digests and visually compare the recorded page/table anchors with the two source PDFs.
- [ ] Commit the runner/tests and exact capture report for either an admitted
  bundle or a valid `BLOCKED_ON_INPUT` result. Add the two bundles and input
  manifest only when capture succeeds:

```bash
git add harness/scripts/run_s0q_047.py harness/src/insurance_harness/s0q_047.py \
  harness/tests/test_s0q_047.py \
  openspec/changes/047-s0q-quality-feasibility/artifacts
git commit -m "feat(047): capture real WeKnora quality inputs"
```

## Task 6: Bind the full-Golden projection and closed model budgets

**Files:**

- Create only after input admission and full-Golden approval:
  - `openspec/changes/047-s0q-quality-feasibility/artifacts/golden-projection.json`
  - `openspec/changes/047-s0q-quality-feasibility/artifacts/run-profile.json`
- Modify: `harness/tests/test_s0q_047.py`

- [ ] Bind one immutable, approved full product Golden artifact identity/digest.
  Historical WIP coverage is insufficient. R2 remains incomplete until the
  separate full-Golden Mission has covered all 60 current extractable medical
  fields with `gpt-5.6-sol`, Evidence verification, human approval, and an
  immutable artifact identity/digest.
- [ ] Freeze a projection that references exactly these four records in that
  full Golden by field/record identity:
  - `产品特色` / `zh_6a3bd6cdbf`: `present A`;
  - `免赔额` / `zh_0612362268`: `typed-present B`;
  - `保证续保` / `zh_74aa1b9c93`: `absent_explicitly`;
  - `宽限期` / `zh_d62301d84c`: `unknown` and must abstain.
  The projection SHALL NOT duplicate expected values, Evidence, or oracle
  spans into a second four-field Golden; it resolves them from the exact
  approved full artifact.
- [ ] Add tests rejecting an unapproved/WIP full Golden, a mismatched artifact
  digest, a missing/duplicate record identity, or copied four-field values.
- [ ] Freeze prompt/schema digests, temperature, seed if supported, timeouts, maximum calls, retry count, and manual active-time ceiling.
- [ ] Resolve and record one immutable Bailian weak-model identity and one immutable strong diagnostic identity. A rolling alias without provider/deployment attestation is insufficient.
- [ ] Add tests proving:
  - the formal weak chain rejects any strong-model client;
  - any missing/rolling model identity, open call budget, or unbounded retry remains `BLOCKED_ON_INPUT`;
  - the strong B arm has a separate finite budget and cannot feed its output into another arm.
- [ ] If an immutable model identity cannot be proven, stop after the valid W1 bundle with `BLOCKED_ON_INPUT`; do not guess an ID or call the provider.
- [ ] On that fail-closed result, write the exact profile-admission reason into
  the capture/run evidence, skip Task 7, and execute Task 8's blocked-only
  delivery path.
- [ ] If admitted, mark R1–R3 complete and commit:

```bash
git add openspec/changes/047-s0q-quality-feasibility/artifacts \
  openspec/changes/047-s0q-quality-feasibility/tasks.md \
  harness/tests/test_s0q_047.py
git commit -m "docs(047): freeze quality projection and budgets"
```

## Task 7: Run the bounded A–D falsification

**Files:**

- Modify: `harness/src/insurance_harness/s0q_047.py`
- Modify: `harness/scripts/run_s0q_047.py`
- Modify: `harness/tests/test_s0q_047.py`
- Create after an admitted run:
  - `openspec/changes/047-s0q-quality-feasibility/artifacts/run-results.json`

- [ ] Add failing deterministic/replay tests for:
  - A: oracle span → extraction and typed normalization;
  - B: fixed span/schema → weak output versus isolated strong diagnostic;
  - C: fixed raw output → normalizer and comparator;
  - D: fixed typed Claim → Evidence verifier;
  - field-level results retain attempt, fixed-input digest, tri-state value, Evidence, bucket, abstention, manual actor/reason/active duration;
  - verdict PASS only when all four fields and all four arms pass;
  - any failure is retained by field and bucket and cannot be averaged away.
- [ ] Implement one `diagnose` subcommand by composing existing Harness compiler/normalizer/comparator/Evidence behavior where available. Add only thin S0-Q-specific glue for the fixed four-field matrix.
- [ ] Run replay/deterministic tests first. Expected: PASS.
- [ ] Run the single bounded provider command only after profile admission:

```bash
cd harness
uv run python scripts/run_s0q_047.py diagnose \
  --artifacts ../openspec/changes/047-s0q-quality-feasibility/artifacts
```

Expected: one immutable result file. Strong-model calls appear only in B and never in the formal feasible numerator.

- [ ] Classify the result:
  - all four fields and A–D pass within budgets:
    `KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`;
  - otherwise: retain exact failed fields and one of
    `input_integrity | candidate_region | product_version | extraction |
    normalization | comparator | evidence_verifier | abstention`.
- [ ] Do not retry outside the frozen budget. A correction is allowed only for the directly demonstrated bottleneck and must rerun the same fixed slice.
- [ ] Commit:

```bash
git add harness/src/insurance_harness/s0q_047.py harness/scripts/run_s0q_047.py \
  harness/tests/test_s0q_047.py \
  openspec/changes/047-s0q-quality-feasibility/artifacts/run-results.json
git commit -m "test(047): run narrow-slice quality falsification"
```

## Task 8: Final evidence, review, and delivery

**Files:**

- Modify: `openspec/changes/047-s0q-quality-feasibility/tasks.md`
- Modify: `openspec/changes/047-s0q-quality-feasibility/validation-report.md`
- Modify: `mvp_handoff_jlx.md`

- [ ] Record exact base/head/tree, runtime image digests, source/bundle/profile/result digests, commands, PASS/FAIL/NOT RUN truth, cleanup state, manual active time, provider usage, and the binary verdict.
- [ ] Mark R5 complete when the admitted matrix ran. Mark R6 complete only for the exact feasible verdict; otherwise keep it unchecked and report the bottleneck.
- [ ] Blocked-only path: if Task 5 or Task 6 returned
  `BLOCKED_ON_INPUT`, record the exact input/profile gap and scratch cleanup
  proof, keep R1–R3/R5–R6 truthful, state provider/A–D as NOT RUN, and continue
  with review and PR delivery. A valid blocked result is an S0-Q falsification
  output, not an uncommitted local stop.
- [ ] Update handoff only with established facts and the next single mainline task. Do not declare `QUALITY_APPROVED`, MVP complete, Release integration complete, or Wiki publication.
- [ ] Run proportional gates:

```bash
cd harness
uv run pytest -q tests/test_s0q_047.py tests/test_source_weknora_017.py
uv run ruff check src/insurance_harness/adapters/weknora/admin_client.py \
  src/insurance_harness/s0q_047.py scripts/run_s0q_047.py tests/test_s0q_047.py
uv run mypy src/insurance_harness/adapters/weknora/admin_client.py \
  src/insurance_harness/s0q_047.py scripts/run_s0q_047.py
cd ..
openspec validate 047-s0q-quality-feasibility --strict
git diff --check
```

Expected: PASS. Full/provider/live/PostgreSQL suites remain NOT RUN except for the two explicitly bounded S0-Q commands already evidenced.

- [ ] Obtain independent Spec and Quality/Delivery review on the exact head. Findings are limited to reproducible contract, security/permission/data, real-concurrency, or delivery failures; also report `MAINLINE DRIFT` and `DETAIL TRAP`.
- [ ] Address only confirmed blockers, rerun proportional checks, then commit:

```bash
git add openspec/changes/047-s0q-quality-feasibility \
  mvp_handoff_jlx.md
git commit -m "docs(047): report S0-Q falsification verdict"
```

- [ ] Push one Draft PR from `codex/047-s0q-narrow-slice-run`. Do not mark Ready or merge until exact-head review and CI are green.

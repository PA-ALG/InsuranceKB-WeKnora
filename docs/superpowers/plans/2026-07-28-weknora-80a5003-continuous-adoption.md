# WeKnora Immutable Upstream Thin Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development or superpowers:executing-plans.
> Execute one task at a time with RED→GREEN checkpoints.

**Goal:** Adopt the exact upstream identity selected by the tracked manifest, preserve
W1 and PostgreSQL data, and leave a small manifest-driven path for the next fixed
upstream identity.

**Architecture:** Use the manifest as the only target input, a finite read-only check
for identity/path/migration/plugin evidence, and standard Git merge/replay history as
the only patch carrier. Keep official and enterprise migrations in separate ledgers,
then close targeted Code and Artifact gates.

**Tech Stack:** Git, Python 3.12/pytest, Go 1.24, PostgreSQL 16/17,
Vue/TypeScript, GitHub Actions, Docker Buildx.

---

## Scope and stop rules

- Authoritative specification:
  `openspec/changes/045-weknora-80a5003-continuous-adoption/specs/weknora-continuous-adoption/spec.md`.
- Current target values come only from
  `deploy/upstream/weknora-adoption-target.json`. The current commit is
  `80a5003cc99a427098afe184eee6601916d3d156`; do not add that value to generic
  code.
- `discover latest-stable|mainline-head` proposes immutable manifest data only.
- Use the true project↔target Git merge-base. Runtime lock is a second comparison
  baseline, never a merge-base substitute.
- Standard Git merge/replay commits are the only patch carrier.
- Do not touch a live database. Migration tests use disposable PostgreSQL or a
  verified backup clone in Artifact.
- Keep `source_reader` blocked. Do not claim P4a/P4c, consumer adaptation or
  Artifact readiness without their real gates.
- Wiki history/diff/edit/revert are product acceptance, not Harness W1 endpoints.
- Stop on unknown identity, migration checksum, plugin digest/node, dirty/partial
  database state or unapproved project-owned path.

## Explicit non-files

Do not create or maintain:

- `deploy/upstream/weknora-enterprise-schema-objects.yaml`;
- `deploy/upstream/weknora-adoption-report.json`;
- W1 patch/bundle/receipt files;
- generic DDL/schema-object/collision engines;
- `bundle`, `verify-bundle` or arbitrary patch DSLs.

Necessary evidence stays in deterministic `check` stdout and CI logs.

## Retained control files

- `deploy/upstream/weknora-adoption-target.json` — approved immutable identity.
- `deploy/upstream/weknora-plugin-contract.yaml` — Harness public/ACL/readiness
  contract and validation nodes.
- `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml` — W1 ownership/path
  registry only; not an apply manifest.
- `harness/scripts/prepare_weknora_adoption.py` — manifest discovery and finite
  `check`.
- `harness/tests/test_prepare_weknora_adoption_045.py` — focused parser/check
  mutation tests.

---

### Task 1B: Slim the submitted contract slice

**Files:**

- Modify: `harness/scripts/prepare_weknora_adoption.py`
- Modify: `harness/tests/test_prepare_weknora_adoption_045.py`
- Retain: `deploy/upstream/weknora-plugin-contract.yaml`
- Remove from 045: `deploy/upstream/weknora-enterprise-schema-objects.yaml`

- [x] **Step 1: Remove schema-inventory production parsing**

Delete enterprise schema object models, generic SQL/schema semantics and collision
expectations.

- [x] **Step 2: Remove matching tests and duplicate Python truth sources**

Keep YAML as the readable contract and one semantic SHA256 anchor for schema v1.

- [x] **Step 3: Keep plugin safety semantics**

Retain closed endpoints, principal/Space/ACL/zero-write, typed error, retry/timeout,
readiness and exact validation-node checks. Keep all current states false and the
future code node planned.

- [x] **Step 4: Verify the slim slice**

Run focused pytest, Ruff, strict mypy, compile and diff/scope checks. This submitted
slice is not final adoption.

---

### Task 1C: Implement the finite `check`

**Files:**

- Modify: `harness/scripts/prepare_weknora_adoption.py`
- Modify: `harness/tests/test_prepare_weknora_adoption_045.py`
- Read: target manifest, runtime lock, W1 path inventory and plugin contract

- [ ] **Step 1: Write identity RED tests**

Cover dirty target checkout, wrong origin, wrong HEAD/tree, missing release/required
ancestor and mutable-ref substitution. Each case must return `block`.

Run:

```bash
uv run pytest tests/test_prepare_weknora_adoption_045.py -q -k 'check and identity'
```

- [ ] **Step 2: Implement manifest-driven target verification**

Resolve all values from the manifest. Verify clean checkout, official origin, exact
HEAD/tree and ancestors with standard Git.

- [ ] **Step 3: Write the two-delta RED tests**

Prove the source delta uses the true project merge-base and the deployed delta uses
runtime lock. Intersect both path lists with registered W1 paths. A registered
overlap must return `manual_review_required`; runtime lock must never alter the source
merge-base.

- [ ] **Step 4: Implement only standard Git path comparison**

Use `git merge-base` and `git diff --name-only`. Sort and deduplicate paths. Do not
inspect content semantics or choose a merge side.

- [ ] **Step 5: Write migration/plugin RED tests**

Cover official filename/head/checksum drift, plugin digest drift, existing-node
deletion, planned-node mutation and false state promotion. Retain retry/timeout and
duplicate-key/type mutation coverage.

- [ ] **Step 6: Implement migration and plugin checks**

Enumerate target official migration filenames/SHA256 up to manifest head and compare
the merged project files byte-for-byte only after target is an ancestor of project
HEAD. Before merge, report `pre_merge` after validating the target chain. Invoke the
existing plugin parser/digest/node validation.

- [ ] **Step 7: Emit minimal deterministic JSON**

Output only verdict, target identity, the two W1 overlap arrays, official migration
filename/head/checksums and plugin digest/node status. Verdict is exactly
`pass|manual_review_required|block`. No timestamps, absolute paths, raw or
unfiltered input values, file contents or tracked output file.

- [ ] **Step 8: Verify format invariance and semantic sensitivity**

Comment/whitespace/mapping-order changes must preserve output. List/path/value
mutation must change verdict or block. Do not add an extension/plugin framework.

---

### Task 2: Merge exact upstream and replay W1/logger

**Files:**

- Modify: official source paths produced by the standard Git merge
- Modify: registered W1 paths only where human overlap review requires replay
- Modify: existing logger redaction path/tests only if official merge touches them
- Modify: W1 path inventory for exact ownership/test/remove-condition metadata

- [ ] **Step 1: Verify pre-merge check**

Run `check` against the clean exact target. Stop on `block`. Review every listed
overlap before changing source.

- [ ] **Step 2: Fetch and merge the exact manifest SHA**

Use the official remote and a normal non-squash Git merge. Verify the resulting
history contains manifest target and release/required ancestors.

- [ ] **Step 3: Resolve registered overlaps manually**

For each overlap, decide from the W1 contract and focused tests whether upstream,
W1 or a combined implementation is correct. Record the result as ordinary replay
commits. Do not generate patch files.

- [ ] **Step 4: Replay W1 and logger redaction**

Limit production changes to registered paths and the already-approved logger
security behavior. Any new path/patch identity stops the task for approval.

- [ ] **Step 5: Verify exact official source**

Run `check` again. Official migration files must be byte-identical to target, and
only reviewed W1 overlaps may remain as project-owned changes.

---

### Task 3: Implement dual migration and the legacy 000066 bridge

**Files:**

- Create/modify: `migrations/enterprise/versioned/*`
- Preserve: `migrations/versioned/*` exactly from target
- Create/modify: focused legacy W1 `000066` byte/checksum fixture
- Modify: PostgreSQL migration orchestration and focused tests

- [ ] **Step 1: Write origin-classification RED tests**

Cover fresh target, pre-66, upstream-66-plus, legacy-W1-66, known bridge checkpoint,
unknown, dirty, partial and checksum mismatch.

- [ ] **Step 2: Preserve the legacy fixture**

Store the historical W1 `000066` bytes/checksums only for bridge verification. It is
not a patch bundle and is never applied by workflow.

- [ ] **Step 3: Add enterprise source/ledger**

Run official `migrations/versioned` with `schema_migrations`, then enterprise
migrations with `enterprise_schema_migrations`.

- [ ] **Step 4: Implement locked bridge convergence**

Perform raw-SQL read-only preflight, acquire advisory lock/transaction, re-read the
fingerprint, then converge only known legacy state. Unknown/dirty/partial state exits
with zero writes.

- [ ] **Step 5: Run PostgreSQL matrix**

Use disposable PostgreSQL 16/17. Verify preserved W1 rows, official span semantics,
both ledgers clean, crash/restart idempotence and no silent skip.

---

### Task 4: Close targeted compatibility

**Files:**

- Modify only focused W1/public REST/product tests required by actual merge behavior
- Update plugin validation node status only when the exact real test exists

- [ ] **Step 1: Run W1 descriptor/chunk/manifest/race tests**

Verify current committed descriptors, typed not-committed reasons,
`last_committed`, pagination/reparse/delete races and digest vectors.

- [ ] **Step 2: Implement the planned in-progress evidence test**

Add the real
`TestGetKnowledgeRevisionInProgressIncludesLastCommitted`, then change its plugin node
from planned to existing. Final Code gate must remain blocked until both are true.

- [ ] **Step 3: Verify public/ACL behavior**

Run public REST envelope, Space/RAW-KB ACL, denied mutation and zero-write tests.
Do not enable source download or source-reader mutation.

- [ ] **Step 4: Verify product acceptance separately**

Test Wiki history, line diff, manual-edit optimistic locking, revert creating a new
revision and unauthorized zero-write. Do not add these routes to the W1 plugin
contract.

- [ ] **Step 5: Run focused quality gates**

Run affected Go/frontend/Python tests, frontend type-check, OpenSpec strict and
diff/scope checks.

---

### Task 5: Build trusted multi-images

**Files:**

- Modify: existing main-only trusted workflow
- Modify: existing source/image lock files
- Modify: existing server/worker/frontend image definitions only as required

- [ ] **Step 1: Write workflow policy RED tests**

Require an exact merged source identity, no floating source ref, no patch download or
apply step, and one shared commit/tree/lock across images.

- [ ] **Step 2: Run thin check before build**

Workflow must stop on `block` or unresolved `manual_review_required`.

- [ ] **Step 3: Build all required images from merged main**

Build server, worker, frontend and any already-required runtime image from the same
source. Publish immutable digests, provenance and SBOM.

- [ ] **Step 4: Run targeted pre-publish gates**

Run official/enterprise migration tests, W1/plugin compatibility and product
acceptance before publishing adopted candidates.

---

### Task 6: Close Artifact

**Files:**

- Modify: existing image lock/runtime deployment metadata
- Modify: existing Artifact workflow/probes only

- [ ] **Step 1: Pin exact multi-image digests**

Verify all images carry the same approved commit/tree/lock and originate from the
merged main workflow.

- [ ] **Step 2: Exercise migration on safe data**

Restore a verified backup clone or disposable representative database. Run bridge,
official and enterprise migrations; verify data and both ledgers.

- [ ] **Step 3: Run runtime probes**

Verify W1 plugin/readiness, Space/ACL and zero-write behavior plus product
history/diff/edit/revert smoke.

- [ ] **Step 4: Keep readiness truthful**

Artifact closes only when identity, migrations, W1/plugin and product probes pass.
Consumer adaptation, source-reader authority and P4a/P4c remain false unless their
separate real work is complete.

- [ ] **Step 5: Final verification**

Run:

```bash
openspec validate 045-weknora-80a5003-continuous-adoption --strict
git diff --check
```

Review changed paths against task ownership. Do not create an adoption report,
bundle or receipt.

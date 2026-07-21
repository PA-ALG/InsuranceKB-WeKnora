# PR #22 Fast-Follow Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve PR #22's H1.3a correction, reconcile it with the current `main`, and leave 009/011/012 specifications and project status truthful and ready for their dependency-ordered implementation.

**Architecture:** Treat the existing OpenSpec deltas as the design authority. Merge current `main` into the PR branch without rewriting history, separate observable drift dimensions from causal attribution, align reliability providers with the durable ledgers now present on `main`, and update only the roadmap/status files already owned by PR #22.

**Tech Stack:** Markdown, OpenSpec CLI, Git/GitHub Actions.

---

### Task 1: Synchronize the PR branch with current main

**Files:**
- Resolve only existing PR #22 paths if conflicts occur.

- [ ] **Step 1: Record the old-head divergence and changed-file boundary**

Run: `git rev-list --left-right --count HEAD...origin/main && git diff --name-only origin/main...HEAD`

Expected: PR head is one commit ahead and multiple commits behind; changes remain within the 009/011/012 specifications and shared status documents.

- [ ] **Step 2: Merge current main without force-pushing**

Run: `git merge --no-edit origin/main`

Expected: merge succeeds or reports only shared-document conflicts that can be resolved from current-main facts plus PR #22's semantic delta.

- [ ] **Step 3: Verify no unrelated main changes were lost**

Run: `git diff --name-status origin/main...HEAD`

Expected: only PR #22 files and this execution plan differ from `main`.

### Task 2: Make H1.3a observationally and causally honest

**Files:**
- Modify: `openspec/changes/011-knowledge-health/specs/knowledge-health/spec.md`
- Modify: `openspec/changes/011-knowledge-health/tasks.md`
- Modify: `openspec/changes/011-knowledge-health/proposal.md`

- [ ] **Step 1: Capture the ambiguous pre-fix wording**

Run: `rg -n "A≠C 内部|manifest.*区分|两维并报|独立维度" openspec/changes/011-knowledge-health`

Expected: the spec permits A/B and A/C coexistence but still risks treating a changed toolchain digest as the unique cause of A/C drift when inputs also changed.

- [ ] **Step 2: Specify independent evidence axes and multi-signal output**

Require independent comparison of frozen-vs-current input identity and frozen-vs-current compiler/schema/purpose identities. If both change, report both `pending_content_change` and `compiler_version_change`; describe them as evidence signals, not proof that either alone caused the rendered difference.

- [ ] **Step 3: Add the mixed local-change scenario and task acceptance wording**

Add a scenario where content identity and toolchain identity both change and both signals are retained. Keep A≠B remote drift independent, so all applicable signals may coexist.

- [ ] **Step 4: Align the reliability-provider source with current main**

Reference the 024 durable attempt ledger through the admitted/approved run registry for compiler attempts, while retaining explicit `unavailable` for sources that still lack a durable ledger. Do not claim that 021 lifecycle events are a bridge parse-failure ledger.

### Task 3: Reconcile roadmap and claimability with current main

**Files:**
- Modify: `HANDOFF.md`
- Modify: `docs/insurance-kb/13-blueprint-status.md`
- Modify: `docs/insurance-kb/22-parallel-execution-blueprint.md`
- Modify: `openspec/changes/009-concept-layer/proposal.md`
- Modify: `openspec/changes/009-concept-layer/tasks.md`
- Modify: `openspec/changes/011-knowledge-health/proposal.md`
- Modify: `openspec/changes/011-knowledge-health/tasks.md`
- Modify: `openspec/changes/012-qa-objects/proposal.md`
- Modify: `openspec/changes/012-qa-objects/tasks.md`
- Modify: `openspec/changes/README.md`

- [ ] **Step 1: Update facts that changed after the old PR head**

Record that 021/024 are merged and 020 T1 is in PR #24. Preserve the distinction between software completion and real baseline/uplift evidence.

- [ ] **Step 2: Express claimability per dependency, not as a blanket release**

Keep 011 claimable after this spec correction; keep 009 after 010 knowledge-domain T5+; keep 012 after 010's QA staging/frozen-contract work. Avoid wording that all three can start immediately.

- [ ] **Step 3: Remove self-fulfilling merge claims**

Use wording true inside the commit (for example, “the correction is present in this spec”) instead of claiming PR #22 was already merged before GitHub performs the merge.

- [ ] **Step 4: Check stale markers**

Run: `rg -n "PR #12.*收口中|收口前不可认领|021.*待人工|024.*PR #13.*未合|fast-follow.*已合入" HANDOFF.md docs/insurance-kb openspec/changes`

Expected: no stale project-status claim remains in the files touched by PR #22; historical records are not rewritten.

### Task 4: Validate, publish the review conclusion, and merge

**Files:**
- Modify: PR #22 body/comment only through GitHub after local verification.

- [ ] **Step 1: Run strict specification validation**

Run: `DO_NOT_TRACK=1 openspec validate 009-concept-layer --strict`, then repeat for 011 and 012.

Expected: all three exit 0.

- [ ] **Step 2: Run repository gates on the exact final tree**

Run from `harness/`: `uv run ruff check .`, `uv run mypy src tests`, and `uv run pytest -m "not live and not integration_postgres" -q`.

Expected: all exit 0. Also run `git diff --check` from the repository root.

- [ ] **Step 3: Push without rewriting PR history**

Commit the focused correction and push `HEAD:docs/wave2-fastfollow` without force.

- [ ] **Step 4: Verify CI and merge**

Confirm the PR head matches the pushed commit, all required GitHub checks pass, and GitHub reports the branch mergeable. Post an objective review comment including residual dependencies, then merge to `main` and verify the merge commit contains the correction commit.

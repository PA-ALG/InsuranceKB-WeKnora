# MVP Mainline Collaboration Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Freeze the user-approved collaboration rules that keep Enterprise LLM
Wiki work on the MVP mainline and bound review/rework.

**Architecture:** This is a docs-only governance change. `AGENTS.md` carries the
default execution rules; the control board records the dated decision and live
GitHub facts. No product contract, DAG, code, migration, or task implementation
changes.

**Tech Stack:** Markdown, Git, GitHub CLI.

---

## Contract Card

- **Business value:** reduce repeated review loops and keep three Codex lanes
  producing small, user-approved MVP increments.
- **Authority:** user-approved Mission Card and current main; this plan does not
  authorize W1, P1, G0a, or any other feature.
- **Owner:** one writer for the exact three-file scope.
- **Path budget:** exactly `AGENTS.md`,
  `docs/insurance-kb/23-mvp-control-board.md`, and this plan.
- **Non-goals:** code, tests, migrations, provider/live/PG, onboarding,
  architecture/DAG changes, upstream Tencent work.
- **Stop conditions:** dirty/non-isolated worktree, main drift before delivery,
  fourth changed path, unverifiable GitHub facts, or a requested product/design
  change.

## Task 1: Freeze the collaboration contract

**Files:**
- Modify: `AGENTS.md`
- Create:
  `docs/superpowers/plans/2026-07-27-mvp-mainline-collaboration-governance.md`

- [ ] Add the mandatory pre-start Mission Card fields and user approval gate.
- [ ] Freeze three-Codex lane topology, rotating roles, unique write ownership,
  latest-main worktrees, and non-waiting reviewer behavior.
- [ ] Freeze model/effort defaults and the separate approval rule for max/ultra.
- [ ] Freeze BLOCKER/BACKLOG/REJECTED criteria and bounded review rounds.
- [ ] Freeze one-user-value, 1–2-workday, 30-minute-review PR sizing.
- [ ] State that Claude is outside the current schedule and feature Mission
  Cards still require case-by-case user approval.

## Task 2: Record the dated control-board decision

**Files:**
- Modify: `docs/insurance-kb/23-mvp-control-board.md`

- [ ] Add one decision entry without changing the approved product DAG or task
  completion states.
- [ ] Record fresh GitHub totals, open PRs/issues, and the history-only status
  of PR #26/#28/#33/#44.
- [ ] If the live GitHub snapshot differs from an earlier instruction, record
  the fresh snapshot and do not infer implementation approval from it.

## Task 3: Verify and deliver as Draft

- [ ] Run `git diff --check`.
- [ ] Verify the diff is exactly the three approved paths and Markdown is
  UTF-8/LF.
- [ ] Fresh-check GitHub PR totals, merged/open/closed-unmerged sets, and open
  issues; update only current fact lines if they changed.
- [ ] Verify no product status, architecture, or DAG changed.
- [ ] Commit once, push the `codex/` branch, and create a Draft PR.
- [ ] Report exact base/head/tree, three files, checks, and
  `functional/full/provider/live/PG: NOT RUN`.

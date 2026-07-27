# MVP Mainline Collaboration Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Freeze the user-approved collaboration rules that keep Enterprise LLM
Wiki work on the MVP mainline and bound review/rework.

**Architecture:** This is a docs-only governance change. `AGENTS.md` carries the
default execution rules and this plan records their bounded delivery. No product
contract, DAG, code, migration, or task implementation changes.

**Tech Stack:** Markdown, Git, GitHub CLI.

---

## Contract Card

- **Business value:** reduce repeated review loops and keep three Codex lanes
  producing small, user-approved MVP increments.
- **Authority:** user-approved Mission Card and current main; this plan does not
  authorize W1, P1, G0a, or any other feature. PR #53 remains external in-flight
  P1 work: its existence is neither approval nor a completed dependency.
- **Owner:** one writer for the exact two-file scope.
- **Path budget:** exactly `AGENTS.md` and this plan.
- **Non-goals:** code, tests, migrations, provider/live/PG, onboarding,
  architecture/DAG changes, upstream Tencent work.
- **Stop conditions:** dirty/non-isolated worktree, main drift before delivery,
  third changed path, unverifiable GitHub facts, or a requested product/design
  change.

## Task 1: Freeze the collaboration contract

**Files:**
- Modify: `AGENTS.md`
- Create:
  `docs/superpowers/plans/2026-07-27-mvp-mainline-collaboration-governance.md`

- [x] Add the mandatory Mission Card fields and user approval gate for delivery
  tasks that write or change repository/GitHub/external state; keep pure
  read-only review and approved-task verification outside that extra gate.
- [x] Freeze three-Codex lane topology, rotating roles, unique write ownership,
  latest-main worktrees, and non-waiting reviewer behavior.
- [x] Freeze model/effort defaults and the separate approval rule for max/ultra.
- [x] Freeze BLOCKER/BACKLOG/REJECTED criteria and bounded review rounds.
- [x] Freeze one-user-value, 1–2-workday, 30-minute-review PR sizing.
- [x] State that Claude is outside the current Codex schedule and feature Mission
  Cards still require case-by-case user approval.

## Task 2: Verify and deliver as Draft

- [x] Run `git diff --check`.
- [x] Verify the diff is exactly the two approved paths and Markdown is
  UTF-8/LF.
- [x] Verify PR #53 is external in-flight and no file overlaps this governance
  change; do not assess, modify, or authorize its P1 work.
- [x] Verify no product status, architecture, or DAG changed.
- [x] Commit and push the `codex/` branch while keeping the existing PR Draft.
- [x] Report exact base/head/tree, two files, checks, and
  `functional/full/provider/live/PG: NOT RUN`.

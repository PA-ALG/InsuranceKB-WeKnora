# V3 Governance Mission 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the repository's executable old projector authority with the approved V3 governance direction while preserving honest current-state evidence and making no functional-code or migration change.

**Architecture:** This is one documentation-only governance change. It records a sole serving Active Release authority, treats WeKnora as a conditionally accepted carrier, freezes the old 018/projector route, and authorizes only the S0-R/S0-Q feasibility work that follows.

**Tech Stack:** Markdown, OpenSpec strict validation, Git diff/scope checks.

---

### Task 1: Freeze the authoritative inputs and current identity

**Files:**
- Add: `jlx_enterprise_llm_wiki_complete_728_v3.md`
- Add: `mvp_handoff_jlx.md`
- Modify: `HANDOFF.md`

- [x] Preserve the user-approved V3 and handoff text as review inputs.
- [x] Record current main `529d72c994369750b26e352a70fd6284e8b0fd9d`.
- [x] Distinguish upstream capability `80a5003`, image build source `a8bf55ae...`, and current main.
- [x] Keep Full Artifact/W1 runtime probes open.

### Task 2: Record the conditional authority decision

**Files:**
- Add: `docs/superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md`
- Add: `docs/superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md`
- Modify: `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
- Modify: `docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md`
- Modify: `openspec/changes/033-production-architecture-reset/*`

- [x] Freeze the single serving Active Release principle.
- [x] Mark WeKnora as `ACCEPTED_CONDITIONALLY`.
- [x] Preserve Harness ownership of semantic compilation, Candidate, review, and authorization.
- [x] Freeze, but do not delete, legacy 018 state and migrations.
- [x] Prohibit a Harness Active-to-WeKnora Active projector.

### Task 3: Align repository-level execution instructions

**Files:**
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/insurance-kb/00-project-overview.md`
- Modify: `docs/insurance-kb/README.md`
- Modify: `docs/insurance-kb/14-deployment-runbook.md`
- Modify: `docs/insurance-kb/16-roadmap.md`
- Modify: `docs/insurance-kb/22-parallel-execution-blueprint.md`
- Modify: `docs/insurance-kb/23-mvp-control-board.md`
- Modify: `docs/insurance-kb/24-legacy-asset-disposition.md`

- [x] Replace executable projector language with the V3 current/target-state split.
- [x] Make Mission 0 → capability gap/S0-Q → S0-R → joint gate → MVP the only executable order.
- [x] State that legacy rewiring and deletion are demand-driven and not an MVP prerequisite.

### Task 4: Correct 043 and 045 status without implementing them

**Files:**
- Modify: `openspec/changes/043-p2d-space-security-boundary/*`
- Modify: `openspec/changes/045-weknora-80a5003-continuous-adoption/*`
- Modify: `openspec/changes/README.md`

- [x] Preserve 043 Space/principal/epoch/ACL/cross-Space/zero-write contracts.
- [x] Mark 043 `SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`; do not authorize its old projector principal or permanent cardinality.
- [x] Record `1 RAW KB + 1 release-managed Wiki KB` as an MVP profile only.
- [x] Mark 045 source adoption, migration bridge, trusted images, and digest pin complete.
- [x] Keep Full Artifact/W1 runtime probes and source-reader authority open.

### Task 5: Verify the bounded governance delta

**Files:**
- Verify all changed paths.

- [x] Run `git diff --check`.
- [x] Run strict validation for OpenSpec 033, 043, and 045.
- [x] Search executable governance files for stale PostgreSQL Active/projector authorization.
- [x] Confirm zero changes under functional source, migrations, workflows, and deployment locks.
- [x] Report historical baseline OpenSpec failures separately; do not expand Mission 0 to repair them.

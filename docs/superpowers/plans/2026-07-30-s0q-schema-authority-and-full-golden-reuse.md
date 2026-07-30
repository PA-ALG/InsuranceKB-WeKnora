# S0-Q Schema Authority and Full Golden Reuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the owner-supplied workbook as the exact business Schema authority and make S0-Q select its four diagnostic records from the existing full-field Golden Product annotation.

**Architecture:** Preserve the original XLSX bytes and document their relation to the existing YAML registry. Reuse the existing Golden annotation subsystem and full medical-product WIP; do not create a second four-field Golden artifact or run a selective annotation path.

**Tech Stack:** XLSX source artifact, existing Schema YAML/Golden JSONL, Markdown/OpenSpec, Git/GitHub Draft PR.

---

### Task 1: Add the exact Schema authority

**Files:**
- Create: `docs/insurance-kb/schema-authority/产品知识库字段标签维度-20240205.xlsx`
- Create: `docs/insurance-kb/schema-authority/README.md`
- Modify: `docs/insurance-kb/07-schema-baseline.md`

- [x] **Step 1: Copy the owner-approved public workbook**

Copy `/Users/houjing/Downloads/产品知识库字段标签维度-20240205.xlsx` byte-for-byte
to the repository target. Do not rewrite or rebuild the workbook.

- [x] **Step 2: Verify binary identity**

Run:

```bash
shasum -a 256 \
  /Users/houjing/Downloads/产品知识库字段标签维度-20240205.xlsx \
  docs/insurance-kb/schema-authority/产品知识库字段标签维度-20240205.xlsx
```

Expected: both equal
`5cd0ed8af0bc10fec488d0d83e8e28c7c0d64408c4fc25cca92b2a365355fdb6`.

- [x] **Step 3: Record workbook-to-registry mapping**

The authority README must record:

- exact identity and the owner's explicit approval for public storage;
- eight structured field sheets and their exact existing YAML mappings;
- the embedded screenshots as field-location/table/condition guidance;
- screenshots do not supply per-product Golden answers;
- the medical line has 49 extractable fields derived from this workbook;
- later four baseline files and v1.1 extensions remain compatible historical
  additions pending separate authority reconciliation.

- [x] **Step 4: Correct human-readable provenance**

Update `07-schema-baseline.md` to distinguish the checked-in 2024 authority
from later additions. Do not modify runtime YAML bytes or registry version.

### Task 2: Bind 047 to the existing full Golden

**Files:**
- Modify: `openspec/changes/047-s0q-quality-feasibility/proposal.md`
- Modify: `openspec/changes/047-s0q-quality-feasibility/specs/s0q-quality-feasibility/spec.md`
- Modify: `openspec/changes/047-s0q-quality-feasibility/tasks.md`
- Modify: `docs/superpowers/plans/2026-07-30-s0q-narrow-slice-run-mission-card.md`
- Modify: `docs/superpowers/specs/2026-07-30-s0q-narrow-slice-run-design.md`

- [x] **Step 1: Amend the delivery scope truthfully**

Update `proposal.md` and `tasks.md` so the original spec-only five-Markdown
delivery remains recorded as historical fact, while this separately approved
authority amendment may add the exact XLSX, authority README, and bounded
provenance/contract updates. Remove the stale claim that README is a non-goal
for the amendment.

- [x] **Step 2: Freeze the Schema authority identity**

Q2 and the Mission Card must bind the workbook path/SHA and require each S0-Q
field to resolve to its workbook sheet and existing registry field identity.

- [x] **Step 3: Freeze the full-Golden relationship**

State explicitly:

- Golden annotation remains full-field; selective four-field annotation is
  forbidden as a Golden refresh;
- S0-Q selects exactly four diagnostic records from the frozen full product
  Golden;
- R2 stays incomplete until a separate Golden Mission uses `gpt-5.6-sol` for
  all 60 current extractable medical fields, closes Evidence verification and
  human approval, and produces an immutable artifact identity/digest;
- the current WIP proves coverage only and cannot be called frozen/approved;
- Golden values/oracle spans cannot enter the evaluated weak-model prompt.

- [x] **Step 4: Validate OpenSpec**

Run:

```bash
openspec validate 047-s0q-quality-feasibility --strict
```

Expected: PASS.

### Task 3: Audit existing full-field coverage without re-annotation

**Files:**
- Read: `dataset/goldenset/wip-gs-v0.1/平安e生保（尊享版）医疗保险/fields.json`
- Read: `dataset/goldenset/wip-gs-v0.1/平安e生保（尊享版）医疗保险/golden.jsonl`
- Modify: `openspec/changes/047-s0q-quality-feasibility/validation-report.md`

- [x] **Step 1: Recompute coverage**

Verify:

- current WIP has 60 unique records for 60 current extractable registry fields;
- 49 records correspond to workbook-authoritative extractable fields;
- 11 records correspond to later v1.1 extensions;
- there are no duplicate or missing field identities.

- [x] **Step 2: Verify the S0-Q projection exists**

Confirm `产品特色`, `免赔额`, `保证续保`, and `宽限期` are present in the full
Golden with the intended four tri-state/typed classes. Do not copy them into a
new projection-specific Golden file.

- [x] **Step 3: Record truth, not approval**

The validation report must say the historical full-field WIP exists and covers
the slice, but its full current-model re-annotation/provenance approval is a
separate Golden Mission. This PR does not silently approve the WIP or run
models.

### Task 4: Update delivery truth and verify

**Files:**
- Modify: `openspec/changes/047-s0q-quality-feasibility/tasks.md`
- Modify: `openspec/changes/047-s0q-quality-feasibility/validation-report.md`
- Modify: `HANDOFF.md`
- Modify: `mvp_handoff_jlx.md`

- [x] **Step 1: Record partial progress**

State:

- Schema authority is admitted;
- existing full Golden coverage is identified;
- no four-field Golden artifact or model run occurred;
- R2 remains blocked until the full 60-field Golden Mission closes;
- W1 table-structure and embedding credential blockers remain;
- A-D remains `NOT RUN`, so S0-Q remains `BLOCKED_ON_INPUT`.

Update the top current-state block in root `HANDOFF.md`. Keep
`mvp_handoff_jlx.md` synchronized only for its S0-Q execution snapshot; it is
not a substitute for root HANDOFF.

- [x] **Step 2: Run bounded gates**

Run:

```bash
openspec validate 047-s0q-quality-feasibility --strict
git diff --check
git status --short
```

No full/provider/live/PostgreSQL/Release/Wiki run is authorized.

- [ ] **Step 3: Review and deliver**

Require independent exact-diff Spec and Quality/Delivery review. After
approval, commit and push the existing Draft branch; do not mark Ready or
merge.

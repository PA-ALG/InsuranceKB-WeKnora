# MVP Human Wiki Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 032 as a separate read-only product Wiki that shows approved product facts, Evidence, typed gaps, version, and manifest identity to people without mixing consumption with the 008 operator workbench.

**Architecture:** A small `human_reader` service groups canonical facts returned by `ApprovedSnapshotReader`; a FastAPI/Jinja adapter renders a product directory and product page. It reuses M0 consumption grants and never imports workbench write actions, mutable Claim tables, MCP internals, or WeKnora writers.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Pydantic v2, existing `ApprovedSnapshotReader`, pytest TestClient.

---

## Authority and boundaries

- Spec: `openspec/changes/032-human-wiki-reader-mvp/` (HR1–HR6).
- Dependencies: 029 exact `ApprovedSnapshotReader.read_current` and exported canonical DTOs, plus 013 `access/tokens.py`; service work can start with an exact fake, final integration waits for both.
- Risk: **A** for Space/auth, **C** for read-only UI.
- Use @superpowers:test-driven-development and @superpowers:verification-before-completion.
- Allowed: new `human_reader/`, its templates/tests/report, plus read-only imports from M0-owned `access/`. Forbidden: modifying `access/`, `workbench/`, `knowledge/`, `mcp/`, publisher, WeKnora write adapter, schema editor.
- This campaign has explicit business-owner authorization to commit, push, and open a ready PR after verification; the execution session SHALL NOT self-merge.

## File map

**Create**

- `harness/src/insurance_harness/human_reader/__init__.py` — stable `create_app`/service exports.
- `harness/src/insurance_harness/human_reader/models.py` — directory/product page view models.
- `harness/src/insurance_harness/human_reader/service.py` — canonical fact grouping and typed gap mapping.
- `harness/src/insurance_harness/human_reader/app.py` — injectable read-only FastAPI factory.
- `harness/src/insurance_harness/human_reader/templates/products.html.j2`
- `harness/src/insurance_harness/human_reader/templates/product.html.j2`
- `harness/src/insurance_harness/human_reader/templates/unavailable.html.j2`
- `harness/tests/test_human_reader_service_032.py`
- `harness/tests/test_human_reader_app_032.py`
- `harness/tests/test_human_agent_same_snapshot_032.py`
- `openspec/changes/032-human-wiki-reader-mvp/validation-report.md`

### Task 1: Freeze the human read view model

- [ ] **Step 1: Write HR1/HR4 RED tests**

Import 029 canonical result/fact/Evidence/failure DTOs. Require product/version identity, `snapshot_id`, `manifest_hash`, approval principal, facts grouped for rendering by schema field group, Evidence summaries, typed gaps, disclaimer, and internal-preview label. Structured Evidence must render source system/record/revision/locator/hash without page/chunk. Add a boundary assertion that 032 defines view models only and no second canonical fact/Evidence model.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_human_reader_service_032.py
```

Expected: FAIL because `human_reader` is absent.

- [ ] **Step 3: Implement frozen view models**

Views contain only serving DTO data. Do not add `Claim`, `ReviewItem`, or SQLAlchemy objects to model fields.

- [ ] **Step 4: Run model GREEN**

Expected: DTO/serialization tests PASS.

### Task 2: Directory and product service over approved facts

- [ ] **Step 1: Write HR2 RED tests**

Test directory groups only products present in current approved facts; product page filters exact product/date through the shared method; mutable candidate Claim is invisible; unapproved/manifest mismatch returns unavailable; typed gap does not become an empty “complete” page; a returned `value_state="unknown"` fact renders as unknown plus “未收录不等于不存在” rather than not-found.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_human_reader_service_032.py -k "directory or product or approved or gap"
```

- [ ] **Step 3: Implement service**

`list_products(scope)` calls `read_current(scope, predicates=None)` without product filter and groups canonical facts. `get_product(scope, product_id, effective_on, predicates=None)` calls the same method with exact filters. Preserve canonical fact identity/value/order; rendering-only grouping must not change data, and `ServingFailure` is the only source of unavailable/not-found pages.

- [ ] **Step 4: Run GREEN with 029 regressions**

```bash
cd harness
uv run pytest -q tests/test_human_reader_service_032.py tests/test_serving_reader_029.py
```

Expected: PASS.

### Task 3: Fail-closed authentication and read-only routes

- [ ] **Step 1: Write HR1/HR3 route RED tests**

Target routes:

```text
GET /spaces/{space_id}/products
GET /spaces/{space_id}/products/{product_id}?as_of=YYYY-MM-DD
```

Test no token=401, wrong Space=constant 403, cross-Space product=not-found indistinguishable, and route enumeration has only GET/HEAD plus framework docs disabled.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_human_reader_app_032.py -k "auth or route or space"
```

- [ ] **Step 3: Implement injectable FastAPI app**

Resolve token through `insurance_harness.access.tokens` before service calls. Disable docs/redoc; do not mount workbench routers. Convert typed gaps to stable user pages/statuses without leaking target Space/product existence.

- [ ] **Step 4: Run GREEN**

Expected: PASS; fake service call count remains zero for rejected auth.

### Task 4: Minimal human-friendly templates

- [ ] **Step 1: Write rendering RED tests**

Assert visible product/version, snapshot/hash short IDs, field groups, value state, Evidence source/reference, disclaimer, internal preview, and “未收录不等于不存在” for gaps. Assert no approve/reject/publish/rollback form or POST action.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_human_reader_app_032.py -k "render or evidence or no_write"
```

- [ ] **Step 3: Implement three server-rendered templates**

Keep CSS inline/minimal for MVP; do not spend the PR on design-system work. Evidence links may point to a stable source reference only when present; no fabricated document link for structured data.

- [ ] **Step 4: Run GREEN**

Expected: PASS via TestClient.

### Task 5: Human/Agent same-snapshot contract

- [ ] **Step 1: Write HR5 RED integration test**

Seed one approved snapshot with document, structured, and `unknown` facts. Call 032 service and 013 `get_product_facts` with the same Space/product/date/predicates. Both must import 029's public DTOs. Compare `snapshot_id`, `manifest_hash`, canonical Evidence identities, and the already-canonical `(claim_id, revision_no, predicate, value_state, value)` sequence without adapter re-sorting.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_human_agent_same_snapshot_032.py
```

Expected: FAIL if either adapter alters/filter facts differently.

- [ ] **Step 3: Fix only adapter mapping, never serving facts**

Both adapters consume the same public serving result. Do not add cross-imports between `human_reader` and `mcp`; the test imports each public service independently.

- [ ] **Step 4: Run GREEN**

Expected: exact canonical tuples and hashes match.

### Task 6: P-1/internal-preview boundary and handoff

- [ ] **Step 1: Add HR6 zero-writer test**

Inject a WeKnora writer fake if the composition root exposes one; otherwise statically assert `human_reader` imports no `adapters.weknora` writer/publisher and service requests cause zero writer calls.

- [ ] **Step 2: Run focused suite/static checks**

```bash
cd harness
uv run pytest -q tests/test_human_reader_service_032.py tests/test_human_reader_app_032.py tests/test_human_agent_same_snapshot_032.py
uv run ruff check src/insurance_harness/human_reader tests/test_*032.py
uv run mypy src/insurance_harness/human_reader
```

Expected: PASS.

- [ ] **Step 3: Complete validation report**

Record route inventory, auth matrix, human/agent equality, mutable-read absence, zero writer/model, and `WeKnora production Wiki UI/P-1=NOT RUN`.

- [ ] **Step 4: Independent review and PR-ready verification**

Reviewer checks HR1–HR6 and rejects workbench/publisher scope creep. Run full deterministic once after findings close; record seven-stage time.

- [ ] **Step 5: Human commit boundary**

Report exact diff/tests/NOT RUN and stop feature work. Under this campaign's explicit authorization, commit/push and open a ready PR after review; do not self-merge.

# MVP MCP Agent Reader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the 013 MVP core with three deterministic read-only MCP tools—product resolution, approved product facts, and frozen Claim Evidence—using the exact same approved snapshot contract as the human reader.

**Architecture:** Keep MCP as a thin adapter over `ApprovedSnapshotReader`; product resolution uses existing Space-scoped product/alias master data, while facts/Evidence never read mutable Claim. A shared consumption-token package binds principal→Space for 013 and later 032, and the official stable MCP v1 SDK exposes a loopback Streamable HTTP endpoint.

**Tech Stack:** Python 3.12, official `mcp>=1.27,<2` SDK, FastMCP/Streamable HTTP, Pydantic v2, existing SQLAlchemy read services, pytest/httpx.

---

## Authority, dependency, and honest scope

- Specs: `openspec/changes/013-insurance-mcp/specs/insurance-mcp/spec.md` plus `openspec/changes/013-insurance-mcp/mvp-profile.md`.
- Dependency: 029 public `ApprovedSnapshotReader.read_current` plus its exported canonical fact/Evidence/result/failure DTOs; development may start against an exact protocol fake, final contract tests wait for 029.
- SDK decision: stable v1 line with `<2` upper bound; v2 is prerelease during this MVP. M0 is the sole owner of `pyproject.toml`/`uv.lock` for this wave.
- Risk: **A** for token/Space isolation, **C** for transport adapter.
- Use @superpowers:test-driven-development and @superpowers:verification-before-completion.
- Full compare/history/SSE/production SSO and actual WeKnora Agent mounting are deferred unless 030 captures live evidence.
- AI session does not commit/push.

## File map

**Create**

- `harness/src/insurance_harness/access/__init__.py` — public consumption-grant exports.
- `harness/src/insurance_harness/access/tokens.py` — strict token→principal+Space grants for 013/032; no UI session/CSRF behavior.
- `harness/src/insurance_harness/mcp/models.py` — MCP transport request/response/not-found envelopes only; import canonical fact/Evidence DTOs from `knowledge.serving`.
- `harness/src/insurance_harness/access/settings.py` — package-local immutable token-grant settings, passed explicitly to factories.
- `harness/src/insurance_harness/mcp/settings.py` — package-local disclaimer/loopback host/port; no global config mutation.
- `harness/src/insurance_harness/mcp/service.py` — three pure read services over product master + approved reader.
- `harness/src/insurance_harness/mcp/auth.py` — request token extraction and grant-to-scope binding.
- `harness/src/insurance_harness/mcp/server.py` — injectable FastMCP factory/Streamable HTTP app.
- `harness/tests/test_serving_access_tokens_013.py`
- `harness/tests/test_mcp_service_013.py`
- `harness/tests/test_mcp_streamable_http_013.py`
- `openspec/changes/013-insurance-mcp/validation-report-mvp.md`

**Modify**

- `harness/pyproject.toml` and `harness/uv.lock` — pin `mcp>=1.27,<2` once.
- `harness/src/insurance_harness/mcp/__init__.py` and `mcp/README.md` — public factory/tool contract and status.

`harness/src/insurance_harness/config.py` is owned and merged by S0/027 only. M0 never edits it; any later global composition alias is a separate serialized integration patch after 027. Package factories receive `ServingAccessSettings/McpSettings` explicitly.

### Task 1: Pin SDK and shared token grants

- [ ] **Step 1: Write fail-closed grant RED tests**

Cover missing token, malformed config, blank principal, empty Spaces, duplicate token, target Space not granted, and constant non-leaking error shape.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_serving_access_tokens_013.py
```

Expected: FAIL because `insurance_harness.access` is absent.

- [ ] **Step 3: Implement immutable grants**

`ServingGrant` contains only principal and a non-empty frozen Space set. Token strings are used as lookup keys but never serialized/logged. Unknown and wrong-Space tokens fail before product/snapshot queries.

- [ ] **Step 4: Run GREEN**

Expected: PASS.

- [ ] **Step 5: Add the official stable dependency**

Run:

```bash
cd harness
uv add "mcp>=1.27,<2"
```

Expected: `pyproject.toml` and `uv.lock` change; no prerelease v2 is selected. If resolution selects `2.*`, stop and report rather than weakening the bound.

- [ ] **Step 6: Human commit boundary for shared dependency/grants**

Report diff and exact resolved SDK version. Do not commit/push.

### Task 2: Freeze MCP core DTOs and reject semantics

- [ ] **Step 1: Write DTO RED tests**

Import 029 canonical DTOs and require every success/not-found transport envelope to contain `as_of_date`, `schema_version`, safe `snapshot_id`, safe `manifest_hash`, `disclaimer`, and `trace_id`; reasons are an enum, not empty arrays/exceptions. Add a static/public-contract assertion that MCP does not define a second canonical fact or Evidence model.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mcp_service_013.py -k "envelope or not_found"
```

- [ ] **Step 3: Implement stable models**

Transport models wrap, but do not reinterpret, 029 canonical facts/Evidence. Structured Evidence has structured source fields and no optional fake page/chunk placeholders in serialized output.

- [ ] **Step 4: Run GREEN**

Expected: PASS.

### Task 3: `resolve_product`

- [ ] **Step 1: Write RED tests**

Test exact product code/name, alias, ambiguous family returning candidates, `as_of_date` version filtering, no applicable version, and cross-Space non-disclosure.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mcp_service_013.py -k "resolve_product"
```

- [ ] **Step 3: Implement resolution using existing master data**

Order is exact→alias→candidates. Never fuzzy-select one product. Open a short-lived read-only Session after grant/scope verification and reuse 003 alias/version semantics.

- [ ] **Step 4: Run GREEN with product regressions**

```bash
cd harness
uv run pytest -q tests/test_mcp_service_013.py -k "resolve_product" tests/test_product_aliases.py tests/test_product_register.py
```

Expected: PASS.

### Task 4: `get_product_facts`

- [ ] **Step 1: Write RED tests**

Use an exact `ApprovedSnapshotReader.read_current` fake and real 029 fixture. Test current/date-filtered facts, selected predicates, coverage gap, an approved `value_state="unknown"` fact, candidate Claim changed after snapshot, returned snapshot/hash, canonical order, and zero mutable-Claim queries.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mcp_service_013.py -k "product_facts"
```

- [ ] **Step 3: Implement a thin serving adapter**

Call `read_current` exactly once with Space/product/version/predicates/date filters. Copy its canonical facts without changing values, Evidence identity, or ordering. A successful fact with `value_state="unknown"` remains in the success response with `value=None`; only `ServingFailure` coverage codes map to typed not-found. Never convert unknown into absence or not-found.

- [ ] **Step 4: Run GREEN with 029 contract**

```bash
cd harness
uv run pytest -q tests/test_mcp_service_013.py -k "product_facts" tests/test_serving_reader_029.py
```

Expected: PASS.

### Task 5: `get_claim_evidence`

- [ ] **Step 1: Write RED tests**

Test published frozen document Evidence, frozen structured Evidence, draft/candidate claim indistinguishable from absent, cross-Space non-disclosure, and no source/Claim-table lookup after snapshot.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mcp_service_013.py -k "claim_evidence"
```

- [ ] **Step 3: Implement lookup over approved frozen facts**

Call `ApprovedSnapshotReader.read_current(scope, claim_id=claim_id)` exactly once. Preserve the imported canonical Evidence tuple without scanning, re-sorting, or defining a second read/DTO path. A later optimized index must preserve this serving interface.

- [ ] **Step 4: Run GREEN**

Expected: PASS; structured response contains locator/hash/mapping version and lacks page/chunk keys.

### Task 6: Streamable HTTP server contract

- [ ] **Step 1: Write transport RED test**

Create the injectable server with a fake service, mount Streamable HTTP at `/mcp`, connect with the official SDK client, authenticate with a token header, list tools, and call `resolve_product`. Assert loopback default and no stdio-based WeKnora claim.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_mcp_streamable_http_013.py
```

- [ ] **Step 3: Implement server factory**

Use `FastMCP(..., stateless_http=True, json_response=True)` or the exact equivalent supported by resolved v1.27.x; mount its Streamable HTTP ASGI app. Handlers validate token/Space before calling service. No write tools/resources/prompts are registered.

- [ ] **Step 4: Run GREEN**

Expected: one complete SDK client↔server round trip PASS, fake service exactly once.

### Task 7: Validate and hand off 013 core

- [ ] **Step 1: Run focused suite/static checks**

```bash
cd harness
uv run pytest -q tests/test_serving_access_tokens_013.py tests/test_mcp_service_013.py tests/test_mcp_streamable_http_013.py tests/test_serving_reader_029.py
uv run ruff check src/insurance_harness/access src/insurance_harness/mcp tests/test_*013.py
uv run mypy src/insurance_harness/access src/insurance_harness/mcp
```

Expected: PASS.

- [ ] **Step 2: Complete validation report**

Report three tools, auth matrix, approved-reader proof, zero model/write, resolved SDK version, and exact transport evidence. Mark compare/history as deferred and real WeKnora Agent mounting as `NOT RUN` unless 030 supplies live evidence; report `013 overall=PARTIAL`.

- [ ] **Step 3: Independent review and one PR-ready full deterministic run**

Review M1–M5 only against the MVP profile, run full deterministic once after findings close, then report seven-stage time.

- [ ] **Step 4: Human commit boundary**

Stop with exact diff/test evidence. Do not commit/push.

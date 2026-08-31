# 830 G1 Entity Page Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 815 已验收的真实医疗险 Candidate/Claim/Evidence 确定性投影为一个实体作用域页面图，并由现有 WeKnora Candidate/Review/Release/Head 生命周期原子保存和读取 1 overview + 7 section + 67 FieldAssertion + 1 空 free_wiki；完成真实 M1 Preview、M2 76/76 全图和 M3 隔离 `NOT_FOR_PRODUCTION` Release，不触碰生产 `8081`，不启动 G2。

**Architecture:** Harness 新增一个纯函数式 `EntityPageManifest` 编译器：输入是已验证的 815 `KnowledgeWikiReleaseV1`（其 `candidate_sha256`、字段 Claim、Evidence receipt 与 exact citation 已冻结）和 `PresentationProfile`，输出 76 个带稳定 entity/page identity 的结构化页面成员。WeKnora 只镜像该已冻结跨语言合同，验证完整 manifest 后复用现有 preparation/review/release/Head/CAS、ACL 和 exact source reader；前端遍历 payload 中的有序 Profile，不持有 67 字段标题或 7 节点的第二份权威。旧 75-member Release 保持原字节和 pinned 可读，新 76-member Release 是 successor；两者不互相 fallback。

**Tech Stack:** Python 3.12、Pydantic v2、pytest、Ruff、mypy；Go 1.25、现有 WeKnora Wiki Release/CAS repository、Gin、Go test/vet；Vue 3、TypeScript、现有 TS/Vitest/Vue Test Utils；Docker 只在 D2 由总控按 B0 image-impact 构建一次，D3 复用同一 digest。

---

## Frozen execution identity

- `PARENT_GOAL=G1`
- `BASE_COMMIT=d2ce44cb2107575f7624b3735c653078ae2a98b6`
- `BASE_TREE=c7853fa71a5fbe826c3faf04ce3e8a2ad1168255`
- `M0_INITIAL_COMMIT=0f1cbe1840774aca6e1a3eb74bbc65687d97680b`
- `M0_INITIAL_TREE=447dcbde22641136effc6d612134caeb7348fc4f`
- `BRANCH=codex/830-g1-field-assertion-pages`
- `CURRENT_RED=NO_ENTITY_SCOPED_INDEPENDENT_FIELD_PAGES`
- `NEXT_PHYSICAL_RESULT=真实 815 Candidate Preview 的 overview + 1 section + 3 FieldAssertion + 空 free_wiki + 稳定 URL + 短标题/长 namespace + exact source click`
- `M1_STOP_DEADLINE=2026-09-02 23:42:03 +08:00`
- `G2_AND_LATER=LOCKED`
- `ACTUAL_CANDIDATE_SHA256=4aebf1e1b755e7d4dee4ea62dac86318f6229aeca6bc2ca52510dcf8883efea1`
- `ACTUAL_CANDIDATE_FILE_SHA256=7799539c4b44e74e1b157ccfae2ab6f32b0eecfb1e9415e70b15751a3f5fb3ca`
- `CLAIM_SET_SHA256=2586b88cae0f3a13c55e2be7f08fa9f892261264c01f9ca75a21ff05b614354c`
- `EVIDENCE_AUTHORITY_SHA256=d56cd38c18ccc1aa511b0a1f89ffdf52899d477cbf5336b6f84ee9662bc995d0`
- `PRESENTATION_PROFILE_SHA256=d83a3b38e3b72bd986823d373b86fe1077e0baa6333a27dc74a2545f58bfd3e9`

权威需求、STOP 条件和 Owner matrix 只来自 OpenSpec 126；本计划不能放宽它们。总控是唯一 integration、commit、push、PR、merge Owner。执行窗口不得运行 `git add`、`git commit`、`git push`、`gh pr` 或改治理/Evidence 文件。

## Frozen cross-language contract

Win1 必须在一个新模块内实现并冻结下列语义；不得修改既有 `schema-pack.v1`、旧 75-member payload 或旧 Release hash：

1. `PresentationProfileV1`：有序 section 集合，每个 section 有稳定 key、短标题和有序 field mapping；每个 field 有稳定 key、唯一 section、短标题；公共 validator 不允许 `len(sections) == 7` 之类医疗险全局判断。
2. `EntityPageIdentityV1`：`entity_id + page_kind + stable_key` 生成唯一 namespace/page ID 和稳定 route；显示名、taxonomy parent 和导航位置不参与 identity。
3. `FieldClaimRefV1`：绑定 source Candidate、source Release、source member digest、字段结构化 Claim digest；Section/Overview 只持有同一 ref，不复制可编辑正文。
4. `EntityFieldAssertionPageV1`：短标题、完整 namespace、section、三态、value、typed unknown reason、Claim ref、Evidence receipts 和 exact citations；known citation 只重绑新 page identity，其 revision/PDF/page/quote/locator/content hash 必须逐项等于 815 source。
5. `EntityOverviewPageV1`、`EntitySectionPageV1`：只含 Profile/导航和字段 Claim/Evidence refs；不保存独立正文副本。
6. `EntityFreeWikiPageV1`：G1 entries 必须严格为空。
7. `EntityPageMemberV1` 与 `EntityPageManifestV1`：顺序严格为 overview、Profile sections、Profile fields、free_wiki；医疗险实例恰好 76 个唯一 page ID；manifest/hash 覆盖全部 payload、Profile、source Candidate/Release。

推荐稳定 route suffix：

```text
/wiki/entities/<entity_id>/overview
/wiki/entities/<entity_id>/sections/<section_key>
/wiki/entities/<entity_id>/fields/<field_key>
/wiki/entities/<entity_id>/free-wiki
```

WeKnora API 可在现有 scope/release 前缀下承载这些 suffix，但前端用户 URL 必须保留 `entity_id` 和 stable key。explicit pinned read 必须直接读取请求 release；current read 必须在请求开始只观察一次 Head。不存在、foreign 或不完整时 typed fail closed，禁止转 current/latest。

---

## Task 1: Baseline and M0 review gate（总控 + 只读 Review）

**Files:**

- Read: `docs/insurance-kb/evidence/830-g1/frozen-input-manifest.json`
- Read: `docs/insurance-kb/evidence/830-g1/m0-validation.json`
- Read: `docs/insurance-kb/evidence/830-g1/actual-input-authority.json`
- Read: `docs/insurance-kb/evidence/830-g1/medical-presentation-profile.v1.json`
- Read: `openspec/changes/126-830-g1-entity-field-assertion-pages/**`
- Create later by controller only: `docs/insurance-kb/evidence/830-g1/tests/m0-baseline.json`

- [ ] Run the existing Python baseline against worktree source:

```bash
cd harness
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m pytest tests/test_medical_schema_pack_596_1.py tests/test_schema_wiki_release_596_1.py -q
```

Expected: existing 75-member compiler tests PASS. This is baseline, not G1 evidence.

- [ ] Run the existing Go baseline with a sandbox-writable cache:

```bash
GOCACHE=/private/tmp/weknora-830-g1-go-cache \
  go test ./internal/types ./internal/application/service ./internal/handler ./internal/router
```

Expected: PASS. A failure writing the default user cache is environment setup and must not be recorded as RED.

- [ ] Require the visible read-only Review task to report immutable `M0_COMMIT/M0_TREE`, R1-R9 coverage, both self-hashes, findings and `UNRESOLVED_COUNT=0` before any production implementation.
- [ ] Controller records commands, exit codes and hashes; reviewer never writes the receipt.

## Task 2: Harness requirement-first RED（Win1, tests only）

**Files:**

- Create: `harness/tests/test_entity_page_graph_830_g1.py`
- Read only: `harness/src/insurance_harness/knowledge_compiler/schema_wiki_release_596_1.py`
- Read only: `harness/src/insurance_harness/knowledge_compiler/schema_first_contracts.py`
- Read only: `harness/src/insurance_harness/knowledge_compiler/medical_schema_pack_596_1.py`

- [ ] Add one test that compiles the existing 815-compatible medical release and asserts the G1 manifest has 76 unique members. Run only that test.

```bash
cd harness
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m pytest tests/test_entity_page_graph_830_g1.py::test_g1_r2_exact_76_unique_pages -q
```

Expected RED: old projection exposes only 75 members / no free_wiki.

- [ ] Add minimal REDs for stable entity route/identity, all 67 three-state FieldAssertions, payload short title + namespace, and Profile-driven 2-section topology.

```bash
cd harness
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m pytest tests/test_entity_page_graph_830_g1.py -q
```

Expected REDs: no entity-scoped page identity/route, no `PresentationProfile`, no `free_wiki`, and title lives outside the old payload. Import/environment errors alone are not acceptable completion evidence; report the exact failing requirement assertion.

- [ ] Report the command, exit code, failing test names and expected-vs-actual values to the controller. Do not create a RED receipt file and do not edit production code before M0 Review PASS.

## Task 3: Harness compiler and PageManifest GREEN（Win1）

**Files — exact Win1 write domain:**

- Create: `harness/src/insurance_harness/knowledge_compiler/entity_page_graph_830_g1.py`
- Create/modify: `harness/tests/test_entity_page_graph_830_g1.py`
- Create: `harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json`
- No other file is writable without controller approval.

- [ ] Implement the closed Pydantic models and canonical hash functions in the new module. Reuse `schema_wiki_canonical_bytes` / `schema_wiki_sha256`; do not create a second hash algorithm.
- [ ] Build the medical PresentationProfile from `make_medical_schema_pack_596_1()` and `approved_schema_rows()` so all 67 short titles are code-owned input, not copied from the frontend table.
- [ ] Implement a generic validator that accepts a legal 2-section Profile and rejects duplicate/missing field mappings, unstable keys, duplicate page IDs and non-empty G1 free_wiki.
- [ ] Implement `compile_entity_page_manifest_830_g1(source_release, space_id, profile)` as a pure function over a freshly validated 815 source release. It must not read WeKnora DB, network, filesystem, Provider or model.
- [ ] Preserve source Claim/Evidence: for every known field compare revision ID, parsed PDF hash, page, locator, quote, bbox and content hash before/after; for unknown preserve value/Evidence empty and typed reason.
- [ ] Prove title/taxonomy changes leave page ID/route and Claim/Evidence refs unchanged.
- [ ] Emit the deterministic cross-language JSON vector from the same real-shaped 815 release test object; vector must include Profile, all 76 members, 67 FieldAssertions, state distribution and manifest self-hash. It is contract evidence, not M1 live evidence.
- [ ] Run focused tests:

```bash
cd harness
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m pytest tests/test_entity_page_graph_830_g1.py \
  tests/test_medical_schema_pack_596_1.py tests/test_schema_wiki_release_596_1.py -q
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m ruff check src/insurance_harness/knowledge_compiler/entity_page_graph_830_g1.py \
  tests/test_entity_page_graph_830_g1.py
```

Expected: GREEN; existing 75-member tests remain byte/hash compatible.

- [ ] Report `git diff --check`, exact modified paths, vector hash, test counts and residual risks. Do not commit.

## Task 4: Controller freezes the shared contract and evaluates Win2 condition

**Files:**

- Modify by controller only: `openspec/changes/126-830-g1-entity-field-assertion-pages/validation-report.md`
- Create by controller only: `docs/insurance-kb/evidence/830-g1/tests/harness-red-green.json`
- Modify by controller only: this plan if an exact path correction is required.

- [ ] Controller inspects every Win1 diff, reruns Task 3 commands and rejects out-of-domain changes.
- [ ] Read-only Review checks the proposed contract/vector against G1-R1/R2/R3/R4/R5/R8/R9; unresolved must be 0.
- [ ] Controller commits the frozen Harness contract only after verification. Commit message contains `G1` and `NEXT_PHYSICAL_RESULT=M1_REAL_815_ENTITY_PAGE_PREVIEW`.
- [ ] Create Win2 only if all are true: Win1 write paths are frozen; Win2 paths below are disjoint; Win1 can continue the actual 815 input/preview evidence lane while Win2 implements validation/read/UI; both directly converge on the same M1 Preview. Otherwise retain a single writer and report why.

## Task 5: WeKnora cross-language validation and current/pinned RED→GREEN（Win2 if enabled）

**Files — exact WeKnora write domain:**

- Create: `internal/types/entity_page_graph_830_g1.go`
- Create: `internal/types/entity_page_graph_830_g1_test.go`
- Create: `internal/application/service/entity_page_graph_830_g1.go`
- Create: `internal/application/service/entity_page_graph_830_g1_test.go`
- Create: `internal/handler/entity_page_graph_830_g1.go`
- Create: `internal/handler/entity_page_graph_830_g1_test.go`
- Modify: `internal/router/routes_schema_wiki.go`
- Modify: `internal/router/routes_schema_wiki_test.go`
- Read only: `harness/tests/fixtures/entity_page_graph_830_g1_contract_vector.json`

- [ ] RED: parse the frozen vector and require all canonical hashes/topology. Expected old failure: no Go G1 PageManifest contract.
- [ ] GREEN: mirror the frozen types and canonical preimages exactly; accept the 2-section generic test vector and medical 76 vector without hardcoding 7.
- [ ] RED: current read must pin Head once and return the entity page; explicit pinned read must read the exact requested release even when it is not current. Add negative tests for nonexistent/foreign/incomplete release and prove no call falls back to current/latest.
- [ ] GREEN: add a bounded service over the existing WikiRelease repository/ACL. It validates the complete stored 76-member manifest before returning one page. It does not add a table, migration, service, publisher, Head or Harness online reader.
- [ ] Add current and explicit pinned routes under the existing scope-derived Schema group. Route parameters map only to validated entity/page identities; title/category never selects a page.
- [ ] Keep old 75-member current/pinned reads working unchanged.
- [ ] Run:

```bash
GOCACHE=/private/tmp/weknora-830-g1-go-cache go test \
  ./internal/types ./internal/application/service ./internal/handler ./internal/router
GOCACHE=/private/tmp/weknora-830-g1-go-cache go vet \
  ./internal/types ./internal/application/service ./internal/handler ./internal/router
```

Expected: G1 vector, current/pinned no-fallback and legacy tests all GREEN. Report results; do not commit.

## Task 6: Entity routes and profile-driven UI RED→GREEN（same Win2, after Go contract GREEN）

**Files — exact frontend write domain:**

- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/views/knowledge/KnowledgeBase.vue`
- Create: `frontend/src/api/schema-wiki/entityPageGraph830G1.ts`
- Create: `frontend/src/api/schema-wiki/entityPageGraph830G1.spec.ts`
- Create: `frontend/src/views/knowledge/schema-wiki/entityPageGraph830G1Contract.ts`
- Create: `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.vue`
- Create: `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.spec.ts`
- No package/lockfile change unless controller separately approves it.

- [ ] RED: router resolves overview/section/field/free-wiki semantic URLs containing stable entity/key; field click goes to that entity's own field URL; changing titles/navigation does not change URL.
- [ ] RED: renderer accepts a 2-section payload and displays short payload titles while retaining full namespace in page metadata. Expected old failure: combined browser/static 67-title table and no entity semantic route.
- [ ] GREEN: parse only the frozen G1 wire contract, iterate Profile sections/fields, render three-state FieldAssertion and empty free_wiki, and use exact release-pinned citation transport. Do not use `MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS` as entity-page authority.
- [ ] Both current and `?release_id=<exact>` page loads must surface typed failure; no UI retry to current/latest or page 1.
- [ ] Run only focused TS/Vue tests first, then the existing schema-wiki suite and typecheck using the repository's declared package commands. Missing dependencies must be installed by the controller from the lockfile and are not RED.
- [ ] Report commands, exit codes, rendered route/title/namespace assertions and changed paths; do not commit.

## Task 7: M1 real 815 Candidate Preview（controller integration）

**Files:**

- Create by controller: `docs/insurance-kb/evidence/830-g1/m1/entity-page-preview.json`
- Create by controller: `docs/insurance-kb/evidence/830-g1/m1/source-click.json`
- Create by controller: `docs/insurance-kb/evidence/830-g1/m1/runtime-identity.json`
- Create by controller: M1 UI screenshots under `docs/insurance-kb/evidence/830-g1/m1/ui/`
- Update by controller: OpenSpec tasks/validation report.

- [ ] Integrate Win1/Win2 only after both diffs are reviewed; controller runs all focused suites and creates the M1 commit.
- [ ] In an isolated D1 preview process, obtain the exact 815 release custody through existing WeKnora authority (never by Harness DB access), verify release `release-42a3dd0c-ec76-4017-a288-37f1b13519a0` / epoch 2 / source hashes, and feed that exported immutable object to the Harness pure compiler.
- [ ] Serve the resulting manifest through the G1 WeKnora preview/read path. This generated artifact is runtime evidence, not a checked-in test fixture and not a second serving authority.
- [ ] Prove in UI/API: overview, `application-and-contract`, `insured_eligibility`（present）、`guaranteed_renewal_period`（absent_explicitly）、`cooling_off_period`（unknown）、empty free_wiki, stable URLs, short titles, full namespaces.
- [ ] Click at least one known field through existing exact source authority and record revision/PDF/page/quote/locator. Corrupt one locator component and prove typed fail closed without page-1 fallback.
- [ ] Record zero Provider/model calls, zero DB/release/head writes for Preview, and production `8081` identity unchanged.
- [ ] If this physical result does not exist by `M1_STOP_DEADLINE`, set `G1=STOPPED`; do not build more framework.

## Task 8: M2 complete 76-page graph

**Files:** same approved product paths; controller Evidence only under `docs/insurance-kb/evidence/830-g1/m2/`.

- [ ] Run 76/76 unique identity, 67/67 bijection, state distribution `present=2`, `absent_explicitly=1`, `unknown=64`, typed unknown reason, exact section membership and empty free_wiki checks on the actual 815 manifest.
- [ ] Run title/category/taxonomy reparent mutation tests and prove page ID/route/Claim/Evidence identity stable.
- [ ] Run known Evidence equality for every known field and a generic 2-section renderer test; do not register another product Profile.
- [ ] Controller commits M2 only after read-only Review reports unresolved 0.

## Task 9: M3 single atomic isolated Release（controller only for environment/Git）

- [ ] Freeze integration head/tree and evaluate B0 `image-change-impact.json`.
- [ ] D2: build only affected app/frontend images once; record source tree, Dockerfile/context, lockfile, base digest, args and image digest.
- [ ] D3: start isolated environment using the same D2 digest; snapshot production `8081` and production Active before any isolated write.
- [ ] Submit the exact 76-member Candidate bundle to the existing WeKnora preparation/review/release lifecycle. Produce one `NOT_FOR_PRODUCTION` Release and activate it only in the isolated scope with the existing Head CAS.
- [ ] Prove before CAS the complete old release is readable; after CAS current is the complete 76-member release; explicit pinned reads of both old and new releases remain exact; no read sees a mixed set.
- [ ] Perform source-click regression for all three known fields and a drift/fail-closed case.
- [ ] Record Candidate/preparation/review/receipt/release/head/epoch/image/runtime identities and prove Provider/model calls, production `8081` changes and production Active changes are all zero.

## Task 10: Evidence, independent final review, CI and PR

- [ ] Controller completes `docs/insurance-kb/evidence/830-g1/`: frozen input, entity/page manifest, 76 identity/hash index, Profile identity, route stability, state counts, source clicks, Candidate/Review/Release, current/pinned, no-mix, image/runtime, UI, requirement matrix, tests/CI, git diff/status and reviewer result.
- [ ] Update OpenSpec matrix for every G1-R1..R9 with exact RED → implementation → test → commit → live evidence links. No live evidence means status is not PASS.
- [ ] Send exact candidate head/tree/runtime/release to the visible read-only Review task. Fix only BLOCKERs in approved paths; maximum three review loops.
- [ ] Run final focused suites, applicable repository CI, `git diff --check`, scope audit and clean-worktree check. Use `superpowers:verification-before-completion` before any PASS claim.
- [ ] Push one G1 branch/PR; controller alone creates/updates/merges. Read `superpowers:finishing-a-development-branch` before deciding merge/cleanup.
- [ ] Final response is only `G1=PASS|FAIL|STOPPED` plus required identities/evidence and G2 readiness. Never start G2.

---

## STOP audit

Immediately stop and return to the user if completion requires a new service/table/database, Harness online DB read, second publisher/Head/Wiki, per-page activation, title/category authority, editable Markdown fact copy, Provider/model, production `8081` or production Active mutation, G2+ concept work, more than two writable lanes, or a repeated blocker after one minimal correction. A test fixture, screenshot, receipt or new validator cannot substitute for the real M1/M3 physical result.

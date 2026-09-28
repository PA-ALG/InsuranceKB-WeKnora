## Description

Upgrade the existing product to fixed WeKnora v0.8.2 source `3e8b0bfc80b845b2d4b2ed683994748741450a97` from product baseline `8ccc2ac942df7572499ac7b25e14587c594918db`. Preserve the Harness REST/lifecycle boundary, immutable source revisions, current ACL and sole published Release authority. Native transport replaces the old model dispatch path; source mutation and worker writes retain generation fences and exact-batch cleanup. Migration 077 preserves legacy Wiki history through an exact reviewed exception.

The final Go correction closes imported lint findings without changing the product comparison baseline. Test fixtures reflect the current native revision and processing contracts; replacement-file SHA updates and rollback retain the correct source identity. Mocked endpoint tests no longer depend on public DNS or real OSS requests. The service package has an explicit 20-minute test budget within the unchanged 30-minute CI job bound.

**Keep Draft. No merge, original-runtime cutover, new App build or model/provider execution is authorized by this update.**

## Goal / Spec Authority

- Goal: `830-UPSTREAM-PLUGIN-BOUNDARY`; upgrade within the existing product boundary.
- OpenSpec: `130-weknora-082-harness-plugin-boundary`, requirements UPG-01–UPG-09.
- Requirement/spec baseline: `2a6bd5c5ae3d66857408bd58295aae3fa0620c81`, OpenSpec directory tree `c991550329b494392162c017ee065d36f2a83d49`; current owner scopes are recorded in `current-slice-paths.json`.
- Unique integration owner: root. Disjoint service/nonservice writers and independent reviewer are recorded in the same scope manifest.
- Final software: `d5be03b3b2da18d9bdcfb8f32d66e0bc31843a83`, tree `e2c8f4882ff9afd6c5e73c21f1f7fc1db84f33ea`.

## SDD Evidence and Testing

- Initial upgrade conflicts, source-integrity regression and actual CI failures provide RED; detailed requirement mapping and prior evidence remain in the OpenSpec validation report.
- Full root lint: **PASS, zero findings**, uncapped output, unchanged product merge base. Final run 57.981 seconds. Exact 290-path software index passed independent review with zero blockers.
- First complete local four-package run: **FAIL**, retained intact; 741.06 seconds with no timeout, 3,706 passed / 11 skipped / 48 failed test events including parent/subtests. Failures were caused by local fake-IP DNS, system Python 3.9/user-site packages and DNS-dependent OSS fixtures.
- Reviewed recovery: **265 passed**, covering every one of the 48 failed events, all 121 selected top-level service tests and the complete file package. Python used a cached isolated 3.12 environment without installed packages. Existing safety assertions remain; OSS tests exercise real SDK GET 404 → PUT 403 behavior against a local server. This is composite local evidence, not a claim that the first complete run passed.
- Nonservice affected checks: **214 passed** across Feishu, search, tools and handlers.
- Source lock and adoption-report verification bind the final software; report `dfaf453e…` remains byte-identical to the earlier reviewed report. Existing images retain their own source identities.
- Earlier frontend validation: 1,283 passed / one existing skip, type-check and 10 style guards passed. License/Nginx fixtures and CLI/client checks also passed against their recorded identities.
- Remote checkpoint `2a6bd5c5a`: 19 successful, two failed, five skipped checks. Pinned dsh real E2E and deterministic checks passed. **Final-head remote CI remains pending and must be observed to completion.**

## Mechanical Exemption

- [x] Used for exact formatting, comments, binding-preserving names and metadata corrections under UPG-08/09; paths and frozen hashes are recorded in `root-lint-closure-20260928.json` and the owner manifest.
- [x] Reviewer explicitly confirmed the exemption. Evaluated strings, tag bytes, compiler directives, variadic calls and type aliases were checked. Nineteen indivisible schema/GORM tags have individually justified line-only `lll` exceptions; no global exclusion or rule reduction.

## Delivery and Remaining Acceptance

Old-version recovery using App source b393 **passed** before the upgrade. The subsequent isolated migration using App source e71/image `442701a3…` **passed**: official110/false, enterprise5/false, pg_search0.22.6, all 61 original table projections, protected 21 knowledge rows/216 spans, and epoch27/member/source/citation/PDF continuity. Both test Apps are stopped; the original eight services remain unchanged. Six legacy log entries are preserved; zero legacy-log-page data does not exercise nonempty archival. Harness password authentication remains untested.

App build attempts remain five, with no additional build in this correction. DocReader e71/image `d1777cd…` passed its recorded build and isolated smoke. UI source82/image `1ca8b0c…` passed build/static smoke, but its incorrect identity label keeps exact reuse blocked. These artifacts are not represented as builds of final software d5be.

Original-runtime deployment, new-source artifact delivery, provider probes and new business tracer/Candidate/review/publish/activation remain **NOT RUN**. Existing epoch27 is not switched. Fixtures and local software checks do not establish business/live acceptance.

## Checklist

- [x] Goal, OpenSpec, requirement authority and frozen software identity are recorded.
- [x] RED or explicit reviewer-confirmed mechanical exemption is recorded.
- [x] Local validation, initial failures, skips and limitations remain explicit.
- [x] Fixture/provider-zero results are distinct from live/business evidence.
- [x] Deployment and other unexecuted gates are explicit.
- [x] Independent code review and affected local checks passed.
- [ ] Final exact-head remote CI has passed.

Receipts: `docs/insurance-kb/evidence/830-upgrade/`; current status and full mapping: HANDOFF and OpenSpec 130.

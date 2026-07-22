# 031 hunk replay manifest

> This manifest is part of the local Phase 2 review evidence. It does not authorize push, merge,
> provider/live execution, T2.3 provenance synthesis, or promotion of PR #26 from Draft.

## Immutable sources and replay contract

- source checkpoint commit: `3daefa10fa5336b3cc5b520f9c3ecc3200513050`
- source checkpoint tree: `38c60af88f55b907f73ac4b012523da09b572862`
- source merge base: `1b0578698554a71ecfc89cd441345e33609a539f`
- replay base: `fde06802ebc25bde6a6a07c3ff575bd9f59806d5`
- D layer parent commit: `040f3d4a549fc2e5ea82925e1a122a03a424a4be`
- D layer parent tree: `42f2be0414f7089bb6c268d2cb0bfd33ba75a817`
- old canonical D evidence commit/tree: `ea07da40df0f0f1492820f65a52c505e83d3b36f` /
  `adce230a27ccd910f99d391e105635a42d090e50`; its B/C blobs are historical evidence, not a
  whole-tree replay target after the reviewed B/C hardening.
- replay rule: apply the complete merge-base-to-checkpoint 031 patch to the replay base; preserve the
  replay-base blob for every path outside this allowlist.

The source patch contains 45 paths. The canonical replay differs from the replay base on 44 source
paths; `openspec/changes/README.md` is the sole main-equivalent path because the replay base already
contains the approved 031 registry entry. This manifest is the only additional Phase 2 evidence path.

## Path allowlist and ownership

### A — foundation, authority and provider-cap

Whole-path ownership:

- `.gitignore` — offline signing/private-material deny patterns.
- `dataset/shouxian_product/平安福满分（2026）养老年金保险/product_meta.json` — byte-preserving O1
  canonical input rename.
- `harness/src/insurance_harness/goldenset/admission_identity.py`
- `harness/src/insurance_harness/goldenset/admission_models.py`
- `harness/tests/test_operational_authorization_031.py`
- `harness/tests/test_operational_input_031.py`
- `harness/tests/test_operational_provenance_031.py`
- `harness/tests/test_run_admission_budget_020.py`
- `harness/tests/test_run_admission_identity_020.py`
- `harness/tests/test_run_admission_models_020.py`
- `harness/tests/test_run_admission_session_lock_020.py`

Shared-path logical hunks:

- `admission_authority.py`: all authority-file safety, domain-separated signing, root trust policy,
  production/test capability seals, pricing/provider-cap/provisioning authorization verification.
- `admission_cli.py`: trusted-key-policy configuration and root-owned trust loading only; generic
  keygen/render/sign/verify infrastructure stays usable, operational domain dispatch is C.
- `admission_infrastructure.py`: pricing/provider-cap/provisioning payloads and approvals,
  `VerifiedPricingCapability`, `VerifiedProviderCapCapability`, their production/test issue/require
  functions, signed bytes/digests and provisioning verification. Transport/receipt evidence is B;
  adoption/cleanup authorization is C.
- `admission_budget.py`: workspace-aware spend attestation, shared fixed+inference cap identity and
  aggregation, v5 infrastructure reserve schema, `InfrastructureReserveSnapshot`,
  `InfrastructureCreatePermit`, production/test ledger mode, root-owned policy/internal clock,
  provisioning reserve/account APIs and pricing-derived role rate. Topology/receipt annex is B;
  adoption/cleanup lookup is C.
- `test_operational_authority_031.py`: authority/path/policy tests except the five operational CLI
  ceremony round trips owned by C.
- `test_operational_infrastructure_ledger_031.py`: v5 reserve/shared-cap/mode/rollback/migration REDs;
  topology/receipt REDs are B and adoption/cleanup compatibility REDs are C.
- `test_operational_cost_cleanup_031.py`: pricing/provider-cap signature, shared cap and production
  versus test capability REDs before topology/receipt/adoption/cleanup scenarios.

A uses an intermediate schema-v5 boundary. It SHALL NOT contain transport, receipt, adoption,
cleanup, topology or finalizer production behavior. A–C carry a minimal typed execution blocker.

### B — receipt, transport and reconciliation

Shared-path logical hunks:

- `admission_infrastructure.py`: deployment receipt content/receipt, verified transport identity,
  verified reconciled receipt, credential reference, production/test transport and receipt seals,
  receipt/reconciliation digests and verification. Caller clone minting remains rejected.
- `admission_deployment.py`: provider manifest/request/journal/reconciliation/observation models;
  fixed Bailian endpoint and list/create/detail transport; safe operation store and OS run lock;
  canonical production controller; provisioning/reconciliation/replay; immutable receipt and
  independent reconciliation artifacts; strong/weak observation refresh. DELETE, adoption and
  cleanup methods are C.
- `admission_budget.py`: schema v6 topology and v7 receipt annex; durable topology records and opaque
  `VerifiedFinalTopology`; single/dual final bind; receipt/reconciliation loaders; exact workspace,
  project, credential, cap evidence/approval and observation joins; atomic topology replay and fresh
  production reload; v5/v6-to-v7 fail-closed migration.
- `test_operational_deployment_031.py`: canonical factory, no-DI, provisioning, transport,
  receipt/reconciliation, observation refresh, crash recovery and replay REDs; adoption/cleanup REDs
  are C.
- `test_operational_infrastructure_ledger_031.py`: transport/receipt seal isolation, clone rejection,
  topology transactions, strong/weak drift, atomic rollback and v7 migrations.
- `test_operational_cost_cleanup_031.py`: production topology/provenance, receipt exact-join and
  private test issuer rejection REDs before adoption/cleanup scenarios.

B SHALL expose no executable adoption/cleanup or 020 finalizer route. Any forward seam is typed,
side-effect-free and blocked.

### C — adoption, cleanup and operator ceremony

Shared-path logical hunks:

- `admission_infrastructure.py`: adoption and cleanup authorization payloads, domains, signed bytes,
  digests and root-policy verification.
- `admission_budget.py`: `InfrastructureCleanupBinding`, adoption reserve/test seam, adoption-specific
  segmented-price checks in final binding, and durable cleanup ownership lookup.
- `admission_deployment.py`: adoption result and state machine; cleanup journal v1/v2, transport
  identity, receipt/result, production cleanup-only factory, DELETE state machine, post-lock freshness,
  atomic artifact publication, causal authorization recovery and exact terminal replay.
- `admission_cli.py`: provisioning/adoption/pricing/provider-cap/cleanup domain-to-role mapping and
  render/sign/verify dispatch; generic crypto and root trust loading remain A.
- `test_operational_authority_031.py`: independent operational-domain CLI round trips.
- `test_operational_deployment_031.py`: adoption/cleanup caller-trust rejection, post-lock freshness,
  atomic failure/replay and zero-I/O expiry REDs.
- `test_operational_infrastructure_ledger_031.py`: adoption cost/no-create-permit, stale/cross-cap and
  cross-run replay, public clone rejection, legacy cleanup lookup and no-READY migration REDs.
- `test_operational_cost_cleanup_031.py`: adoption pricing, real adoption-to-artifact-to-v7-bind-to-
  cleanup E2E, cleanup authority/transport/endpoint/freshness/replay/404/v1-v2/ambiguous-delete and
  causal receipt REDs.

C SHALL keep operational execution typed BLOCKED until D installs the canonical finalizer.

### D — canonical finalizer, execution wiring and evidence

Whole-path ownership:

- `HANDOFF.md`
- `docs/superpowers/plans/2026-07-21-operational-run-admission.md`
- `docs/superpowers/specs/2026-07-21-operational-run-admission-design.md`
- `harness/src/insurance_harness/goldenset/admission.py`
- `harness/src/insurance_harness/goldenset/admission_coordinator.py`
- `harness/src/insurance_harness/goldenset/run_020.py`
- `harness/tests/test_operational_coordinator_031.py`
- `harness/tests/test_operational_stack_blocker_031.py` — deletion only. This A-C-only test asserts
  the temporary production blocker; D removes that blocker and replaces it with the four fresh
  finalizer/zero-effect boundary tests. The C parent contains the file and the D candidate must not.
- `harness/tests/test_run_admission_canary_authorization_020.py`
- `harness/tests/test_run_admission_canary_ledger_020.py`
- `harness/tests/test_run_admission_canary_runtime_020.py`
- `harness/tests/test_run_admission_candidate_resume_020.py`
- `harness/tests/test_run_admission_entrypoints_020.py`
- `harness/tests/test_run_admission_evaluator_020.py`
- `harness/tests/test_run_admission_production_wiring_020.py`
- `harness/tests/test_run_admission_request_pool_020.py`
- `harness/tests/test_run_admission_runtime_020.py`
- `harness/tests/test_run_admission_usage_020.py`
- `openspec/changes/020-golden-v01-baseline-run/specs/run/spec.md`
- `openspec/changes/031-operational-run-admission/design.md`
- `openspec/changes/031-operational-run-admission/proposal.md`
- `openspec/changes/031-operational-run-admission/specs/operational-admission/spec.md`
- `openspec/changes/031-operational-run-admission/tasks.md`
- `openspec/changes/031-operational-run-admission/validation-report.md`
- `openspec/changes/031-operational-run-admission/stacked-review-plan.md`
- this manifest.

D removes the temporary blocker and installs the only production submit/resume/begin-product path,
post-observation/pre-evaluator and post-evaluator reloads, post-settlement candidate finalization plus
normal/resume candidate-evaluator return topology/cap revalidation,
typed infrastructure failure reporting and conservative cost exposure.

D therefore owns exactly 26 paths. The 26th path is only the deletion above; rewriting it, moving its
assertions elsewhere, or adding a 27th path is outside this manifest.

## Main-equivalent and conflict decisions

- `openspec/changes/README.md`: mapped as `main-equivalent`; latest main already has the approved 031
  registry entry, so the canonical replay preserves the latest-main blob exactly.
- `HANDOFF.md`: conflict-approved D hunk; preserve latest main's Enterprise LLM Wiki/MVP control board
  and integrate only the 031 status section. The old checkpoint top-of-file status is superseded.
- `run_020.py`: replay only the finalizer Protocol/dependency/function and four call-site hunks on the
  C blob. Preserve the C `TrustedKeyPolicy -> public_key` adapter and the 027/030 composition/reason-
  code boundary; the old canonical whole-file blob is forbidden.
- `admission.py`: preserve the C/main `Mapping[str, Ed25519PublicKey]` evaluator contract. The only D
  adaptation separates the private testing ledger seam from the production root-owned ledger call.
- `admission_coordinator.py`: production observation refresh uses the B canonical no-argument
  controller path, which reloads topology/cap/transport identity from durable root-owned state;
  caller-selected target/nonce reconstruction is testing-only.

## Replay audit

For every stacked head, reviewers SHALL compare its changed paths and logical symbols with this
manifest. For the final D head:

1. `git diff --name-status C..D` is exactly the 26-path D allowlist; the blocker test is the sole
   deletion and is absent from D;
2. paths outside the allowlist preserve the exact C-parent blob and mode, including the nine frozen
   C security paths;
3. D-owned whole paths that remain compatible with the old canonical are compared blob-for-blob;
   the explicit adaptations above are reviewed by symbol/hunk and RED evidence instead of forcing
   obsolete B/C blobs back into the tree;
4. no temporary A–C blocker remains, while four-boundary/typed-blocker/zero-effect coverage remains;
5. aggregate focused/static/OpenSpec/diff/secret pass before cross-window review; the single final
   deterministic gate runs only after the exact frozen candidate receives C/I=0.

# 027 Validation Report

> Status: T1 inventory and Task 2 frozen authority contracts are complete. Task 3's
> canonical policy, opaque permit/decision authority and receipt models are implemented;
> Task 4 gateway/transport and production entrypoint wiring remain pending. Real-provider
> validation is not claimed here.

## Focused deterministic baseline

Command:

```bash
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m pytest -q tests/test_production_model_boundary_027.py
```

Recorded corrective result: **102 passed in 0.53s**. Focused Ruff passed, and strict mypy
over both `src/insurance_harness/model_policy` and the changed 027 test file reported no
issues. `git diff --check` also passed. These are focused Task 2/3 results, not a full
deterministic-suite claim.

Real provider: **NOT RUN**. The focused baseline is deterministic and does not prove
provider availability, canonical gateway readiness, production entrypoint closure or
completion of PWB1-PWB5.

## Admission binding decision

Task 2 freezes `StrictAdmissionRequestBinding` as the caller-declared expected scope.
Every field is independently mandatory:

- purpose, run schema version, run id/revision and Space;
- admission artifact ref and digest;
- manifest, eligibility, Golden slice and routing-policy hashes;
- schema, template-lock and structured-dispatch hashes;
- model-plan, deployment-roles and resource-caps hashes;
- rights and provenance hashes;
- clean integration SHA.

None of these expected values may be inferred, copied, defaulted or reconstructed from
admission **actual** observations. In particular, a probe, matching artifact or 020
canonical response cannot supply the expected scope for a 030 MVP run.

Task 2 also freezes rich, serializable `AdmissionBinding` actual data. It mirrors the full
expected scope as actual purpose/schema/run/Space/artifact and all hashes, and additionally
records READY/BLOCKED state, aware expiry, the exact approved `ModelIdentity` set and exact
approved template hashes. Raw READY data remains evidence, not process authority.

`AdmissionVerifier` is the sole frozen verification Protocol:
`verify(request: StrictAdmissionRequestBinding, /) -> VerifiedAdmission`. The returned
`VerifiedAdmission` is immutable, process-local, non-serializable and caller-unconstructable;
its serializable `AdmissionVerificationReceipt` records verifier id/version, verification
time, request digest, binding digest and verified-binding digest without granting authority.
The future canonical verifier registry must be selected from code by independent expected
purpose/run-schema values and must not accept caller binding, READY state or verifier
override.

Canonical production composition SHALL obtain `VerifiedAdmission` and inject one
`GuardedModelClient`. Every model call SHALL provide only
`VerifiedAdmission + ModelCallContext`. Inside that client, canonical policy SHALL evaluate
the exact approved identity and call scope, issue opaque process-local
`IssuedModelPermit`, and emit receipt-only `ModelPermitView`; the view is never call
authority. Caller-supplied permit, policy, issuer or guard is forbidden. Missing,
mismatched, expired, non-READY or cross-scope data SHALL fail closed before transport.

Task 3 implements policy/permit/decision authority as process-local identity side tables.
Capability objects carry no mutable payload slots; registry snapshots store canonical JSON,
primitive policy data and referenced capability identities. PID/process-nonce checks and
child-fork registry rotation revoke copied, deserialized, restarted or fork-inherited
objects. Public properties rebuild fresh audit DTOs, while authority predicates consume
only canonical registry snapshots. The canonical policy snapshot digest is bound into both
opaque `IssuedModelPermit` authority and receipt-only `ModelPermitView`. Approved identity
keys are rebuilt from exact built-in tuple/string values; subclasses, duplicates, malformed
roles and caller-iterator failures are rejected before a policy snapshot is registered.

`PolicyReceipt` validates coherent ALLOW/DENY shapes. DENY receipts take readable scope only
from verified admission facts and record attempted input solely as a domain-separated
digest; raw attempted provider/deployment/policy/purpose/schema/Space/run/revision/call-scope
values are not echoed. Expiry checks require aware datetimes and fail closed. Corrective
tests cover coordinated payload mutation, cross-Space/full-binding/call-scope replay,
policy/composition replacement, copied/constructed views, registry lifecycle, child-fork
rotation and concurrent reads with zero authority transfer.

Task 4 must still implement the canonical `GuardedModelClient`, transport boundary,
production registry/entrypoint wiring and call-scope recomputation from trusted
job/stage/input/prompt facts. Candidate-promotion orchestration SHALL validate receipts
upstream; it SHALL NOT add `IssuedModelPermit`, `ModelPolicy`, `AdmissionBinding` or receipt
parameters to zero-model product/knowledge functions.

## Scope and evidence status

- Entrypoint/package/command inventory: documented in
  `artifacts/entrypoint-inventory.md`.
- Real provider: **NOT RUN**.
- Task 2 frozen contracts: complete for strict request/rich binding,
  `AdmissionVerifier`, opaque `VerifiedAdmission`, verification receipt, opaque
  `IssuedModelPermit` and receipt-only `ModelPermitView`.
- Task 3 policy/permit/decision evaluator and production composition authority are complete.
  Task 4 remains pending for canonical verifier-registry integration,
  `GuardedModelClient`, transport enforcement, trusted call-scope recomputation and
  production entrypoint closure.
- Provider contract or quality claim: none.
- Product CLI and knowledge importer/merge/review/source-lifecycle/publisher exports:
  recorded as zero-model boundaries that keep their own governance/approval/snapshot
  contracts. They receive no new `IssuedModelPermit`, `ModelPolicy`, `AdmissionBinding`
  or receipt parameters; no product/knowledge code or state was changed.
- The gap described above is approved to be closed inside 027's own compiler/model-policy
  domain; no 020, 030, 031, knowledge, MCP, runtime, dataset or structured-import scope is
  borrowed.

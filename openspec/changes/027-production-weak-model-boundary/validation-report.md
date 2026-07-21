# 027 Validation Report

> Status: T1 inventory refreshed after rebase onto `fde06802`; Task 2 frozen authority
> contracts are implemented. Canonical verification/policy/gateway wiring and real-provider
> validation are not claimed here.

## Focused deterministic baseline

Command:

```bash
PYTHONPATH=src /Users/houjing/Documents/LLM_wiki/insurancekb-weknora/harness/.venv/bin/python \
  -m pytest -q tests/test_production_model_boundary_027.py
```

Recorded focused result: **28 passed in 0.56s**. Focused Ruff and mypy checks were also
clean. A fresh docs-correction rerun remained **28 passed in 0.29s**. These are focused
Task 2 results, not a full deterministic-suite claim.

Real provider: **NOT RUN**. The focused baseline is deterministic and does not prove
provider availability, canonical gateway readiness, or completion of PWB1-PWB5.

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

Once the Task 3/4 verifier registry, internal policy/decision receipt and gateway are
enforced, this design SHALL prevent borrowing 020 state for 030 even when model or template
values overlap. Candidate-promotion orchestration SHALL validate receipts upstream; it
SHALL NOT add `IssuedModelPermit`, `ModelPolicy`, `AdmissionBinding` or receipt parameters
to zero-model product/knowledge functions.

## Scope and evidence status

- Entrypoint/package/command inventory: documented in
  `artifacts/entrypoint-inventory.md`.
- Real provider: **NOT RUN**.
- Task 2 frozen contracts: complete for strict request/rich binding,
  `AdmissionVerifier`, opaque `VerifiedAdmission`, verification receipt, opaque
  `IssuedModelPermit` and receipt-only `ModelPermitView`.
- Task 3/4 remain pending for the canonical verifier registry, internal policy decision
  receipt, `ModelCallContext`, `GuardedModelClient`, production composition and entrypoint
  closure.
- Provider contract or quality claim: none.
- Product CLI and knowledge importer/merge/review/source-lifecycle/publisher exports:
  recorded as zero-model boundaries that keep their own governance/approval/snapshot
  contracts. They receive no new `IssuedModelPermit`, `ModelPolicy`, `AdmissionBinding`
  or receipt parameters; no product/knowledge code or state was changed.
- The gap described above is approved to be closed inside 027's own compiler/model-policy
  domain; no 020, 030, 031, knowledge, MCP, runtime, dataset or structured-import scope is
  borrowed.

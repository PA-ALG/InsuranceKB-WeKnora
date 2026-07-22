# 027 Validation Report

> Status: T1 inventory, Task 2 frozen authority contracts, Task 3 policy authority and
> Task 4's canonical atomic gateway are implemented and independently approved.
> Task 5 production entrypoint wiring is intentionally still pending.
> Real-provider validation is not claimed here.

## Focused deterministic baseline

Command:

```bash
cd harness
.venv/bin/python -m pytest -q tests/test_production_model_boundary_027.py
.venv/bin/python -m pytest -q tests/test_production_model_boundary_027.py \
  -k pwb4_gateway
.venv/bin/ruff check src/insurance_harness/model_policy \
  tests/test_production_model_boundary_027.py
.venv/bin/mypy --strict src/insurance_harness/model_policy \
  tests/test_production_model_boundary_027.py
cd ..
git diff --check -- harness/src/insurance_harness/model_policy/gateway.py \
  harness/src/insurance_harness/model_policy/models.py \
  harness/src/insurance_harness/model_policy/policy.py \
  harness/src/insurance_harness/model_policy/__init__.py \
  harness/tests/test_production_model_boundary_027.py \
  openspec/changes/027-production-weak-model-boundary/validation-report.md
```

Recorded Task 4 result: **193 passed in 2.19s**. The focused gateway subset reported
**91 passed, 102 deselected in 1.56s**. Focused Ruff passed, and strict mypy
over both `src/insurance_harness/model_policy` and the changed 027 test file reported no
issues. `git diff --check` also passed. These are focused Task 2/3/4 results, not a full
deterministic-suite claim.

Final independent Task 4 review: **Spec Approved** and **Quality Approved**, with zero
Critical or Important findings. One non-blocking lifecycle cleanup remains explicitly owned
by Task 5: if a misbehaving synchronous receipt sink returns a synchronous generator, the
call already fails closed with zero transport, but Task 5's durable sink adapter should also
best-effort close that generator and retain a regression test for the frame lifecycle.

Real provider: **NOT RUN**. The focused baseline is deterministic and does not prove
provider availability, production entrypoint closure or completion of PWB1-PWB5.

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
`GuardedModelClient`. Its public call accepts only `VerifiedAdmission` plus frozen,
non-authoritative `ModelCallFacts` and `ModelCallRequest`; it does not accept internal
`ModelCallContext`, a caller scope hash, permit, decision, policy, guard, verifier, binding
or clock. Inside that client, canonical policy evaluates the exact approved identity and
privately derived call scope, then issues opaque process-local
`IssuedModelPermit`, and emits receipt-only `ModelPermitView`; the view is never call
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

Task 4 implements the sealed `GuardedModelClient` as the only atomic native-async model-call
boundary. Its public `async call(...)` runs on the caller's event loop and thread; production
contains no `asyncio.run`, worker-thread or sync bridge. It accepts only the exact
package-owned canonical adapter backed by an opaque, non-copyable and non-serializable
executor capability; arbitrary caller adapters are factory-rejected. Executor and stateful
test-target authority live only in closure-private, lock-protected weak registries. Registry
values do not retain their weak keys. Their immutable canonical bytes and primitive tuples
are authenticated with a process-local HMAC over dispatcher, full identity, policy, route
configuration, object generations, target type/descriptor/code identity, exact target
snapshot/invoke function identity and code, their recursive closure fingerprints, PID and
process generation. Each consume rechecks the helper identity, code and closure digest
against the issuance snapshot before verifying the MAC. The execution callable uses only the
validated issuance helper copied to its local call snapshot; no module-global dispatcher,
executor-state or mutable helper-selector cell is reread after authorization. The gateway
supplies the sealed full bound `ModelIdentity` itself and immediately awaits only the freshly
authorized callable. The frozen transport terminal value is exact built-in `str`, matching
the existing compiler `ModelClient.complete` Protocol. The executor and gateway both reject
bytes, arbitrary objects, nested awaitables, iterators and sync/async generators. Rejected
deferred values are cancelled or closed; async cleanup is awaited. Regression tests verify
generator frames are closed, no lazy execution is observed, no second receipt is written and
no unclosed-deferred warning is emitted. A bare caller-defined `Awaitable` without an explicit
`aclose`/`cancel`/`close` lifecycle is never awaited during rejection, so its deferred body
cannot run. Cancellation while awaiting an explicit async cleanup propagates as
`CancelledError`; cleanup never converts cancellation into provider failure. Rejection uses
the stable, secret-free transport error.
`asyncio.CancelledError` remains cancellation and propagates without retry or
provider-failure relabeling.

The receipt sink remains a strict sync `record(receipt) -> None` boundary. An async sink is
factory-rejected; a sync sink that returns an awaitable or any other non-`None` value is a
typed `receipt_sink_failure`, with a deferred result closed when possible and zero
transport. Provider execution is eligible only after the canonical sync sink returned
successfully; Task 4 does not claim durable persistence. Selecting and proving a durable
production receipt sink is a Task 5 gate.

The gateway snapshots and revalidates frozen call facts/request, verifies content and
rendered-prompt digests, derives a domain-separated call-scope hash from
job/stage/attempt/input/prompt facts plus the canonical admission request, full binding and
verified-binding digests, and builds `ModelCallContext` only internally. The package-private
Task 4 factory validates the proposed transport identity against the canonical policy
snapshot, then issues an opaque executor and sealed `_BoundModelTransport` that bind
canonical identity JSON, policy digest, exact canonical adapter and the executor's
authenticated authority digest. The bound-transport registry is independently
closure-private and weak-keyed. Every pre-sink and post-sink snapshot must reproduce the
same authority digest; swapping a target, executor, binding or coordinated public view cannot
redirect the call. PID/process-generation checks, HMAC-key rotation and child-fork registry
reset revoke copied, collected, restarted or inherited authority. Because
canonical `IdentityKey` does not contain family, no deployment-name heuristic is used: the
full bound identity, including family, is compared exactly against call facts,
admission-approved identity and permit before transport. Wrong provider/deployment/role/
policy, strong and rolling identities are rejected at binding; a family mismatch is rejected
at call time with zero receipt and zero transport. The gateway has no payload attributes,
and the gateway, adapter, executor and transport binding are
non-copyable/non-serializable/fork-transferable.

The explicit stateful test bridge exposes no writable endpoint, model, credential, result or
call-list fields. Its closure retains canonical configuration bytes and observations, while
the executor keeps only a weak target reference and authenticates the issuance-time target
generation/configuration. Consumption revalidates the exact target type and async `complete`
descriptor/code against that canonical snapshot before returning a callable; invocation
revalidates the same target snapshot again immediately before using immutable result bytes.
The former writable result/route state and module-visible executor-state helpers no longer
exist; tests assert that route fields cannot be added or changed. Current regressions exercise
the actual closure helper selectors and helper dependencies and require failure before any
executor or target observation. Noncanonical adapter tests prove only factory rejection of
non-package executor shapes; they do not claim execution-time global/default drift coverage.
Separate barrier-controlled tests cover the target check/use interval and async revocation
after the executor is authorized but before the final target registry check. That late
revocation remains typed `authority_revalidation_failed`, preserves the single ALLOW policy
receipt and produces zero executor-terminal and target-I/O observations. Tests also cover
mismatched model issuance,
target/code mutation, rejection of a custom target shape, garbage collection, copy/deepcopy/
serialization, child-fork revocation and concurrent use. The bound gateway strongly retains
its package executor; the composition caller must retain the stateful target and receipt sink
for the required lifetime.

Stateful request mapping is deterministic and strict: valid UTF-8 `rendered_prompt` maps to
the target's `system` argument, and valid UTF-8 `content` maps to `user`. Both fields are
validated as non-empty UTF-8 at the public model boundary and revalidated from canonical
request data before authority is consumed. Invalid or forged byte payloads fail closed with
zero receipt and zero target calls.

For a policy DENY, the gateway persists exactly one frozen DENY receipt and makes zero
transport calls. For ALLOW, each pre-sink and post-sink authorization uses a two-phase A/B
optimistic snapshot. A reads gateway, composition, bound transport, package dispatcher,
executor route authority and policy authority, followed by a canonical decision/use-time
check with fresh UTC. B rereads all authority, must match A and the sealed expected
identity/digest, and performs a second last-moment UTC/expiry/full-scope decision check. Only
B's fresh callable may be returned. The pre-sink callable is explicitly discarded. After
the sync sink succeeds, the sink is freshly resolved and the entire A/B check runs again
immediately before awaiting the new transport callable. This catches expiry crossed during
authority validation as well as sink-time revocation, target/code mutation or route drift.

Sink failure, authority drift and malformed pre-evaluation input make zero transport calls.
A post-sink expiry/revocation/mutation can therefore leave one ALLOW policy receipt and zero
transport calls; the receipt records the policy permission decision, not transport success.
Invalid pre-evaluation inputs use a typed, secret-free error and zero sink because no safe
policy receipt exists yet. `ModelGatewayDenied` from a final authority check remains typed
instead of being relabelled as provider failure; `CancelledError` still propagates unchanged.
Other transport exceptions are converted to a secret-free typed error with no retry,
fallback, second receipt or candidate promotion. Executor observations are explicitly named
terminal observations and are not claimed as provider/network evidence; the stateful target's
post-authority observation is the deterministic I/O boundary used by Task 4 tests. Task 4
deliberately does not add orchestration outcome, retry, fallback or promotion ports.

The current executor modes and stateful target are test-only. Task 5 must add a reviewed
production dispatcher and immutable configuration snapshot that bind provider, endpoint,
credential and client lifetime to the exact `ModelIdentity`, while strongly retaining the
production client and sink. Task 5 must reuse this guard/binder instead of recreating model
policy or transport authorization outside it, and durable sink selection remains a Task 5
gate. Task 5 still owns canonical production composition and entrypoint wiring.

## Scope and evidence status

- Entrypoint/package/command inventory: documented in
  `artifacts/entrypoint-inventory.md`.
- Real provider: **NOT RUN**.
- Task 2 frozen contracts: complete for strict request/rich binding,
  `AdmissionVerifier`, opaque `VerifiedAdmission`, verification receipt, opaque
  `IssuedModelPermit` and receipt-only `ModelPermitView`.
- Task 3 policy/permit/decision evaluator and the composition-domain seal/evaluator hook
  are complete. Task 4's canonical `GuardedModelClient`, transport enforcement and trusted
  call-scope recomputation are complete and independently approved with zero Critical or
  Important findings.
  The 030 production verifier bridge remains absent and therefore fail-closed; Task 5 owns
  production composition/entrypoint wiring.
- Provider contract or quality claim: none.
- Product CLI and knowledge importer/merge/review/source-lifecycle/publisher exports:
  recorded as zero-model boundaries that keep their own governance/approval/snapshot
  contracts. They receive no new `IssuedModelPermit`, `ModelPolicy`, `AdmissionBinding`
  or receipt parameters; no product/knowledge code or state was changed.
- The gap described above is approved to be closed inside 027's own compiler/model-policy
  domain; no 020, 030, 031, knowledge, MCP, runtime, dataset or structured-import scope is
  borrowed.

# 027 Validation Report

> Status: Tasks 1–4 and Task 5's compiler-entrypoint boundary are implemented. Production
> command routing is guarded and fail-closed, but production model execution is deliberately
> unavailable until the separately owned 030 verifier and reviewed 028 provider adapter
> exist. Real-provider validation is not claimed here.

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
Critical or Important findings. The Task 5 lifecycle regression now proves that a
misbehaving synchronous sink's returned generator is closed with zero transport. No durable
production sink is claimed because the reviewed 028 adapter that must own production
transport/sink lifetime is absent.

Real provider: **NOT RUN**. The focused baseline is deterministic and does not prove
provider availability or a usable production transport.

## Task 5 compiler-entrypoint evidence

The production compiler command now requires `model_profile=production` and complete,
independent frozen policy settings. It has no CLI model or replay override. Before DB/source
or provider construction it compares the CLI Space, loads the code-owned schema bytes,
derives the canonical schema hash, builds `StrictAdmissionRequestBinding`, fixes weak-model
identities for the compiler roles, and invokes the single composition verifier selector.
Missing 030 fails as `canonical_verifier_unavailable`. A deterministic selector fake proves
that even successful verification ends as `canonical_adapter_unavailable` with zero raw
transport construction while the reviewed 028 adapter is absent. Therefore this report does
not claim that production model calls are available.

`ExtractionPipeline` defaults to `model_profile=disabled`. Production construction requires
the sealed compiler client, exact extract deployment, canonical schema hash, DB-attested
Space and guarded judge. A code-owned weak-key snapshot freezes independent copies of the
client, registry, model id, config and scope; the production judge is rebuilt from the sealed
client. Behavioral TOCTOU tests coordinate post-construction replacement of client, judge,
registry, model, profile and Space and observe zero raw-client calls while canonical run
identity and guarded dispatch remain in use. Offline/replay pipelines have no such snapshot
and retain their explicitly selected test behavior.

After durable attempt reservation, compiler calls derive separate, domain-separated input,
content and rendered-prompt digests from trusted reservation/run/field facts and code-owned
prompt/schema facts. The compiler template hash names the exact code-owned prompt template;
it is not a 028 `TemplatePackage` hash. Exact template membership, stage role and reservation
identity are evaluated by `GuardedModelClient`. Template mismatch records DENY and performs
zero transport calls. Unknown/rolling/strong identity, raw client, legacy gateway/Claude
judge and missing/default profile tests use explicit client/schema/transport counters and
all observe zero calls before typed refusal.

Approved weak-transport failure is classified as retryable without changing identity. Guarded
extract, verify/vote and consensus/judge regressions each drive the canonical failing executor
to the exact configured attempt limit and observe zero strong/offline fallback calls. Extract
already returned an `unknown/dead_letter`; Task 5 review found that vote retained its original
present/high candidate and judge escaped on its first failure. The corrective implementation
now supersedes every candidate for the failed field with one `unknown/dead_letter`, records a
compiler dead letter and leaves no judge queue or ChangeSet/promotion output. Template/policy
DENY remains non-retryable.

Replay and offline execution require explicit `replay` or `offline-eval`; replay additionally
requires a fixture directory. `apply-judgements` requires explicit `manual` or
`offline-eval`. The production compiler never selects these paths as fallback. This is a
command/model-authority boundary only: no general downstream artifact-provenance or
candidate-promotion gate was added, so later import/use of offline artifacts remains a
separate owner/adapter governance contract.

Independent quality review found that the inventoried product classifier still accepted a
caller-provided raw model client without a profile. A deterministic RED observed one raw
`complete` call. The approved minimal correction keeps the default and product CLI paths
strictly deterministic, permits that historical fallback only with explicit `offline-eval`
or `replay`, and raises typed `ClassificationModelBoundaryError` before `complete` for
missing/default/disabled/production/unknown profiles. This does not add a production guarded
classifier; future production classification must enter canonical composition and derive
trusted call facts separately.

The final quality review also exposed contradictory inventory wording around compiler
helpers. `call_and_parse`, `gapfill_field`, `vote_field` and standalone `JudgeDispatcher`
are library/transport primitives: raw-client use is offline/non-production and conveys no
`VerifiedAdmission`, receipt authority or production-state progression. Production means
the code-owned composition root, production CLI and sealed pipeline/factory/persistent entry
path. Machine-enumerated source proofs require those roots to construct/validate the sealed
client, forbid raw client constructors in their call sites, retain the guarded primitive
chain and keep the callable primitives out of the compiler package export surface. Arbitrary
same-process Python relabelling an offline return value is outside this capability boundary;
future 028 production orchestration must pass `GuardedModelClient` into the primitives.

Final deterministic Task 5 evidence:

```bash
cd harness
PYTHONPATH=src .venv/bin/python3.12 -m pytest -q \
  tests/test_production_entrypoints_027.py \
  tests/test_production_model_boundary_027.py tests/test_config.py \
  tests/test_compiler_llm.py tests/test_source_pipeline_cli_017.py \
  tests/test_product_classify.py
# 286 passed in 4.32s

PYTHONPATH=src .venv/bin/python3.12 -m pytest -q \
  tests/test_compiler_pipeline.py tests/test_source_pipeline_checkpoint_017.py \
  tests/test_source_pipeline_runtime_017.py tests/test_source_pipeline_cli_017.py \
  tests/test_recall_config_024.py
# 128 passed in 15.56s

.venv/bin/ruff check src/insurance_harness/model_policy \
  src/insurance_harness/config.py src/insurance_harness/compiler/cli.py \
  src/insurance_harness/compiler/extract.py src/insurance_harness/compiler/judge.py \
  src/insurance_harness/compiler/llm.py src/insurance_harness/compiler/pipeline.py \
  src/insurance_harness/product/classify.py \
  tests/test_production_entrypoints_027.py \
  tests/test_production_model_boundary_027.py tests/test_source_pipeline_cli_017.py \
  tests/test_product_classify.py \
  tests/test_compiler_pipeline.py tests/test_source_pipeline_checkpoint_017.py \
  tests/test_source_pipeline_runtime_017.py tests/support/source_pipeline.py
# All checks passed!

.venv/bin/mypy src/insurance_harness/model_policy \
  src/insurance_harness/config.py src/insurance_harness/compiler/cli.py \
  src/insurance_harness/compiler/extract.py src/insurance_harness/compiler/judge.py \
  src/insurance_harness/compiler/llm.py src/insurance_harness/compiler/pipeline.py \
  src/insurance_harness/product/classify.py
# Success: no issues found in 13 source files
```

The first inventory RED was one missing compiler CLI guard edge. The coordinated pipeline
TOCTOU RED was three failures: one raw extraction call, one raw judge route and one attacker
registry identity read. The initial PWB3 transport RED showed extraction
`ModelTransportError` escaping before the configured attempt limit. Independent review then
added two corrective REDs: judge made one attempt and escaped, while exhausted vote preserved
the pre-verification present/high candidate. All three guarded stages now use the configured
weak-model limit and fail as `unknown/dead_letter`; policy DENY remains non-retryable. The
exact old source-CLI compatibility slice is also GREEN
at **18 passed**, with production tests moved to the canonical builder and legacy gateway
cleanup retained only under explicit `offline-eval`.

Real provider: **NOT RUN**.

## Task 6 PR-ready evidence

The single local complete deterministic pytest run was executed after the first independent
spec and quality approvals. It is recorded as a failure, not a pass:

```bash
cd harness
PYTHONPATH=src .venv/bin/pytest -m "not live and not integration_postgres" -q
# 2940 passed, 30 deselected, 12 failed in 653.61s (real 660.52s)
```

Eleven failures stopped at `PipelineConfig.model_profile=disabled` before their original
business assertions because four `ExtractionPipeline` construction sites across three older
test areas had not made their offline lane explicit. The approved mechanical migration added
`model_profile="offline-eval"` only to the existing evidence-lineage, template-fastpath and
precommit-contract fixtures. The 020 test was renamed and documents that it proves only the
artifact precommit invariant; it does not claim production model admission. The 020 executor
itself still defaults fail-closed before the reviewed 028 wiring exists; separate 027 tests
cover the default-disabled/raw-client rejection and sealed-client production boundary. The
twelfth failure was a three-second spawned session-lock holder timeout under full-suite load;
unchanged focused rerun passed:

```bash
PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_run_admission_session_lock_020.py::test_d1_5_competitor_fails_before_recovery_or_ledger_mutation
# 1 passed in 4.08s

PYTHONPATH=src .venv/bin/pytest -q \
  tests/test_evidence_lineage_017.py tests/test_template_fastpath.py \
  tests/test_run_admission_baseline_production_020.py
# 102 passed in 4.21s

.venv/bin/ruff check .
# All checks passed! (real 0.10s)

.venv/bin/mypy src tests
# Success: no issues found in 305 source files (real 2.38s)

DO_NOT_TRACK=1 openspec validate 027-production-weak-model-boundary --strict
# Change '027-production-weak-model-boundary' is valid

git diff --check
# PASS

cli/scripts/check-secret-tokens.sh
# no committed credentials found in docs
```

Independent final Task 6 review approved the mechanical patch with zero Critical and zero
Important findings. The spec/scope reviewer also reported zero Minor findings after fresh
`102 passed` compatibility and `240 passed` 027-focused runs. The quality reviewer reported
one documentation-only Minor—the four-construction-site wording and explicit 020 fail-closed
state above—and otherwise approved after a fresh combined `342 passed` run plus the unchanged
session-lock focused test.

Per the control decision, the failed local full run is not relabelled as PASS and is not
repeated merely to erase its evidence. The final pushed SHA must first open as a Draft PR and
receive the equivalent GitHub deterministic CI. Only an all-green equivalent CI may convert
the PR to Ready; if no equivalent workflow exists, a second local complete deterministic run
is required before Ready.

Seven-stage record (honest availability): design/coding/review-wait/rework active durations
were not instrumented and are **NOT RECORDED** rather than inferred from commit timestamps;
focused command times are 4.32s, 15.56s, 4.08s and 4.21s as listed above; local full pytest
was 653.61s (real 660.52s) and failed 12; final full CI is **PENDING**; live/provider is
**NOT RUN**. PostgreSQL `integration_postgres` is **NOT RUN** in the local deterministic lane.

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

The current executor modes and stateful target are test-only. Task 5 wires the compiler to
the fixed verifier selector and then deliberately returns `canonical_adapter_unavailable`.
The separately owned 028 implementation must add a reviewed production adapter and durable
sink that bind provider, endpoint, credential and client lifetime to the exact
`ModelIdentity`, reusing this guard/binder rather than recreating policy authorization.

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
  Task 5's compiler composition/entrypoint wiring is complete and fail-closed. The selected
  030 verifier module and reviewed 028 provider adapter remain absent, so production model
  execution is unavailable.
- Provider contract or quality claim: none; real provider is **NOT RUN**.
- Product CLI and knowledge importer/merge/review/source-lifecycle/publisher exports:
  recorded as zero-model boundaries that keep their own governance/approval/snapshot
  contracts. They receive no new `IssuedModelPermit`, `ModelPolicy`, `AdmissionBinding`
  or receipt parameters; no product/knowledge code or state was changed.
- No 020, 030, 031, knowledge, MCP, runtime, dataset or structured-import implementation
  scope is borrowed. This report does not claim a cross-domain artifact-promotion gate.

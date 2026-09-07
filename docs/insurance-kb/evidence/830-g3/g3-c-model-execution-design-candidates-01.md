# G3 C actual model execution: bounded design candidates (read-only 01)

Date: 2026-09-07

Status: `DESIGN_CANDIDATES_READY; REAL CALL AUTHORITY AND REAL INPUTS ABSENT`.

Scope: static inspection only. This report created no admission artifact, permit,
PolicyReceipt, provider request, HTTP call, database write, candidate, or release.

## Fixed findings

1. C already requires a real guard-issued receipt. `ModelReceiptBindingV1` carries the
   `PolicyReceipt`, sorted material bindings, actual request/input/raw-output/execution
   receipt hashes (`batch_entity_resolution_830_g3.py:360-366`). `_valid_model_receipt`
   requires `ALLOW`, coherent permit data, exact G3 purpose/schema/classify identity,
   corpus Space and material entry hashes (`:1075-1104`). Human approval is a separate
   authority input; it cannot be copied into either permit field or a PolicyReceipt.
2. The existing sealed authority chain is reusable: `GuardedModelClient.call` revalidates
   the admission, facts, exact request bytes and bound identity (`gateway.py:238-297`),
   persists the decision before transport (`:299-332`), and fails closed on sink errors
   (`:466-476`). `PolicyReceipt` is explicitly audit data and never transport authority
   (`models.py:246-309`); the sink is synchronous (`:312-315`).
3. Current production wiring cannot execute G3 unchanged. The canonical selector accepts
   only the MVP purpose/schema (`run_admission/evaluator.py:421-502`); the compiler CLI
   binds no `classify` identity and ends in `canonical_adapter_unavailable`
   (`compiler/cli.py:217-251`). Test-only gateway constructors are not authority.
4. G2 proves a useful bounded-run audit shape, not C authority. Its approved budget fixed
   run IDs, two calls, model/endpoint, token ceilings, zero retries, fail-stop behavior and
   no candidate approval (`b-source-recovery-budget.json:2-29`). Compile and review each
   preserved validated result/response-receipt hashes and call counts
   (`b-source-compile-execution.json:2-22`; `b-source-review-execution.json:2-40`). Exact
   private artifacts also retain request identity, STARTED, HTTP request/response, raw model
   output and response receipt. The historical runner source is absent, and those artifacts
   contain no current C PolicyReceipt; reuse their persistence pattern only.
5. The model cannot author the final `MaterialProposalV1` verbatim. That DTO contains
   `model_request_sha256` and its own hash (`batch_entity_resolution_830_g3.py:432-473`).
   Putting the final HTTP-byte hash inside the request that is itself hashed is circular.
   A local assembler must strictly parse a model-facing semantic response without transport
   hashes, inject the already computed actual request hash, verify every Evidence quote and
   corpus reference, then compute the canonical material/proposal-batch hashes. It must not
   fill absent labels, identity fields, Evidence or dispositions.

## Candidate A — bounded G3 guarded executor (recommended)

Add one G3-specific command/module for this frozen batch; do not create a service, database
or caller-supplied transport authority. Make only the narrow extensions inside the existing
model-policy composition root:

- select exactly `(g3-batch-resolution, 830-g3-v1)` and verify one frozen admission/run plan;
- bind exactly one reviewed `classify` `ModelIdentity` and model-plan/template set;
- construct a code-owned OpenAI-compatible transport behind `GuardedModelClient`;
- use a durable synchronous `ReceiptSink` that creates and fsyncs one immutable receipt file
  before the transport can run.

The command validates frozen Catalog/Corpus/ExistingSnapshot/Policy/page map and a sorted
window manifest; writes request identity and durable STARTED; serializes exact request bytes
with the existing `compiler/llm.py:376` `openai_compat_request_bytes`; invokes only the sealed
guard; and saves exact request bytes, raw HTTP response, exact returned content, emitted
PolicyReceipt and an execution receipt atomically. No retry or redirect is allowed. A failed
or outcome-unknown call stops all later windows and preserves partial artifacts. A successful
semantic response is assembled locally as described above and then validated as C DTOs.

The execution receipt must bind the separately hashed human authorization/budget artifact,
admission artifact and verified binding, window/material manifest, request HTTP bytes,
PolicyReceipt bytes, response HTTP bytes, raw returned content, parsed semantic projection,
final `MaterialProposalV1` values, identity/model/endpoint/protocol, status and provider usage.
It grants no candidate or release approval.

This is the shortest closure in the existing G3 scope: one profile, one identity, one bounded
runner and one durable sink. It does not require reopening historical 027/028 as projects or
finishing a generic production adapter.

## Candidate B — narrow `ProductionCompilerClient` classify entry

Add the same G3 profile, exact identity, durable sink and code-owned guarded transport, then
bind only `classify` into a dedicated G3 entrypoint that calls existing
`compiler/llm.py:239` `_complete_reserved_model_call`. That code already derives
`ModelCallRequest`/`ModelCallFacts`; `compiler/llm.py:224` maps the classify role.

This reuses reservation/metering and template/input fact construction, but changes more
shared compiler surface and risks inheriting assumptions from extract/gap/verify/consensus.
It must not call `_build_production_compiler_client` or relax its fail-closed state. The G3
entrypoint still needs the same semantic-response assembler and artifact writer. Therefore
Candidate B has no authority or audit advantage for this one batch; choose it only if review
finds the existing reservation semantics already match the final G3 window plan exactly.

## Windows, authorization and five outcomes

- Freeze sorted, non-overlapping material windows and a maximum call/token budget before
  seeking real external-send authorization. One window may cover all 15 only after actual
  W1 bytes show it fits. `ProposalBatchV1` permits multiple receipt bindings and binds each
  proposal to its actual request (`batch_entity_resolution_830_g3.py:477-496`).
- The human authorization names exact frozen request/window inputs and limits effects. At
  runtime the canonical verifier issues `VerifiedAdmission`; the guard alone evaluates and
  persists the ALLOW/DENY PolicyReceipt. None may be synthesized from the authorization.
- The model proposes semantic identity/evidence. `resolve_batch` produces MATCH, CREATE,
  MULTI, NEEDS_CONFIRM or QUARANTINE from real proposal/source/policy/existing inputs. Five
  nonzero classes are a validation target, not permission to invent a proposal, source defect,
  Seed label or QUARANTINE. A valid batch may have zero in any class.

## Work possible before source approval

- Review and fake-test the bounded runner, O_EXCL/fsync sink, no-retry transport wrapper,
  fail-stop ledger, artifact manifest and strict semantic-response parser with fake bytes.
- Freeze the model-facing response schema, prompt/template source, canonical JSON rules,
  candidate classify identity/model/endpoint/protocol and proposed budget ceiling.
- Draft the exact admission/authorization preview and Policy/Seed evaluation proposal, while
  marking all source-bound hashes and real outcomes unresolved.
- Complete source-independent catalog validation and native-page join methodology.

## Work that must wait for actual SOURCE_PASS / W1 / source IDs

- Freeze all 15 RegisteredSource and acquisition receipts, actual knowledge/source/revision
  IDs, complete W1 rows/manifests, canonical native hashes and pre-model page assignment.
- Build the actual `BatchCorpusV1`, actual serving-head `ExistingEntitySnapshotV1`, accepted
  `BatchResolutionPolicyV1`, exact windows/material bindings and token measurements.
- Render and serialize the exact request bytes; only then are the request SHA and final
  authorization preview knowable. Current source authorization does not authorize these C
  classifier calls (`c-model-seam-root-disposition-01.json:11-13`).
- After separate explicit external-send approval: verify admission, execute through the guard,
  persist real PolicyReceipt/request/response/raw output, assemble the ProposalBatch, and run
  pure `resolve_batch`. No batch candidate or release follows without its own existing gate.

## Decision

Candidate A is reviewable within current G3 scope. Remaining execution blockers are concrete:
an accepted G3 admission/profile instance, exact classify identity/model configuration, durable
sink and bounded transport factory, final semantic response schema/parser, actual SOURCE_PASS
inputs/page map/ExistingSnapshot/Policy/windows, and separate C model-call authorization. None
requires a generic platform, but none may be replaced by historical G2 receipts or user prose.


# G3 C model execution seams — read-only, 2026-09-07

Scope: static inspection only; HTTP/provider/DB/Docker calls=0, writes to repo=0.

## Required G3 scope already enforced by C

- `harness/src/insurance_harness/knowledge_compiler/batch_entity_resolution_830_g3.py`
  fixes purpose=`g3-batch-resolution`, run schema=`830-g3-v1`, role=`classify`.
- `_valid_model_receipt` requires both `PolicyReceipt` and its `permit_view` to match
  purpose/schema, requires `permit_digest`, exact corpus Space, classify identity key,
  material entry hashes, and G3 classifier-input hash. The receipt is evidence only;
  it cannot authorize transport.

## Existing authority chain that can be reused

1. `model_policy/composition.py:ProductionModelComposition.verify` is the code-owned
   verification entry; `_bind_verified_production_model_composition` binds exact approved
   `ModelIdentity` keys and model-plan hash after canonical admission verification.
2. `model_policy/gateway.py:GuardedModelClient.call` revalidates VerifiedAdmission,
   `ModelCallFacts`, request-byte digests, role/identity/purpose/schema/Space/template/model
   plan, persists one `PolicyReceipt`, then and only then invokes its sealed transport.
3. `compiler/llm.py:_complete_reserved_model_call` is the closest implemented caller:
   it maps `classify` stage to classify role, creates `ModelCallRequest`/`ModelCallFacts`,
   and calls the guard. Its reservation and template/input hashing can be reused only if
   a G3 orchestration owner supplies the exact G3 run/material facts.
4. `compiler/llm.py:openai_compat_request_bytes` is the existing exact HTTP-body
   serializer. `knowledge_compiler/deepseek_locator_extractor_596_1.py:
   _deepseek_request_bytes` is a G2/schema67 specialization, not a G3 identity.
5. `knowledge_compiler/ec01_formal_candidate_run_815.py:_RecordingTransport` shows the
   bounded G2 response-byte/hash capture pattern. It records response content in memory;
   it is not a durable PolicyReceipt sink and does not itself persist exact HTTP bytes.

## Current blockers/config gaps before any real G3 classify attempt

- No registered admission profile exists for the G3 pair. `run_admission/evaluator.py:
  select_canonical_admission_verifier` accepts only `enterprise-wiki-mvp` /
  `enterprise-wiki-mvp.v1`; the requested G3 pair returns `unknown_admission_profile`.
- No production transport assembly exists. `compiler/cli.py:
  _build_production_compiler_client` verifies/binds and then deliberately raises
  `canonical_adapter_unavailable`; gateway assembly and stateful executor constructors in
  `gateway.py` are explicitly test-only. A fake/test constructor cannot be used for G3.
- The compiler production builder currently creates extract/gap/verify/consensus
  identities and omits classify, although the generic reserved-call code understands the
  classify role. A G3 production composition must bind the approved classify identity.
- No durable production `ReceiptSink` implementation is present. The guard requires a
  synchronous `record(receipt) -> None` before transport; test collectors are not usable.
- `existing-model-config-readonly.json` contains the G2 runtime KB embedding model and a
  summary-model ID, with details only for the embedding row. It contains no approved
  classify `ModelIdentity` (provider, immutable deployment, family, role, policy version),
  no G3 model-plan/admission/template hashes, no G3 endpoint/protocol binding, and no
  classify credential reference. The summary ID cannot be inferred to be the classifier.
- Existing G2 execution artifacts demonstrate hashes and saved raw outputs, but their
  actual provider runners are not present as reusable production source. The EC01 recorder
  stores response bytes only. Before execution, freeze one durable artifact writer that
  atomically retains exact serialized HTTP request bytes, raw HTTP response bytes, their
  hashes, the guard-emitted PolicyReceipt, and the G3 execution receipt/material bindings.

## Shortest safe integration point

Add G3 purpose/schema support at the existing canonical admission selector and complete
the already-owned 028 production adapter/composition path; then invoke the existing guard
with role `classify` and use the G2 byte-capture shape around that guarded transport. Do not
call `OpenAICompatClient` or a legacy G2 transport directly: those paths can save raw bytes
but cannot issue the required real permit/PolicyReceipt. Freeze the exact classify model
identity, admission artifact/model-plan/template hashes, G3 run/Space/revision, endpoint
protocol, credential reference, synchronous durable receipt sink, and raw-artifact paths
before asking for external-send authorization.

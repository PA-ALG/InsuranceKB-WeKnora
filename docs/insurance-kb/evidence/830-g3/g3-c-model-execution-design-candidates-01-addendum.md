# G3 C model execution candidate A — admission scope correction

Date: 2026-09-07

Status: `CANDIDATE_A_REQUIRES_A_BOUNDED_NEW_SIGNED_PROFILE; NOT_JUST_A_SELECTOR_CASE`.
No implementation or runtime action was performed.

The current `StrictAdmissionRequestBinding` and `AdmissionBinding` make all content,
eligibility, golden, routing, schema, template, structured-dispatch, model-plan,
deployment-role, resource-cap, rights, provenance and clean-integration hashes mandatory
(`model_policy/admission.py:61-119`). The existing verifier derives them with MVP-specific
23-entry data, five registration records and fixed routing/golden schemas
(`run_admission/evaluator.py:260-385`). Its signed payload is exactly `MvpAdmissionPlan`,
including entry count 23 and the full lock set (`run_admission/models.py:285-360`), and the
envelope is bound to that payload/signature domain (`:388-414`). Therefore adding the G3
purpose/schema pair to `select_canonical_admission_verifier` is insufficient and unsafe.

A real Candidate A requires a separate, narrowly typed
`G3BatchResolutionAdmissionPlan` and signature domain/envelope branch, plus a code-owned
verifier that derives every mandatory `AdmissionBinding` fact from current G3 artifacts.
It may reuse the shared request/binding/VerifiedAdmission DTOs, trust-root signature check,
composition, gateway and PolicyReceipt machinery. It must not reuse MVP field meanings with
dummy, empty or unrelated hashes.

Facts that can be derived once the corresponding G3 artifacts are frozen are: purpose and
schema; one run ID/revision and actual Space; approval artifact ref/digest and expiry;
material/window manifest; classifier response schema; exact prompt/template locks; one
approved classify identity and model-plan/deployment-role hashes; call/token/time caps;
source/acquisition/native/W1 corpus provenance; rights/external-send scope; repository clean
integration SHA. The profile must specify exact canonical derivations for each.

Facts not currently available are the actual SOURCE_PASS corpus/provenance and rights closure,
final windows and request manifest, accepted response schema/template, accepted classify
identity/model configuration, signed external-send approval, and a legitimate golden/Seed
artifact. `golden_slice_hash`, `eligibility_hash`, `routing_policy_hash` and
`structured_dispatch_hash` cannot inherit MVP semantics; the G3 profile must define bounded
C-specific meanings backed by real artifacts. If G3 has no legitimate golden slice, the
shared mandatory field cannot be filled with a placeholder: either freeze an actual G3
validation slice or explicitly revise the shared admission schema under independent review.

The production weak-model policy is a second independent gate. Its DeepSeek exception is
exactly `(deepseek, deepseek-v4-flash, extract, schema67-deepseek-v1)`
(`model_policy/policy.py:255-303`), so the G2 model cannot be relabeled `classify`. A Qwen
candidate must match an already code-allowed provider/family/deployment grammar and still be
the exact identity in the signed G3 plan and separately approved human window; no provider
probe or policy broadening is justified here.

This profile/verifier is more than a one-layer runner connection. It remains bounded to C and
does not require a generic adapter, but it needs its own design and independent review before
Candidate A implementation. Until then the correct boundary is STOP before any real C model
call.


# 020 Golden v0.1 Run Admission Design

Date: 2026-07-19

> [!CAUTION]
> **历史设计，不能单独授权运行。** 本文保留 020 T1 admission 合同与历史上下文；当前权威门禁由 [Enterprise LLM Wiki 北极星设计](2026-07-21-enterprise-llm-wiki-north-star-design.md) 取代。`NS-RIGHTS=recorded` 已满足；020 真实 annotation/baseline/judge/merge/release 仍必须满足 `NS-0=verified ∧ canonical admission=READY`，且使用经新 OpenSpec/质量验收的 execution surface。030 MVP 使用独立 admission，不能借用本文工件。

## Context

Change 020 is the first budgeted data run on the critical path. It completes the two
missing Golden products and then runs the thirteen-product weak-model baseline. The
operation consumes external model capacity, writes resumable artifacts, and later
becomes evidence for a production QualityProfile. A prose checklist alone cannot
prevent a stale fingerprint, an unapproved model, or an insufficient budget from
starting a call.

The current workspace is intentionally not ready:

- change 021 has not been committed and merged into `main`;
- the eleven historical WIP `golden.jsonl` files do not contain per-record
  `annotator_model` or `created_at` fields;
- the two missing products have source PDFs and field plans but no Golden records;
- the historical baseline script predates the current compiler source contract and
  has no total token/cost reservation guard.

The admission implementation must therefore be useful while returning `BLOCKED`.
It must never turn incomplete evidence into `READY` merely to unblock a run.

## Goals

1. Represent the exact annotator, weak extractor, and judge identities without
   ambiguous aliases.
2. Bind one admission revision to dependency revisions, all deterministic input
   fingerprints, the thirteen-product run plan, and cryptographically verifiable
   business approvals.
3. Check credentials and endpoint connectivity without calling an inference route.
4. Fail closed when historical Golden provenance is absent or unproved.
5. Produce a redacted, auditable `READY` or `BLOCKED` artifact that a later runtime
   must revalidate before starting a product.
6. Reserve the worst-case cost of the next product before it starts and stop safely
   between products when the remaining approved budget is insufficient.

## Non-goals

- No annotation, extraction, judging, or other model inference in T1.
- No relabelling of the eleven existing products.
- No rewrite of extraction semantics, evaluation metrics, or 019 release/profile
  contracts.
- No claim that an offline/static check is sufficient for `READY`.
- No secret values in configuration, reports, logs, exceptions, or committed files.

## Chosen approach

Use a typed, machine-readable admission plan plus a fail-closed CLI. Generate the
human-readable `run-admission.md` and canonical JSON result from the same evaluated
object.

A documentation-only checklist was rejected because it is not load-bearing. Directly
embedding all checks in the historical baseline script was rejected because that
mixes T1 with the broken runner and makes the safety gate impossible to test without
the expensive path.

## Admission contract

### Model roles

The plan contains exactly three roles:

- `annotator`: creates the two missing Golden products;
- `weak_extractor`: runs the product extraction baseline;
- `judge`: resolves the configured judge path or records the explicit external
  adjudication contract.

Every role records a non-empty `provider`, exact `model_id`, protocol, base URL, API
key environment-variable name, provider-policy identifier, and signed
`expected_model_revision` or immutable deployment ID. Exactness is provider-specific:
the policy fixes the accepted model-ID grammar and the canonical metadata fields used
to prove that revision/deployment. Model aliases such as `best`, `latest`, or a family
name without a concrete provider model ID are invalid. A provider that cannot expose
a stable revision/deployment identity cannot make this reproducible baseline
`READY`; observation time alone is not a substitute. Roles may share a credential in
the local environment, but the plan never infers sharing and records each reference
explicitly.

The initial known weak-extractor profile is Bailian/DashScope
`deepseek-v4-flash`. The final annotator and judge IDs remain blocked until they are
explicitly selected and approved; the checker must not invent them from local-live
WeKnora roles. The judge is a model role for this baseline. A `claude-session` label
is not sufficient unless the exact executing provider/model and adapter contract are
pinned. Human review remains the final governance step but does not replace the judge
model identity required by admission.

The tracked pre-admission document represents this incompleteness with a distinct
typed `pending_immutable_identity` variant whose immutable revision/deployment fields
are necessarily null. It is a well-formed input that always derives `BLOCKED`; it is
not accepted by the probe or budget-rate identity functions. Likewise, a missing
required product input uses `pending_required_input`, and a not-yet-approved budget
uses a null contract reference. This avoids fake SHAs/revisions while preserving the
exit-2 distinction between an honest incomplete plan and an invalid exit-1 document.

### Dependency and input pins

One plan pins:

- the merge revisions that delivered changes 019 and 021;
- schema, prompt, template, WIP Golden, and execution-surface tree fingerprints;
- a canonical manifest containing exactly thirteen unique product directories, their
  line keys, every consumed PDF digest, `product_meta.json` digest, `fields.json`
  digest, and any other consumed input digest;
- the checkpoint/run root as a repository-relative path.

Each required change revision must be an ancestor of the evaluated repository
revision. The evaluated commit is recorded in the result rather than embedded in the
tracked plan, avoiding a self-referential commit SHA. The checker computes the
domain-separated canonical SHA-256 of this complete identity request and requires the
signed plan payload to bind that digest; replacing the manifest and its matching file
digests cannot reuse an existing provenance/budget approval. The checker computes the
execution-surface tree digest from all tracked and untracked files under declared
consumed code/config/input roots, excluding only explicit cache/output patterns. An
unlisted, missing, extra, duplicate, dirty, or changed consumed file changes the
digest and blocks admission. Absolute paths are rejected. Shared digests and the next
product's digests are recomputed before every product call.

### Historical Golden provenance

The eleven existing products need a product-specific provenance record containing
the exact provider/model ID, an annotation time or explicitly documented bounded
time, and the evidence basis. A global `default_annotator` is never acceptable
admission evidence. Unknown provenance is a visible blocker; the checker must not
mutate WIP rows or fabricate timestamps.

Provenance and budget approval use detached Ed25519 approval envelopes. The canonical
plan payload includes one stable `run_identity` and purpose (`gs-v0.1-baseline`); one
admission is valid for exactly that run and cannot authorize a newly named run. Its
`plan_payload_hash` excludes every approval envelope, observation, and derived state,
so it has no self-reference.

Signatures use a versioned, domain-separated byte contract, never ad-hoc field
concatenation:

```text
UTF8("insurancekb.run-admission.<budget|provenance>.v1\0")
  || canonical_json_utf8(envelope_payload)
```

`canonical_json_utf8` rejects floats and unknown fields, sorts object keys, preserves
array order, uses compact separators, and encodes UTF-8 without ASCII escaping. The
YAML boundary also rejects duplicate mapping keys instead of applying last-key-wins.
The
envelope payload includes `plan_payload_hash`, `run_identity`, purpose, scope,
approver identity/role, issued/expiry times, and the exact approved budget or product
entries. A budget entry repeats the approved ceilings and binds the canonical full
budget contract by SHA-256; revision 1 has no predecessor, while every later signed
payload carries a monotonic revision and the previous approval-envelope digest.
Trusted approver public keys and allowed roles come from deployment-owned
configuration outside the plan/repository. The run CLI cannot select that file: the
production loader only accepts the code-fixed, root-owned, non-symlink
`/etc/insurancekb/run-admission-trust.yaml` with no group/world write permission. An
unknown key, unauthorized role,
expired envelope, wrong domain/scope/run/payload hash/contract hash/chain, or modified
attestation blocks admission.

The two new products acquire provenance from their actual model calls in T2 and are
not backfilled in T1.

### Budget policy

Budget values are integers or decimal strings, never binary floating-point values.
The policy records:

- currency and price-snapshot identity/time;
- approved total input tokens, output tokens, and cost in minor currency units;
- per-role pricing assumptions;
- per-stage and per-product worst-case reserves;
- a provider-side project/key spend-cap attestation no greater than the approved cap;
- a detached budget approval envelope over `plan_payload_hash`, the approved caps,
  and the canonical full-contract digest.

One durable run-level budget account is keyed by a domain-separated digest of
`run_identity + purpose`, independent of an approval revision. Changing the run
identity changes the plan hash and requires a new account/approval. Increasing a cap
for the same run creates a monotonically numbered budget approval envelope that binds
the preceding approval digest and new plan payload hash; applying it atomically raises
the existing account ceiling but preserves every settled, reserved, released, and
uncertain entry. A new ceiling cannot be below already consumed/reserved/uncertain
debits. The ledger uses `(budget_account_identity, stage, product_id)` as the unique
product reservation identity and a stable request-attempt identity beneath it; all
processes, admission revisions, and resumes for the run debit that same account.

Reservation and remaining-balance deduction occur in one transaction protected by a
SQLite `BEGIN IMMEDIATE` lock for the local controlled runner (the same protocol can
later be backed by PostgreSQL). Product reservations transition only through
`reserved -> settled` or `reserved -> released`; recovery reuses an existing matching
reservation instead of deducting twice. Each logical request has a unique
`(budget_account, stage, product, request_unit, attempt_no)` row and an owner token.
The request unit is a domain-separated SHA-256 over the signed role, the complete
model-role identity, and the exact UTF-8 system/user prompts. Enumerable calls must
match an exact signed request reserve. Dynamic retry, gap-fill, and judge prompts may
instead claim from a signed per-product/per-role pool that fixes the model-role
identity, canonical RoleRate digest, maximum attempt count, and per-attempt
input/output/cost bounds. Exact reserves plus every pool's worst case must fit the
product, account, and provider caps. Unvisited dynamic branches create no attempt;
every created attempt must still reconcile to terminal, uncertain, or durable
provider no-usage evidence.
The sender must win an insert/CAS claim in the same locked transaction before it may
perform network I/O; observers/losers never send. Lease expiry alone cannot transfer
send ownership because provider receipt may be ambiguous. Release and attempt claim
use the same lock, so a reservation cannot be released while another process can
create/own an attempt.

A request attempt is durably recorded before network I/O with its request
max-token/cost bound. On recovery, **every attempt without
a durable terminal response is `uncertain`**, including the inherently ambiguous
crash boundary between local preparation and provider receipt. It is charged at its
full reserve and is never automatically replayed. A reservation can be released only
when no request attempt was ever created, or when provider idempotency/usage
reconciliation supplies durable proof that no capacity was consumed. Actual usage
settles the reservation; an observed overage blocks all later products and is bounded
by the separately attested provider spend cap.

Pool-aware schema upgrades are part of the durable recovery contract. They run in one
transaction, backfill legacy exact attempts through their signed request limits,
verify row counts and identities before replacement, and preserve every column that
exists in the legacy table. Any mismatch fails closed and leaves that table intact.

For a successful call, the owner writes the exact UTF-8 response to a mode-0600
checkpoint artifact with file and parent-directory `fsync`, then records its SHA-256
and terminal ledger state. A later observer may reuse only a terminal artifact whose
bytes match that ledger digest. Missing, malformed, oversized, symlinked, or
digest-mismatched response artifacts pause the run and never cause another send.

Before a product starts, the runtime must reserve its worst-case token and cost
allowance. If the remaining approved balance cannot cover the next product, it stops
before that product and preserves the ledger/checkpoint. Expanding a cap requires a
new plan payload hash and chained signed budget approval, atomically applied to the
same run-level account. Existing exact reserves and dynamic pools are immutable;
changing a pool's model-role identity, RoleRate digest, attempt count, or per-attempt
bound requires a new run/account rather than an in-place ceiling revision. Admission
cannot become `READY`
until the runtime capability/version implementing this ledger has passed deterministic
recovery and two-process contention tests.

### Connectivity and credential checks

Safe default execution is static and performs no network access. Static mode always
reports connectivity as unverified and can never produce `READY`.

Probe mode uses a code-owned provider allowlist. A plan selects a policy but cannot
invent its own probe target. Every remote policy requires HTTPS with normal TLS
certificate verification and fixes `(protocol, origin, method, normalized_path)` plus
model revision/deployment extraction rules. The initial production policy uses the
documented Bailian dedicated-deployment detail contract:
`GET https://dashscope.aliyuncs.com/api/v1/deployments/{deployed_model}` and only
retains `output.deployed_model`, `base_model`, `gmt_modified`, and `status`. The
OpenAI-compatible inference base URL remains
`https://dashscope.aliyuncs.com/compatible-mode/v1`; no undocumented `/models`
response is treated as identity evidence. A public alias such as
`deepseek-v4-flash` without a dedicated `deployed_model` or other provider-verifiable
immutable identity remains `BLOCKED`. The HTTP client always uses
`trust_env=False`, no ambient HTTP(S)/SOCKS proxy, and `follow_redirects=False`.
Loopback HTTP is allowed only by a distinct test-only policy that accepts no production
credential and whose route is the exact code-owned `/metadata/{deployed_model}` path.
Probe mode:

1. resolves only provider-policy allowlisted credential environment variables;
2. allows only `GET` or `HEAD`, an empty body, and no query, userinfo, or fragment;
3. normalizes/percent-decodes the URL before exact policy comparison;
4. disables automatic redirects and blocks every 3xx before following it; origin,
   method, and path must remain exactly policy-defined;
5. sends an authenticated request only to the documented deployment-detail endpoint;
6. never calls chat completions, responses, embeddings, rerank, OCR, or another
   inference route;
7. compares the canonical returned revision/deployment with the signed expected value;
8. records only role, endpoint origin, status class, latency, and redacted failure
   reason.

The clock, whole-probe monotonic deadline, and maximum probe/price ages are code-owned,
not plan-controlled. The request forces identity encoding and rejects any compressed
response before body iteration, then streams the identity body through a hard byte
limit; malformed/duplicate-key, recursively pathological, or oversized responses fail
closed. Every provider field must match its code-owned deployment-ID, model-ID,
timestamp, or status grammar. Blocked results never retain response-derived identity;
successful audit fields are copied only from the signed plan after exact comparison.
Test-only loopback policy requires an internal test capability and is rejected by the
production constructor.

Missing credentials, unsupported probe configuration, URL-embedded secret, encoded
path mismatch, redirect, authentication failure, timeout, or unreachable endpoint all
block admission. Secret values and response bodies are never persisted. Probe and
provider price observations have explicit maximum ages; expiry blocks runtime until a
fresh probe and, when pricing changed, a new approval.

## Evaluation and artifacts

The CLI has a deterministic core and thin Git/environment/HTTP adapters:

```text
python -m insurance_harness.goldenset.admission check \
  --plan openspec/changes/020-golden-v01-baseline-run/run-admission.yaml \
  --result-json <run-dir>/admission-result.json \
  --report-md openspec/changes/020-golden-v01-baseline-run/run-admission.md \
  [--probe]
```

The canonical result contains the plan payload hash, evaluated repository revision,
execution-surface digest, all recomputed fingerprints, verified approval identities,
individual checks, blockers, budget summary, checker/capability versions, observation
expiry, and derived final state. Exit status is `0` only for `READY`, `2` for a
well-formed but blocked plan, and `1` for invalid input or an internal/checker error.
Static mode and the present pre-021 state must exit `2`.

`run-admission.md` is a rendering of that result, not a second hand-maintained source
of truth. JSON is the atomic commit marker; Markdown embeds its canonical SHA-256 and
is explicitly non-authoritative without the matching JSON. Both files and their
parent-directory entries are fsynced. Rendering is redacted and stable apart from
explicit observation time and probe latency. The evaluator reads a new decision time
after identity/probe work and re-applies every check expiry at that time, including
the budget envelope, price, and provider-attestation minimum expiry.

## Runtime consumption

Future T2/T4 entrypoints must not accept a bare `--force` and must never trust an
editable `state` or blockers field from a stored result. Immediately before each
product they run the same evaluator again: recompute the plan payload hash, approval
signatures/expiry, provider observation expiry, dependency ancestry, execution-surface
and relevant input digests, derive `READY`, and reserve that product's allowance.
Changing the stored result cannot grant admission. A changed model, source, schema,
prompt, template, Golden set, budget, approval, or dependency revision makes the old
result stale and blocks the call.

The first post-admission model operation is one missing-product canary. The process
stops after that product for quote/dispute, actual-cost, and checkpoint review. Without
a valid canary-review envelope, fresh authorization contains only
`("annotation", "平安爱满分（2026）两全保险")`; baseline authorization is empty.

The canary's pre-run input snapshot is immutable. Cache, manifest, Golden output, and
the unsigned review candidate go only to a code-fixed protected content-addressed run
root that is excluded from that execution's consumed-input and execution-surface
digests. Producing those outputs therefore does not change the execution plan hash.
They become inputs only when promoted to a later immutable release and newly approved
admission revision.

A canary-review envelope uses its own domain-separated Ed25519 signature. In addition
to the reviewed evidence, its payload signs `review_decision`, an ordered unique set
of exact `(stage, product)` grants, execution plan hash/revision, runtime capability
version, run/purpose, canary stage/product, budget account/revision/approval digest,
and the canonical settlement snapshot. The evaluator may return only a subset of the
signed targets. The first review's least-privilege grant is solely the second missing
product's annotation; thirteen-product baseline remains empty until the immutable
Golden release is a newly approved admission input and receives its own explicit
stage authorization.

Because the review is created after the evaluated Git revision, it is not inserted
into the tracked admission plan. Production loads it only from a code-fixed,
repository-external, deployment-owned approval inbox. Every path component and the
file are opened without following symlinks, are root-owned and not group/world
writable, and are size/unique-key bounded. The CLI cannot select this inbox. Loading
the detached envelope changes neither Git revision nor plan/execution hash. A
canary-review object inserted into the tracked plan, candidate, observation, or result
is never an authority and is rejected when the typed schema does not permit it.

The settlement snapshot preimage is deterministically ordered and covers the account,
budget approval, reservation state/maximum, and every attempt's unit, number, role,
limit kind, state, maximum, actual usage/cost, usage provenance, response digest, and
no-usage proof. Every canary attempt must be terminal with verified provider usage;
prepared, sent, uncertain, or conservative-usage attempts cannot unlock continuation.
The payload also signs checkpoint/manifest, Golden, quote verification, disputed-rate
numerator/denominator, and quality-threshold version. Cost is recomputed from the
signed RoleRate and must agree with ledger and envelope.

The canonical envelope digest is the capability identity. The ledger rechecks current
time, account revision, settlement snapshot, and content-addressed evidence, then
atomically claims `(account, envelope, target)` and reserves the target. Same-target
recovery is idempotent; another target or anything outside the signed grant is denied.
Any duplicate, rejected, invalid, expired, drifted, or old-budget envelope empties the
global authorization instead of falling back to initial-canary mode. Syntax/schema
errors are invalid input; a parsed but semantically invalid review is `BLOCKED`.

`CanaryReviewCandidate` is only a canonical display of the payload to be signed. It
is not an approval-union member, carries no authorization state, and is never read by
the evaluator. Writing or editing a candidate, result, or observation cannot grant a
target.

The production invoker returns typed content and provider usage. Missing or malformed
usage may still settle conservatively at the full reserve, but cannot satisfy canary
review and emits `canary_actual_usage_unverified`. Every production command holds one
exclusive, code-owned run-session lock across recovery, begin, model/artifact work,
and settlement. A competing process fails before recovery, so it cannot mark a live
sender's prepared/sent attempt uncertain. The guarded runtime checks the freshly
derived `(stage, product)` authorization immediately before the atomic product
reservation; an editable result or unsigned review candidate never expands scope.

## Test strategy

Tests cite the OpenSpec clause in their names. Deterministic unit tests cover:

- all three exact model roles and rejection of aliases/placeholders;
- dependency ancestry and every deterministic fingerprint;
- thirteen-product input completeness and repository-relative paths;
- product-specific historical provenance and rejection of a global default;
- missing credentials, failed probes, inference-route rejection, and report
  redaction;
- exact probe method/origin/normalized path, encoded-path and redirect rejection;
- HTTPS/TLS enforcement, `trust_env=False`, ambient proxy isolation, and signed
  expected model-revision comparison;
- detached approval identity/role/signature/expiry, versioned canonical signed bytes,
  cross-domain/scope/run replay, and tampered state/blocker refusal;
- total/per-product/request reserve arithmetic, two-process contention, every crash
  boundary, attempt owner-CAS with exactly one outbound request, uncertain-attempt
  handling, release/claim race exclusion, release proof, cross-run budget replay,
  settlement, partial-consumption cap expansion without debit reset, and new-revision
  requirement;
- exact thirteen-product manifest, every consumed file digest, dirty/untracked input,
  execution-surface digest, canonical result hashing, exit status, and stale-result
  revalidation.
- typed provider usage and signed-rate cost calculation; absent/invalid usage settles
  conservatively but cannot unlock continuation;
- signed canary-review domain/scope/run/plan/role/expiry and exact binding to
  settlement, checkpoint, Golden, quote, disputed-rate, and actual usage evidence;
- initial one-product authorization, atomic continuation prerequisite checks, and a
  competing run-session process being rejected before recovery.

HTTP and Git behavior use injected fakes in unit tests. A live metadata probe is an
explicit external gate and never part of deterministic CI.

## Delivery sequence

1. Harden D1 in OpenSpec and obtain an independent specification review.
2. Write failing admission tests, then the smallest typed evaluator and CLI.
3. Implement and attest the durable runtime reservation/revalidation capability.
4. Generate the honest pre-merge `BLOCKED` report with zero model calls.
5. After a human commits/merges 021, rebase on the new `main`, pin the merge revision,
   obtain exact signed provenance/model/budget approval, and run non-inference probes.
6. Only after freshly deriving `NS-RIGHTS=recorded`, `NS-0=verified`, and canonical admission `READY`—and confirming the approved execution surface—start one missing-product canary under T2.

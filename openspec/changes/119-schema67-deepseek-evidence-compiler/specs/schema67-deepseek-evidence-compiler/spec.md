# Schema67 DeepSeek Evidence Compiler Specification

## ADDED Requirements

### Requirement: SDEC1 exact approved Schema67 snapshot

The compiler SHALL accept only product `596-1`, review package
`596-2-golden-human-review`, schema `medical-schema67.v1`, workbook SHA-256
`808473db9c4d0093bc4ddbe9e11dae6ef6f6c6927aefc6ce6fe65d1a9f56bb29`,
and the exact ordered 67 field IDs whose newline-terminated ordered-list
SHA-256 is
`8ffe2a043dfae6e65d84f213d42818de3c6c1c39c1fcb0c9eccd14367a30db24`.
It SHALL bind the exact normalized workbook range `01_完整Schema!A5:H71` —
ordinal, category, field name, field ID, description, raw value shape, raw
source authority and raw formation mode — whose canonical schema-row SHA-256
is `cb49f9e27356316a72c258b2b9030257bf434d47a988f61dc820b826c222a57c`.
It SHALL recompute schema-row, ordered-ID and snapshot identities and compare
the schema-row identity with that approved constant. The approver SHALL be exact
`linyao`, the approval authority reference SHALL be exact
`user-message:019fda9b-schema67-approved-no-changes`, and both SHALL participate
in the snapshot and contract-set preimages.
Missing, duplicate, extra, reordered or mutated rows and identity drift SHALL
fail closed.

#### Scenario: a caller substitutes one field

- **WHEN** one row is removed, duplicated, reordered or replaced while a caller
  keeps the old declared digest
- **THEN** snapshot validation fails and produces no field contracts

#### Scenario: a caller rehashes modified workbook content

- **WHEN** a caller preserves the workbook SHA string and ordered IDs but
  changes any description, raw value shape, raw source authority or raw
  formation mode and recomputes every caller-controlled digest
- **THEN** snapshot validation still fails against the approved schema-row hash

#### Scenario: a caller substitutes the approval authority

- **WHEN** a caller changes any suffix of the approval authority reference and
  recomputes the snapshot digest
- **THEN** snapshot validation fails before a field contract set is produced

### Requirement: SDEC2 production field contracts and adjudication separation

Every approved row SHALL compile to one immutable `FieldContractV1` binding its
field identity, category, description, value-shape class, ordered formation
modes, allowed source roles, Evidence requirement, generic evidence-gated
tri-state policy and hardness. `FieldContractV1` and `FieldContractSetV1` SHALL
NOT expose candidate status, candidate value/Evidence hashes, replay receipts,
allowed-state oracle or candidate-result/snapshot identity.

Candidate/result custody SHALL NOT be present in `ApprovedSchemaSnapshotV1`.
It remains a separate Lane C post-output adjudication input. Lane C SHALL map
`current_material_not_involved` to `unknown`; `source_explicit_absence` SHALL
require exact replayable Evidence for the same field and state. These outcome
rules SHALL NOT become per-field production answer hints.

#### Scenario: material silence is reported as absence

- **WHEN** production contracts are serialized before model execution
- **THEN** no candidate state, answer, Evidence or per-field allowed-state hint
  is present

#### Scenario: candidate custody is injected into a schema row

- **WHEN** a caller adds candidate status, value, Evidence or replay fields to
  a schema row
- **THEN** strict DTO validation fails and no field contract is compiled

### Requirement: SDEC3 deterministic hardness

Hardness SHALL be derived only from the canonical formation modes, value-shape
class, source cardinality, cross-source need, Evidence requirement, rule
derivation and external-authority need. It SHALL expose the vector plus a closed
`H0_EXACT | H1_BOUNDED | H2_SEMANTIC | H3_EXTERNAL_AUTHORITY` band. Model
identity, confidence, prompt, candidate answer and Golden value SHALL NOT enter
the preimage.

#### Scenario: the same contract is replayed

- **WHEN** the same canonical field contract is compiled twice
- **THEN** its hardness vector and digest are byte-stable

### Requirement: SDEC4 exact MaterialProfile and TemplatePackage selection

When an approved schema is present, selection SHALL derive exact disjoint
single-role subsets for `terms`, `brochure` and `rate_table`. Each selection
SHALL require exactly one approved material profile and TemplatePackage whose
fields equal only that role's subset. A profile claiming all 67 fields or fields
from another role SHALL fail closed.

Fields with multiple approved material roles SHALL be exposed only as explicit
synthesis fields and SHALL NOT be duplicated into individual material tasks.
Fields whose roles are external or otherwise unavailable in the current three
materials SHALL be exposed as deferred unknown fields and SHALL create no
material/provider task. The selector SHALL bind all subset identities into its
result hash.

For the approved current-material routing, the exact partition SHALL be 35
terms-only, four brochure-only, one rate-only, four terms+brochure, two
terms+rate and 21 deferred unknown fields. The six multi-source fields SHALL be
`product_summary`, `product_overview`, `coverage_responsibilities`,
`coverage_summary`, `social_insurance_requirement` and `underwriting_method`.

#### Scenario: schema binding drifts

- **WHEN** an otherwise approved profile names a different schema-contract hash
- **THEN** selection is `BLOCKED` and TemplatePackage resolution is not called

#### Scenario: a terms profile claims all fields

- **WHEN** one terms profile self-consistently lists all 67 Schema fields
- **THEN** selection is `BLOCKED` before TemplatePackage resolution

### Requirement: SDEC5 no-schema-only GenericFactEnvelope fallback

`GENERIC_FACT_FALLBACK` SHALL be reachable only when the caller explicitly has
no approved schema snapshot. The envelope SHALL use a `generic/` fact key,
carry no formal field ID, bind verified free-form Evidence receipts, and set
`release_eligible=false`. A malformed, revoked or mismatched schema SHALL never
fall back.

For fallback state, `unknown` SHALL carry no value or Evidence; `present` SHALL
carry a value and at least one Evidence receipt; `absent_explicitly` SHALL carry
no value and at least one Evidence receipt whose state is exact
`absent_explicitly`.

#### Scenario: an invalid schema tries fallback

- **WHEN** a schema object is present but fails identity validation
- **THEN** selection is typed `BLOCKED`, not `GENERIC_FACT_FALLBACK`

### Requirement: SDEC6 offline and authority boundary

Lane A SHALL parse no XLSX, copy no candidate/Golden value, call no provider or
model, and write no Golden, database, WeKnora or Release state. It SHALL not
modify the existing 596-1 contracts, MaterialProfile implementation or
TemplatePackage core. Public results SHALL contain only immutable DTOs, typed
reason codes and canonical identities.

#### Scenario: validation runs

- **WHEN** focused and bounded tests execute
- **THEN** provider, DB, WeKnora and Golden-write counts remain zero

### Requirement: SDEC7 bounded exact DeepSeek execution

Lane B SHALL use only provider `deepseek`, protocol `openai_compatible`, base URL
`https://api.deepseek.com/v1` and model `deepseek-v4-flash`, with temperature
zero, max output 8192, timeout 180 seconds, request-level
`thinking={"type":"disabled"}`, no `enable_thinking` field, plus
`response_format={"type":"json_object"}`. The response format SHALL be
code-owned and caller-invariant. The execution identity and each request digest
SHALL bind that exact policy.
Provider `aliyun`, every DashScope endpoint and model
`deepseek-v4-flash-0731` SHALL be rejected before credential access or provider
transport. There SHALL be no provider, endpoint or model fallback.

Before credential access, the non-secret authority SHALL join the exact tenant
ID, Space ID and one unique active `KnowledgeQA` model-row identity. That row
SHALL bind its stable row ID, row source `remote`, runtime provider `deepseek`,
name `deepseek-v4-flash` and base URL `https://api.deepseek.com/v1`. The
execution identity SHALL independently bind provider `deepseek`. Missing,
duplicate, cross-tenant, cross-Space or drifted authority SHALL fail closed with
credential and provider call counts both zero.

The exact execution SHALL contain
eight main tasks covering the 46 executable fields and SHALL append the exact 21
deferred fields as `unknown` without provider calls. Across the batch it MAY use
at most two extra calls selected from one identical empty/invalid-content retry,
one response-contract repair and one Evidence repair. Each kind SHALL occur at
most once; any pair MAY compose, while requiring all three SHALL fail before the
next transport call. It SHALL use no fallback model. FieldContract plus exact
MinerU locators SHALL own
the deterministic per-field/per-source selection, and DeepSeek SHALL act only as
Extractor. Locator provider calls SHALL be exact zero. The execution receipt
SHALL bind distinct deterministic selection-policy, locator-authority and final
selection hashes. Normal execution SHALL make eight provider calls and the
two-extra-call pool SHALL cap the entire batch at ten. Each
exact serialized OpenAI-compatible HTTP JSON envelope SHALL be at most 128 KiB
before any corresponding transport call and SHALL declare the exact Extractor
response contract. Field rows and Evidence MAY arrive only under that contract;
duplicate/missing/extra fields, foreign locator references, extra keys or
identity drift SHALL fail closed.
The initial request, its identical retry and any response-contract regeneration
SHALL use the same OpenAI-compatible serializer and exact response-format field.
`finish_reason=length` SHALL raise the existing truncated-output failure for
both empty and nonempty content; partial content SHALL NOT be parsed as a
complete response. Generic OpenAI-compatible callers that do not opt into a
response format SHALL retain their prior exact request bytes.
The model request SHALL expose one task-global, globally unique opaque locator
slot catalog and one field-to-source-role-to-allowed-slots map. Catalog content
SHALL appear exactly once. Raw locator refs SHALL appear only in the code-owned
complete `(field, source role, slot) -> locator ref` map and SHALL NOT appear in
the model-visible request or response. Slot policy, ordering, collision rules
and the complete map SHALL bind execution identity, request and receipt custody;
validation SHALL independently sort the unique original contract
`source_locator_refs` lexicographically, assign `slot-0001...` in that exact
order, reconstruct the catalog, field/source-role rows and complete code-only
map, and require all three to equal the supplied authority before transport.
A self-consistent reordering with a recomputed authority hash SHALL fail closed.
Any drift SHALL fail before transport. The model response SHALL contain only
`fields`, and each field SHALL contain only `field_id`, `state`,
`value_snapshot` and Evidence triples of
`source_role`/`locator_slot`/`quote_snapshot`. Product, source, revision, parse-attempt,
document, manifest, page, parent and content-hash custody SHALL be derived from
the exact field-specific prompt authority and canonical ParsedDocument facts.
The request-visible response contract SHALL declare all validator invariants:
exact field count and order; required keys with no additional properties;
`present | absent_explicitly | unknown`; `unknown` with explicit null value and
empty Evidence; known states with a nonblank value and at least one unique
Evidence triple; exact field/source-role slot membership; nonblank quotes that replay as
substrings under exact 057 NFKC, whitespace, punctuation and case
normalization, never semantic paraphrases; exact length 1 through 512,
single-line, no-CR/LF and no-leading-or-trailing-whitespace constraints for
`field_id`, `value_snapshot`, `source_role`, `locator_slot` and
`quote_snapshot`; and all
forced-unknown field IDs. It SHALL include an ordered shape-only skeleton and
SHALL NOT relax any parser, hydration or 057 check.
A slot outside the exact field/source-role membership SHALL fail before 057
verification or receipt binding. Code SHALL map an accepted slot to the original
locator and run the unchanged hydration and 057 replay; final Evidence and
Candidate custody SHALL contain the original locator and no slot. A known
multi-source field SHALL provide Evidence for every required source role; code
SHALL NOT auto-fill a missing role. The selection-policy hash SHALL bind the exact
algorithm version, tokenization/stoplist/scoring/tie-break/input/output ordering;
the authority hash SHALL bind locator order and ordinal; provider task and
attempt hashes SHALL bind that policy plus the complete field prompt authority.
The policy hash SHALL also bind exact `str.casefold` normalization and the
whole-CJK-sequence minimum/maximum lengths used by the selector. The sole public
production-transport entrypoint SHALL be `compile_schema67_deepseek_task`; a
single-task entrypoint accepting caller-selected contracts, locators or a fresh
budget SHALL NOT exist or be exported.

A parseable Extractor response that fails only a fixed model-correctable
response-contract category MAY consume the batch's one response-contract-repair slot for
one complete regeneration. An initial Extractor response that remains empty or
invalid JSON after the exact identical retry MAY consume that same slot. Its
repair category SHALL be exactly `MODEL_CONTENT_EMPTY` or `MODEL_JSON_INVALID`,
and its failed-response digest SHALL bind the second response from the identical
request pair. Eligible parseable categories SHALL be limited to top-level or
field shape, exact field count/set/order, forced-unknown state, visible string
constraints and a model-selected slot outside that field/source-role set.
For a locator-membership failure, code SHALL derive only the contract-ordered
unique failed field IDs. The repair payload SHALL contain those IDs and SHALL
contain no locator reference, quote or raw response. A code-owned repair-policy
hash, the failed IDs, repair resolution, request and receipt SHALL bind the same
unchanged slot and locator authority. Missing, duplicate, out-of-contract,
reordered or caller-forged failed IDs SHALL fail before transport or receipt
admission. If the regenerated response still selects an invalid slot, the
task SHALL stop after exactly two calls and SHALL NOT issue a third call.
Code-owned source, parser-locator, content-hash, table/cell or output-custody
failure SHALL NOT be repaired and SHALL fail before another transport call.
The regeneration SHALL reuse the exact task, model, field contracts, field-local
locator authority, selected locator snapshots, response contract and request
size gate. It MAY add only a fixed repair kind/number/reason plus parent-request
and failed-response hashes; it SHALL NOT include the raw failed response. The
accepted response SHALL pass the same parser, hydration and 057 gates. A second
parseable response-contract failure SHALL stop without another contract
regeneration. An empty or invalid-JSON regeneration response MAY consume the
batch's single identical-content retry only when the initial Extractor has not
already consumed it; otherwise it SHALL stop after the regeneration call. No
decode or parseable failure SHALL permit a second contract regeneration.
An Evidence repair MAY follow a successful response-contract repair when the
unchanged 057 verification remains insufficient. It SHALL use one private full
plan/resolution trace and expose only a receipt-safe summary binding exact field
IDs, plan/parent/request/response/resolution hashes and the opaque private trace
hash. The plan SHALL cover every non-PASS result in exactly one matching initial
verification batch; its resolution SHALL preserve prior PASS results, cover the
full batch in order and finish with all PASS and no Gap/ReviewItem. Non-plan
outputs and receipts SHALL remain byte-identical, and repaired Evidence locator
refs SHALL remain inside the trusted prepared-task authority. Receipts SHALL bind
the repair kind, fixed reason, failed-response hash, repair request and accepted
response hash while preserving the total `8 + at most 2 extras = 10` batch
ceiling. When the fixed reason is `MODEL_CONTENT_EMPTY` or
`MODEL_JSON_INVALID`, the task receipt SHALL require the exact history
`extractor_calls=2`, `repair_calls=1`, `transport_retries=1`,
`response_contract_repairs=1`, `evidence_repairs=0`, `total_calls=3`; a
self-consistent generic budget tuple
with a shorter history SHALL be rejected even when its receipt hash is
recomputed.

#### Scenario: a request exceeds the bound

- **WHEN** the canonical request body exceeds 128 KiB
- **THEN** execution fails with `MODEL_REQUEST_TOO_LARGE` before that transport
  call

#### Scenario: official DeepSeek thinking policy drifts

- **WHEN** the exact request omits `thinking`, changes its type, enables it or
  contains any `enable_thinking` field
- **THEN** execution identity validation fails before provider transport

#### Scenario: a foreign provider identity is supplied

- **WHEN** provider is `aliyun`, the endpoint is DashScope, the model is
  `deepseek-v4-flash-0731`, or the exact tenant/Space/model-row authority is
  missing, ambiguous or drifted
- **THEN** execution fails before credential access and provider transport,
  with no fallback to the foreign identity

#### Scenario: JSON response transport policy drifts

- **WHEN** the exact 119 request omits `response_format`, changes its type or
  uses a stage-specific serializer
- **THEN** execution identity or request-custody validation fails before the
  drifted request is accepted

#### Scenario: a length response contains partial content

- **WHEN** the provider returns nonempty content with `finish_reason=length`
- **THEN** the client raises `TruncatedOutputError` and the partial content is
  never accepted as complete JSON

#### Scenario: a caller tries to restore an LLM Locator stage

- **WHEN** execution prepares the exact eight tasks
- **THEN** the receipt records zero Locator calls, the transport receives only
  Extractor or targeted-repair requests, and the batch provider-call ceiling is
  ten

#### Scenario: the exact batch exhausts the transport ceiling

- **WHEN** eight prepared tasks consume any legal pair of shared extras
- **THEN** the orchestration records exactly ten provider calls, and an eleventh
  call is rejected before transport

#### Scenario: a parseable response violates the visible contract

- **WHEN** the first Extractor response has a model-correctable fixed contract
  failure, the response-contract repair slot is unused and the shared extra-call
  budget has capacity
- **THEN** one contract-identical regeneration may run, raw response content is
  not persisted or reprompted, and any second parseable contract failure stops
  fail-closed; an empty or invalid-JSON regeneration response may consume only
  the batch's one distinct identical-content retry

#### Scenario: an initial response remains undecodable after its identical retry

- **WHEN** the same initial Extractor request returns empty content or invalid
  JSON twice, the response-contract repair slot is unused and the shared
  extra-call budget has capacity
- **THEN** one response-contract regeneration may run with the fixed decode
  category, parent request hash and second-response hash but without raw response
  content; any empty, invalid-JSON or parseable contract-invalid regeneration
  stops after that call without a fourth provider call

#### Scenario: code-owned custody is inconsistent

- **WHEN** response hydration finds source, locator fact, content hash or cell
  custody inconsistent with Admission
- **THEN** execution stops before a contract-repair transport call

### Requirement: SDEC8 native MinerU locator custody

For admitted MinerU artifacts, a plaintext block snapshot SHALL be usable only
when it reproduces the parser-owned
`sha256("mineru-060:block-content\\0" + plaintext)` hash for the exact block.
Recovery MAY enumerate deterministic projections of the captured whole-document
snapshot, but only a cryptographic hash match SHALL establish the preimage. The
public execution boundary SHALL derive role inputs and field-local locator sets
from admitted artifacts, captured snapshots and FieldContract text; callers
SHALL NOT supply preselected role inputs or locator sets. Each captured snapshot
SHALL match the admitted source SHA, capture identity, content snapshot hash and
raw/sanitized structure hashes before locator recovery. Production preparation
SHALL consume the relation-bound Admission result, freshly replay the 061
receipt and recompute the relation-bound integration digest before using its
internal admitted artifacts.
Multiline or over-512-character candidates SHALL remain unavailable to the
current locator DTO. Field-local narrowing SHALL depend only on FieldContract
text and recovered source blocks, include bounded neighboring blocks, and SHALL
never read Golden values or infer a locator using semantic similarity or a
model.
Rate-table fields SHALL receive no block-only locator authority. Until exact
table/cell locator preimages are recovered, each such field SHALL be marked
`requires_unknown_review`; both model `present` and `absent_explicitly` claims
SHALL fail before hydration or 057.

#### Scenario: Markdown resembles a block but does not hash exactly

- **WHEN** a candidate string is lexically similar but does not reproduce the
  native block hash
- **THEN** it is not exposed as a canonical locator

#### Scenario: a caller crops the capture to one authentic block

- **WHEN** a caller supplies one authentic block and its self-computed plaintext
  hash, alters matching caller-side admitted metadata, but retains the original
  Admission receipt
- **THEN** execution fails before task preparation or transport

### Requirement: SDEC9 expert and Evidence admission separation

After Lane B freezes one exact ordered-67 candidate, Lane C SHALL bind the
linyao receipt to the approved workbook/schema/candidate authority and SHALL
replay every `present` or `absent_explicitly` Evidence item through 057. Known
fields without replayable Evidence SHALL not be Wiki-admissible. Evidence-only
success MAY authorize a later offline semantic comparison, but SHALL expose no
publishable fields and SHALL keep Wiki admission false until the separate
semantic evaluation passes. It SHALL NOT itself claim that candidate text is
semantically equal to the expert reference. Golden/reference content SHALL not
be read before candidate output freeze.

#### Scenario: all fake outputs are unknown

- **WHEN** a no-provider integration emits exact ordered-67 `unknown` outputs
- **THEN** the chain may prove control-flow and semantic-eval readiness with zero
  publishable fields, but it does not prove extraction quality

### Requirement: SDEC10 sealed expert reference and deterministic comparison

Total-control SHALL derive one ordered-67 hash-only reference snapshot from the
exact approved workbook and bind it to the exact linyao approval receipt. The
snapshot SHALL contain exact states, explicitly allowed rendering hashes,
required component hashes, required source SHA-256 values, reference Evidence
branch hashes and explicit-absence quote hashes. Runtime SHALL NOT read the
workbook, accept caller-authored reference rows, or accept a duck/self-hashed
comparator authority. The sole comparator SHALL return deterministic exact-state
and approved-rendering outcomes through the existing Lane C public comparison
contract. It SHALL use no fuzzy similarity, model judge or Golden prompt input.
Unknown SHALL remain `PENDING`; Wiki admission and publishable fields SHALL stay
false/empty unless all 67 correctness and completeness axes pass, including 057
Evidence source coverage for every known or explicit-absence field.
The receipt SHALL be the single code-owned pre-approved identity, including its
exact issue time, expiry time, provenance and receipt hash; a caller-selected
time window SHALL NOT mint approval. Before comparison, the comparator authority
reference bundle, expert subject and expert receipt hashes SHALL exactly equal
the Lane C base result. A mismatch SHALL fail with
`SEMANTIC_COMPARATOR_AUTHORITY_INVALID` before any field comparison, without
equating the approved reference candidate hash to a future model CandidateV2.

#### Scenario: caller reissues the same approval subject

- **WHEN** a caller changes only the receipt issue/expiry window and recomputes
  its hash while retaining the same workbook, linyao and provenance subject
- **THEN** reference construction rejects it as a foreign receipt identity

#### Scenario: comparator and base use different receipts

- **WHEN** a comparator authority is bound to receipt A but the Lane C base
  result presents receipt B, even if both share the same expert subject
- **THEN** semantic evaluation fails before the first comparison and Wiki
  admission remains false with no publishable fields

#### Scenario: a caller rewrites one approved reference fact and rehashes it

- **WHEN** any allowed rendering, component, source, Evidence branch, absence
  quote, field order or comparator authority is changed and locally rehashed
- **THEN** the code-owned authority replay rejects it before semantic evaluation

#### Scenario: a candidate abstains

- **WHEN** any candidate field is `unknown`, including a fixed
  current-material-not-involved field
- **THEN** its semantic axes are `PENDING`, a ReviewItem remains, Wiki admission
  is false and publishable fields are empty

### Requirement: SDEC11 T15k minimal first-request contract and demotion

T15k SHALL be an additive, task-local amendment over integrated tree authority
`6d160c276efd77f1e067430325e7159724fd58fa`; v2-v9 and T15j SHALL remain
unchanged historical evidence.

The v9 external/internal ledger and its two provider calls SHALL remain
immutable governance-budget history. Its frozen authority records provider
label `aliyun` with the same official endpoint, `deepseek-v4-flash` model and
request-envelope policy. The corrected provider declaration creates a new
code-owned execution identity, so
the successor MAY bind v9 only as `prior_provider_calls=2`; it SHALL NOT treat
the v9 responses or receipts as new response semantics, model-receipt or
Candidate ancestry. Current calls SHALL remain exact eight and cumulative calls
SHALL remain exact ten.

The first Extractor request SHALL explicitly expose the complete fixed 057
contract. For `present`, the existing 057 normalization of `value_snapshot`
SHALL equal the normalized form of at least one complete `quote_snapshot`.
Every known field SHALL supply Evidence covering every required source role,
and every Evidence member SHALL select only an existing slot authorized for
that exact field. Each quote SHALL replay through the unchanged 057 locator
check. Forced-unknown fields SHALL remain exact unknown/null/empty Evidence.
The request SHALL include the task-global slot catalog only once and SHALL NOT
copy it into field rows or contain any Golden/reference state, value or hint.

Demotion SHALL run only after every expected code-owned `VerificationBatchV1`
has been constructed completely and returned normally. Code SHALL take every
field having any non-`PASS` result across those complete batches, then order the
deduplicated IDs by the prepared field order. A multi-source field with one or
more non-`PASS` source branches SHALL be demoted as one whole field. Exactly
those fields SHALL become `state=unknown`, `value_snapshot=null` and
`evidence=[]`. Every PASS field output byte and its existing
`FreeformEvidenceBindingReceiptV1` byte SHALL remain unchanged and in the same
order.

A structural, parser, request-envelope, visible-string, locator, hydration,
source-custody or verifier execution failure SHALL terminate the run and SHALL
NOT authorize demotion. T15k SHALL make no transport retry, response-contract
repair or Evidence repair.

Successful demotion SHALL create exactly one private
`EvidenceDemotionReceiptV1`. It SHALL contain exactly these nine fields and no
budget or call-count field:

- `policy_sha256`;
- `parent_bound_attempt_sha256`;
- ordered `verification_batch_hashes`;
- exact ordered `demoted_field_ids`;
- `initial_output_sha256`;
- `final_output_sha256`;
- ordered `final_evidence_receipt_hashes`;
- `pass_preservation_sha256`; and
- self-authenticating `receipt_hash`.

The trusted Candidate loader SHALL reconstruct the non-PASS union directly from
the initial code-owned batches, reorder it by the prepared field order, replay
the initial-to-final transformation and recompute every receipt hash. It SHALL
reject an omitted, expanded, duplicated or reordered demotion scope even when
the caller recomputes `receipt_hash`; it SHALL also reject any mutation of a
PASS output or preserved `FreeformEvidenceBindingReceiptV1`.

For every demoted field, Lane C and the candidate report SHALL emit exact
`PENDING` plus one `ReviewItem` with reason
`EVIDENCE_NONPASS_DEMOTED`. The semantic comparator SHALL NOT process an unknown
field. Any unknown field SHALL keep Wiki admission false and publishable fields
and count empty/zero.

The private `EvidenceDemotionReceiptV1` and every demotion-specific public or
private report projection SHALL contain no pre-demotion value, quote, locator
or locator ref, slot, request or response content, or filesystem path. Only the
typed receipt fields and hashes above may carry demotion custody.

The existing `Schema67BatchExecutionReceiptV1` and `Schema67BudgetReportV1`
SHALL each add fixed facts `prior_provider_calls=2` and
`cumulative_provider_calls=10`. Their existing current fields SHALL be exact
`task_count=8`, `provider_calls=8`, `extractor_calls=8`, `locator_calls=0`,
`transport_retries=0`, `response_contract_repairs=0`, `evidence_repairs=0` and
`repair_calls=0`. `EvidenceDemotionReceiptV1` SHALL carry none of these budget
facts. This is batch-receipt/report custody only; T15k SHALL create no durable
call-budget allocation, pretransport intent log or restart/recovery facility.
It SHALL add no child OpenSpec, general-purpose platform, Golden feedback path
or Release action.

#### Scenario: the first request hides a 057 rule

- **WHEN** the first Extractor request omits normalized present-value equality,
  required-role coverage, field-local slot membership, quote replay or a
  forced-unknown constraint, duplicates the catalog, or includes a
  Golden/reference hint
- **THEN** request authority validation fails before transport

#### Scenario: one branch of a multi-source field is non-PASS

- **WHEN** all code-owned batches complete and any source branch for one field
  is `FAIL` or `GAP`
- **THEN** that whole field appears once in prepared field order and becomes
  exact unknown/null/empty Evidence while every PASS output and
  `FreeformEvidenceBindingReceiptV1` remains byte-identical

#### Scenario: verification infrastructure fails

- **WHEN** structure, parsing, envelope, string, locator, hydration, source
  custody or verifier execution fails
- **THEN** execution terminates without demotion, retry or repair

#### Scenario: a caller rehashes a false demotion scope

- **WHEN** a caller omits, adds, duplicates or reorders a demoted field, mutates
  a PASS output or receipt, and recomputes `EvidenceDemotionReceiptV1.receipt_hash`
- **THEN** the trusted loader rejects it after recomputing scope and
  PASS-preservation custody from the initial batches

#### Scenario: a demoted field reaches Lane C

- **WHEN** a validated `EvidenceDemotionReceiptV1` binds one demoted unknown
- **THEN** that field is `PENDING` with reason `EVIDENCE_NONPASS_DEMOTED`, the
  comparator skips it, Wiki admission is false and publishable count is zero

#### Scenario: exact call facts drift

- **WHEN** `Schema67BatchExecutionReceiptV1` or `Schema67BudgetReportV1` differs
  from prior `2`, current exact task/provider/extractor `8`/`8`/`8`, zero
  locator/retry/repair calls or cumulative `10`, or the demotion receipt carries
  a budget field
- **THEN** loading fails closed before Lane C evaluation

# 119 · Schema67 DeepSeek Evidence Compiler MVP

## Goal

Create the schema-first vertical compiler for the product `596-1` MVP. The
compiler consumes an already-approved, immutable Schema67 snapshot from the
separate review package `596-2-golden-human-review`, compiles
exact field contracts and deterministic hardness, and selects an approved
MaterialProfile plus the existing TemplatePackage resolver. Only a genuinely
absent approved schema may enter a non-publishable GenericFactEnvelope fallback.

The source authority is the user-approved workbook
`596-2-golden-human-review-人工确认.xlsx` with SHA-256
`808473db9c4d0093bc4ddbe9e11dae6ef6f6c6927aefc6ce6fe65d1a9f56bb29`.
Its Schema67 and later adjudication package are expert-approved without value
changes by approver `linyao`. Lane A consumes only the non-sensitive Schema
definition; candidate/result values remain outside the production compiler and
belong to Lane C after output freeze. The legacy eighteen-field authority is
excluded from this Mission.

## Design

1. `ApprovedSchemaSnapshotV1` is the Lane A schema authority boundary. It
   carries the workbook's exact normalized `01_完整Schema!A5:H71` rows with
   canonical SHA-256
   `cb49f9e27356316a72c258b2b9030257bf434d47a988f61dc820b826c222a57c`,
   including category, name, ID, description, raw value shape, raw source
   authority and raw formation mode. It also binds the ordered 67 field IDs
   with SHA-256
   `8ffe2a043dfae6e65d84f213d42818de3c6c1c39c1fcb0c9eccd14367a30db24`,
   the distinct product/review-package identities, an expert-approval
   provenance reference
   `user-message:019fda9b-schema67-approved-no-changes` and exact approver
   `linyao`. Runtime Lane A validates
   the repo-frozen normalized rows; it neither parses XLSX nor accepts a
   caller-rehashed substitute.
2. `compile_schema_contracts` produces production-safe immutable
   `FieldContractSetV1` and a
   deterministic `HardnessVectorV1` per field. Hardness is a closed vector of
   formation, shape, source cardinality, Evidence and authority needs; no model
   confidence or candidate answer participates. Candidate status, value,
   Evidence, allowed-state oracle and adjudication hash are absent even from
   the Lane A snapshot DTO.
3. `select_schema_compilation` selects exactly one approved role-specific
   material profile, then calls the existing `resolve_template` once for that
   exact subset. The workbook review routing freezes 35 terms-only, four
   brochure-only, one rate-only, four terms+brochure and two terms+rate fields;
   21 current-material-not-involved fields are deferred unknown. Single-source
   tasks are disjoint and the six multi-source fields are emitted only as
   explicit synthesis fields.
4. `GenericFactEnvelopeV1` is allowed only when no approved schema exists. It
   reuses verified free-form Evidence receipts, carries no formal schema field
   identity, and is never release-eligible. An invalid, revoked or mismatched
   schema is a block, not a fallback.
5. In adjudication and output validation, `当前材料未涉及` is `unknown`.
   `absent_explicitly` is legal only when the output records explicit source
   absence or non-applicability and binds
   an exact 057 `FieldCandidateV1` snapshot plus `VerificationBatchV1` replay
   identity. A bare Evidence digest cannot authorize absence. These rules are
   not encoded as a per-field Golden answer oracle in production contracts.

6. Lane B binds the exact official DeepSeek execution identity: provider
   `deepseek`, protocol `openai_compatible`, base URL
   `https://api.deepseek.com/v1` and model `deepseek-v4-flash`. It executes
   eight bounded Extractor tasks over the 46 fields covered by the current three
   materials. FieldContract plus exact MinerU locators deterministically owns
   selection; no Locator provider call exists. Each receipt records zero Locator
   calls and binds the exact selection policy, authority and selected-map hashes.
   Normal execution is eight provider calls. One batch-wide pool permits at
   most two extra calls: no more than one identical empty/invalid response
   retry, one response-contract correction and one Evidence repair, with each
   kind usable at most once and any two kinds composable. All three kinds in one
   batch fail before a further transport call, so the hard cap remains ten.
   Every request uses that official endpoint, with request-level
   `thinking={"type":"disabled"}`, no `enable_thinking` field and exact
   `response_format={"type":"json_object"}`.
   Provider `aliyun`, every DashScope endpoint and model
   `deepseek-v4-flash-0731` are foreign identities and fail before credential
   access or provider transport; no provider, endpoint or model fallback is
   permitted. Before credential access, the non-secret authority also binds
   the exact tenant ID, Space ID and one unique active `KnowledgeQA` model row:
   stable row ID, row source `remote`, runtime provider `deepseek`, name
   `deepseek-v4-flash` and the exact official base URL. The execution identity
   independently remains provider `deepseek`. Missing, duplicate or drifted
   authority remains zero-credential and zero-provider.
   The response format is code-owned, participates in the execution identity
   and is reused unchanged by the initial request, identical retry and
   response-contract repair. The model response is semantic-only: field ID, state,
   value snapshot and selected locator-ref/quote pairs. Product, source,
   revision, parse-attempt, document, manifest, page, parent and content-hash
   custody are hydrated from the field-specific code-owned authority before
   any 057 call; extra model-authored custody keys fail closed. Every request
   declares an executable Extractor response contract isomorphic to the strict
   validator: exact keys/order, the three-state enum, explicit
   `unknown -> null + []`, nonblank known values plus field-local normalized
   replayable (never paraphrased)
   Evidence, forced-unknown fields and no extra properties. The same contract
   exposes the existing full string boundary for `field_id`, `value_snapshot`,
   `locator_ref` and `quote_snapshot`: length 1 through 512, one line, no CR/LF
   and no leading or trailing whitespace. Parser limits are therefore not
   hidden from the model. The contract carries an ordered shape-only skeleton so these
   invariants are not hidden from the model. Every request is strict JSON and has its
   exact serialized OpenAI-compatible HTTP JSON envelope
   capped at 128 KiB before transport. Execution identity and request receipts
   hash that same envelope rather than only the user prompt. A provider
   `finish_reason=length` is truncated output even when partial content is
   nonempty and therefore never reaches JSON validation as a complete result.
   `compile_schema67_deepseek_task` is the only public entrypoint allowed to
   construct production transport; no caller-selected contracts, locators or
   fresh per-call budget can bypass relation admission or the exact batch.
   The locator-policy hash binds the actual `str.casefold` normalization and
   whole-CJK-sequence length bounds in addition to tokenization and ordering.
   The model-visible locator authority is one task-global opaque slot catalog
   plus a field-to-source-role-to-allowed-slots map. Slot IDs are task-global
   unique; catalog content appears once; raw locator refs remain in a complete
   code-only mapping and never enter the model request or response. The slot
   ordering/collision policy, complete map and dynamic authority hash bind the
   execution identity, request and receipt. Validation independently recomputes
   the declared `locator_ref_lexicographic` order from the original field/source
   refs, assigns canonical `slot-0001...`, and requires the catalog, field rows
   and code-only map to equal that reconstruction before transport. Code maps an exact
   `(field, source role, slot)` back to the original locator before unchanged
   057 replay; final Evidence and Candidate custody retain the original locator,
   not the slot.
   A parseable response that violates only the visible response contract may
   consume the batch's single response-contract-repair slot for one contract-identical
   regeneration. When the violation is field-local locator membership, code
   derives the contract-ordered unique `failed_field_ids`; the repair sees only
   those field IDs plus fixed hashes, never a locator, quote or raw response.
   The repair policy, failed IDs, resolution and receipt are identity-bound,
   while the complete slot and locator authority remains unchanged. An initial Extractor
   response that remains empty or invalid
   JSON after its exact identical retry may consume that same slot using only
   the fixed decode category and the second response digest. The repair
   transmits no raw failed response, changes no field, locator, model or custody
   authority, and records only fixed failure codes and cryptographic hashes.
   Code-owned source, locator-fact and cell custody failures remain immediately
   fail-closed. An invalid field/role/slot on the regenerated response stops
   after the exact second call; no repeated response-contract repair is
   available. A response-contract repair and an Evidence repair MAY both occur
   in the same task or batch; each retains its own typed trace and they share
   the two-extra-call ceiling. Any invalid regeneration stops without another
   contract regeneration; an empty or invalid-JSON regeneration may consume
   the shared identical retry only when it remains unused. The ten-call ceiling
   is unchanged. A receipt carrying either decode category is valid only with
   the exact history `extractor=2, repair=1, retry=1,
   response_contract_repairs=1, evidence_repairs=0, total=3`; generic budget
   arithmetic cannot forge a shorter decode-repair history.
7. Real MinerU input recovers plaintext only when its exact native
   domain-separated block hash is reproduced from the captured whole-document
   snapshot. Field-local narrowing uses only the FieldContract text and exact
   recovered blocks; it never uses Golden values, candidate answers, similarity
   inference or LLM-authored locator facts.
   The public execution boundary derives material-role inputs and locator sets
   from admitted artifacts, captured source snapshots and FieldContract text;
   callers cannot inject preselected role inputs or locator sets. The captured
   whole-document snapshot is also bound to the admitted capture identity,
   content hash and raw/sanitized structure hashes, so a caller-selected subset
   cannot masquerade as the original capture. The production entrypoint consumes
   the relation-bound Admission result, freshly replays its 061 receipt and
   recomputes its integration digest; it does not accept naked admitted sources.
   Until table/cell preimages are available, the `rate_table` role exposes no
   block locator authority and therefore forces its fields to unknown/review.
8. Lane C binds the one code-owned, pre-approved linyao receipt identity; callers
   cannot choose its issue/expiry window or mint another receipt with the same
   subject. It validates the exact 67
   output membership, replays every known/explicit-absence Evidence locator
   through 057 and separates Evidence admission from later offline semantic
   comparison. Evidence-only success permits semantic evaluation but never
   grants Wiki admission or publishable fields. Deferred fields remain exact
   `unknown`.
9. Total-control loads the approved 596-2 workbook into one code-owned,
   hash-only ordered-67 reference authority bound to that exact linyao receipt.
   Before any field comparison, the comparator authority must exactly join the
   base reference bundle, subject and receipt identities.
   The deterministic comparator accepts only this sealed authority: exact state
   and explicitly approved rendering hashes determine semantic outcome, while
   057-verified source coverage determines completeness. Caller-authored
   reference rows, self-hashed comparator DTOs, fuzzy similarity and model
   judging are rejected. Any unknown is pending; any non-PASS axis keeps the
   batch non-publishable and Wiki admission false.

## Lane interfaces

- Lane B consumes the production-safe `FieldContractSetV1`; Lane C consumes the
  separately verified candidate/adjudication package only after model outputs
  are frozen. Neither lane may reintroduce candidate values into
  `ApprovedSchemaSnapshotV1`.
- Lane A owns no workbook parser, candidate value or provider call. Lane B owns
  no Golden read. Lane C runs only after candidate output freeze and owns no
  Release or serving authority.
- The existing TemplatePackage models/catalog port/resolver are consumed as-is;
  the 596-1-specific `material_profiles.py` and exact-eight contracts remain
  unchanged.

## Non-goals

No child OpenSpec, generic schema platform, rule engine, model routing, XLSX
mutation, Golden write, DB/migration, WeKnora or Release action. No
legacy-eighteen compatibility path and no GPT comparison.

## Path budget

One integrated 119 scope: registry, this OpenSpec, schema selection/contracts,
the task-local DeepSeek compiler, the expert/Evidence gate, their focused tests,
and the already-approved production-model identity boundary.

## T15k minimal B/C rescue amendment

T15k is an additive, task-local amendment over integrated tree authority
`6d160c276efd77f1e067430325e7159724fd58fa`. It preserves the v2-v9 and T15j
history above and changes only the first-request Evidence contract plus
post-verification demotion custody.

1. The first Extractor request exposes the complete fixed 057 contract. A
   `present` value must equal at least one Evidence quote after the existing 057
   normalization; every known field covers all required source roles, uses only
   existing field-local slots and carries replayable quotes. Forced-unknown
   fields remain unchanged. The request neither duplicates the slot catalog nor
   contains Golden/reference content.
2. After all code-owned `VerificationBatchV1` objects complete normally, code
   computes the union of every non-`PASS` result and emits it once in prepared
   field order. Any non-`PASS` source branch demotes the whole multi-source field
   to exact `unknown` / `null` / empty Evidence. PASS output bytes and
   `FreeformEvidenceBindingReceiptV1` bytes remain verbatim. Structural, parser,
   envelope, string, locator, hydration, source or verifier failures are
   terminal. Retry, response-contract repair and Evidence repair are disabled.
3. Demotion creates exactly one private `EvidenceDemotionReceiptV1` with exactly
   nine non-budget fields: `policy_sha256`, `parent_bound_attempt_sha256`,
   ordered `verification_batch_hashes`, exact ordered `demoted_field_ids`,
   `initial_output_sha256`, `final_output_sha256`, ordered
   `final_evidence_receipt_hashes`, `pass_preservation_sha256` and its own
   `receipt_hash`. The Candidate loader recomputes scope from the initial
   batches and rejects missing, expanded, reordered or self-rehashed scope and
   any PASS output or receipt mutation.
4. Lane C and the report map each demoted field to `PENDING` plus a `ReviewItem`
   with reason `EVIDENCE_NONPASS_DEMOTED`. The comparator does not process
   unknown fields; any unknown fixes Wiki admission false and publishable count
   at zero. Demotion-specific private/public custody retains no pre-demotion
   value, quote, locator/ref, slot, request/response or filesystem path.
5. The existing `Schema67BatchExecutionReceiptV1` and
   `Schema67BudgetReportV1`—never `EvidenceDemotionReceiptV1`—bind the exact
   budget facts. Both add fixed `prior_provider_calls=2` and
   `cumulative_provider_calls=10`; their existing current fields are fixed to
   task/provider/extractor `8`/`8`/`8`, locator/retry/response-contract-repair/
   Evidence-repair/repair calls all zero. T15k creates no durable call-budget
   allocation, pretransport intent log or restart/recovery facility.

The v9 ledger's two provider calls used provider label `aliyun` with the same
official endpoint, model and request-envelope policy. They remain immutable
cross-identity governance-budget history. The corrected provider declaration
creates a new code-owned execution identity, so v9 crosses into the successor
only as `prior_provider_calls=2`;
its responses and receipts are not new response semantics, model-receipt or
Candidate ancestry. The fixed current eight calls therefore produce lifetime
governance budget `2 + 8 = 10` without increasing the authorized allowance.

No child OpenSpec, general-purpose platform, Golden feedback or Release action
is added.

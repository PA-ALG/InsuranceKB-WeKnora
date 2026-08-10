# 119 Validation Report

Status: `STABLE CANDIDATE — UNCOMMITTED`

- Authority base/HEAD: `2f356368342d2d4578e18315a9fedf739ab73190`.
- Workbook SHA-256: `808473db9c4d0093bc4ddbe9e11dae6ef6f6c6927aefc6ce6fe65d1a9f56bb29`.
- Exact normalized `01_完整Schema!A5:H71` row SHA-256:
  `cb49f9e27356316a72c258b2b9030257bf434d47a988f61dc820b826c222a57c`.
- Fresh GitHub authority reported open PR count: `0`.
- Clean baseline: existing 073/052/028/schema focused set, `145 passed`.
- TDD RED: focused collection failed with `ModuleNotFoundError` for the absent
  `schema_first_contracts` module (exit 2) before production implementation.
- Initial focused GREEN: `8 passed`.
- Unified-goal authority RED: missing `APPROVED_BY` import failed collection;
  explicit absence without replay custody then failed its focused assertion.
- Independent-review corrective RED: missing review-package authority failed
  collection; exact foreign field ID, product/review identity, Golden-oracle
  leakage, all-67 material profile and role partition assertions then failed.
- A5 authority RED: four caller-rehashed row mutations preserved the workbook
  SHA string and ordered IDs; the description mutation reached compilation
  without `SCHEMA_SNAPSHOT_INVALID` (`1 failed`, expected vulnerability).
- A5 GREEN freezes all eight non-sensitive workbook Schema columns, removes
  candidate/result custody from Lane A and rejects synthetic 67-row snapshots.
- A6 authority RED showed `user-message:attacker` could replace the approval
  provenance and pass after caller-side rehash (`1 failed`). GREEN freezes
  `user-message:019fda9b-schema67-approved-no-changes` at both snapshot and
  contract-set DTO boundaries.
  Focused result: `14 passed`.
- Current-material routing was independently frozen from the approved review
  package without reading candidate values: `35` terms-only, `4`
  brochure-only, `1` rate-only, `4` terms+brochure, `2` terms+rate and `21`
  deferred unknown fields.
- Bounded 119/073/052/028/schema regression (nine exact test files):
  `547 passed`.
- Ruff on the two production modules plus the focused test: PASS.
- Strict mypy on the same three paths: PASS (`0` issues).
- `DO_NOT_TRACK=1 openspec validate
  119-schema67-deepseek-evidence-compiler --strict`: valid.
- Candidate-vs-base `git diff --check`: PASS; the current integrated A/B/C
  candidate spans 22 declared paths. Exact path and tree custody are frozen only
  after the final verification pass.
- The selector reuses the existing TemplatePackage resolver; the bounded
  regression proves the legacy 596-1/073, 052 and 028 contracts remain green.
- Integrated C/057/B/client focused verification after the independent-review
  correctives: `113 passed`; bounded 15-file A/B/C/upstream regression:
  `601 passed`. Ruff and strict mypy on the corrected production
  boundaries: PASS.
- Real-artifact no-provider replay consumed exact terms, brochure and rate
  captures: Admission `READY_FOR_QUALITY_FALSIFICATION`, eight relation
  bindings, eight Schema67 tasks, 16 fake calls, 67 ordered outputs and Lane C
  `READY_FOR_OFFLINE_GOLDEN_EVAL` with Wiki admission false and zero publishable
  fields. Production input preparation recovered and selected locators from the
  admitted artifacts and FieldContract text; no caller-provided locator set was
  accepted. A cropped authentic-block snapshot with a self-computed hash was
  rejected even when caller-side admitted custody was changed to match, because
  the retained 061 Admission receipt and recomputed relation-bound integration
  digest failed before execution preparation. The fresh real-artifact relation
  integration digest is
  `3f9ef7c77194335ed817431eb816df76f09a8326f675b6ca036bcc0039b2311e`.
  This proves control flow only; all fake outputs were `unknown` and no quality
  claim is made.
- Exact recoverable single-line block locators: terms `558`, brochure `328`,
  rate table `16`. After freezing request-level thinking disabled, the fresh
  provider-zero replay measured a maximum exact serialized HTTP JSON request
  body of `104,258` bytes, below the code-owned 128 KiB limit. The corrected
  execution identity is
  `b2b980479536ac1168bc8c2b2a6f607c900c2fcae68434e4112f4fec4d3501a7`.
- Provider/model/Golden read or write/DB/PG/WeKnora/live/full: NOT RUN /
  FORBIDDEN for this no-provider checkpoint.
- A first authorized official-API attempt reached no provider because the
  repo-external runner unpacked the frozen admission tuple in the wrong order;
  a private RED/GREEN regression corrected that custody-only defect. The first
  effective batch then terminated at approximately the 180-second request
  timeout without publishing a candidate. The official model defaults to
  thinking mode, while the previously validated direct configuration explicitly
  disabled thinking. A focused RED/GREEN corrective now puts exact
  `thinking={"type":"disabled"}` in the transmitted JSON, execution identity,
  128-KiB calculation and full-envelope request digests. A corrected provider
  execution remains NOT RUN at this checkpoint.
- That corrected execution reached the official endpoint once and returned a
  parseable Locator object, then failed closed as `LOCATOR_SELECTION_INVALID`
  before Extractor, candidate publication or Golden access. The frozen prompt
  had required only “strict JSON” but had not declared the exact response
  object expected by its validator. A second focused RED/GREEN corrective now
  embeds that exact contract and canonicalizes only harmless field/reference
  ordering while retaining strict identity, exact field set, uniqueness and
  allowed-reference checks. A further provider execution remains NOT RUN at
  this checkpoint.
- The user-approved final corrective removes that redundant model Locator stage:
  FieldContract plus exact MinerU locators now owns deterministic selection and
  DeepSeek is Extractor-only. The first focused RED supplied only one Extractor
  response and reproduced the old failure at `_parse_locator_selection` as
  `LOCATOR_SELECTION_INVALID` (`1 failed`). GREEN removes the Locator transport,
  records `locator_calls=0`, binds separate selection-policy, locator-authority
  and deterministic-selection hashes, and keeps an exact Extractor response
  contract in the sole main request. Normal exact-eight execution is eight
  provider calls; retry, response-contract repair and Evidence repair share at
  most two extras, setting the hard cap at ten.
- The subsequent B1-B4 RED set reproduced cross-field same-document Evidence
  laundering, model-authored custody, block-only rate-table known states and
  incomplete locator/provider identity plus budget orchestration. GREEN narrows
  model output to semantic-only fields, hydrates all custody from exact parser
  facts, rejects both present and explicit-absence rate claims before hydration,
  and binds policy/order/full prompt authority. The eight-task fake transport
  now mechanically reaches exactly ten calls with a legal pair of extras and
  rejects a third extra/call eleven before transport.
- Fresh successor verification: focused `31 passed`; bounded 119/057/061/069/092
  plus schema-first and expert-gate regression `266 passed`; Ruff PASS; strict
  mypy on the production module and focused test PASS (`0` issues); strict
  OpenSpec PASS. No provider, Golden read/write, DB, PG, WeKnora, live or full
  run occurred.
- Exact-tree follow-up RED reproduced two public-authority gaps: the legacy
  single-task production transport remained callable, and the selector policy
  hash did not change when casefold or whole-CJK sequence bounds changed. GREEN
  removes that entrypoint/export and binds all three actual selector rules.
  Fresh successor bounded regression remains `266 passed`; Ruff PASS; strict
  mypy PASS (`0` issues); strict OpenSpec PASS. Provider/Golden/DB/PG/WeKnora/
  live/full remain NOT RUN.
- The first authorized real batch stopped after exactly one Extractor provider
  call with `EXTRACTOR_RESPONSE_INVALID`; Locator, retry, repair and Golden
  counts were zero, cleanup was `CLOSED`, and no candidate was published. The
  terminal ledger proved nonempty JSON reached validation but retained no raw
  response. Phase-1 review found the request-visible contract listed only key
  names while the strict validator also required undisclosed tri-state,
  null/empty, Evidence, extra-key and forced-unknown invariants. The load-bearing
  RED supplied a natural parseable response containing only `field_id` plus
  `state=unknown`: the validator rejected it while the old prompt omitted the
  required explicit `value_snapshot=null` and `evidence=[]` rule. GREEN exposes
  the existing rules, exact field-to-source-locator authority and an ordered
  shape-only skeleton without relaxing parsing, hydration or 057. Fresh focused
  verification is `33 passed`; bounded 119/057/061/069/092 plus schema-first and
  expert-gate regression is `268 passed`; Ruff and strict mypy
  on the changed production/test files PASS. No corrective provider call or
  Golden/DB/PG/WeKnora action occurred at this checkpoint.
- Independent delta review then found the contract's word `verbatim` was
  stricter than 057, which replays substrings after NFKC, whitespace,
  punctuation and case normalization. A second RED captured that exact
  asymmetry plus an explicit semantic-paraphrase rejection; GREEN now states
  normalized-equivalent replay only. The three-real-artifact provider-zero
  replay remains eight tasks, 67 outputs, zero Locator calls, zero publishable
  fields and a maximum exact HTTP request body of `107186` bytes, below the
  `131072`-byte bound.
- A final bounded delta review found that the strict extractor DTO already
  accepted strings through 512 characters and rejected 513, while the visible
  response contract disclosed only `nonblank`. The RED proved the parser
  boundary and failed on the missing request metadata. GREEN binds one shared
  512 constant into parser validation, response-contract metadata and system
  wording for `field_id`, `value_snapshot`, `locator_ref` and `quote_snapshot`;
  initial and repair requests share that same builder. No hydration, locator or
  057 rule was relaxed. Fresh focused verification is `34 passed`; the existing
  bounded 119/057/061/069/092 set is `269 passed`; Ruff, strict mypy, strict
  OpenSpec and candidate-vs-base diff checks PASS. The three-real-artifact
  provider-zero public chain remains eight tasks, 67 outputs, zero Locator
  calls, zero publishable fields and a maximum exact HTTP request body of
  `115211` bytes, below `131072`.
- A second exact-contract review found the same parser regex also required
  length at least one, a single line, no CR/LF and no leading or trailing
  whitespace. The RED proved legal one-line strings through 512 pass and empty,
  leading/trailing-whitespace, embedded-CR/LF and 513-character values fail for
  every visible `NonBlankStr` response field, while the request contract omitted
  those rules. GREEN replaces the standalone maximum with one private immutable
  constraint object that drives Pydantic, all four response-contract entries and
  the shared initial/repair system wording. Parser, hydration, locator and 057
  behavior remain unchanged. Fresh targeted verification is `3 passed`; the
  existing bounded set remains `269 passed`; Ruff, strict mypy, strict OpenSpec
  and candidate-vs-base diff checks PASS. The three-real-artifact provider-zero
  public chain remains eight tasks, 67 outputs, zero Locator calls and zero
  publishable fields; its maximum exact HTTP request body is `115541` bytes,
  below `131072`.
- The next authorized one-shot reached the first Extractor once and failed
  closed with `EXTRACTOR_RESPONSE_INVALID`; provider calls were `1`, retry and
  repair were `0`, cleanup was `CLOSED`, Candidate remained absent and Golden
  reads remained `0`. The private terminal ledger retained no response content,
  so the exact historical subcategory is intentionally unrecoverable.
- T15e RED proved that a parseable shape-invalid response stopped after one call
  even though the exact batch still owned its shared repair budget
  (`3 failed`). GREEN replaces the generic code with fixed secret-free response
  categories, keeps code-owned custody failures non-repairable, and permits one
  contract-identical regeneration that transmits only fixed repair metadata and
  hashes, never the failed response. Its receipt binds repair kind, fixed reason,
  failed/accepted response hashes and the exact repair request. The successor
  budget permits at most two extras: retry plus one repair, or the two distinct
  repair kinds; any third extra fails before transport.
- Fresh focused verification after T15e: `39 passed`, including a repair-stage
  empty/invalid-JSON response consuming the one distinct identical-content retry
  without opening a second contract-regeneration slot. Fresh bounded
  119/057/061/069/092/schema-first/expert-gate regression: `274 passed`.
  Ruff and strict mypy on the changed production/test files: PASS. No corrective
  provider, Golden, DB, PG, WeKnora, live or full action occurred.
- T15f RED reproduced the authorized real-run terminal shape without reading its
  response: repeated empty/invalid JSON stopped after the identical Extractor
  retry, left the response-contract repair kind unused and caused the complete eight-task
  fake batch to stop on call two (`5 failed`). GREEN carries only the fixed
  decode category and second-response SHA into the existing response-contract
  regeneration. Blank/blank and invalid/invalid now reach the same strict
  parser, code-owned hydration and 057 path; a failed regeneration makes no
  fourth call. A private sentinel is absent from the repair request, receipt
  digest forgery is rejected, and the complete fake batch remains exactly ten
  calls. A follow-up RED rehashed a decode-repair receipt as a generic valid
  `1 extractor + 1 repair` history and reproduced acceptance (`1 failed`).
  GREEN requires the exact `2 extractor + 1 repair + 1 retry` decode history
  while leaving parseable shape-repair histories unchanged. Focused T15f
  verification: `7 passed`; full focused 119 verification: `44 passed`; bounded
  119/057/061/069/092/schema-first/expert-gate regression: `319 passed`. Ruff
  and strict mypy on the changed production/test files PASS;
  OpenSpec 119 strict is valid. Provider, Golden, DB, PG, WeKnora, live and full
  remain NOT RUN.

The candidate remains uncommitted and unpushed. Its exact tree and independent
temporary-index custody SHA are reported out of band after the final freeze so
the report does not create a self-referential tree identity.

## T15g sealed reference authority and comparator

- Workbook bytes were read only after confirming SHA-256
  `808473db9c4d0093bc4ddbe9e11dae6ef6f6c6927aefc6ce6fe65d1a9f56bb29`.
  The exact 67 review rows mechanically yield 45 `present`, one
  `absent_explicitly`, 21 `unknown` and 94 reference Evidence branches. Runtime
  embeds only their canonical hashes and the exact three approved source PDF
  SHA-256 values; it contains no workbook path, free-text answer or secret.
- RED first reproduced the absent comparator module and the old caller-selected
  reference/self-rehash authority seam. GREEN adds the code-owned reference
  loader, exact linyao receipt replay, immutable factory seal and concrete
  deterministic comparator accepted by the existing Lane C public gate. A fake
  comparator can no longer claim `EQUIVALENT`; mutated rendering, component,
  source, Evidence or absence rows remain rejected after local rehash.
- Fresh focused expert/comparator tests: `54 passed`. Fresh bounded 057 plus
  Lane C tests: `118 passed`. Ruff and strict mypy on the four changed
  source/test files: PASS. OpenSpec strict and final candidate custody are
  recorded after the final freeze. Provider, Golden write, DB, PG, WeKnora,
  live and full remain NOT RUN.

## T15j exact named receipt and comparator/base join

- RED reproduced two independently valid caller-selected issue/expiry windows
  for the same linyao subject, and reproduced a comparator bound to receipt A
  continuing against a base result carrying receipt B.
- GREEN removes caller-selected time parameters from the public receipt factory,
  pins one issue time, expiry time, provenance and receipt SHA-256, and rejects
  every alternate self-rehashed window. Semantic evaluation now compares the
  comparator authority's reference bundle, expert subject and expert receipt
  identities with the base result before the first field comparison.
- Fresh expert/comparator focused verification is `56 passed`; the report
  integration suite is `15 passed`; 057 Evidence verification is `64 passed`
  (`135` total across the three Lane C groups). Ruff and strict mypy PASS on
  the changed Python scope. Provider, Golden write, DB, PG, WeKnora, live and
  full remain NOT RUN. Final OpenSpec/diff/privacy and successor custody are
  recorded after the final freeze.
- The final mechanical integration restacked the independently approved T15j
  tree onto the sealed Lane C/comparator/report delta. Its full eight-task
  fixture carries one response-contract repair and one Evidence repair on the
  same task: the trusted Candidate v2 loader preserves both traces and the
  exact candidate hash, while the report replays `8 + 2 = 10` calls. The
  deterministic reference remains `45 present / 1 absent_explicitly / 21
  unknown` with `94` reference branches; Wiki admission is false and the
  publishable count is zero. Lane C/DeepSeek/comparator/report verification is
  `136 passed`; the additional 057/061/069/092/schema-first bounded set is
  `214 passed`. Ruff, strict mypy, strict OpenSpec and candidate-vs-base
  diff/privacy checks PASS. Provider, credential, Golden write, DB, PG,
  WeKnora, live and full remain NOT RUN.

## T15k minimal B/C rescue contract

- Baseline integrated tree authority is exact
  `6d160c276efd77f1e067430325e7159724fd58fa`; the v2-v9 and T15j records above
  remain unchanged historical evidence.
- The first Extractor request must expose the complete 057 contract: normalized
  present-value equality with at least one quote, known-field required-role
  coverage, exact field-local slots, replayable quotes and unchanged forced
  unknowns, with one catalog copy and no Golden/reference content.
- Only a complete code-owned VerificationBatch non-PASS union may demote fields.
  IDs are emitted once in prepared field order; any non-PASS multi-source branch
  demotes the whole field to unknown/null/empty Evidence. PASS output and
  `FreeformEvidenceBindingReceiptV1` bytes remain verbatim. Structural, parser,
  envelope, string, locator, hydration, source and verifier failures terminate;
  retry and both repair kinds are zero.
- Exactly one private `EvidenceDemotionReceiptV1` has exactly nine non-budget
  fields: policy hash, parent-attempt hash, ordered batch hashes, exact demoted
  IDs, separate initial and final output hashes, final Evidence receipt hashes,
  PASS-preservation hash and self hash. The trusted loader recomputes scope from
  initial batches and rejects omission, expansion, reordering, caller rehash or
  PASS mutation.
- Lane C/report maps demoted unknown to PENDING plus ReviewItem reason
  `EVIDENCE_NONPASS_DEMOTED`; the comparator skips unknown, and any unknown keeps
  Wiki admission false with zero publishable fields. Demotion custody retains no
  pre-value, quote, locator/ref, slot, request/response or filesystem path.
- Existing `Schema67BatchExecutionReceiptV1` and `Schema67BudgetReportV1` alone
  bind prior provider `2`, current exact task/provider/extractor `8`/`8`/`8`,
  zero locator/retry/response repair/Evidence repair/repair calls and cumulative
  provider `10`. Budget facts never enter `EvidenceDemotionReceiptV1`. No durable
  call-budget coordination, pretransport intent log, restart/recovery facility,
  child OpenSpec or generic platform is introduced.

### T15k required exact-10 TDD matrix

Each row MUST first be executed and observed RED, then implemented and observed
GREEN. All ten rows were NOT RUN in the specification-only Task 0; the later
minimal B+C implementation completed that RED-to-GREEN matrix as recorded below.

1. Parameterize first-request prompt validation over normalized present-value/
   quote equality, required-role coverage, exact field-local slot membership,
   quote replay, forced-unknown constraints, a single catalog copy and no
   Golden/reference content; each omitted or mutated rule fails before transport.
2. An eight-field `7 PASS + 1 non-PASS` batch demotes exactly one field.
3. Any non-PASS branch demotes the whole multi-source field.
4. Forced unknown remains unchanged and outside demotion scope.
5. Loader rejects missing, extra, duplicated, reordered, replaced or self-rehashed
   demotion scope.
6. Loader rejects mutation of a non-demoted PASS output or its preserved
   `FreeformEvidenceBindingReceiptV1`.
7. Structural, parser, envelope, visible-string, locator, hydration,
   source-custody or verifier error produces zero Candidate and no demotion.
8. A trusted-loader round trip accepts `Schema67BatchExecutionReceiptV1` only
   with `prior_provider_calls=2`, existing `task_count=8`, `provider_calls=8`,
   `extractor_calls=8`, `locator_calls=0`, `transport_retries=0`,
   `response_contract_repairs=0`, `evidence_repairs=0`, `repair_calls=0` and
   `cumulative_provider_calls=10`; parameterized one-at-a-time drift of each fact
   is rejected even after recomputing `batch_receipt_sha256`.
   `Schema67BudgetReportV1` mirrors those exact facts, while any budget-field
   injection into exact-nine `EvidenceDemotionReceiptV1` is rejected even after
   recomputing `receipt_hash`.
9. All eight real serialized request bodies are below `131072` bytes.
10. Lane C/report emits demoted PENDING + ReviewItem, skips unknown comparison,
    keeps Wiki false/publishable zero and excludes forbidden demotion content.

The matrix SHALL assert that private `EvidenceDemotionReceiptV1` has exactly
`policy_sha256`, `parent_bound_attempt_sha256`, `verification_batch_hashes`,
`demoted_field_ids`, `initial_output_sha256`, `final_output_sha256`,
`final_evidence_receipt_hashes`, `pass_preservation_sha256` and `receipt_hash`.
Its private/public projections retain no pre-demotion value, quote, locator/ref,
slot, request/response or filesystem path. Budget facts remain separate in
existing `Schema67BatchExecutionReceiptV1` and `Schema67BudgetReportV1` only.
- This Task 0 changes documentation only. Production, tests, provider,
  credential, DB, Golden write, WeKnora, live and full: NOT RUN / OUT OF SCOPE.
- Task 0 strict OpenSpec gate: PASS (exit `0`), exact output
  `Change '119-schema67-deepseek-evidence-compiler' is valid`.
- Task 0 exact four-file `git diff --check`: PASS (exit `0`, no output).
- Task 0 obsolete-expansion term check: no matches for the review's five legacy
  coordination phrases (expected `rg` exit `1`, no output).

### T15k final provider-zero implementation evidence

- The minimal B+C implementation, exact-10 RED-to-GREEN matrix and independent
  final Spec review are complete. Final Spec review: GO, zero blockers. This is
  an implementation/test/review closeout only, not a real vertical-loop claim.
- Fresh focused suites: DeepSeek `69 passed`, Expert `77 passed` and Report `35
  passed`. Fresh root bounded regression: `279 passed`.
- Ruff lint: PASS. Strict mypy: PASS. Strict OpenSpec: PASS. Final diff-check:
  PASS.
- The format-check for
  `deepseek_locator_extractor_596_1.py` and
  `test_deepseek_locator_extractor_119.py` reports historical whole-file
  formatting differences. It is explicitly not recorded as PASS, and no
  formatting-only rewrite was made.
- Provider, WeKnora, DB, credential, Excel and Golden actions: `0`. No real
  Candidate was published, no evaluator was executed and no real Wiki action was
  performed.

### Official DeepSeek identity specification correction

- The user-selected successor authority is provider `deepseek`, protocol
  `openai_compatible`, official endpoint `https://api.deepseek.com/v1`, exact
  model `deepseek-v4-flash`, request-level
  `thinking={"type":"disabled"}`, no `enable_thinking` field and
  `response_format={"type":"json_object"}`.
- This four-document correction does not claim that production, tests or an
  execution package already implement the corrected provider declaration.
  Their RED-to-GREEN evidence and frozen successor identity must be recorded
  separately before authorization. Provider, credential, DB, WeKnora, Golden,
  Candidate, evaluator and Wiki actions remain `0` / NOT RUN here.
- The immutable v9 external/internal ledger records two calls against the same
  official endpoint, model and request-envelope policy. Those calls remain
  `prior_provider_calls=2` governance-budget history only; their responses and
  receipts are not new response semantics, model-receipt or Candidate ancestry.
  The successor remains fixed at current exact eight, cumulative exact ten and
  zero retry or repair calls.
- Provider-zero specification correction is not evidence of improved model
  quality, eight successful responses, Candidate publication or Wiki readiness.

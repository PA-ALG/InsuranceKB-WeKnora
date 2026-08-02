# 069 validation report

Status: `CORRECTIVE GREEN / EXTERNAL DELTA REVIEW PENDING`

## Identity and scope

- authoritative final replay base:
  `4cfdfd208c5bf94248eaaca8bca7b399871f0558`
- the mechanical replay added merged 066 plus MinerU/061 evidence updates; it
  has zero overlap with the strict six 069 paths.
- merged 068 dependency: PR #97 / main tree
  `14e9197d45c59d783cd0401018bad40dc6ee0782`
- branch: `codex/069-596-1-semantic-input-binding`
- allowed paths: four OpenSpec files, one task-local module, one focused test
- provider/Golden/live/PG/WeKnora/full: `NOT RUN`

## Current evidence

- Exact merged 068 v2 bytes bind source/parser/config/raw/sanitized/content
  hashes and attempt `2/bounded_upgrade/generation=0`; composition additionally
  consumes the public 061 replay/admission receipt digest.
- 069 keeps the ten-task preimage model-neutral while exact arm/model/prompt/
  budget/normalizer/output identities bind each arm response and receipt.
- Corrective RED: focused collection failed because
  `SemanticRepairBundleV1` did not exist; behavior REDs then covered the prior
  arm-exchangeable response, foreign-attempt Evidence, unknown cross-product,
  block-only rate Evidence, split/duplicate/cross-arm repair batches and
  caller-self-issued parse admission.
- The obsolete candidate `3748f7e755db694798e8f2975b92a9b2ad6297c7`
  was rejected because bound attempts and the repair bundle did not close the
  canonical arm/receipt/normalizer and exact 057 verification custody. New REDs
  reproduced arm mutation, missing receipt, split/duplicate/cross-arm bundles,
  nonexistent locators, a canonically rehashed foreign model ID, and a
  self-consistent 057 failure whose reason differed from the exact 054 outcome.
- Response binding now calls merged 057 `verify_evidence_batch`, binds the
  resulting verification into the immutable attempt hash and derives the exact
  054 PASS/unknown outcomes from that result. The repair boundary accepts no
  caller verification: it replays merged 057 `bind_054_attempt_receipt` and
  `plan_targeted_repair` from the bound attempt set. Each 064 receipt is also
  replayed against the admitted document/manifest, converted back to its exact
  field output and used to regenerate the full 057 verification before 054 is
  bound. A mixed PASS+GAP fixture proves both candidate-snapshot and
  unresolved-reason custody in one active partition; a canonically rehashed
  contradictory unknown receipt is rejected.
- Corrective focused GREEN after the final-main replay: `18 passed in 11.91s`;
  the exact repair-bundle counterexamples are `1 passed in 9.96s` after their
  RED failed as expected.
- Predecessor bounded 052/053/054/057/060/061/069 evidence was
  `262 passed in 21.45s`; it was not repeated after the final narrow
  response-to-verification bridge because the frozen final gate is the focused
  069 set plus static/OpenSpec checks.
- Ruff exact source/test: `PASS`.
- Strict mypy exact source/test: `Success: no issues found in 2 source files`.
- OpenSpec 069 strict: `valid`; its telemetry flush emitted a non-gating offline
  DNS warning after validation completed. `git diff --check`: `PASS`.
- Real provider execution remains gated outside 069 by exact 060 admission;
  no handwritten or self-issued parse admission is created in production.
  Successful composition fixtures use a narrow simulated future 061 authority;
  a separate focused negative restores the actual public 061 function and
  proves empty sanitized structure plus nonempty ParsedDocument locators are
  rejected. Those simulated successes are not evidence that current 060 can
  ADMIT the real terms/rate pair.
- Frozen Golden18 handoff (not consumed by this Golden-blind composer): file
  SHA `466110f885882ac5eac3484dbb8d7fc438c3768a6e65f6cd500fcae07c294b05`,
  canonical SHA `23816ccdfa9258bb4785ed0d1032c8281c1eda047c7801543b2032649b567dc2`,
  upstream Critical18 SHA
  `12b648d509c53b7ce1659abbf95811d437c3d22f729d46a58545f47e09bee344`;
  P0/P1 `7/11`, unique `18`, Schema60 inclusion `PASS`.
- Provider call, Golden read, runtime write, commit, push and PR remain zero.

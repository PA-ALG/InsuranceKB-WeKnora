# 596-1 Vertical Falsification Specification

## ADDED Requirements

### Requirement: VF1 required contracts gate all execution

061 quality execution SHALL consume, without local redefinition, the approved exact
060 MinerU native structure bridge public contract. The 060 seam SHALL be the real module
`insurance_harness.compiler.native_mineru_cloud`, its
`build_mineru_parsed_document_v1` builder, `NativeMinerUStructureError`, and the
merged 053 `ParsedDocumentV1`, `ParseManifestV1`, and
`ParseQualityDecisionV1` types exposed by that module. Before this exact public contract
and its required symbols exist, admission SHALL return typed
`BLOCKED_ON_REQUIRED_CONTRACTS` with a canonical list of missing contracts.

Admission SHALL also require exactly three typed immutable intake receipts in exact
terms, brochure and rate-table role order. Each receipt SHALL bind the approved exact
596-1 source SHA256 and material profile, recomputed `ParsedDocumentV1.document_hash`,
`ParseManifestV1.manifest_hash`, `ParseQualityDecisionV1.decision_hash`, and the exact
document -> manifest -> decision subject/parser/attempt/snapshot chain. It SHALL carry
the sanitized 060 structure bytes, exact raw/sanitized hashes and exact approved 052
`MaterialProfileResolution`. Admission SHALL invoke the real
`build_mineru_parsed_document_v1` with those bytes and identity facts, and require the
replayed document, manifest and decision to equal the claimed receipt. The 060 decision
MUST be terminal `ADMIT`, bind the admitted attempt, contain no reason code, and agree
with a fully satisfied manifest. A manually constructed or self-consistent ADMIT object
does not prove 060 execution. Missing, duplicate, extra, malformed, cross-role,
cross-source, hash-drifted or non-ADMIT receipts SHALL remain
`BLOCKED_ON_REQUIRED_CONTRACTS`; three arbitrary SHA strings never claim ADMIT.

The 060 module and builder SHALL be resolved lazily inside admission. A missing or
broken import SHALL NOT prevent the 061 module itself from importing. Every nested
052/053/060 DTO SHALL be revalidated before dereference and replay; malformed bypass
objects SHALL produce the same typed block without exposing raw exception detail,
traceback or private path. Required 060 exports SHALL be read exactly once inside the
same no-detail boundary and captured immutably; downstream admission SHALL NOT perform
a second module attribute lookup.

Dependency admission SHALL execute before any Provider/model call and before any
049 Golden read. A blocked admission SHALL report `provider_calls = 0` and
`golden_reads = 0`; it SHALL NOT create a Candidate, Release, score or terminal
GO/NO-GO result. Import failure or incomplete public symbols SHALL fail closed.

The merged 059 named-human activation authority is the Go service contract
`HumanBatchDecisionReceiptV1`, `ActivateReviewed` / `Revert`, immutable Head receipt and
opaque pinned reads. 061 SHALL NOT require, create or probe a duplicate Python 059 module,
and a fake Python module or caller-supplied release reference SHALL NOT affect quality
admission or scoring.

#### Scenario: merged 060 exists but parse artifacts are absent

- **WHEN** 061 runs on authoritative main containing exact 060 without the three
  admitted parse artifacts
- **THEN** it returns `BLOCKED_ON_REQUIRED_CONTRACTS`, lists the three admitted
  parse-artifact contract,
  performs zero Provider calls and reads zero Golden bytes

#### Scenario: three arbitrary artifact hashes are supplied

- **WHEN** a caller supplies three distinct 64-hex values without exact typed 060
  document/manifest/ADMIT decision custody
- **THEN** admission remains `BLOCKED_ON_REQUIRED_CONTRACTS` with zero Provider and
  Golden access

#### Scenario: a caller constructs a self-consistent ADMIT decision

- **WHEN** a caller supplies matching document/manifest/decision hashes but no replayable
  sanitized structure and approved 052 resolution, or replay produces a different result
- **THEN** admission remains `BLOCKED_ON_REQUIRED_CONTRACTS`; the caller's ADMIT value is
  not accepted as 060 authority

#### Scenario: an exact 060 public symbol drifts

- **WHEN** the 060 public module imports but any required builder/error/053 DTO
  symbol is missing
- **THEN** admission also lists the 060 contract, fails closed and performs no
  partial evaluation

#### Scenario: a fake Python 059 module is injected

- **WHEN** a caller injects a local `candidate_releases` Python module or release object
- **THEN** quality readiness and scorer outcome are unchanged and no final GO is minted

### Requirement: VF2 one exact product, three exact sources and Schema60

The eventual falsification run SHALL bind ProductVersion `596-1`, the exact
terms, brochure and rate-table PDF byte identities, their exact SourceRevision
identities, the approved Schema60 identity and the 060 canonical structure
artifact identities. Missing, duplicated, cross-product or changed identity
SHALL produce typed NO-GO before extraction.

Final MVP GO SHALL consume the merged Go 059 named-human activation custody. A fixture
Candidate, an unapproved human batch, a caller-declared approval, a locally reconstructed
Release or an opaque caller-supplied reference SHALL NOT satisfy this requirement.

#### Scenario: PR1 Candidate is supplied without named-human Release

- **WHEN** the three sources and Schema are exact but only 059 PR1 artifacts exist
- **THEN** the pure scorer MAY produce only
  `QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE` or typed NO-GO; it cannot produce final GO

### Requirement: VF3 the experiment has a frozen 10-task and 18-call budget

The run SHALL execute exactly ten admitted tasks: eight narrow weak-model tasks
and two deterministic rate-table tasks. The baseline arm MAY make at most six
Provider calls. The candidate arm MAY make eight initial calls and at most four
targeted-repair calls. The whole run SHALL enforce a hard cap of eighteen
Provider calls.

The current deterministic ledger SHALL be pure and SHALL emit typed NO-GO for
any per-arm/repair/total overrun, fallback call or extra retry. It SHALL NOT issue
the calls it counts. Every counter SHALL be a non-negative runtime integer; booleans,
floats, NaN and other numeric lookalikes SHALL fail closed.

There SHALL be no fallback model/parser, strong-model judge, hidden retry,
additional task, prompt tuning after observing Golden, or dynamic experiment
router. Deterministic rate tasks SHALL not consume Provider budget.

#### Scenario: an arm asks for one additional retry

- **WHEN** the next call would exceed its arm budget or the run hard cap
- **THEN** the run stops with a typed budget NO-GO and does not issue the call

### Requirement: VF4 output custody precedes Golden evaluation

Each arm SHALL finish and content-address its complete raw output before the
runner may open or otherwise read 049 Golden. The score receipt SHALL bind the
frozen output hash, exact Golden artifact hash, exact Schema60 hash and exact
evaluation implementation identity. Golden values SHALL NOT enter prompts,
normalization rules, repair selection or parser choice.

The frozen arm envelope SHALL bind ProductVersion, exactly three source SHA256
identities, Schema, parser, model, prompt, budget, normalizer and comparator identities
plus all field outputs. It SHALL bind approved arm-profile SHA256
`c64ce6227b714fb9a47fe2c15cd51349df4fccc8770fb95442aed86061f39fe3` and the
closed roles baseline=`pdfplumber/default` attempt 1 and
candidate=`mineru-cloud-pipeline/bounded_upgrade` attempt 2. Both semantic arms SHALL
use exact `DeepSeek V4 Flash` at `https://api.deepseek.com/v1` with equal product,
source, Schema, model, prompt, budget, normalizer and comparator identities; only the
approved parser role/artifact may differ. The parser artifact identities SHALL differ.
Swapped/reused parser roles, an alternate/self-attested profile, Qwen semantic
arm/judge/fallback or shared-identity drift SHALL be typed NO-GO.

The scorer SHALL compare both arms and Golden against the approved exact
ProductVersion `596-1`, ordered terms/brochure/rate-table source SHA tuple, Schema
version `v1.1+b31a411c621c`, registry SHA256
`5d222c68f228d57c9061fc329f85a26191f6c847f7122f221e6aff92147b9db5`, arm-profile
SHA256 and canonical DeepSeek semantic-model identity. Cross-arm agreement alone SHALL
NOT authorize a caller-selected product, source set, Schema or model identity.
The arm-profile label SHALL be recomputed from the approved parser, model, prompt,
budget, normalizer and comparator facts; two arms that agree on jointly mutated
component identities SHALL NOT retain approved profile authority.

The public scorer SHALL accept the exact approved 049 `596.jsonl` bytes, not a
caller-constructed Golden DTO. It SHALL validate file SHA256
`562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`, strict UTF-8
JSONL shape, exact ordered Schema60 identities, tri-state/value and Evidence custody.
The parsed Golden SHALL bind exact 049 release SHA256
`fca06f988bf0310d12a0f6f8d0703a9476c54a5405676fb1a9b3476f91ec21d0`, artifact SHA256
`83032da028ef227071fddac0ed422cbb9d1c2cc31e195972f9878a67d95b44ca`, approval subject
SHA256 `6feb2acf4be1ab5ce075b662bc9c9a40024038ca2324b893d3f31b1384f7674b`, exact ordered
source tuple and exact Schema60. The score receipt SHALL bind both arm output hashes,
the Golden file SHA/content digest, those Golden identities, the replayed three-artifact
admission digest, evaluator identity, budget, metrics and reasons; recomputation SHALL
be byte-mutation sensitive. It SHALL NOT duplicate Go 059 activation or CAS.

The public deterministic scorer SHALL first internally replay exact admission for all
three `AdmittedParseArtifactV1` receipts and recompute one immutable custody digest.
Non-READY admission or arm/output binding drift SHALL stop before inspecting Golden
bytes. Only after both envelopes and their hashes bind that digest may the scorer parse
the exact Golden bytes. A caller-supplied status token, Golden DTO or self-attested
receipt SHALL NOT open scoring.

#### Scenario: evaluator attempts early Golden access

- **WHEN** either arm has not yet frozen its complete output hash
- **THEN** Golden access fails closed and the run produces typed NO-GO

#### Scenario: both arms agree on a foreign authority

- **WHEN** both arms use the same caller-selected product,
  source tuple, Schema or semantic-model identity
- **THEN** scoring returns typed authority NO-GO even though cross-arm equality holds

### Requirement: VF5 quality gates are field- and Evidence-aware

The pure scorer's only successful quality value SHALL be
`QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE`. It requires all sixty Schema fields to be
accounted for and all of the following gates:

- critical18 silent error equals zero;
- critical known Evidence coverage equals 100 percent;
- overall known Evidence coverage is at least 95 percent;
- every rate fact binds exact page, table and cell plus row, column, header and
  span facts from the 060 canonical structure;
- every field state preserves `present | absent_explicitly | unknown` semantics;
- no caller input can claim or fabricate named-human Release authority.

The Golden denominator and both arms SHALL equal the approved exact ordered Schema60
field-ID tuple, not merely any 60 unique IDs. Its critical set
SHALL equal the approved ordered P0-seven plus P1-eleven tuple and bind
`critical18-candidate.v1` SHA256
`12b648d509c53b7ce1659abbf95811d437c3d22f729d46a58545f47e09bee344`; an arbitrary
set of 18 booleans, reordered tuple or substituted field identity SHALL be typed
NO-GO. Missing, duplicate, reordered or foreign IDs SHALL be typed NO-GO. The approved
rate-field subset SHALL derive from exact IDs `zh_7fe8603c08` and `zh_c588207763`;
a caller-supplied rate flag SHALL exactly match that derivation and cannot remove
locator requirements. `unknown` SHALL remain an abstention and
SHALL NOT count as Evidence coverage for a Golden-known field.

Each arm SHALL deterministically report exact tri-state correctness, normalized value
correctness over Golden-known/present fields, abstentions, misses, hallucinations
(Golden unknown but arm known), wrong values, total exact-field correctness and
Evidence coverage as integer counts and basis-point rates. Baseline metrics are
diagnostic only. Candidate GO additionally SHALL require critical18 exact semantic
errors = 0, hallucinations = 0, tri-state correctness at least 57/60 and normalized
value correctness at least 95 percent by integer cross-multiplication. These rules do
not introduce another aggregate value threshold.

Evidence table/cell/header strings SHALL be non-blank, row/column indexes non-negative
and spans positive. Rate completeness SHALL enforce those semantic constraints rather
than treating any non-`None` placeholder as complete.

Any unmet gate, insufficient denominator, disputed authority, identity drift,
unsupported structure or incomplete Evidence SHALL end in a typed NO-GO. A
model score or aggregate average SHALL NOT override a failed critical gate.

#### Scenario: rate value has page and quote but no cell coordinates

- **WHEN** a rate fact lacks any required table/cell/row/column/header/span fact
- **THEN** the run emits typed Evidence-structure NO-GO even if the value matches
  Golden

#### Scenario: only fifty-nine distinct output fields are frozen

- **WHEN** an arm omits, duplicates or substitutes any Schema60 field ID
- **THEN** scoring returns typed NO-GO without changing the fixed denominator

#### Scenario: a caller declassifies a rate field

- **WHEN** an exact approved rate field has a false rate flag or lacks its required
  structural locator
- **THEN** scoring returns typed authority or Evidence-structure NO-GO

#### Scenario: Golden bytes or custody is mutated

- **WHEN** any `596.jsonl` byte changes or its parsed release, artifact, approval subject,
  ordered sources or Schema60 authority changes
- **THEN** scoring returns typed authority NO-GO and cannot mint a valid score receipt

#### Scenario: caller attempts to bypass parse admission

- **WHEN** any of the three intake receipts fails real 060 replay, is non-ADMIT or has
  byte/identity drift while the caller provides otherwise matching arm outputs
- **THEN** scoring returns typed NO-GO before Golden access and cannot use a status token
  or injected Golden object to bypass admission

#### Scenario: all deterministic gates pass

- **WHEN** both hashes and identities are exact, budget is within 6+8+4/18,
  Candidate fields biject Schema60, critical semantic/silent errors and hallucinations
  are zero, tri-state/value/Evidence thresholds pass and every rate locator is complete
- **THEN** the scorer returns `QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE`

#### Scenario: total control completes the real Go release proof

- **WHEN** the quality result is pending and the real Go 059 activation endpoint returns
  an immutable receipt/Head and pinned read/revert are demonstrated
- **THEN** total control MAY issue `MVP_VERTICAL_SLICE_GO`; the Python scorer still does not
  mint or verify that authority

### Requirement: VF6 current checkpoint is not an evaluation platform

This change SHALL remain a task-local, deterministic runner and focused test.
It SHALL NOT add a DB/migration, queue, experiment registry, model leaderboard,
prompt optimizer, parser winner, WeKnora write, production release, fallback or
general evaluation framework. Current dependency admission SHALL not read
environment credentials or filesystem Golden paths.

#### Scenario: dependency gate tries to prepare an experiment

- **WHEN** a required contract is absent
- **THEN** preparation stops at the typed dependency result with zero side effect

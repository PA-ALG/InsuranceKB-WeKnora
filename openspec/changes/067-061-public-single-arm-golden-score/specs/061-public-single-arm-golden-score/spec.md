# 061 Public Single-Arm Golden Score Specification

## ADDED Requirements

### Requirement: SAG1 admission and frozen custody precede Golden parsing

`score_admitted_frozen_arm` SHALL first replay the existing 061 exact three-artifact
admission. It SHALL then validate a complete `FrozenArmOutputV1` hash and require its
parse-artifact receipt digest to equal the replayed admission digest. Non-READY
admission, malformed output or hash/receipt drift SHALL return a typed block before the
exact 049 Golden parser is invoked.

#### Scenario: admission is not READY

- **WHEN** any parse artifact fails real 060 replay
- **THEN** single-arm scoring returns typed blocked, parses zero Golden bytes and emits
  no field score

### Requirement: SAG2 the seam is MinerU-specific and non-model authority is exact

The arm SHALL be role `candidate` and bind exact ProductVersion `596-1`, ordered three
source SHA256 identities, approved Schema version/hash, MinerU candidate parser
identity/mode/attempt, prompt, budget, normalizer and comparator identities, exact60
field order and admission digest. Baseline, non-MinerU, missing, duplicate, reordered,
foreign or caller-selected non-model authority SHALL fail before Golden parsing.

Semantic model id, API base and identity SHA SHALL be complete and included in both arm
and score receipts, but SHALL NOT be compared to the approved DeepSeek identity. This
permits an offline GPT-5.6-sol arm without granting that model production authority.

#### Scenario: only the model identity changes

- **WHEN** two otherwise equal, valid MinerU arm outputs carry different complete model
  identities and identical field results
- **THEN** both receive equal metrics but different score receipt hashes

### Requirement: SAG3 exact approved Golden bytes remain the only oracle

After admission and output authority pass, the seam SHALL invoke the existing strict
049 `596.jsonl` parser. Any byte or custody drift SHALL return typed Golden invalid.
The public API SHALL NOT accept a caller-built `GoldenSetV1` or expected values.

#### Scenario: one Golden byte changes

- **WHEN** the supplied bytes do not match exact approved 049 custody
- **THEN** no score is emitted and the result records `GOLDEN_596_BYTES_INVALID`

### Requirement: SAG4 metrics and absolute gates reuse 061 semantics

The seam SHALL return existing `ArmQualityMetricsV1` and the same absolute candidate
gate reasons used by 061: critical semantic/silent error, hallucination, tri-state
57/60, known-value 95 percent, critical Evidence 100 percent, overall Evidence 95
percent and rate locator completeness. It SHALL derive critical/rate/value flags from
the approved Golden/Schema identities, not caller labels.

#### Scenario: an approved rate field lacks a complete locator

- **WHEN** its field value matches but page/table/cell/row/column/header/span is incomplete
- **THEN** metrics are returned with `RATE_EVIDENCE_LOCATOR_INCOMPLETE`

### Requirement: SAG5 field results disclose correctness, not Golden answers

The result SHALL contain exactly sixty ordered field entries with field id, critical
priority, rate flag, tri-state correctness, exact-field correctness, Evidence presence
and rate locator completeness. It SHALL NOT expose a per-field flag that reveals
whether a Golden value participated in comparison, nor serialize expected state,
expected value, Golden reasoning, source quote or any other Golden answer.

#### Scenario: result is serialized

- **WHEN** a caller serializes the public score DTO
- **THEN** no Golden expected value or answer-bearing field name appears

### Requirement: SAG6 the score receipt binds all disclosed custody

`AdmittedFrozenArmScoreV1` SHALL bind status/reasons, output hash, full arm identity,
admission digest, exact Golden release/artifact/approval/file/content identities,
evaluator identity, metrics and all sixty field correctness entries into one C0 hash.
Any bound mutation SHALL change the receipt hash or fail replay.

#### Scenario: semantic model identity mutates

- **WHEN** only the bound model identity changes while field bytes remain equal
- **THEN** field metrics remain equal and the C0 score receipt changes

### Requirement: SAG7 the child remains a narrow deterministic seam

067 SHALL change only the existing 061 module and a focused test besides its OpenSpec
files and registry row. It SHALL perform no filesystem/environment/network/provider/
parser/database/WeKnora operation and SHALL NOT introduce a model registry, leaderboard,
generic evaluator, routing policy or production authorization.

#### Scenario: a caller supplies a new model name

- **WHEN** the model identity is structurally complete
- **THEN** it is only bound into the offline score receipt and no production capability
  is registered or invoked

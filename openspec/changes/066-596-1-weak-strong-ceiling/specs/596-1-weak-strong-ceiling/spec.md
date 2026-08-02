# 596-1 Weak/Strong Ceiling Comparison Specification

## ADDED Requirements

### Requirement: WSC1 both outputs freeze before Golden access

The comparison SHALL consume exactly two `FrozenArmOutputV1` values. Before invoking
the 067 scorer for either arm, it SHALL validate both complete DTOs and replay both
output hashes. If either output is malformed, mutable or incorrectly hashed, the
comparison SHALL return a typed block with zero scorer invocation and zero Golden
access.

#### Scenario: strong output hash drifts

- **WHEN** the weak output is valid but the strong output hash no longer matches
- **THEN** the comparison blocks before either arm is scored

### Requirement: WSC2 only model identity may differ

Both outputs SHALL be candidate MinerU arms for exact ProductVersion 596-1 and SHALL
bind the same ordered three sources, Schema version/hash, parser identity/mode/attempt,
parse-artifact receipt, prompt, normalizer, comparator and call/retry budget identities.
Their arm profile SHALL equal the task-local approved hash over the exact model-neutral
069 plan preimage: ordered eight semantic tasks, two deterministic-rate tasks and a
Schema60 field bijection. Equality to any other caller-chosen hash is insufficient.
Weak SHALL be exact `DeepSeek V4 Flash`; strong SHALL be exact `gpt-5.6-sol` on the
`offline-codex-strong-ceiling` execution surface. Any other drift SHALL block before
scoring.

#### Scenario: prompt identity differs

- **WHEN** both outputs are individually frozen but prompt hashes differ
- **THEN** neither score is produced and the reason is typed shared-input drift

#### Scenario: both arms substitute the same foreign task plan

- **WHEN** both outputs carry the same valid-looking but unapproved arm-profile hash
- **THEN** neither score is produced and the reason is typed task-plan drift

### Requirement: WSC2a strong execution receipt is external and exact

The comparison SHALL require a caller-provided `StrongExecutionReceiptV1` issued by
the actual offline Codex strong execution stage. The receipt SHALL bind exact execution
surface, `gpt-5.6-sol`, run identity, shared input hash, approved task-plan hash,
model/prompt/budget identities and frozen output hash. Its receipt hash SHALL be
recomputed from the canonical preimage. The comparison SHALL provide no receipt
builder and SHALL NOT derive this receipt from caller-supplied API base or model hash.
Missing, placeholder, foreign-surface, malformed or mismatched receipts SHALL block
before the first scorer or Golden access.

#### Scenario: no actual strong execution receipt exists

- **WHEN** frozen arm DTOs are supplied without the external strong execution receipt
- **THEN** comparison remains typed blocked with zero scorer invocation

### Requirement: WSC3 067 remains the sole Golden scorer

After both pre-Golden gates pass, the comparison SHALL call
`score_admitted_frozen_arm` once for weak and once for strong using the same admitted
parse artifacts and exact Golden bytes. It SHALL NOT parse Golden, compare values or
reimplement metrics. A non-SCORED result from either scorer SHALL produce a typed
comparison block.

#### Scenario: Golden bytes are invalid

- **WHEN** both 067 calls return Golden invalid
- **THEN** the comparison returns typed Golden invalid with no field delta

### Requirement: WSC4 deltas are answer-safe

For exact60 ordered fields, the comparison SHALL expose only field id, critical/rate
classification and the two scorers' correctness/Evidence/locator booleans plus a
derived `STRONG_BETTER | WEAK_BETTER | TIED_CORRECT | TIED_INCORRECT` class. Aggregate
deltas SHALL be arithmetic differences between public 067 metrics. No expected state,
expected value, Golden reasoning, quote or extracted answer SHALL be serialized.

#### Scenario: comparison is serialized

- **WHEN** a caller serializes the comparison result
- **THEN** no Golden answer-bearing field or arm value appears

### Requirement: WSC5 comparison is offline evidence, not authority

The result SHALL bind both output hashes, both model identities, the external strong
execution receipt/run identity, both 067 score receipt hashes, shared
artifact/Schema/task/prompt/normalizer/budget identities, answer-safe deltas and
evaluator identity into a C0 hash. It SHALL NOT select a production model, authorize a
release, call a provider, act as judge/fallback or create model registry state.
It SHALL NOT authorize automatic repair, Release or Active Head mutation.

#### Scenario: external strong run identity changes

- **WHEN** two otherwise identical valid comparisons bind different external run receipts
- **THEN** the comparison receipt changes and no production capability is minted

### Requirement: WSC6 implementation remains task-local

066 SHALL add one module, one focused test and four OpenSpec files only. It SHALL not
modify 067/068/069 or build a generic evaluation platform.

#### Scenario: a third model is supplied

- **WHEN** either role is not the exact frozen weak or strong model
- **THEN** the comparison fails closed rather than routing or falling back

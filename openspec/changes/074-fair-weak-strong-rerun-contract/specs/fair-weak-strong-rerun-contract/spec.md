# Fair Weak/Strong Rerun Contract Specification

## ADDED Requirements

### Requirement: FWR1 exact 073 authority precedes every arm call

The task-local runner SHALL call the existing 073 authority verifier before validating
or invoking either arm. A missing, stale, foreign, malformed or drifted receipt SHALL
return a typed block with zero weak and strong calls.

#### Scenario: exact user receipt is missing

- **WHEN** an otherwise valid fair-rerun request omits the 073 receipt
- **THEN** the result is blocked with `EXACT_USER_RECEIPT_MISSING` and both call counts
  remain zero

### Requirement: FWR2 both arms consume one exact shared input contract

Both arms SHALL bind the same three ordered parser artifacts, 069/072 composition,
Schema60 task partition, prompt semantics, budget, normalizer, output contract and parser
receipt. The weak model SHALL be DeepSeek V4 Flash and the strong model SHALL be
gpt-5.6-sol. Any drift SHALL fail closed before either arm call.

#### Scenario: one shared identity drifts

- **WHEN** source, parser receipt, task plan, Schema, prompt, budget or normalizer differs
  between the arms or from the approved contract
- **THEN** the runner blocks before execution

### Requirement: FWR3 execution is fixed, bounded and model-only

The runner SHALL invoke weak then strong exactly once through task-local seams. It SHALL
provide no retry, fallback, route selection, prompt tuning or third-model path. A weak
failure SHALL prevent the strong call; a strong failure SHALL preserve the completed
weak result only in memory and SHALL NOT authorize scoring.

#### Scenario: weak arm fails

- **WHEN** the weak task-local seam raises an execution error
- **THEN** weak count is one, strong count is zero, and no scoring receipt exists

### Requirement: FWR4 complete outputs freeze before Golden authority

Each arm SHALL return exactly one ordered Schema60 field bijection. The runner SHALL use
the existing arm freeze/hash function and verify both hashes before emitting an immutable
pair receipt. The runner SHALL have no Golden input or read path.

#### Scenario: an arm omits a field

- **WHEN** either arm output is not the exact ordered Schema60 set
- **THEN** the runner fails before emitting the pair receipt

#### Scenario: both outputs are complete

- **WHEN** both exact outputs freeze and replay successfully
- **THEN** the pair receipt is `OUTPUTS_FROZEN_FOR_049_SCORING`, binds both output hashes,
  and only then may an external caller invoke the existing 071/066 scoring path

### Requirement: FWR5 existing authority semantics are preserved

The pair receipt SHALL preserve the existing 071 result statuses: weak=`SCORED` and
strong=`UNADMITTED_RAW`. It SHALL NOT grant Release, production, machine-auto or Golden
authority and SHALL perform no DB, WeKnora or provider action during this implementation.

#### Scenario: strong result is frozen

- **WHEN** the strong output hash verifies
- **THEN** its authority remains `UNADMITTED_RAW`; freezing does not upgrade it

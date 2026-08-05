# Fair Experiment Executable Bridge Specification

## ADDED Requirements

### Requirement: FEB1 public execution requires opaque authorization

079 SHALL expose a public production transport `Protocol` and `execute_and_freeze(...)`.
The API SHALL require a non-null opaque authorization object and pass it to the transport
without inspecting, serializing, hashing, logging or returning it. Missing authorization
SHALL return a typed block with zero transport calls.

#### Scenario: authorization is missing

- **WHEN** a caller invokes the public execution API without authorization
- **THEN** both transport call counts and Golden reads remain zero

### Requirement: FEB2 074 remains the sole fair rerun execution contract

The bridge SHALL call `run_596_1_fair_rerun` and adapt its weak and strong execution
seams to one task-local transport. Weak SHALL be exact `DeepSeek V4 Flash`; strong SHALL
be exact `gpt-5.6-sol` on `offline-codex-strong-ceiling` only. Both SHALL share exact
three artifacts, Schema60, task decomposition, parser, prompt, normalizer, comparator,
timeout, budget, retry and fallback identities. The transport SHALL receive weak then
strong exactly once. Each submission SHALL carry the exact validated public
`SemanticInputCompositionV1`, including all three source content snapshots, composed
tasks, both task blueprints and the exact arm identity; prompt text resolution remains a
transport concern under the frozen prompt contract/template identity. No third model,
retry, fallback or production strong path exists.

#### Scenario: shared identity drifts

- **WHEN** either identity or its execution receipt changes a shared component
- **THEN** execution or sealing fails closed before Golden access

### Requirement: FEB3 transport execution receipts are replayed, not caller asserted

Each transport submission SHALL return the complete ordered Schema60 output plus a
task-local receipt whose canonical preimage binds role, composition, shared-input hash,
approved task-plan hash, exact model identity, prompt, budget, candidate frozen-output
hash and non-placeholder run identity. The bridge SHALL recompute and verify this receipt.
The strong result SHALL additionally return the externally issued public
`StrongExecutionReceiptV1`; the bridge SHALL retain and pass that exact object unchanged
to 066 and SHALL NOT mint, locally validate or reconstruct its upstream preimage. A
missing or foreign-typed receipt SHALL prevent sealing; semantic or hash drift remains
immutable seal custody and SHALL be rejected only by the public 066 preflight before
Golden loading.

#### Scenario: transport changes the frozen output hash

- **WHEN** the returned fields no longer replay to the receipt's frozen-output hash
- **THEN** the bridge returns typed receipt drift and no Golden loader is called

### Requirement: FEB4 074 pair is mechanically admitted to 066

Only after both 074 outputs and its pair receipt replay SHALL the bridge use the existing
`freeze_arm_output` to re-freeze the weak fields with `arm="candidate"`. It SHALL retain
the strong candidate output and include both 074 and canonical weak hashes in its
immutable sealed receipt. The seal SHALL retain the exact public 074 inputs and
`FairRerunResultV1`. Replay SHALL call public `run_596_1_fair_rerun` with deterministic
executors returning only the stored frozen field tuples and compare the complete replayed
result, including its pair receipt; it SHALL NOT locally reconstruct the 074 pair hash or
the 066 strong receipt preimage. It SHALL NOT duplicate upstream DTO, freeze/hash
implementation or scorer.

#### Scenario: complete pair freezes

- **WHEN** weak then strong each return one exact ordered Schema60 field set and exact
  receipts
- **THEN** the sealed receipt verifies both 074 hashes and contains the exact two
  candidate outputs required by 066

### Requirement: FEB5 Golden loading follows complete seal replay

`score_frozen_experiment(...)` SHALL first validate the exact sealed DTO, seal hash,
public 074 replay result/pair receipt, both output hashes, both transport receipts, the
externally issued strong-receipt custody, all shared/model identities and
strong-offline-only marker. It SHALL then call public
`compare_596_1_weak_strong_ceiling` with the exact sealed outputs/receipt, exact admitted
parse artifacts and fixed invalid synthetic Golden bytes. Only exact
`GOLDEN_INVALID / GOLDEN_596_BYTES_INVALID` admits the real Golden loader. Any other
preflight result or exception SHALL return typed blocked with `golden_reads=0`; only after
successful preflight SHALL the loader run once and public 066 run normally with the
unchanged strong receipt.

#### Scenario: sealed output mutates before scoring

- **WHEN** either output or pair receipt no longer matches the seal
- **THEN** the Golden loader and 066 scorer are not invoked

### Requirement: FEB6 strong output remains descriptive offline evidence

The bridge and its result SHALL preserve weak=`SCORED` and strong=`UNADMITTED_RAW`.
Strong execution SHALL never become production, fallback, judge, repair, Review, Release,
machine-auto or serving authority. No API SHALL accept a production strong surface.

#### Scenario: strong surface changes to production

- **WHEN** a transport receipt or identity names any surface other than
  `offline-codex-strong-ceiling`
- **THEN** the bridge fails closed before Golden access

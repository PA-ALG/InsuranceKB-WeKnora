# 596-1 Incremental Update Vertical Specification

## ADDED Requirements

### Requirement: IUV1 exact synthetic identity and partition

The task-local runner SHALL consume one strict synthetic fixture bound to exact
Space, ProductVersion `596-1`, subject, Schema version, and sixty unique ordered
field IDs. Exactly four declared fields SHALL be affected and the other
fifty-six SHALL be unchanged. The affected set SHALL contain exactly one
`enrich`, one `supersede`, one `conflict`, and one `retract`; `add` SHALL be
forbidden. The exact mapping SHALL be `clause_version→enrich`,
`zh_1ec5e3f2cc→supersede`, `zh_3d8424595d→conflict`, and
`zh_f32c510a5e→retract`. Equivalent ordering SHALL be canonicalized before
hashing, while movement into, out of, or within this mapping SHALL fail closed.
The fixture, 052 catalog, and all three material resolutions SHALL each bind
the approved exact ordered Schema60 canonical hash; a self-consistent
replacement catalog or replacement field in the other fifty-six SHALL fail
before preimage processing.
Fixture values SHALL be synthetic hashes and SHALL NOT load or resemble 049
expected answers.

#### Scenario: partition drifts

- **WHEN** a fixture adds, removes, duplicates, reorders ambiguously, or moves a
  field across Space, ProductVersion, subject, or the affected partition
- **THEN** the runner fails closed before Candidate assembly and emits no result

### Requirement: IUV2 existing custody contracts remain authoritative

The runner SHALL revalidate caller-provided 052 material catalog/resolutions
and one immutable preimage containing all sixty baseline facts plus their
exact hashes, three candidate facts, one retraction proof, exact 053 parsed
documents/manifests/quality decisions, 054 task/attempt/receipt chains, 057
`FieldCandidateV1` and exact Evidence snapshot preimages, verification batches
and fact links, repair resolutions, and review policy. Every known candidate
SHALL be replayed through the public 057 verifier against the exact bound 053
artifact, and its 054 receipt SHALL bind the replayed result. Retraction SHALL
add one independently replayable `absent_explicitly` candidate/Evidence on the
new terms revision, one 057 verification, one 054 receipt, and one link binding
those identities to the `RetractionProof` evidence hash, scope, and replacement
source.
Missing, extra, duplicate, unused, or drifted custody SHALL fail before
Candidate/HumanBatch assembly. The runner SHALL NOT generate any of these
authoritative inputs. It SHALL call public 058 `compile_incremental_changes`
and public 059 `build_fixture_candidate_batch` directly and SHALL NOT copy,
replace, or reimplement their action, source-authority, retraction, Evidence,
Candidate, or HumanBatch rules.

#### Scenario: custody identity drifts

- **WHEN** any catalog, resolution, parsed artifact, receipt, verification,
  candidate preimage, fact, scope, explicit-absence Evidence, or snapshot hash
  differs from the exact synthetic preimage, even if its dependent batch, link,
  receipt, or proof is recomputed consistently
- **THEN** the runner returns a typed failure with zero Candidate and HumanBatch

### Requirement: IUV3 exact four-action semantics

The affected fields SHALL prove the existing governance semantics: equal value
plus new verified Evidence produces `enrich`; a different value with
deterministically higher approved source authority produces `supersede`; a
different value without a deterministic authority winner produces `conflict`
and preserves both facts and all Evidence; and complete-scope explicit absence
with exclusive support and a newer approved replacement authority produces
`retract` without physically deleting history.
The explicit absence SHALL be supported by an exact locator and replayed 057
PASS on the new terms 053 artifact; a predictable or caller-invented absence
hash SHALL NOT authorize retraction.

#### Scenario: absence or authority is ambiguous

- **WHEN** absence is merely unknown, support is not exclusive, or authority
  cannot be deterministically ordered
- **THEN** retraction or supersession is not fabricated and compilation fails
  closed or retains an explicit conflict

### Requirement: IUV4 unaffected facts remain byte-identical

The runner SHALL revalidate caller-provided canonical hashes for all sixty
baseline facts and return the exact fifty-six unchanged hashes. Those hashes
SHALL equal the validated baseline fact objects and SHALL be absent from the
058 ChangeSet, 059 Candidate changes, and HumanBatch items. Moving a fully
recomputed fact between the exact affected and unchanged partitions SHALL fail
closed.

#### Scenario: unchanged field enters the affected pipeline

- **WHEN** an unchanged scope appears in candidate facts, a retraction proof,
  the ChangeSet, Candidate changes, or HumanBatch items
- **THEN** the runner fails closed rather than widening the update

### Requirement: IUV5 deterministic non-authoritative receipt

The runner SHALL return an immutable 078 receipt binding fixture hash, caller
preimage hash, exact root identity, ordered affected action map, ChangeSet
hash, Candidate hash, HumanBatch hash, and the fifty-six unchanged fact hashes.
Equivalent fixture, authority, fact, artifact, receipt, verification, and link
iteration order SHALL NOT change the receipt. Any managed mutation SHALL
change a canonical digest or fail validation.

#### Scenario: equivalent input is reordered

- **WHEN** the same exact validated facts and receipts arrive in another
  iteration order
- **THEN** the resulting 078 receipt and all governed hashes remain identical

### Requirement: IUV6 zero external effects and zero release authority

The implementation SHALL be pure task-local composition. It SHALL perform no
Golden read, provider/model call, network, environment, filesystem write,
database, PostgreSQL, WeKnora, migration, Release, Active Head, or production
action. The fixture Candidate/HumanBatch and 078 receipt SHALL NOT grant review
approval or release authority.

#### Scenario: runner executes successfully

- **WHEN** all exact synthetic custody inputs validate
- **THEN** only immutable in-memory DTOs and canonical hashes are returned and
  every external-effect counter remains zero

# Extraction task and receipt specification

## Purpose

Define the smallest pure domain contract for bounded extraction work. The
contract records task identity, attempts, and typed receipts. It does not run a
model, persist a job, admit a parsed document, or grant release authority.

## ADDED Requirements

### Requirement: ETR1 exact task identity

An `ExtractionTaskV1` MUST bind:

- exact `space_id`, `product_version_id`, and `source_revision_id`;
- exact material role, module identity, and risk-partition identity;
- one non-empty, unique, canonical-ordered tuple of field IDs;
- exact C0 artifact references for the source and all approved upstream inputs;
- an explicit attempt/field budget; and
- a code-owned canonical task hash.

The task MUST additionally bind one `ExtractionTaskProfileV1` built from the
merged 052 `MaterialProfile`, exact material-profile binding hash,
`ParsePolicyReceipt`, applicable `FieldAuthority`, and extraction attempt
budget. The selected task fields MUST be a subset of that authority group; the
task material role MUST be either its primary role or an explicit support role.
The task's top-level role, budget, and material-profile C0 hash MUST exactly
match the frozen profile.
The material-profile input reference MUST use the merged 052
`material-profile-template-binding.v1` object type, not merely reuse its hash
under another object type.

The task MUST reject blank or wildcard identity, duplicate or non-canonical
field order, a field count above its explicit budget, malformed C0 hashes,
unknown/extra input members, and input identities containing `golden`,
`provider`, `prediction`, `release`, or `approval` markers.
Every identity component MUST reject embedded glob metacharacters and
wildcard-semantic tokens such as `space-*`, `coverage-*`, `risk-?`, or
`version-all`; validation is a finite code-owned check, not a pattern platform.

#### Scenario: material × module × risk partitions differ

Changing any one of material role, module ID, risk partition ID, ordered fields,
or upstream C0 reference MUST change the task hash.

#### Scenario: whole-product expansion is not implicit

A caller providing more fields than the task's explicit `max_fields` MUST
receive a typed validation error. The implementation MUST NOT silently enlarge
the budget or split/merge work.

### Requirement: ETR2 explicit bounded attempts

The budget MUST permit exactly one initial attempt and either zero or one
targeted repair. `max_total_attempts` MUST equal
`1 + max_targeted_repairs`; values beyond two total attempts are invalid.

For a 052-backed extraction task profile, the extraction budget MUST be frozen
to one initial attempt plus at most one targeted repair. This extraction budget
is independent from `ParsePolicyReceipt.max_parser_attempts`: the latter records
upstream parser attempts and MUST NOT grant extra extraction attempts.

An attempt MUST bind the task hash, exact attempt number, purpose, exact field
IDs, optional parent receipt hash, and a canonical attempt hash. Attempt 1 MUST
be `initial`, have no parent receipt, and cover exactly the task fields. Attempt
2 MUST be `targeted_repair`, bind the exact initial receipt hash as its parent,
and be derived from that receipt's unresolved fields.

#### Scenario: caller requests a third attempt

- **WHEN** an existing chain already contains initial and targeted-repair receipts
- **THEN** another repair request fails with `repair_budget_exhausted`

### Requirement: ETR3 typed immutable receipts

Every attempt MUST produce one immutable `AttemptReceiptV1` containing:

- exact task and attempt hashes, number, purpose, and attempted fields;
- one and only one explicit outcome for every attempted field;
- an explicit attempt outcome and, where required, reason code; and
- a code-owned canonical receipt hash.

A `ReceiptChainV1` MUST bind the exact `ExtractionTaskV1`. Its initial receipt
MUST cover every task field exactly; a valid two-field receipt cannot be used as
the initial receipt of a three-field task even when its task hash is copied.

Candidate field outcomes MUST carry an opaque candidate artifact reference and
no failure reason. `unknown`, `blocked`, and `failed` outcomes MUST carry a
reason and no candidate artifact. Missing outcomes, duplicates, extras, hash
drift, and default/empty outcomes MUST fail closed.

#### Scenario: a receipt omits an attempted field

- **WHEN** receipt outcomes are not an exact ordered bijection with attempted fields
- **THEN** validation fails and no receipt is produced

### Requirement: ETR4 at most one targeted repair

The targeted repair field set MUST be the canonical unresolved subset from the
initial receipt. Candidate fields from the initial receipt MUST NOT be retried.
Repair after a fully successful receipt, repair of a repair receipt, caller
addition/removal of fields, or any third attempt MUST fail closed.
Two initial receipts with the same unresolved subset but different receipt
hashes MUST produce different repair attempt hashes.

#### Scenario: one field is already a candidate

- **WHEN** the initial receipt has one candidate and two unresolved fields
- **THEN** the repair attempt contains exactly the two unresolved fields

### Requirement: ETR5 terminal and failure zero-default behavior

There MUST be no default success, candidate, receipt outcome, or reason.
Blocked/failed attempt receipts MUST contain zero candidate outcomes. Budget
exhaustion or remaining unresolved fields MUST remain explicit and MUST NOT be
promoted to a candidate, admitted bundle, or release fact.

#### Scenario: a failed attempt contains a candidate

- **WHEN** an attempt is declared `failed` but any field has candidate status
- **THEN** receipt validation fails rather than retaining a partial candidate

### Requirement: ETR6 Golden blind and non-authority

Task and receipt modules MUST NOT import Golden artifacts or accept artifact
types/extra members containing `golden`. They MUST NOT read a Golden dataset,
provider result, prior prediction, release, or approval record.

The DTOs and hashes are audit/domain facts only. They MUST NOT mint C0,
CandidateRelease, Release, VerifiedAdmission, capability, permit, or production
execution authority.

#### Scenario: caller supplies a Golden artifact reference

- **WHEN** an input object type contains `golden`
- **THEN** task validation rejects it before task hashing

### Requirement: ETR7 merged 052 and exact 053 admission boundary

The task profile MUST consume the real merged 052 public DTOs. A receipt whose
policy fields or required capabilities differ from its `MaterialProfile` MUST
fail validation. A field-authority group that does not apply to the profile's
material role, a caller-supplied authority mode, a non-repair extraction budget,
or a binding-hash mismatch MUST fail closed.

#### Scenario: parser and extraction budgets differ

- **WHEN** the 052 parse-policy receipt records its own bounded parser budget
- **THEN** the extraction profile records that receipt unchanged while keeping
  its separate one-initial-plus-one-repair maximum

The single `ParsedArtifactAdmissionPort` MUST consume the real 053
`ParsedDocumentV1`, `ParseManifestV1`, and `ParseQualityDecisionV1` DTOs. It
MUST require ADMIT and exact shared Space/ProductVersion/SourceRevision,
material-profile binding, source SHA, parse-policy receipt, manifest inventory,
admitted attempt, and measured capability facts. Attempt 1 MUST use the
receipt's approved default parser profile and attempt 2 MUST use its bounded
upgrade profile. Both the document and manifest privacy/output policy refs MUST
exactly match the receipt, and the bound snapshot MUST record
`pagination_complete=true`. Its opaque references MUST use the computed hashes
supplied by those exact DTOs. It MUST NOT redefine a 053 DTO/hash, admit drifted
or non-ADMIT artifacts, or expose provider execution.

#### Scenario: the quality decision references another manifest

- **WHEN** an otherwise valid quality-decision DTO carries a different manifest
  hash
- **THEN** the port fails with `parse_artifact_admission_mismatch` and emits no
  input-reference bundle

#### Scenario: a self-consistent ADMIT bypasses evaluator policy

- **WHEN** self-consistent 053 DTOs use the wrong parser profile for their
  attempt, drift either privacy/output policy ref, or bind an incomplete
  paginated snapshot
- **THEN** the port fails with `parse_artifact_admission_mismatch` and emits no
  input-reference bundle

### Requirement: ETR8 pure bounded domain surface

The implementation MUST be limited to frozen Pydantic DTOs and deterministic
builders/validators. It MUST have no queue, worker, Agent, DB, migration,
provider, model, network, filesystem, environment, CLI, WeKnora, or live I/O.

#### Scenario: implementation attempts runtime I/O

- **WHEN** either production module imports DB, network, filesystem, provider,
  worker, or any 053 module other than its exact pure contract
- **THEN** the focused import/scope gate rejects the candidate

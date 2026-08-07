# 096 Private Receipt → 092 Authority Adapter Specification

## ADDED Requirements

### Requirement: PRA1 exact private file snapshot

The adapter SHALL read one bounded relation receipt from an exact regular `0600` file by
no-follow open and one descriptor snapshot. Symlink, mode, type, size or pre/post inode,
size, mtime or ctime drift SHALL return a fixed typed block with no bytes or partial DTO.

#### Scenario: file changes during read

- **WHEN** the descriptor snapshot changes between the bounded pread and final fstat
- **THEN** the adapter returns `BLOCKED_ON_CROSS_PAGE_BINDING` and exposes no receipt

### Requirement: PRA2 canonical 096 replay

Receipt bytes SHALL be exact canonical UTF-8 JSON with one terminal newline, no duplicate
key, extra field, non-finite value or trailing byte. The adapter SHALL validate the exact
096 DTO and call its public replay so the receipt preimage, relation binding preimage and
all nested digests are recomputed by their owning contracts.

#### Scenario: attacker reseals one outer digest

- **WHEN** a source, endpoint, parser, member, policy, context or nested binding fact drifts
  while an attacker changes one self-reported digest
- **THEN** public replay or cross-contract comparison blocks before 092

### Requirement: PRA3 independent 083 custody replay and 092 authority binding

The adapter SHALL accept exactly three custody byte payloads and invoke public 083 intake
to rebuild the bundle; it SHALL NOT accept a caller-constructed bundle or self-reported
bundle digest. It SHALL independently revalidate exact 092 source-authority and
material-profile tuples. It SHALL require exact terms, brochure, rate order; one Space;
ProductVersion `596-1`; exact source SHA; exact parser/config and bounded-upgrade policy
binding. It SHALL NOT derive runtime IDs or profile authority from receipt text.

#### Scenario: cross-product receipt

- **WHEN** receipt, bundle, source authority or profile refers to another product/source
- **THEN** the adapter returns a fixed block and no 092 input context

### Requirement: PRA4 exact 098 marker authority

The adapter SHALL obtain exactly one section map and one table map only through the exact
098 public authority builder and validate both as public 092 DTOs. Missing or incompatible
098 symbols SHALL return `DEPENDENCY_UNAVAILABLE`; incomplete current evidence SHALL stay
`BLOCKED_ON_CROSS_PAGE_BINDING`. It SHALL NOT infer endpoints from path hashes, adjacent
pages, body/Markdown text or fuzzy matches.

#### Scenario: current 098 candidate

- **WHEN** the frozen 098 candidate exposes no exact terms+rate 092-map builder
- **THEN** production resolution is `DEPENDENCY_UNAVAILABLE` before any 092 call

### Requirement: PRA5 exact relation provider and composition-only output

Success SHALL return only a frozen `VALIDATED` context containing the exact source
authorities, profile resolutions, two marker maps and a relation provider accepted by 092.
The provider SHALL select only the receipt's terms/section or rate/table binding and SHALL
recheck bundle, source, ParsedDocument and ParseManifest identities on every call. Any
failure exposes zero partial context. A synthetic complete fixture may prove the context
can call 092, but SHALL NOT claim ADMIT, READY or real MinerU success.

#### Scenario: document or manifest drifts after adaptation

- **WHEN** 092 invokes the provider with a different document or manifest identity
- **THEN** the provider raises one fixed privacy-safe typed failure

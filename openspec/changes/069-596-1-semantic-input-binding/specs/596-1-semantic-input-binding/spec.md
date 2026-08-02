# Product 596-1 shared MinerU semantic task composer specification

## ADDED Requirements

### Requirement: SIB1 exact shared MinerU custody precedes composition

The composer SHALL bind ProductVersion `596-1`, the exact ordered
terms/brochure/rate-table sources, approved Schema60, exact 052 resolved
material/template/source authority, exact 060 admitted ParsedDocument and
ParseManifest receipts, and exact 068 `mineru-semantic-content-custody.v2` from
the same parser read. The exact three-source set MUST first replay through the
public 061 admission boundary, and its admission receipt digest MUST be part of
the composition identity. A caller-constructed self-consistent `ADMIT` DTO is
not authority.

Source, parser/model/config, raw/sanitized structure, content snapshot, attempt,
document and manifest hashes MUST agree transitively. Missing, duplicate,
cross-source, cross-attempt or hash-drifted input SHALL fail before emitting a
task, provider request or Golden access. Markdown SHALL NOT create or repair a
structure locator.

#### Scenario: content and structure come from different reads

- **WHEN** an 068 content hash or parser identity differs from its exact 060
  admitted artifact
- **THEN** composition fails with no task or partial output

### Requirement: SIB2 the task plan is a fixed Schema60 bijection

The composer SHALL produce exactly ten tasks: four terms semantic tasks, four
brochure semantic tasks and two deterministic rate tasks. Their field tuples
SHALL form an exact unique Schema60 bijection and every field SHALL use its
approved 052 primary source authority.

Each arm SHALL bind its exact task/module/risk identity, field tuple, source,
material/template, parser/custody, model, prompt, budget, normalizer and
output-contract identities. The shared ten-task preimage and Schema60
partition remain model-neutral. The eight semantic tasks may create model
requests; the two rate tasks are deterministic and MUST NOT create model
requests.

#### Scenario: one field is missing or assigned to another source

- **WHEN** a Schema60 field is omitted, duplicated, substituted or routed away
  from its 052 primary source
- **THEN** no task plan or attempt is emitted

### Requirement: SIB3 merged 054 attempts and bounded 057 repair

Every semantic task SHALL be built through the merged 054 task profile and sole
ParsedArtifactAdmissionPort, followed by its merged 054 initial attempt. Model
output SHALL produce an exact immutable, arm- and composition-bound attempt
receipt whose canonical hash binds the receipt chain, 064 Evidence receipt
hashes and the 057 verification generated from that same response-binding
operation. The repair operation MUST consume the complete ordered set of eight
semantic attempt receipts and their bound 057 verification/locator plans; it
MUST NOT accept a caller replacement verification. The merged 057 receipt
binder MUST validate the complete active 054 receipt partition, including PASS
candidate hashes and unresolved reason-code equality, and the merged 057
planner MUST reproduce the bound locator plan. Every locator reference MUST
exist in the exact admitted ParsedDocument. The operation SHALL emit one
immutable bundle with unique task IDs and derive at most four unresolved task
repairs. Split `4+1`, duplicate-task, missing-receipt, cross-arm,
cross-composition, retry, fallback and a third attempt are forbidden.

Deterministic rate tasks SHALL bind the same admitted source and output identity
but consume no provider or repair budget. Their known Evidence MUST use the
merged 057/064 page+table+cell+row/column/header/span locator; block-only or
missing-cell Evidence is forbidden.

#### Scenario: a fifth repair is requested

- **WHEN** four exact task repairs already exist
- **THEN** the bundle fails closed before another request is emitted

### Requirement: SIB4 strict JSON and exact 064 Evidence

A semantic response SHALL be one strict JSON object with an exact field
bijection for its owning task. Known output SHALL map to merged 064
`FreeformFieldOutputV1`; unknown output SHALL carry no value or Evidence.

For each known item, locator content supplied by the response MUST occur in the
exact 068 document snapshot, hash to the exact 060 block/table/cell content
hash, and contain the quote verbatim. Source/page/block/table/cell/row/column/
header/span facts SHALL copy one-to-one from the exact 060 ParsedDocument.
069 SHALL NOT infer, complete, downgrade or synthesize a locator.

Non-JSON, missing/duplicate/extra fields, quote absence, locator/content drift
or task/attempt/receipt drift SHALL emit no 064 receipt.

#### Scenario: text exists but locator content hash differs

- **WHEN** a quote appears in the full 068 text but the supplied locator
  snapshot does not match the selected 060 locator content hash
- **THEN** Evidence binding fails rather than attaching the quote heuristically

### Requirement: SIB5 one model-neutral bundle for weak and ceiling arms

The public composer SHALL be consumable by 061 and 066. The same MinerU
authority and Schema60 partition may be instantiated with the exact DeepSeek V4
Flash identity or the later exact `gpt-5.6-sol` identity. Model, prompt, budget,
normalizer and output-contract identities MUST be explicit and byte-sensitive.
Each response and receipt MUST bind one exact arm blueprint and model identity;
the arms are not exchangeable. 069 does not choose or authorize either model.

The module SHALL contain no HTTP transport, provider credential, Golden loader,
scorer, DB, migration, queue, WeKnora call, parser router or release authority.

#### Scenario: execution identity changes

- **WHEN** model, prompt, budget, normalizer or output-contract identity changes
- **THEN** bundle/task identity changes while the fixed Schema60 partition does
  not

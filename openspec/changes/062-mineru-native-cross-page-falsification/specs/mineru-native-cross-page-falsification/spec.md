# MinerU exact native cross-page fact falsification specification

## ADDED Requirements

### Requirement: MCPF1 exact task-local identity

062 SHALL run only inside 061 capture policy for the two frozen source SHA-256 values. It
SHALL bind exact raw ZIP SHA-256, MinerU `_backend=pipeline`, `_version_name=3.4.4`, parser
model/config identity and one unique `*_middle.json` member. Other source identities SHALL
retain 061 behavior without producing a cross-page claim.

#### Scenario: native member is unavailable

- **WHEN** an exact source ZIP lacks a unique compatible middle member
- **THEN** projection returns typed `NATIVE_CROSS_PAGE_FACT_NOT_AVAILABLE`, and no relation or
  admission is claimed

### Requirement: MCPF2 hostile ZIP fails closed

The capture-only download SHALL stop after reading at most the fixed compressed-size budget
plus one byte and reject an oversized body before ZIP projection. The projector SHALL enforce
member count, per-member and total uncompressed size and compression-ratio budgets. Member
paths SHALL be relative, clean, UTF-8-safe and unique after slash normalization. Only regular
files and directories are accepted; symlinks and all other special modes, zip-slip, duplicate
normalized names, encrypted entries and sensitive member names SHALL fail closed.
The allowlist is limited to official pipeline presentation, content-list, middle/model JSON,
debug PDF and image output categories. Inventory SHALL contain only category, byte size and
content SHA-256, never member name/path.

#### Scenario: ZIP is ambiguous or hostile

- **WHEN** the HTTP body exceeds the compressed budget, or a member escapes the archive root,
  duplicates another normalized name, exceeds a fixed budget, has a symlink/special mode or
  unsupported class, or has a sensitive name
- **THEN** no projection or capture evidence is published

### Requirement: MCPF3 explicit native fact only

The projector SHALL inspect only `pdf_info[].page_idx`, `para_blocks`, nested block/line/span
structure, type/index and exact vendor booleans `cross_page` and `lines_deleted`. Neither
boolean contains a complete source/target page plus stable node/ref identity. Therefore every
true marker SHALL produce only a domain-hashed structural observation and make the document
`AMBIGUOUS`; `relation_count` and `relations` SHALL remain empty. The projector SHALL NOT
derive an endpoint from page adjacency or manufacture two IDs by hashing one structural path
under different labels. No marker SHALL make the document `ABSENT`. No text, HTML,
coordinates, image data, URL, secret, filename or local path SHALL enter the projection.
Unknown marker values or malformed page/structure identities SHALL fail closed.

#### Scenario: presentation only looks continuous

- **WHEN** Markdown, content-list adjacency, repeated headers, HTML similarity or nearby pages
  look continuous but contain no accepted native marker
- **THEN** 062 emits no relation and SHALL NOT upgrade the result to `PRESENT`

### Requirement: MCPF4 deterministic three-state result

Each exact document SHALL produce `NATIVE_CROSS_PAGE_FACT_ABSENT`,
`NATIVE_CROSS_PAGE_FACT_AMBIGUOUS`, or typed `NATIVE_CROSS_PAGE_FACT_NOT_AVAILABLE`, with
`relation_count=0`, no relation endpoints, hashed ambiguous structural observations, raw ZIP
digest, sorted member inventory digest, middle-member digest and semantic projection digest.
`NATIVE_CROSS_PAGE_FACT_PRESENT` is reserved and SHALL NOT be emitted for the pinned MinerU
schema; enabling it requires a separately reviewed vendor schema that supplies complete
source/target pages and stable native node/ref IDs. Same member bytes and facts SHALL yield
the same semantic projection regardless of ZIP member order or member path. Changing a marker
or its structural location SHALL change the semantic projection digest. Raw ZIP digest may
change with ZIP container bytes and is separate custody, not semantic authority.

#### Scenario: current pinned-schema fixtures

- **WHEN** synthetic native ZIP fixtures contain `cross_page=true`, `lines_deleted=true`, no
  markers, or no compatible middle member
- **THEN** they deterministically yield AMBIGUOUS, AMBIGUOUS, ABSENT, or NOT_AVAILABLE;
  relation count remains zero in every current-schema case

### Requirement: MCPF5 capture-only publication

The projection SHALL be attached only to the existing 061 private evidence and SHALL inherit
its provider budget, deadline, secret/path redaction and atomic no-replace publication. A
projection error SHALL expose no final evidence. 062 SHALL NOT change ordinary MinerU reader
behavior, the 060 native sidecar, 052 admission, or any repository/runtime state.

#### Scenario: final evidence already exists

- **WHEN** publication races an existing final path or projection fails before publication
- **THEN** the existing path remains byte-identical and no partial final file is visible

### Requirement: MCPF6 bounded delivery

062 SHALL modify no more than nine repository paths and SHALL add no migration, DB, provider
call, adapter admission, public parser framework, proto or second runtime. Real two-document
capture remains `NOT RUN` until a separate total-control authorization.

#### Scenario: implementation exceeds the bounded slice

- **WHEN** GREEN requires a tenth path, public DTO/proto, second parser/runtime or real provider
- **THEN** implementation stops and reports the blocker instead of expanding 062

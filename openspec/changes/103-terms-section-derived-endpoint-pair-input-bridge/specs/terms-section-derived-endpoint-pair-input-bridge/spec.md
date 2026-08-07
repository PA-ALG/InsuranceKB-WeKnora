# Terms Section Derived Endpoint-Pair Input Bridge Specification

## ADDED Requirements

### Requirement: TSE1 closed input and marker replay

The bridge MUST revalidate the exact 083 three-source bundle, terms 053
document/manifest and one 101-compatible authority response. It MUST recompute
source/parser/version/raw ZIP/member/marker/path/node/envelope/request/response
digests rather than trust caller assertions.

#### Scenario: custody drift

- **WHEN** any page, node, local index, member, source, parser, version, path,
  marker, envelope or response identity drifts
- **THEN** the bridge returns fixed typed `BLOCKED` and emits no pair/binding/entry

### Requirement: TSE2 deterministic section endpoints

The marker MUST be `cross_page`, node type `text`, and map uniquely to an actual
canonical source block. The target MUST be the unique reading-order-first
qualified content block on exactly the next physical page. Both endpoints MUST
be bound to the same non-empty, replayable section ancestry/outline anchor and
heading-anchor digest by the 101 authority protocol.

#### Scenario: anchor unavailable

- **WHEN** no anchor response exists, a new heading starts, the target is not
  first, pages differ by more than one, or zero/multiple candidates exist
- **THEN** the bridge returns typed `NOT_AVAILABLE` or `BLOCKED` and emits no pair

#### Scenario: semantic temptation

- **WHEN** only adjacent prose, Markdown headings or character similarity exists
- **THEN** the bridge does not inspect or compare text and returns `NOT_AVAILABLE`

### Requirement: TSE3 marker kinds remain distinct

`lines_deleted` MUST NOT be accepted as `cross_page`; unknown marker kinds MUST
fail closed and MUST NOT be normalized into a known kind.

#### Scenario: wrong marker kind

- **WHEN** authority returns `lines_deleted` or an unknown kind
- **THEN** no endpoint pair, binding or receipt entry is produced

### Requirement: TSE4 derived-only composition

A valid pair MUST implement the frozen 086 replay protocol and bind the actual
endpoint IDs/pages, policy and all custody hashes. Through the explicit 102
marker-preserving mode, 086 MAY return only
`DERIVED_STRUCTURAL_BINDING_VERIFIED`; the existing 096 terms entry MUST accept
that exact binding.

#### Scenario: future-complete fixture

- **WHEN** one exact marker, one exact next-page first block and one equal anchor
  preimage satisfy the frozen policy
- **THEN** 103→102→086 returns a verified derived binding and 096 accepts it

### Requirement: TSE5 privacy and current-evidence honesty

The bridge MUST be pure in-memory and MUST NOT expose body, Markdown, URL,
secret or absolute path material. Current real evidence without a structural
anchor MUST remain `SECTION_ANCHOR_NOT_AVAILABLE`.

#### Scenario: no current anchor authority

- **WHEN** the canonical document has locators and reading order but no 101
  section-anchor response
- **THEN** the result is `NOT_AVAILABLE`, not a guessed relation

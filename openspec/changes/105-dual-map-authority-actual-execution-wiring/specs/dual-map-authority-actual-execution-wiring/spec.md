# Dual-map Authority → Actual Execution Wiring Specification

## ADDED Requirements

### Requirement: DMA1 exact dependency order and typed absence

The composer SHALL resolve the exact 101, 098, 103, 100 and 095 public surfaces before
performing file or composition work. If the frozen 103 section replay is absent,
incompatible or returns `NOT_AVAILABLE`, the result SHALL be
`TERMS_SECTION_BINDING_UNAVAILABLE` with zero 100, 092 and 095/087 calls and zero partial
receipt. Other dependency identity or signature drift SHALL be `DEPENDENCY_UNAVAILABLE`.

#### Scenario: current 103 is not frozen

- **WHEN** the exact 103 section-map callable is unavailable
- **THEN** the composer returns `TERMS_SECTION_BINDING_UNAVAILABLE` before private I/O

### Requirement: DMA2 distinct dual-map authority

The composer SHALL consume one real 101 envelope, one 098 rate-table replay and one 103
terms-section replay. It SHALL bind exact product, source role/order, source SHA, parser,
version, native member, endpoint, policy, replay, context, preimage and hash facts. The map
order SHALL be exactly `(terms section, rate table)`. Missing, duplicate, swapped or
cross-product maps SHALL fail before 095/087.

#### Scenario: rate map is reused for terms

- **WHEN** the same table authority is supplied for both relation kinds
- **THEN** composition stops with no actual-execution call

### Requirement: DMA3 public 100 and 092 authority path

105 SHALL pass its exact dual-map replay port into one narrow public 100 seam. 100 SHALL
continue to parse and replay the 096 receipt, rebuild the 083 bundle, validate independent
source/profile authorities and expose only its five 092 arguments. 105 SHALL NOT parse the
receipt, duplicate 100/092 digests or construct authority DTOs directly.

#### Scenario: receipt or binding drifts

- **WHEN** receipt, source/member, binding, policy, replay or context identity changes
- **THEN** 100 or its owning upstream replay blocks and 092 is not called

### Requirement: DMA4 preserve actual private execution gates

The final call SHALL enter the existing 095/087 private execution boundary. Its regular
`0600`, no-follow, distinct-file, exact role/order and stable snapshot checks SHALL remain
unchanged. Symlink, mode, TOCTOU, extra/missing file or artifact identity drift SHALL expose
zero partial output and no admission call.

#### Scenario: private receipt is a symlink

- **WHEN** the relation receipt path is a symlink
- **THEN** existing 095/087 custody returns a fixed input block before 100

### Requirement: DMA5 composition-only terminal result

The composer SHALL allow a future complete fixture to prove the exact
091→101→098/103→102/086→096→100→092→095/087 call graph reaches
`COMPOSITION_SEAM_VERIFIED`. This result SHALL remain synthetic-only and SHALL NOT claim
real MinerU `ADMIT`, `READY`, Release or production eligibility.

#### Scenario: synthetic Protocol attempts production authority

- **WHEN** a Protocol fake is presented through the production resolver
- **THEN** exact symbol/signature identity checks reject it before any private-file read

### Requirement: DMA6 privacy and zero external operation

Typed failures SHALL contain only fixed status/reason codes and SHALL not expose body text,
Markdown, path, URL, secret or raw exception text. Provider/model/Golden/DB/PG/WeKnora,
capture, live and full operations SHALL remain zero.

#### Scenario: dependency exception contains sensitive text

- **WHEN** a dependency raises an exception containing secret, URL, path or source text
- **THEN** only a fixed typed result is returned without chained exception detail

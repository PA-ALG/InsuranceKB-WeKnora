# 596-1 Relation-bound Admission Integration Specification

## ADDED Requirements

### Requirement: RAI1 exact intake and authority closure

092 SHALL replay one immutable 083 bundle in exact terms → brochure → rate order.
It SHALL map `rate` to 052 `rate_table` and no other role. For each source it SHALL
require one closed caller authority carrying the exact Space, source, revision,
attempt, snapshot and mutation-fence identities. It SHALL resolve the registered
052 profile and SHALL NOT derive Space/source/revision/snapshot identity from a
filename, hash, role or raw JSON.

#### Scenario: a rate intake is presented as an ordinary document

- **WHEN** the rate source is not mapped to the exact registered `rate_table` profile
- **THEN** integration returns typed blocked with zero receipts

### Requirement: RAI2 086-to-090 trusted relation translation

Before deriving a binding, 092 SHALL require source and target marker nodes with
typed zero-based page index, node kind and local index. Each node SHALL resolve to
exactly one canonical 053 block or table of the correct source and relation kind.
The structural-path hash SHALL remain custody evidence and SHALL NOT select or
name an endpoint. A missing node, ambiguous mapping or the current one-node 089
shape SHALL return typed blocked with zero output.

092 SHALL then derive exactly one terms `section` binding and one rate `table`
binding through frozen 086. Both SHALL replay with status
`DERIVED_STRUCTURAL_BINDING_VERIFIED`. The adapter SHALL translate them into the
future-090 trusted builder input while binding source/parser/config/raw/sanitized/
material-profile/policy/replay context and the actual 053 endpoint IDs. Section
endpoints SHALL be actual blocks; table endpoints SHALL be actual tables and the
090 replay SHALL preserve bidirectional continuation. Because 086 and 090 use
different relation-kind and endpoint layouts, 092 SHALL explicitly map
`section|table` to `section_continuation|table_continuation`, flatten only the
validated endpoint IDs, reconstruct policy and replay context from the exact 052/
053/083 inputs, and recompute the 090 binding hash at the boundary. It SHALL NOT
forward an 086 hash, a structural-path hash or a caller-reported 090 context as
authority.

#### Scenario: marker hash exists but typed endpoint facts are incomplete

- **WHEN** 089 supplies a path hash without two typed nodes that uniquely resolve
  to the canonical 053 endpoints
- **THEN** integration returns `089_ENDPOINT_AUTHORITY_INSUFFICIENT` and no bundle

#### Scenario: a caller substitutes a locally self-consistent relation

- **WHEN** any 086 or 090 identity, endpoint, kind, hash or replay value drifts
- **THEN** no final receipt or bundle is exposed

### Requirement: RAI3 three real 060 decisions before 061 readiness

The future-090 builder Protocol SHALL use the real 060 input types and return exact
053 document/manifest/decision objects. 092 SHALL construct receipts in exact
terms → brochure → rate-table order. Terms and rate SHALL use their respective
trusted relations; brochure SHALL use none. Every final decision SHALL be `ADMIT`,
bind its exact attempt and contain no reason. Only then SHALL 092 call the existing
061 admission function.

#### Scenario: brochure is partial

- **WHEN** the brochure decision is not `ADMIT` or any final decision is incomplete
- **THEN** the result is blocked and exposes no brochure or sibling receipt

### Requirement: RAI4 atomic READY output

The only success status SHALL be `READY_FOR_QUALITY_FALSIFICATION`, copied from an
exact existing-061 READY result. The immutable result SHALL bind the 083 bundle,
three 052 bindings, both 086 bindings, three 060 receipt identities and the 061
receipt digest. Any failure SHALL return an empty receipt tuple and no admission.
All paths SHALL report `provider_calls=0` and `golden_reads=0`.

#### Scenario: 061 replay is not READY

- **WHEN** existing 061 rejects any relation-bound receipt or replay identity
- **THEN** 092 returns typed blocked with zero bundle and zero partial output

### Requirement: RAI5 deterministic synthetic seam and future rebase

Before 090 is frozen, the focused suite SHALL use an independent minimal Protocol
fixture. It SHALL prove the exact real-060 callable shape, both relation kinds,
table continuation symmetry, section block refs and existing-061 replay. The
fixture SHALL NOT be exported as production authority. The real 090 candidate
must replace it without changing 092 semantics or paths.

#### Scenario: 090 changes its replay contract

- **WHEN** the real builder cannot reproduce the exact receipt consumed by 061
- **THEN** integration remains blocked; the adapter SHALL NOT construct READY itself

### Requirement: RAI6 bounded pure-domain delivery

092 SHALL perform no Provider/model/Golden/filesystem/environment/DB/WeKnora call
and SHALL not modify upstream DTOs or builders. Failure tests SHALL prove
`provider_calls=0` and `golden_reads=0` for role/profile/parser/attempt/marker/
binding/090 replay drift.

#### Scenario: integration needs a wider platform

- **WHEN** implementation requires an eighth 092 path or upstream mutation
- **THEN** development stops rather than creating another authority or framework

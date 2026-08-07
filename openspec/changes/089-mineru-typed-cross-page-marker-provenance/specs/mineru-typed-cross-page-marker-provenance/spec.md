# MinerU typed cross-page marker provenance specification

## ADDED Requirements

### Requirement: MMP1 062 v1 remains byte-compatible

089 SHALL NOT add fields to or change the semantic preimage of
`mineru-native-cross-page-facts.v1`. Existing marker observation hashes, status,
relation count and projection digest SHALL retain their prior meaning.

#### Scenario: companion evidence is produced

- **WHEN** exact MinerU marker provenance is projected
- **THEN** the existing 062 v1 JSON contains no companion fields and its semantic hash is unchanged

### Requirement: MMP2 exact native marker provenance

The companion SHALL bind exact source SHA, parser model, MinerU `3.4.4`, raw ZIP
SHA, unique native member SHA, marker kind (`cross_page` or `lines_deleted`),
zero-based page index, node type, local structural index, a domain-separated
structural-path hash and deterministic item/envelope replay digests.

#### Scenario: the two native marker kinds share one structural node

- **WHEN** one exact node contains both accepted true markers
- **THEN** two distinct typed marker items are emitted and their item digests do not collide

### Requirement: MMP3 exact raw replay, not caller authority

Replay SHALL recompute the companion from the exact raw ZIP bytes and source
identity. Any changed kind, node type, page, path hash, local index, member hash,
raw ZIP hash, source, parser/version identity, item hash, envelope hash,
duplicate identity or unknown marker kind SHALL fail closed.

#### Scenario: caller rebuilds a plausible companion

- **WHEN** any bound field or marker membership differs from the raw native artifact
- **THEN** replay returns the fixed typed invalid error and no replacement evidence

### Requirement: MMP4 privacy-safe non-relation evidence

The companion SHALL contain no content, Markdown, HTML, bbox, raw structural
path, member name, local path, vendor URL, secret or unknown native value. It
SHALL contain no source/target endpoint and no relation or ADMIT claim.

#### Scenario: marker node contains private presentation fields

- **WHEN** a valid marker node also contains body, bbox, URL or unknown fields
- **THEN** those values do not enter marker evidence, errors or replay digests

### Requirement: MMP5 bounded same-domain delivery

089 SHALL change only the existing 062 projector, one new focused test, the
OpenSpec089 documents and registry row. It SHALL perform no provider/model,
Golden, DB, WeKnora, live or full operation and SHALL not modify 083/084/086/090.

#### Scenario: endpoint derivation is requested

- **WHEN** implementation would need to manufacture a source/target endpoint or relation
- **THEN** 089 stops rather than expanding scope

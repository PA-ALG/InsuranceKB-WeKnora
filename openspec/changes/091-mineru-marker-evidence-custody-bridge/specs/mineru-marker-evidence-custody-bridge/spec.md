# MinerU marker evidence custody bridge specification

## ADDED Requirements

### Requirement: MEC1 same-read native authority

For exact 596-1 terms and rate capture, the Go reader SHALL construct the 062
facts and 089 marker companion from the same bounded ZIP bytes and unique native
middle member. Their source, parser model, MinerU version, raw ZIP SHA and native
member SHA SHALL match. Brochure SHALL carry neither envelope.

#### Scenario: facts and marker evidence come from different native inputs

- **WHEN** either envelope is missing or any shared identity differs
- **THEN** capture fails closed with zero final custody artifact

### Requirement: MEC2 immutable capture binding

The private Go custody JSON SHALL carry the unchanged 062 facts beside the 089
companion. The capture identity SHALL bind the 062 projection SHA and 089 replay
digest in addition to the existing source/attempt/parser/structure/content
identity. The companion SHALL remain versioned and SHALL not mutate the 062 v1
preimage.

#### Scenario: a stored envelope is deleted or replaced

- **WHEN** its projection/replay digest no longer matches the same capture identity
- **THEN** the artifact is rejected rather than silently downgraded

### Requirement: MEC3 closed Python replay and exposure

The 083 bytes-only intake SHALL parse marker evidence with `extra=forbid`, validate
the exact allowed kinds, non-negative page/local indexes, safe node type, item
order and uniqueness, and independently recompute structural item and replay
digests using the Go contract. It SHALL expose the immutable typed companion to
086 without creating endpoint, relation or ADMIT authority.

#### Scenario: marker evidence is locally self-rehashed but differs from native custody

- **WHEN** kind, page, path hash, member, source, parser/version, item membership or
  replay digest differs from the facts/capture binding
- **THEN** intake raises one fixed non-echoing typed reason and returns no bundle

### Requirement: MEC4 bundle digest includes marker custody

Terms and rate intake digests SHALL include both the 062 facts digest and 089
marker companion digest. The exact ordered three-source bundle digest SHALL bind
the resulting per-source intake digests. Cross-page and lines-deleted markers on
the same node SHALL remain distinct.

#### Scenario: one marker kind is relabelled while all other fields stay fixed

- **WHEN** the relabelled artifact is presented to intake
- **THEN** marker replay and bundle construction fail closed

### Requirement: MEC5 version and privacy closure

The intake SHALL fail closed for old terms/rate artifacts without the required
marker companion, duplicate or unknown markers, and extra fields. Brochure SHALL
explicitly retain the no-marker compatibility rule. Public marker DTOs and
errors SHALL not contain body, HTML/Markdown, bbox inference, local path, vendor
URL or secret.

#### Scenario: an old terms artifact is supplied

- **WHEN** the legacy v2 capture lacks `cross_page_marker_provenance`
- **THEN** intake returns a fixed marker-envelope error before constructing a bundle

### Requirement: MEC6 bounded non-authoritative delivery

091 SHALL change only Go capture/cross-page same-domain code, 083 intake
same-domain code, focused tests, this OpenSpec and registry. It SHALL perform no
provider/model, Golden, DB, WeKnora, live or full operation and SHALL not modify
086/084/087/090.

#### Scenario: a downstream endpoint or relation is requested

- **WHEN** the bridge would need to invent semantic endpoints or relation authority
- **THEN** implementation stops instead of expanding scope

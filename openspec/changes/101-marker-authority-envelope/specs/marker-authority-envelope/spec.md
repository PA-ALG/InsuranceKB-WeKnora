# Marker authority envelope specification

## ADDED Requirements

### Requirement: MAE1 exact private snapshot input

The exporter SHALL accept exactly terms, brochure and rate custody paths in that
order. Each file SHALL be a regular no-follow file with exact mode `0600` under
one regular no-follow mode-`0700` directory. It SHALL read each open descriptor
once, reject path replacement or mutation across that read, require canonical
single-JSON-plus-LF bytes, and pass the exact bytes to the real 083 validator.

#### Scenario: one artifact changes during the read

- **WHEN** descriptor or path identity, size, time metadata or bytes drift
- **THEN** export returns one fixed typed block and no envelope

### Requirement: MAE2 immutable public marker authority

For exact 091 terms and rate marker custody, the exporter SHALL emit an immutable
`MarkerAuthorityEnvelopeV1`. It SHALL bind product/source order, capture/parser/
version/config facts, raw ZIP and native-member content digests, artifact/intake/
replay digests and every marker's kind, page, node type and local index. Brochure
SHALL remain bound by the three-source bundle but SHALL emit no marker source.

#### Scenario: current custody has one endpoint marker

- **WHEN** the private 091 input is valid with one terms or rate marker
- **THEN** export succeeds with that marker and relation authority `UNBOUND`

### Requirement: MAE3 canonical preimages and replay

Every authority digest created or forwarded by the envelope SHALL be accompanied
by its typed canonical preimage or a typed private-byte leaf descriptor. The
exporter SHALL independently reconstruct each marker structural path from the
same sanitized native snapshot, recheck the Go path hash, marker preimage and 091
replay digest, and expose a canonical node-identity preimage. Consumers SHALL be
able to recompute the source and whole-envelope hashes without raw vendor objects.

#### Scenario: marker and structure are self-consistently moved

- **WHEN** source, member, path, node, marker or replay identity differs
- **THEN** export fails before returning any authority

### Requirement: MAE4 relation authority remains unbound

The envelope SHALL set source/target relation authority to `UNBOUND`. 101 SHALL
not select an endpoint, pair a target, infer adjacency, interpret Markdown/table
text or upgrade 098/099 readiness.

#### Scenario: future fixture contains multiple markers

- **WHEN** all marker provenance is valid but no verified relation exists
- **THEN** all markers are exported in canonical order and relation authority
  remains `UNBOUND`

### Requirement: MAE5 privacy and zero external effects

Public DTOs and typed errors SHALL contain no body, table text, secret, URL,
absolute path or raw vendor object. All failures SHALL produce zero output. The
implementation SHALL return only an in-memory frozen DTO and SHALL expose no file
publication path, so no partial or replaceable namespace artifact exists. It SHALL
perform zero capture, provider/model, Golden, DB/PG, WeKnora, live or full
operation.

#### Scenario: private material is present in an invalid artifact

- **WHEN** validation fails on that artifact
- **THEN** only a fixed reason code escapes and no private value is echoed

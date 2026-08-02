# MinerU semantic content custody specification

## ADDED Requirements

### Requirement: MSC1 same-read semantic custody

The task-local capture SHALL call the configured MinerU reader exactly once and SHALL construct one
artifact from that same `ReadResult.NativeStructure` and `ReadResult.MarkdownContent`. It SHALL NOT
make a second provider call or reconstruct text from sanitized structure.

The JSON contract SHALL be `mineru-semantic-content-custody.v2` and SHALL bind `source_sha256`, one
parser/model/config identity, `raw_structure_sha256`, `sanitized_structure_sha256`,
`sanitized_structure`, `content_snapshot_sha256`, and `content_snapshot`. The request and artifact
SHALL additionally bind the approved 596-1 parse identity `attempt_number=2`,
`attempt_role=bounded_upgrade`, and integer `generation=0`. A deterministic
`capture_identity_sha256` SHALL cover that attempt identity together with the exact source,
parser-config, raw-structure, sanitized-structure, and content-snapshot hashes. Missing or mutated
attempt identity SHALL fail before reader construction.

#### Scenario: same-read result is admitted

- **WHEN** one read returns a valid native artifact and non-empty text
- **THEN** the private artifact contains the exact text and its recomputed SHA-256 alongside the
  exact native structure identities and approved attempt/generation identity, its capture identity
  hash recomputes exactly, and reader invocation count is one

### Requirement: MSC2 fail-closed identity and privacy

Capture SHALL fail before final publication when text is empty, source/parser/artifact identity
drifts, a structure or content hash is invalid, or the artifact would expose a credential or local
absolute path. Typed errors, stdout, ordinary logs, and validation reports SHALL NOT contain body,
credential, source path, or API URL data. The task-local detector SHALL reject absolute POSIX paths
including `/home`, `/var`, and `/Volumes`, Windows drive paths using either separator, and UNC paths
using either separator in both semantic text and sanitized structure. It SHALL NOT classify an
ordinary spaced slash or an HTTP(S) URL as a local absolute path. Sanitized structure SHALL be
checked recursively over decoded JSON string values; scanning JSON-encoded bytes alone SHALL NOT
be accepted because escaping can conceal UNC separators.

#### Scenario: invalid same-read result

- **WHEN** the read result has empty text, a mismatched source/native hash, or text containing the
  in-memory secret or a cross-platform absolute path
- **THEN** capture returns a stable typed error, performs no retry, and publishes no final artifact

### Requirement: MSC3 private atomic no-replace artifact

The combined JSON SHALL be written only beneath the caller's new direct `/private/tmp` output root,
with directory mode `0700` and file mode `0600`, using the existing same-directory atomic
no-replace publication boundary. Existing output SHALL remain unchanged and failures SHALL expose
no partial final file.

#### Scenario: final already exists

- **WHEN** another actor creates the final path before publication
- **THEN** publication fails, preserves the existing bytes, and removes only its private temp file

### Requirement: MSC4 exact three-source 596-1 runner

Before any capture, the runner SHALL verify regular-file bytes for the frozen terms, brochure, and
rate PDFs and their approved SHA-256 identities, a non-empty process-environment credential, and a
nonexistent direct `/private/tmp` output root. It SHALL then invoke capture sequentially exactly
once for terms, brochure, and rate, with no retry, fallback, parallelism, or fourth file.

#### Scenario: source or capture failure

- **WHEN** any preflight identity is missing or drifts
- **THEN** provider invocation count is zero and no output root is created
- **WHEN** one capture fails after earlier captures succeeded
- **THEN** later invocations are zero, earlier private artifacts remain, and the runner returns a
  typed partial failure without leaking provider detail

### Requirement: MSC5 bounded delivery

068 SHALL modify exactly eight capture/runner/OpenSpec paths. It SHALL NOT modify README, a public
DTO, parser behavior, 061/065/067, Golden, DB, WeKnora, provider configuration, or admission. Real
provider/live/PG/full execution remains NOT RUN.

#### Scenario: implementation requires wider scope

- **WHEN** GREEN requires a ninth path or public/runtime platform change
- **THEN** work stops instead of expanding the Mission

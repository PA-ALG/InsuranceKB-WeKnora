# MinerU exact two-source capture runner specification

## ADDED Requirements

### Requirement: M2CR1 exact preflight before provider invocation

The runner SHALL bind the exact repository-relative terms/rate paths and SHA-256 values, verify
both regular-file byte identities, require a non-empty process-environment `MINERU_API_KEY`, and
require the caller output root to be one nonexistent direct child of `/private/tmp`. Every
preflight check SHALL finish before creating the output root or invoking capture.

#### Scenario: preflight drifts

- **WHEN** either source is missing/mutated, the credential is absent, or output already exists
- **THEN** capture invocation count is zero and no runner output root is created

### Requirement: M2CR2 fixed exactly-once sequence

After preflight, the runner SHALL create the output root with mode0700 and invoke the existing
`docparser.CaptureMinerUNativeStructure` exactly once for terms, then exactly once for rate,
using pipeline parser overrides and distinct fixed child directories. It SHALL NOT invoke
brochure/third inputs, retry, fallback or run captures concurrently.

#### Scenario: first or second capture fails

- **WHEN** terms fails
- **THEN** rate invocation count is zero
- **WHEN** rate fails after terms succeeds
- **THEN** the terms evidence remains intact and the runner returns typed partial failure

### Requirement: M2CR3 secret-safe bounded output

The runner SHALL expose no credential CLI/flag/input field. Successful stdout SHALL contain
only a fixed status, masked role, relative artifact name and artifact byte SHA-256. Errors SHALL
be typed and SHALL NOT include the secret, API base, source/output absolute paths or body bytes.

#### Scenario: deterministic fake run

- **WHEN** deterministic fake captures return two valid evidence files
- **THEN** stdout records terms then rate with stable relative names and file hashes, and contains
  no source bytes, full path or credential

### Requirement: M2CR4 bounded delivery

063 SHALL change exactly seven bounded documentation/command/test paths and SHALL not modify the
existing capture library, 061, 062, DB, migration, provider/runtime configuration or admission.
Real provider capture remains NOT RUN.

#### Scenario: implementation needs a wider surface

- **WHEN** GREEN requires an eighth path or an existing capture-library change
- **THEN** work stops instead of expanding the change

# MinerU Capture Typed Failure Specification

## ADDED Requirements

### Requirement: MTF1 closed, stage-proven failure reasons

The capture path SHALL expose stable `errors.Is` sentinels for
`ALLOCATION_FAILED`, `UPLOAD_FAILED`, `STATUS_FAILED`, `PROVIDER_TASK_FAILED`,
`STATUS_BUDGET_EXCEEDED`, `DOWNLOAD_URL_INVALID`, `ZIP_DOWNLOAD_FAILED`,
`NATIVE_STRUCTURE_UNAVAILABLE`, `CROSS_PAGE_PROJECTION_INVALID`,
`ARTIFACT_CUSTODY_INVALID` and `CONTENT_CUSTODY_INVALID`. A stage SHALL be assigned
only at a boundary that mechanically proves it. An unrecognized injected or future
failure SHALL become `CAPTURE_STAGE_UNDETERMINED` rather than a guessed stage.

#### Scenario: the provider task reports failure with a sensitive message

- **WHEN** capture receives a terminal failed state containing arbitrary provider text
- **THEN** `errors.Is` identifies `PROVIDER_TASK_FAILED` and no provider text escapes

### Requirement: MTF2 privacy-safe propagation and zero final artifact

The converter SHALL NOT attach a response body, provider `Msg`/`ErrMsg`, URL, raw
transport error, credential, document content or local path to a capture-policy
sentinel. Artifact capture SHALL preserve recognized sentinels, distinguish structure
and content custody failures, and emit no final artifact for any failure.

#### Scenario: ZIP download returns a body containing secrets and a signed URL

- **WHEN** the capture-policy ZIP stage fails
- **THEN** the returned error matches `ZIP_DOWNLOAD_FAILED`, contains none of those
  values, and the output directory contains no final artifact

### Requirement: MTF3 fixed runner prefix and reason code

The exact 596-1 runner SHALL stop at the first failed source. Its terminal error SHALL
contain only the fixed terms or partial prefix plus one fixed reason code. It SHALL
not contain a wrapped raw error. `LOG_FORMAT`, including the literal value `json`,
SHALL NOT change that terminal reason.

#### Scenario: the second source fails allocation under literal JSON log format

- **WHEN** terms has completed and brochure returns an allocation failure sentinel
- **THEN** the runner returns the fixed partial prefix plus `ALLOCATION_FAILED`, starts
  no rate capture and leaks no raw detail

### Requirement: MTF4 provider behavior remains unchanged

The change SHALL NOT alter allocation/upload/status/ZIP call order, capture timeout,
three-second poll interval, exact 190-poll budget, redirect limit, fail-fast transport
policy, retry/fallback behavior or ordinary-reader behavior. All 082 tests SHALL use
fake transports or existing seams and execute zero provider calls.

#### Scenario: capture status transport fails

- **WHEN** the first status request fails in capture policy
- **THEN** `STATUS_FAILED` is returned after exactly one status call and no retry,
  whereas the ordinary reader retains its existing retry behavior

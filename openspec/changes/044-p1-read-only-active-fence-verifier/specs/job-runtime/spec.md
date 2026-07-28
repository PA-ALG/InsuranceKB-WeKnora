# 044 P1 Read-only Active Fence Verifier Delta

## ADDED Requirements

### Requirement: P1.13 read-only active-fence verification

P1 SHALL expose one public read-only active-fence verifier. Given expected
`space_id`, `job_id`, `lease_generation`, and `attempt`, the verifier SHALL
read the current `wiki_jobs` row and database clock and succeed only when:

1. the row exists in the declared Space;
2. its current generation equals the expected generation;
3. its current state is `running`;
4. its current attempt equals the expected attempt;
5. its lease is present and strictly later than the database current time.

On success the verifier SHALL return the current immutable `JobSnapshot`.
Success SHALL NOT renew the lease, advance state, alter timestamps, append an
Outbox event, or write any other persistent row.

Every rejection SHALL be typed using the existing P1 error families and SHALL
leave job and Outbox rows unchanged. Missing/cross-Space jobs fail closed;
stale generation, non-running state, attempt mismatch, and expired/reclaimed
lease SHALL all reject before a caller performs external I/O.

The verifier SHALL complete its bounded database transaction before returning.
It SHALL NOT hold a transaction or row lock across provider transport.

#### Scenario: current running fence succeeds without renewal

- **GIVEN** a job is `running` with generation `g`, attempt `a`, and an
  unexpired lease
- **WHEN** the verifier is called with the exact Space/job/`g`/`a`
- **THEN** it returns the current `JobSnapshot`
- **AND** the job row, lease expiry, Outbox rows, and all timestamps are
  unchanged

#### Scenario: stale facts reject with zero writes

- **WHEN** the declared Space/job is absent or cross-Space, generation is
  stale, state is not `running`, attempt differs, or the lease is expired or
  has been reclaimed
- **THEN** the verifier raises an existing typed P1 error
- **AND** all job and Outbox rows remain unchanged

#### Scenario: verification and reclaim do not admit a stale worker

- **GIVEN** a running lease reaches expiry while verification and reclaim race
- **WHEN** both transactions complete
- **THEN** verification either linearizes before reclaim and proves the still
  active pre-reclaim fence, or observes the expired/reclaimed fence and rejects
- **AND** it never returns success for a reclaimed generation

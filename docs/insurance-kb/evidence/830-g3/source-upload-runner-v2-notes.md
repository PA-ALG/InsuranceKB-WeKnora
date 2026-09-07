# G3 source upload runner review 2

Status: `FROZEN_PENDING_INDEPENDENT_REVIEW`.

This private review candidate implements the bounded first repair in
`source-upload-runner-repair-1.md` (SHA-256
`3f3a8457ce1f4a15d7bd2cffb473053e164996a824452403dcff9bf74290cbbb`). It was
derived from the frozen v1 runner identified by SHA-256
`9873ea8bd0cab1148354242e20d65145cd96800a735944d262b614a7d5977ce3`.
The repository v1, provisioning v3, embedding guard, and product code were not
modified.

## Implemented repair boundary

1. Authorization requires three exact action scopes: 11 uploads, 11 external
   embedding sends bound to the frozen manifest, and 15 source backfills in the
   order new 11 then old 01-04. Counts and a timezone-bearing `approved_at` are
   exact; extra authorization keys are rejected.
2. Runtime commands accept only the fixed Colima Docker entry. The live gate
   binds the app port, files and docreader volumes with exact access modes,
   relevant storage/docreader environment, and an identical nonempty app/Redis
   password without recording the password.
3. Old 01/03/04 backfill source IDs are checked immediately after their POST and
   before a PASS checkpoint or the next POST. Old 02 accepts only the strictly
   bound actual response. The final 15-item source map check remains.
4. The upload executor reserves all four old knowledge IDs before the first new
   upload, rejects old or repeated response IDs, and registers a new ID before
   returning it. Completion, revision descriptor, and chunk reads bind the
   requested knowledge, tenant, raw knowledge base, file, and parse attempt.
5. The guard ledger must have the exact contract, upstream, manifest SHA,
   maximum 11 attempts, `stopped=false`, and an attempts list. An empty exact
   ledger is checked after guard start and before egress creation.
6. Old inputs are pinned by the fixed `existing-chunk-capture.json` SHA
   `3b14ef391cad1a215a8012acbfb385b0093425aef60c116eebbd0a0a81b54924`.
   The loader checks the PASS contract, exact four identities and capture paths,
   regular-file status, and capture byte hashes before accepting descriptors.
7. A 1440-second monotonic deadline is anchored before guard launch. All new-11
   HTTP calls, polls, sleeps, ledger reads, and final external ledger copy are
   bounded by its remaining time. The 1800-second guard lifetime is unchanged,
   leaving at least 360 seconds for teardown. Old-four backfill runs only after
   guard and egress closure and is outside the external deadline.

## TDD and local checks

- RED: `/private/tmp/g3-source-upload-runner-repair1-red.log` records the new
  expectations failing against the inherited v1 behavior. It contains the
  initial nine-case repair RED plus later focused behavior REDs for strict
  authorization/deadline anchoring, docreader/ledger ordering, and chunk scope.
- Rejected intermediate GREEN attempts are retained as
  `/private/tmp/g3-source-upload-runner-repair1-green.log` and
  `/private/tmp/g3-source-upload-runner-repair1-green-final.log`; neither is the
  acceptance result.
- Final GREEN: `/private/tmp/g3-source-upload-runner-repair1-green-final2.log`,
  33 fake-only tests passed.
- Static parse: `/private/tmp/g3-source-upload-runner-repair1-static.log`, both
  Python files parsed successfully.

No real HTTP, Docker, database, provider, upload, container, or network action
was performed. No authorization artifact was created. Any future execution still
requires the exact 11-upload, 11-external-send, and 15-backfill approval and an
independent review of this frozen candidate.

The saved read-only network observation for the existing G2 app reports that
DashScope resolved to `198.18.0.105` while an official-SNI, default-trust TLS 1.3
handshake passed. That observation did not send HTTP or material and does not
establish that a future G3 target or provider request will succeed; the address
classification alone is not treated as a failure.

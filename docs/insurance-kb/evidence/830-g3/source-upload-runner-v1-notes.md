# G3 source upload runner review notes

Status: `DRAFT_REVIEW / NOT RUN`. This draft has only been imported, compiled,
and exercised with local fakes. It has not opened the API, Docker/Colima, a
database, the guard listener, or any provider connection; it has not uploaded a
file or changed a container/network.

## Frozen scope

The runner is a single target, one-shot executor for tenant `10003`, RAW KB
`b1f1764c-443d-46b8-98e3-d5aa5e55eb42`, the fixed G3 APP/docreader/Redis
containers and the 11 ordered materials `07,08,09,11,12,13,14,17,18,19,21`.
It loads the complete upload `process_config` from the frozen offline plan and
requires its value to equal the hard contract before doing any environment
work. It recomputes each PDF SHA-256, size and MD5 and checks every frozen
embedding request byte/hash. The fixed transport manifest SHA-256 is
`75b40ece28a4219965a6a86be616bb90f17af53252afad6c2243dedb9e377225`.

The POST sends the complete configuration, including
`enable_parent_child=false`. The readback check uses the exact Go DTO encoding:
`ChunkingConfig.EnableParentChild` has `omitempty`, so this one false member is
absent in persisted `metadata.process_overrides`; every other member is compared
to the expected persisted object. The W1 parser identity independently proves
2048/80, the exact separator and chunker digests, builtin parser and the fixed
embedding model.

## Required review and authorization before execution

Execution requires all of the following, none of which this preparation creates:

1. A successful, frozen `830-g3-source-runtime-provision-apply.v1` receipt.
2. A new regular-file `830-g3-source-upload-authorization.v1` receipt with
   `decision=APPROVED`, the exact runner and provision-receipt SHA-256 values,
   the exact manifest, tenant, KB and ordered 11 material IDs, and exactly the
   actions `upload`, `embedding-external-send`, and `source-backfill`.
3. Private single-line email/password files for a human tenant-10003 Admin.
   Their content is held in memory and never written to receipts or response
   artifacts. Login and `/auth/me` must agree on user, active tenant and Admin
   membership. The login POST is the authentication prerequisite; “first POST”
   in the upload gate means the first mutating upload/backfill POST.
4. New, non-existing receipt and artifact paths. O_EXCL prevents resume/reuse.

After approval, the intended command shape is:

```text
python3 /private/tmp/g3-source-upload-runner.py run \
  --authorization <private-authorization.json> \
  --provision-receipt <frozen-provision-pass.json> \
  --receipt <new-private-receipt.json> \
  --artifact-dir <new-private-artifact-directory> \
  --email-file <private-email-file> \
  --password-file <private-password-file> \
  --docker-command-json '["colima","ssh","--profile","default","--","sudo","docker"]'
```

This command is documentation only. Root must use the already reviewed local
transport and current authorization decision rather than copying it blindly.

## One-shot behavior

Before guard staging or egress creation, the runner rechecks the provision PASS,
container names/images/running state, exact internal-network-only membership,
target DB/Redis/batch environment, target Python stdlib/CA, live KB controls,
live model guard base URL, and an exact list of the four cloned knowledge rows.
The list rejects collisions against all 11 new files by MD5, SHA-256, or the
filename-and-size pair; a later 409 is a hard failure and is never treated as a
read-only duplicate check.

It copies only the guard, manifest and 11 request bodies into a new private APP
directory and verifies 13 regular-file hashes. It starts the guard with a fresh
O_EXCL ledger, verifies an empty loopback listener, then attaches only APP to a
new ordinary bridge. This bridge is recorded as transport isolation and is not
described as an endpoint firewall.

Each mutating API POST is durably marked STARTED before its only send. Any
transport exception is `RESULT_UNKNOWN`; HTTP non-200, duplicate, parse failure,
deadline, guard stop or ledger mismatch stops the sequence. Materials are
strictly serial. After each successful upload it waits for completion, requires
exact metadata readback, validates the guard ledger prefix, reads descriptor,
all chunks and descriptor again, recomputes `weknora.chunk_manifest.v1`, then
uses the human-Admin single-revision backfill route and validates its receipt.

After all 11 provider attempts are exact HTTP 200, the ledger is durably copied,
guard is stopped and the dedicated egress network is removed before old-source
work continues. The runner then double-reads/recomputes the frozen W1 revisions
for old 01--04 and calls the same backfill route. Existing source IDs for 01, 03
and 04 must stay exact; 02 receives only its actual G3 source ID. Success reports
11 uploads/provider attempts and 15 W1/source receipts.

On any failure it first tries to copy the guard ledger, then independently tries
guard stop, egress disconnect/removal, APP stop and docreader stop. It inspects
both processes after attempting both stops. Any unverifiable action yields
`STOP_INCOMPLETE`. It never deletes partial DB/volume state and has no retry or
resume path. Redis is neither cleared nor stopped.

## Deliberate source-boundary gap

The public single-revision backfill response does not expose `resource_id`, and
there is no human read-only source-row route in the current router. This runner
therefore cannot close a later C `LiveRevisionSourceReceiptV1` by HTTP alone. It
does not invent `resource_id`, `evidence_parse_attempt_id`,
`parsed_document_sha256`, or `parse_manifest_sha256`; it does not claim C input
closure. A separately reviewed target source-row readback stage is required if
those fields are needed. Old 03/04 also lack admitted parse/live receipts, and
old 02's new G3 source ID cannot reuse the G2 C5 identity.

## Fake-only verification

The test suite covers frozen bytes and 11 unique sources, exact cloned-four
preflight, MD5 conflict rejection, complete process-config upload and Go DTO
readback, human Admin identity, authorization mismatch, durable STARTED failure,
single-send 409/transport behavior, provider non-200 stop, descriptor double
read, manifest/parser checks, frozen legacy descriptors, source seals/old source
IDs, exact 13-file staging, no-op pre-stage teardown, all-process stop order,
preexisting egress rejection, and STOP_INCOMPLETE.

The original behavioral RED log is
`/private/tmp/g3-source-upload-runner-red.log`. The final first-freeze logs are
`/private/tmp/g3-source-upload-runner-green-final2.log` and
`/private/tmp/g3-source-upload-runner-static-final2.log`; their checks bind the
first-freeze runner and tests reported with these notes.

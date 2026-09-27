# G3 source runtime provision/config draft notes

Status: **DRAFT_ONLY / NOT_EXECUTED**.  The paired Python file is a reviewable
bounded run plan.  Root remains the only future executor.  `apply` must not be
used until independent review has passed and a current authorization receipt
has been written for the exact preflight receipt.

Mechanical constant audit: the current draft takes the full AES and config
digests directly from `runtime-readonly-extra.json`.  An earlier historical
draft incorrectly expanded abbreviated digest prefixes from working notes;
that draft is rejected and must not be executed.  Source rows, file references,
file sizes/digests, and app/DocReader/Redis image IDs were also compared by a
local JSON-to-Python-constant check rather than by visual transcription.

## Two-phase interface

1. `preflight --output <new-private-json>` is read-only with respect to Docker,
   PostgreSQL, Redis and the app.  It verifies the four frozen evidence files,
   exact local image IDs, source app/DB/AES identity, target absence, source
   idle state, the three frozen SourceRevision rows, the four knowledge file
   references, and the four physical PDF byte hashes.  It also records a
   content manifest of the current `/app/config` tree and a sanitized
   DocReader environment.  Its only write is the new mode-0600 local receipt.
2. `apply --preflight ... --authorization ... --private-auth ... --receipt
   <new-private-json>` rejects any existing apply receipt.  It persists
   `STARTED` with `O_EXCL` before the first mutation, checkpoints each completed
   step with file and directory `fsync`, and changes to `STOPPED` on the first
   failure.  It performs no automatic rollback, resume or retry.  All partial
   containers, volumes, DB state and the receipt remain for inspection.

The draft authorization receipt contract is:

```json
{
  "contract": "830-g3-source-runtime-provision-authorization.v1",
  "status": "APPROVED",
  "plan_sha256": "a5ebeb07fe01b5e2dfdef9cb2f830eefb4bf9ab66d454de052731f6b7fde9961",
  "preflight_sha256": "<sha256 of the exact preflight receipt>",
  "authorized_actions": ["provision", "configure"],
  "approved_at": "<UTC timestamp>"
}
```

This is a draft gate for review; root should align its final provenance fields
with the actual authorization record without weakening the exact plan and
preflight bindings.

## One-shot apply sequence

- Recheck source app/docreader image identity, source AES digest, source DB
  identity and idle/source snapshots; recheck target DB, objects and port are
  still absent.
- Capture one PostgreSQL custom-format dump with
  `--serializable-deferrable --no-owner --no-acl`, create the target database
  from `template0`, and restore with `--single-transaction --exit-on-error`.
  Dump bytes remain in memory only; the receipt records size/SHA only.
- Before any G3 app start, update only the cloned target KB row: clear
  `summary_model_id` and set question generation to disabled/count zero.  The
  update has exact tenant/KB/old-value predicates.  Readback compares every
  other field except `updated_at` and rechecks the target has no active work.
- Create one `--internal` network and only the dedicated files and DocReader
  temporary volumes.  Attach the existing PostgreSQL container to that network
  under a G3-only alias.  Create a dedicated Redis container on the internal
  network with no published port and DB0.
- Copy only the four frozen `/data/files/<relative-path>` objects from the
  running source app into the G3 files volume.  The helper has `--network none`;
  every target object is checked for exact size and SHA before the helper is
  removed.  The existing empty `content_hash` on resource
  `8af0b514-...` is preserved in the cloned DB; the provisioner does not
  fabricate or backfill it.
- Create all three target containers with `--pull=never` and pinned local image
  digests.  Because G2 `config.yaml` was copied into the source container after
  image creation, re-read the full source `/app/config` tar into memory, require
   its file manifest to equal preflight, and archive-copy those exact bytes into
  the still-stopped G3 app while preserving mode/owner.  Read the stopped G3
   tree back and require byte-for-byte manifest equality, including the frozen
  `config.yaml` SHA.  The source writable layer is never mounted or modified.
- Start Redis, DocReader and app only on the internal network; publish only
  `127.0.0.1:18294:8080`.  A bounded local health poll is the only repeated
  read.  Each mutating DB/API operation is issued once.
- Use a fresh local human login from a private mode-0600 file containing exactly
  `email` and `password`.  Build the KB PUT from the full GET fields and change
  only `wiki_enabled=false`, `graph_enabled=false`, `token_limit=0`, and
  `languages=[]`.  Build the embedding-model PUT from the full non-secret GET
  parameters and change only `base_url` to
  `http://127.0.0.1:19030/compatible-mode/v1`.  The request builder recursively
  rejects credential field names; the handler also preserves stored API key
  and app secret through its credentials subresource boundary.
  Because both zero-value fields use Go `omitempty`, the post-update GET may
  omit `token_limit` and `languages`; readback treats only those two missing
  keys as their defined 0/empty-list values and still rejects nonzero/nonempty
  values.
- Recheck the target three SourceRevision identities, all four file references,
  target idle state, and the unchanged source DB snapshot.

## `/run/c5` decision

The G2 `/run/c5` volume is a closed 15-member **G2 serving preview authority**.
It is not needed by upload or SourceRevision backfill.  The G3 source-only app
therefore does not copy or mount it and does not set
`WEKNORA_SCHEMA_WIKI_C5_INPUT_MANIFEST`; repository construction yields the
supported empty registry.  Copying that bundle would mix G2 serving authority
into the G3 source runtime, while copying only part of it would fail its closed
membership/hash contract.  This also ensures no G2 volume is ever mounted RW.

The app explicitly enables the existing SourceRevision backfill path with
`KNOWLEDGE_REVISION_SOURCE_BACKFILL_ENABLED=true`.  The default 128 MiB object
limit already exceeds the largest frozen PDF (about 1.3 MiB), so the draft does
not override `KNOWLEDGE_REVISION_SOURCE_MAX_OBJECT_BYTES`.  Future backfill must
use a human Admin session plus exact KB write authorization; this provisioner
does not call backfill.

## Secret and network boundary

`SYSTEM_AES_KEY` and the shared PostgreSQL role password are read into process
memory from the source app but never printed or written to receipts.  A fresh
JWT secret and dedicated Redis password are generated in memory.  For Colima,
private env files are sent on stdin to mode-0600 files under
`/run/g3-830-private`; only their SHA values reach the partial receipt.  Native
Docker apply is rejected because the draft has no equally closed remote-secret
staging mechanism.

No app or DocReader egress network is attached.  The script contains no guard
start, model/provider request, upload, build, pull, or eleven-PDF operation.
The configured embedding base URL is loopback and remains unreachable until a
separately authorized guard is later installed inside the app's network
namespace.

The preflight receipt also records the exact provisioner script SHA-256.  Apply
recomputes its own file digest and refuses to proceed unless it equals that
preflight value; the authorization's preflight SHA therefore binds the reviewed
script transitively.  Local API requests install an empty `ProxyHandler` and a
no-redirect handler, preventing system proxy settings from carrying the local
Bearer token away from `127.0.0.1:18294`.

## Review points before any execution

- Confirm the final authorization-receipt contract and exact evidence/plan SHA
  bindings.
- Review the shared PostgreSQL container network attachment as an intentional,
  retained partial mutation on failure.
- Confirm the source app image still exposes the expected shell, `tar`,
  `sha256sum`, and `stat`; preflight/apply fail closed if their readbacks drift.
- Confirm the private operator login is an Admin for tenant 10003 and the
  embedding model remains tenant-owned (`is_builtin=false`), because those are
  required for full GET-derived model configuration.
- Independently review the final script after root incorporates any changes.

No runtime mutation, DB clone, container start, provider traffic, upload, build,
pull, or guard start was performed while preparing these files.

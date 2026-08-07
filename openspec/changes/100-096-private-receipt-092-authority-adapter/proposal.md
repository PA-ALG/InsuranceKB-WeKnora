# 100 · 096 Private Receipt → 092 Authority Adapter

## Goal

Close the exact interface gap found by 095 without manufacturing authority: safely read
one private 096 relation receipt, replay the frozen 096/086 contract, rebuild the exact
091/083 bundle from its three custody byte payloads and independently bind supplied 092 source/profile authorities, obtain exact
terms/rate marker maps only from the frozen 098 public authority surface, and return the
inputs accepted by the public 092 admission API.

## Frozen stack

- authoritative base: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`;
- 092 candidate: `49efbd12084e8069c7a06364ac4835e0bb4e1e86`;
- 096 candidate: `11867ea8318119c5199fbbffc1f8ac9a38c4afee`;
- 098 stacked candidate: `168f1137cb3c4c039c648b62281ea3d09084cb45`.

098 currently exposes only a rate-table `MarkerEndpointPairInputV1` and does not expose
the exact two-map builder required by 092. The production adapter therefore remains
`DEPENDENCY_UNAVAILABLE` until that public authority exists. A synthetic exact builder
may prove composition but cannot claim MinerU, ADMIT or READY.

## Design

1. Open a relation-receipt file once with no-follow semantics. Require a regular `0600`
   file, bounded size, a stable pre/post inode snapshot and one bounded `pread`.
2. Reject duplicate keys, non-UTF-8, non-canonical JSON, extra fields and trailing bytes.
   Parse into the exact 096 DTO and call public `replay_relation_receipt_596_1`; 100 does
   not trust or reimplement its self-reported receipt/binding digests.
3. Feed the exact three capture payloads through public 083 intake; callers cannot submit a
   preconstructed bundle or bundle digest. Revalidate the exact 092
   `SourceAdmissionAuthorityV1` and `MaterialProfileResolution` tuples, then bind their
   product/source/parser/config/policy facts to the replayed receipt and bundle. Caller
   labels never create custody or source/profile authority.
4. Resolve one exact 098 public builder that returns the two public 092
   `TypedMarkerEndpointMapV1` objects. Missing signature, current incomplete evidence or
   any drift is typed fail-closed; 100 never derives endpoints from paths, adjacency,
   body text or Markdown.
5. Return a frozen context containing only the exact public 092 inputs. Its relation
   provider replays the selected 096 binding and verifies the bundle/document/manifest
   hashes on every call. `rate` remains a bundle role; only 092 maps it to `rate_table`.

## Alternatives rejected

- Editing 096 to absorb 092 orchestration: couples two frozen ownership domains.
- Reconstructing source/profile/marker authority from receipt fields: self-attestation.
- A generic receipt/signature/workflow platform: outside the MVP slice.

## Non-goals

No provider/model/Golden, capture, DB/PG, WeKnora, live/full run, ADMIT/READY, parser,
Markdown inference, endpoint heuristic, signature service or generalized receipt framework.

## Path budget

Seven 100-owned paths: registry, four OpenSpec documents, one task-local Python module and
one focused test. Frozen 092/096/098 paths remain byte-identical.

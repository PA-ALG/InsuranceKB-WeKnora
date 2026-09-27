# D Go strict wire presence repair, round 1

Status: DESIGN_PENDING_INDEPENDENT_REVIEW; NOT_DISPATCHED.

Consolidated report: lane-d-go-mirror-independent-review-01.json, SHA
f26245641a354047aa578dc16d528e4ac125250f7eb7cfc1c6019b330650959a; exactly2 BLOCKERs,0 BACKLOG.

This repairs existing D consolidated v2 section5 requirements. No accepted wire shape,
Python behavior, fixture, endpoint, authority or downstream acceptance criterion changes.

## Frozen original and reproduced failure

- Original Go source: d2d5f2efcb899ed0d18791cabdd435af6e72c0a4a32abd86de325a418b151a25.
- Original test: b669dbebae2a75c57e9fa4c7093600d3c91c0a581a6a6e4ad1e66f6b051a5833.
- Immutable original snapshots: d-go-review1-snapshots/manifest.json,
  SHA399d4fd3cc3d181454b89e2a96fdf2874503efe67ea86ef9b0b3c43cee32a493.
- Independent effective RED: removing the explicit-null actor_display_name field from
  request.profile_confirmation.receipt is accepted by Go with all original hashes, while
  Python rejects it. Log g3-d-go-independent-omitted-null-red-01.log,
  SHAbc5a7d115266602e11af011261711897cd4b984d97e1fe612db0f4700f0455ec.
- Four fully rehashed C semantic rejection vectors and all354 Python-to-Go snapshots are
  already independently PASS; preserve those results and rerun only as repair regression.

## Exclusive repair scope

Owner g3_catalog_impl, only internal/types/concept_free_wiki_830_g3.go and its existing
_test.go. No Python/C/common/G2 helper/fixture/service/handler/UI modification in this repair.
This is the first D Go independent-review repair round. Root freezes a consolidated finding
report and this plan before authorizing implementation. Any additional foundational finding
outside that report returns to root rather than being silently added.

## Required behavior

1. Check required JSON property presence and legal nullability before typed decoding can
   erase the distinction. A required nullable field must occur and may contain explicit null;
   omission is invalid. A nonnullable scalar, object, map or collection must reject null,
   including otherwise-valid zero/false/empty values that encoding/json could silently fill.
2. Cover the nested typed G3 wire at every decoding boundary, including embedded G2 data
   governed by D's strict request/result shapes, C inputs/decisions, receipt union variants,
   profile confirmation, bindings, execution contexts and outputs. Opaque raw JSON may be
   decoded by its existing typed contract validator; it must not provide an unvalidated escape.
   Do not fix a hardcoded list of currently observed paths only.
3. Preserve legal explicit nulls, valid empty collections, all required valid zero/false
   values, body TAB/LF/CR, strict duplicate/extra-key/NFC/control checks, and exact source union,
   owner closure, full C replay, semantic hashes and canonical raw/context bindings.
4. Never re-marshal malformed input into a repaired object and then accept its old hashes.
   The malformed input returns the existing public invalid-candidate error.

## C source Hash parity (second consolidated blocker)

Require validHash830G3 for SourceProvenance.acquisition_receipt_sha256,
CorpusEntry.native_capture_sha256 and CorpusEntry.parser_identity_sha256. These are already
C Hash fields, requiring64 lowercase hexadecimal characters; this adds no new source rule.
The independent full rehash native_capture_sha256=not-a-sha256 case is an effective RED.
Add one fully rehashed negative per named field and retain the valid positive fixture.
Do not widen this repair into unrelated C policy, identity or source protocol changes.

## Validation and review

- Before implementation, persist meaningful RED for representative omissions and invalid
  nulls across distinct nesting/receipt/raw boundaries identified by the consolidated report.
  Keep positive explicit-null and valid-empty controls. No exhaustive generated field census
  or new test platform is required.
- Run focused G3 types tests to GREEN, then the full existing internal/types package with
  -p2 using the existing cache. Run gofmt/diff checks. Do not install dependencies.
- Preserve the original full342 fixture and 2,254,490-byte preparation request byte-for-byte.
  Freeze the repaired two file identities, actual RED/GREEN outputs and concise coverage map.
- Independent re-review must run the original omitted/null attacks, four rehashed C vectors,
  canonical fixture and all354 snapshot equality checks against the repaired exact identities.
- Backend and final integrated D acceptance remain closed until independent Go PASS.
  A separately reviewed local UI order amendment may permit mock-only UI development; it
  cannot change this repair or the final acceptance gate.

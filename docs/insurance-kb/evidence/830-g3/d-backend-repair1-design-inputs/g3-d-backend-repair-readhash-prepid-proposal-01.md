# G3 D backend bounded repair proposal: preparation read hash and preparation_id

Status: READ_ONLY_PROPOSAL_AWAITING_CONCENTRATED_REVIEW. No repository file was changed while preparing this proposal.

## Frozen implementation and observed RED evidence

The eleven backend implementation files remain frozen at `/private/tmp/g3-d-backend-implementation-freeze-20260908.json`.

Two independently reproduced behaviors require one bounded repair:

1. The actual full `LoadBatchConceptPreparation830G3` result contains 28 real U+2028 code points. The service claims `read_sha256=0e933f199d51779bb0cf14fff977f7aaf014cc51282839573dc1d0947103ca33`, which is the digest of Go's escaped `\\u2028` preimage. The frozen Python/UI canonical contract produces `3355a7141f3b88f2e13882713f6813122cb46917db6045c748317555c31297e7`. Evidence:
   - `/private/tmp/g3-d-backend-independent-read-hash-probe-01.json`, SHA256 `8cbe08a54dc1ecfb5fd940d2d7cc00a21456381a3112d29cccf42e1715ef0735`
   - `/private/tmp/g3-d-root-frozen-python-read-hash-01.json`, SHA256 `94e09a7af0dc856c3d046b8265a329b98620ba381cb7e1217e8bcfb45dc567f9`
2. A real G3 Create call accepts `preparation_id` containing an internal LF and writes the Draft. Evidence: `/private/tmp/g3-d-backend-independent-preparation-id-red-01.log`, SHA256 `0ccf84286e6172fa576ac942f32d3ec6cc45010bc7dc8b9941879f8cd61f8304`.

The first item is a semantic hash mismatch, not a harmless HTTP rendering difference. Consumers parse the response and canonicalize the logical object; therefore the claimed digest must bind the same unescaped Unicode string values.

## Contract facts

The frozen Python `Text` definition in `batch_concept_compile_830_g3.py` requires all of the following:

- valid strict string and nonempty;
- NFC-normalized;
- exactly equal to its edge-trimmed value;
- no C0 control character U+0000 through U+001F and no DEL U+007F.

It does not impose a 512-byte/rune limit. An implementation must not invent one. Ordinary internal spaces and non-control Unicode remain valid. Real U+2028/U+2029 are not C0/DEL and are valid inside a value, but are invalid at an edge because Python `str.strip()` removes them. Internal TAB/LF/CR are invalid in `preparation_id` because they are C0 controls.

The frozen multiline exception remains limited to exact body fields already validated by the G3 types contract, including `SourceBlock.text` and `Evidence.quote`. TAB/LF/CR in those body values must survive logical JSON round trips. The repair must not broaden identifiers to accept controls and must not remove or normalize body characters.

## Narrow canonical reuse

`types.CanonicalConceptMemberPayload830G2(raw)` is the suitable existing exported canonicalizer for the read-hash payload:

- it validates UTF-8 JSON, unique keys, NFC strings and integer-only numeric representation;
- it decodes with `UseNumber`, emits compact sorted-key JSON with HTML escaping disabled, and safely restores real U+2028/U+2029;
- `entityPageUnescapeLineSeparators830G1` counts preceding backslashes, so an actual U+2028 serialized by Go as `\\u2028` is restored to UTF-8, while the six literal characters `\\u2028` serialized as `\\\\u2028` remain literal;
- it preserves TAB/LF/CR logically: JSON wire escapes remain canonical escapes, and decoding restores the original body string.

The repair should marshal the already typed read-hash payload, pass those bytes to `CanonicalConceptMemberPayload830G2`, retain the existing domain preimage exactly:

`schema-wiki-canonical.v1 NUL batch-concept-preparation-read.830.g3.v1 NUL canonical_payload`

and SHA-256 that exact preimage. It must not call `ReplaceAll`, mutate response content, alter the domain, or modify the shared G1/G2 canonical helpers.

This reuse is safe only because the PageManifest comes from full `validateBatchConceptPreparation830G3` and `preparation_id` receives the separate strict Text check below. The generic canonicalizer permits TAB/LF/CR in non-key JSON string values; it is not by itself an identifier validator and must not be exposed as one.

Gin may still escape U+2028/U+2029 in the outer HTTP response representation. That does not alter the parsed logical string. The embedded `read_sha256` must bind the unescaped canonical logical object, so the parsed response matches Python/UI.

## Minimal production paths

Only these two already authorized production paths need changes:

1. `internal/application/service/concept_free_wiki_830_g3.go`
   - add one private exact G3 structured-Text predicate for `preparation_id` matching the Python rules above;
   - reject an invalid input ID at the beginning of `CreateBatchConceptDraft830G3`, before candidate/base/source verification and before repository Create;
   - reject an invalid requested ID at the beginning of `LoadBatchConceptPreparation830G3`, before repository lookup;
   - require the reopened `preparation.ID` to be exact Text and equal to the requested ID; also apply the strict predicate in `validateBatchConceptPreparation830G3` so review/activate/reopen cannot accept corrupt stored identity;
   - replace only the canonical-byte step inside `batchConceptPreparationReadHash830G3` with the exported types canonicalizer. Keep the payload fields, domain, field exclusion of `read_sha256`, and SHA-256 construction unchanged.
2. `internal/handler/schema_wiki.go`
   - in the `batch-concept-830-g3` Create branch, pass `request.PreparationID` exactly to the G3 service instead of `strings.TrimSpace(request.PreparationID)`;
   - in `ReadBatchConceptPreparation830G3`, pass the decoded route parameter exactly instead of trimming it;
   - retain every G1/G2/legacy `TrimSpace` call and all existing request-key/cardinality behavior.

The handler does not need a second copy of the Text validator. It must preserve the exact decoded value, and the concrete G3 service remains the single write/read admission point. Existing narrow handler spies can assert that no normalization occurred.

No changes are needed in types, Python, C/common, shared canonical helpers, fixtures, repository, router, UI, DTOs, tables, routes or release identities.

## Effective TDD sequence once repair is authorized

Use existing open tests only:

- `internal/application/service/concept_free_wiki_830_g3_test.go`
- `internal/handler/concept_free_wiki_830_g3_test.go`

Do not use missing-import or compile failure as RED.

### Behavior RED

1. Full actual preparation read:
   - create/load the frozen actual342 candidate through the real service;
   - assert 28 U+2028 logical values remain present;
   - assert `read_sha256` is the frozen Python value `3355a7141f3b88f2e13882713f6813122cb46917db6045c748317555c31297e7`;
   - frozen implementation must fail with its current `0e933f...` claim.
2. Hash canonical table using a small typed read payload:
   - real internal U+2028;
   - real internal U+2029;
   - literal six-character `\\u2028` and `\\u2029` values;
   - body TAB/LF/CR;
   - verify actual separators have different canonical bytes/hashes from literal backslash sequences and match frozen Python-generated constants.
3. Service Create rejects each invalid ID before source verifier/repository write: empty, all whitespace, leading/trailing ASCII whitespace, internal TAB/LF/CR, NUL, DEL, edge U+2028/U+2029, edge NBSP and decomposed non-NFC text. Compare repository state before/after and source-verifier call count.
4. Service Load rejects the same invalid identities before lookup, and rejects a directly arranged stored preparation whose internal ID is invalid or differs from the request.
5. Handler Create and preparation GET preserve the exact G3 ID when dispatching. A leading/trailing value and internal LF must reach the validating G3 service unchanged and return 400; they must never be converted into a different valid identity. G1/G2 handler compatibility tests remain unchanged.

### Positive and boundary vectors

Accept and round-trip:

- current ASCII fixture ID;
- NFC Chinese ID;
- internal ordinary space;
- real U+2028/U+2029 only when internal;
- literal backslash-u sequences;
- a value longer than 512 characters while remaining inside the existing HTTP/body capacity, proving no new length cap.

For read content, retain actual U+2028/U+2029 and body TAB/LF/CR. Reject invalid UTF-8 before it can be replaced during `json.Marshal`; safety comes from full typed PageManifest validation plus the new ID validator, not from post-marshal repair.

## Verification and freeze

After the focused RED and implementation:

1. focused service and handler repair tests;
2. existing G3 backend service/handler/router targeted regression;
3. complete `go test -p 2 ./internal/application/service ./internal/handler ./internal/router -count=1` with pipefail and raw log;
4. bounded `go vet` for those packages, `gofmt`, and `git diff --check`;
5. temporary actual service-to-Gin-response check: parse the JSON response, recompute with the frozen Python/UI canonical helper, and require exact equality with embedded `read_sha256`;
6. freeze only changed files and new raw logs, report exact SHA256 and zero live effects.

Existing candidate, member, Catalog, C, Profile, source, review, release and activation hashes must remain byte-for-byte unchanged. Only the runtime preparation-read `read_sha256` changes from the incorrect escaped preimage to the frozen logical canonical preimage.

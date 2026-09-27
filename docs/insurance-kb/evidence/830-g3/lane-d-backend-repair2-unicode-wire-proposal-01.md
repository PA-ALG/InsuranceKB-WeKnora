# G3 D backend repair 2: strict preparation_id JSON Unicode admission

Status: read-only design input; no repository file has been edited for this proposal.

## Confirmed defect and boundary

The G3 create handler first splits the request into `map[string]json.RawMessage`, then performs a second ordinary `encoding/json` decode into `schemaWikiCreateDraftRequest`. Go's decoder replaces malformed UTF-8 inside a JSON string with U+FFFD. The existing G3 service consequently receives a different, valid string and can create a Draft. A lone JSON surrogate has the same replacement risk. Wire admission must reject those bytes before the typed decode.

This repair is limited to:

- `internal/handler/schema_wiki.go`
- `internal/handler/concept_free_wiki_830_g3_test.go`

The G3 service, types canonicalizers, fixtures, UI, G1/G2 paths, routes, and repository remain unchanged.

## Exact implementation

In `decodeSchemaWikiCreateDraftRequest`, keep the existing first-pass raw object parsing, duplicate-key checks, exact variant selection, and second typed decode. After the switch has identified `variant == "batch-concept-830-g3"` and before constructing/running the second decoder, call:

```go
if variant == "batch-concept-830-g3" {
    if _, err := types.CanonicalConceptMemberPayload830G2(fields["preparation_id"]); err != nil {
        return "", service.ErrSchemaWikiPreparationInvalid
    }
}
```

Discard the returned canonical bytes. Continue to decode the original complete request bytes into the destination. This is an admission check on the exact JSON string token, not a normalization step.

The existing helper is suitable because it first applies `conceptJSONUnicodeValid830G2` to the raw token. That rejects malformed UTF-8 and unpaired escaped surrogates before `encoding/json` can replace them. Its canonical tree validation also requires NFC. It accepts a top-level JSON string, preserves the distinction between an actual Unicode scalar and literal backslash text, and already rejects duplicate/trailing JSON forms.

Do not add a scanner, `ReplaceAll`, or a new public helper. Do not apply this check before variant selection or to G1/G2 variants. Do not replace the raw token with canonical output. Existing G3 service validation remains responsible for D Text controls and edge whitespace.

## Behavior RED

Add a handler test using the real `CreateDraft` handler and a spy G3 service. Construct the outer JSON as bytes so malformed input is not sanitized by test-side `json.Marshal`.

The frozen handler must fail these cases because it currently returns HTTP 201 and calls the spy once:

1. raw invalid UTF-8 byte within `preparation_id`, for example `"preparation-<0xff>"`;
2. escaped lone high surrogate, `"preparation-\uD800"`;
3. escaped lone low surrogate, `"preparation-\uDC00"`.

Expected repaired result for each: invalid-preparation HTTP response under the existing error mapping and zero G3 service calls. The RED log must record the pre-repair 201/spy-call behavior. Test each case with fresh context and spy state.

## Positive and compatibility matrix

The same focused test group must prove these G3 inputs reach the spy once with the exact decoded string:

- literal U+FFFD encoded directly as valid UTF-8;
- escaped U+FFFD, `\uFFFD`;
- a valid emoji encoded as a surrogate pair, for example `\uD83D\uDE00`;
- literal backslash-u text, for example JSON `"literal\\uD800"` and `"literal\\u2028"`;
- existing valid NFC identifiers.

The first two intentionally produce the same logical U+FFFD string but are both valid wire encodings. The valid emoji pair decodes to one scalar. Literal backslash-u remains six ordinary characters and must not be interpreted as a surrogate escape.

Add legacy compatibility cases through the same handler showing valid G1 and G2 create bodies still dispatch exactly as before. The new check is gated after exact variant selection, so neither legacy request is passed to the G3 raw-string validator.

## Verification and evidence

Run in order:

1. focused handler RED on the malformed UTF-8 and lone-surrogate cases;
2. focused handler GREEN for the complete negative/positive/legacy matrix;
3. full `./internal/handler` and `./internal/router` tests;
4. `go vet ./internal/handler ./internal/router`;
5. `gofmt` and `git diff --check` for the two authorized paths.

Do not repeat the unchanged service full package or the already-passing service-to-UI interoperability run. Preserve all raw logs with unique repair-2 names and freeze the two file hashes for independent review.

## Expected effects

Malformed wire bytes and lone surrogates fail before the G3 service, source verification, repository writes, or response rendering. Valid U+FFFD, valid supplementary-plane scalars, literal backslash-u text, G3 body TAB/LF/CR rules, and all G1/G2 behavior remain unchanged.

# G3 Task3 query cardinality owner-gap proposal

Status: private review proposal only; no repository edit.

## Minimal additional production path

Add only `internal/handler/concept_free_wiki_830_g2.go` to the existing backend owner matrix. Keep tests in the already-authorized new `internal/handler/concept_free_wiki_830_g3_test.go`. No route, DTO, repository, table, Head, or wire-contract change.

## Narrow service discriminator

Add one narrow method on the existing `SchemaWikiService`, implemented in the already-open G3 service file:

```go
IsBatchConceptRelease830G3(
    context.Context,
    types.WikiReleasePrincipal,
    types.WikiReleaseScope,
    string, // legacy-selected release_id; empty means current
) (bool, error)
```

The method uses `BeginPinnedRead` for empty release and `BeginExactPinnedRead` for a nonempty release, so existing ACL and exact historical pin semantics remain authoritative. It reopens Release, Ready preparation, and stored members. A non-G3 manifest returns `(false, nil)` without changing its old read path. A G3 manifest must pass `validateBatchConceptPreparation830G3` plus release/candidate/base epoch and exact stored-member checks before returning true. Any malformed G3 custody fails closed. It does not return or add a public DTO and does not consult a second Head.

## Handler behavior

Both `ReadPage` and `PreviewCitation` first retain the legacy selection rule, `query.Get("release_id")`, then call the optional discriminator when the service provides it.

Only when the selected/current release is a fully validated G3 release:

- `release_id` may be absent, or occur exactly once with a nonempty value;
- `preparation_id` must be absent;
- no other query key is accepted;
- for citation preview, the already-required single nonempty `release_id` remains required.

For a G2 release, the handler continues its current `Query("release_id")` behavior byte-for-byte, including how it treats repeated, explicit-empty, or ignored query keys. A first G2 `release_id` followed by another value remains a G2 request because the legacy-selected first value determines the target; this avoids global hardening or a frontend hint.

Citation classification happens before calling `IssueConceptCitationAuthority830G2`, so a malformed G3 query cannot mint and discard a token. Page classification likewise happens before the page read call. The existing service read/issue methods still perform their own full pinned reopening, so the discriminator is only a fail-closed routing guard and never cached authority.

## Tests

Use a handler spy implementing the narrow discriminator and existing read/issuer interfaces:

- G3: reject repeated release, explicit-empty release, preparation+release mixed query, and unknown extra query; assert page reader/issuer call count is zero.
- G3: accept absent release for current page, one nonempty release for pinned page/citation.
- G2: assert the prior first-value/empty/ignored-key behavior still reaches the old reader/issuer unchanged.
- discriminator service tests use the activated full 342 fixture and prove current/exact G3 true, actual G2 base false, and stored G3 member/manifest drift error.

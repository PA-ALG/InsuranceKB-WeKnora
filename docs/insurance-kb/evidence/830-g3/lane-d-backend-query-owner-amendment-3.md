# G3 Task3 query cardinality owner-gap amendment v3

Status: DESIGN_V3_PENDING_INDEPENDENT_REVIEW. This is the existing Task3 query requirement with one missing handler path added. It supersedes the v1 bool-discriminator and resolves the v2 citation-choice ambiguity; neither prior proposal authorized code changes.

## Minimal additional production path

Add only `internal/handler/concept_free_wiki_830_g2.go`; tests remain in the authorized new G3 handler test. No route, DTO, repository, table, or second Head.

## Atomic page service entry

Add a narrow optional method implemented by existing `SchemaWikiService` in the open G3 service file:

```go
ReadConceptPageQuery830G3(
    context.Context,
    types.WikiReleasePrincipal,
    types.WikiReleaseScope,
    string,   // member_id
    []string, // exact raw release_id occurrences; nil means absent
    bool,     // preparation_id query key present
) (*ConceptPageRead830G2, error)
```

This method preserves legacy target selection (`first release_id`, absent or first-empty means current), creates exactly one current or exact `WikiReleasePinnedRead`, and uses that same opaque pin for manifest classification and the final page projection. It reopens Release, Ready preparation, and stored members once. If the pinned manifest is G3, it first enforces: release_id absent or exactly one nonempty occurrence, and no preparation_id query key; then it performs full G3 validation and returns the existing exact13-key `concept-page-read.830.g2.v1`. If the pinned manifest is G2, it applies no new query-cardinality rule and executes the existing G2 projection from the same pin, preserving old first-value/empty behavior. The production SchemaWikiService must implement this atomic entry; its conformance is checked. The optional interface preserves older G2-only test doubles, which may retain the old ReadConceptPage830G2 path. It must not provide an unvalidated G3 fallback.

Returning the completed page read, rather than a boolean, removes the classify/current-Head/read TOCTOU. A false G2 classification is never cached across another Head read.

## Citation

Citation already requires a nonempty exact release ID. Use only the following atomic entry. A separate discriminator followed by a second read/issue call is not an allowed implementation:

```go
IssueConceptCitationQuery830G3(
    context.Context,
    types.WikiReleasePrincipal,
    types.WikiReleaseScope,
    string, string, // member_id, citation_id
    []string,       // raw release_id occurrences
    bool,           // preparation_id key present
) (*ConceptCitationContentAuthority830G2, error)
```

It selects the legacy first exact release once, begins one exact immutable pin, reopens and classifies the whole stored preparation, enforces the G3-only cardinality/mixed rule before resolving evidence or signing, then issues through the existing source authority using that validated pin/bundle. G2 uses the same exact pin and old first-value semantics. No evidence is resolved and no token is created before the G3 query gate. The production SchemaWikiService must implement this atomic citation entry; older G2-only doubles may retain their legacy fallback, with no unvalidated G3 path.

## Exact extraction and target selection

The handler reads `values := c.Request.URL.Query()` and passes `values["release_id"]` directly, preserving every occurrence. It derives preparation presence with `_, preparationPresent := values["preparation_id"]`; even an empty value is present. Do not use c.Query/GetQuery to infer cardinality. The legacy selected release is `strings.TrimSpace(first)` when an occurrence exists. Nil means absent. Absent, first-empty or first-whitespace uses current for page reads; citations preserve the existing rejection of an empty selected release. G3 cardinality checks use the original occurrence count and the trimmed selected value. The same single pin determines both G2/G3 classification and the actual result.

## Exact query scope

The new G3 rule covers only the frozen requirements: repeated `release_id`, explicitly empty `release_id`, and presence of `preparation_id` together with the active page/citation request. It does not reject unrelated query keys because the frozen plan does not explicitly authorize that extra hardening.

## Tests

- G3 current page: absent release accepted; explicit-empty, repeated, or preparation_id present rejected before projection.
- G3 pinned page/citation: one nonempty release accepted; repeated or mixed rejected; issuer count remains zero for malformed citation queries.
- G2: repeated/empty/mixed inputs continue to select the first value exactly as before.
- A mutable-Head test advances Head between any test callback opportunities and proves the atomic page entry returns the release pinned by its sole BeginPinnedRead observation.

Additional bounded compatibility cases: first-G2/second-G3 remains the first G2 target; first-empty with current G2 preserves old current behavior; whitespace-only selected release preserves old page/current and citation-rejection behavior. The mutable-Head test must show one current-pin observation and no classify/read split.

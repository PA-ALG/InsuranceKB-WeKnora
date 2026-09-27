# G3 Task3 query cardinality owner-gap proposal v2

Status: private review proposal only; replaces the earlier bool-discriminator proposal because an empty `release_id` current read must not classify and read across two Head observations.

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

This method preserves legacy target selection (`first release_id`, absent or first-empty means current), creates exactly one current or exact `WikiReleasePinnedRead`, and uses that same opaque pin for manifest classification and the final page projection. It reopens Release, Ready preparation, and stored members once. If the pinned manifest is G3, it first enforces: release_id absent or exactly one nonempty occurrence, and no preparation_id query key; then it performs full G3 validation and returns the existing exact13-key `concept-page-read.830.g2.v1`. If the pinned manifest is G2, it applies no new query-cardinality rule and executes the existing G2 projection from the same pin, preserving old first-value/empty behavior. The handler uses this optional entry when present; older service doubles and implementations retain the old `ReadConceptPage830G2` path.

Returning the completed page read, rather than a boolean, removes the classify/current-Head/read TOCTOU. A false G2 classification is never cached across another Head read.

## Citation

Citation already requires a nonempty exact release ID. Add a narrow exact-release discriminator/validator in the same service, or an atomic optional issue method with the raw release occurrences. Prefer the atomic form:

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

It selects the legacy first exact release once, begins one exact immutable pin, reopens and classifies the whole stored preparation, enforces the G3-only cardinality/mixed rule before resolving evidence or signing, then issues through the existing source authority using that validated pin/bundle. G2 uses the same exact pin and old first-value semantics. No token is created before the G3 query gate.

## Exact query scope

The new G3 rule covers only the frozen requirements: repeated `release_id`, explicitly empty `release_id`, and presence of `preparation_id` together with the active page/citation request. It does not reject unrelated query keys because the frozen plan does not explicitly authorize that extra hardening.

## Tests

- G3 current page: absent release accepted; explicit-empty, repeated, or preparation_id present rejected before projection.
- G3 pinned page/citation: one nonempty release accepted; repeated or mixed rejected; issuer count remains zero for malformed citation queries.
- G2: repeated/empty/mixed inputs continue to select the first value exactly as before.
- A mutable-Head test advances Head between any test callback opportunities and proves the atomic page entry returns the release pinned by its sole BeginPinnedRead observation.

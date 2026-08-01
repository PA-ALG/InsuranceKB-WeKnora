# MinerU Native Structured Artifact Retention and Normalization Specification

## ADDED Requirements

### Requirement: MCNP1 exact accepted native schema

060 SHALL accept only effective parser model `pipeline` and one ZIP entry whose basename
ends with `_content_list.json` and whose payload conforms to task-local schema identity
`mineru.content-list.pipeline.v1`: a top-level ordered array; every item has `type`,
non-negative `page_idx` and valid normalized `bbox=[x0,y0,x1,y1]`. The exact accepted
JSON field type SHALL match the frozen schema and every required field SHALL be non-null;
normalized bbox coordinates SHALL be finite, ordered and within inclusive range `0..1000`.
The official type set is `text/header/footer/page_number/aside_text/page_footnote`, `table`,
`image`, `chart`, `equation`, `code` and `list`, with only the type-specific keys documented
by the frozen upstream output-files reference. Table items have provider-native
`table_body`. Non-official aliases such as `title/interline_equation/display_equation`, VLM
or MinerU-HTML output, `content_list_v2.json`, model JSON, Markdown and unknown vendor keys
SHALL NOT become structural authority; an unknown top-level item key is schema drift and
SHALL fail closed rather than be silently ignored.

#### Scenario: ZIP is Markdown-only or ambiguous

- **WHEN** ZIP has no unique valid pipeline content-list, has multiple candidate entries, or
  only contains Markdown/images
- **THEN** reading fails closed with typed native-structure insufficiency and returns no
  structured sidecar

### Requirement: MCNP2 content-addressed sanitized retention

The ZIP boundary SHALL compute SHA-256 over exact native JSON bytes and produce deterministic
canonical `mineru-native-structure.v1` bytes. Sanitized output SHALL contain only schema/raw
hash, exact `parser_model=pipeline`, ordered pages/blocks/tables/cells, stable task-local ids, validated locators, content
digests and structure digests. It SHALL NOT contain body text, table text, unknown vendor
fields, URL, secret or absolute path. Stable ids SHALL bind raw artifact hash, page/order,
type, bbox and content digest.

#### Scenario: caller mutates presentation output

- **WHEN** Markdown or image presentation changes while exact native JSON is unchanged
- **THEN** raw/sanitized hashes and normalized structure remain unchanged

### Requirement: MCNP3 native table grid is proven, never guessed

Table row/column/span SHALL be derived only from fully nested and lexically closed HTML with
non-duplicated and structurally validated `tr` and `td/th` elements in the
provider-native `table_body`, including positive integer `rowspan`/`colspan`. The normalizer
SHALL refuse structural table/cell facts for overlapping occupancy, repaired/malformed HTML,
duplicate span attributes, missing cells or an incomplete grid. Only true HTML void elements
may use self-closing syntax; a self-closing non-void element is malformed and SHALL fail closed.
It SHALL NOT infer cells from Markdown, empty presentation cells or adjacent pages. Header
and cross-page capabilities remain unsupported unless directly proven by the accepted
native item. Because pipeline content-list provides one native table bbox rather than
per-cell spatial boxes, each cell locator SHALL use that exact table-scoped bbox together
with exact row/column/span and SHALL emit `native_cell_bbox_is_table_scoped`; it SHALL NOT
claim a finer spatial bbox.

#### Scenario: native table grid is malformed

- **WHEN** cell spans overlap, leave an ambiguous grid, or cannot be placed deterministically
- **THEN** no table/cell capability is admitted and the bounded attempt returns BLOCK with a
  non-empty ReviewItem

### Requirement: MCNP4 narrow result boundary

The existing Go-local MinerU Cloud reader SHALL carry one content-addressed native structured
sidecar through `ReadResult`, binding source SHA-256, schema identity, raw SHA-256 and sanitized canonical
JSON. Existing Markdown/image behavior SHALL remain unchanged. Because this reader does not
traverse docreader gRPC, 060 SHALL NOT widen the proto or create a second serving runtime.
The effective parser model SHALL be checked before provider I/O and re-bound into the sidecar;
caller configuration SHALL NOT label VLM or MinerU-HTML output as pipeline.

#### Scenario: current boundary discards the artifact

- **WHEN** a completed ZIP contains a valid native content-list
- **THEN** RED demonstrates current `ReadResult` cannot expose its identity or structure;
  GREEN exposes exactly one bound sanitized sidecar without provider or filesystem writes

### Requirement: MCNP5 sole 053 bridge and bounded quality gate

The task-local Python adapter SHALL consume only the validated sidecar and SHALL directly
use merged 053 `ParsedDocumentV1`, `build_parse_manifest` and `evaluate_parse_quality`. It
SHALL receive exact subject/parser/attempt/snapshot/output-policy/052 resolution context;
attempt SHALL be `2/bounded_upgrade`. Raw native artifact hash SHALL equal both the expected
artifact hash and `ParseSubjectV1.raw_artifact_hash`. Before constructing 053 evidence, the
adapter SHALL revalidate ID uniqueness, page membership, per-page indices, table/cell/header
membership, table-scoped bbox equality and exact non-overlapping complete occupancy. Any
identity drift, malformed payload, missing required
capability or policy mismatch SHALL produce typed failure or 053 BLOCK+ReviewItem. Caller
flags, copied DTOs or sidecar self-claims SHALL NOT authorize ADMIT.
An invalid native bbox SHALL retain only a content-addressed `native_structure_invalid`
observation without an invalid locator. The adapter SHALL include that observation in the
document/manifest and SHALL return BLOCK+ReviewItem regardless of which structural
capabilities the MaterialProfile requires.

#### Scenario: complete bounded upgrade

- **WHEN** exact native structure satisfies every capability in the exact 052 profile
- **THEN** the adapter may return 053 ADMIT with matching document/manifest hashes and no
  additional parser/provider call

#### Scenario: bounded upgrade is insufficient

- **WHEN** any required structure fact is absent or ambiguous
- **THEN** decision is BLOCK+ReviewItem; no third attempt, fallback, publication or provider
  call occurs

### Requirement: MCNP6 bounded delivery scope

060 SHALL remain within 12 repository paths and SHALL NOT add migration, DB, queue, parser
router, provider call, Paddle/ODL/third parser, Golden dependency or generic artifact/parser
platform.

#### Scenario: implementation requires a broader authority

- **WHEN** GREEN requires a thirteenth path, migration, proto/general API or second runtime
- **THEN** implementation stops and reports the exact blocker rather than expanding scope

# Clarification: G2 unknown fields, empty aliases, and C identity projection

Date: 2026-09-07

This attachment narrows the conclusion of
`g3-c-existing-entity-g2-identity-trace-readonly-01.md`. The original report is unchanged.
It does not construct an `ExistingEntitySnapshotV1` or authorize any execution.

## 1. Empty `approved_aliases` is valid

`ExistingEntityV1.approved_aliases` is a tuple with no minimum length
(`batch_entity_resolution_830_g3.py:505-516`). Its validator only requires canonical
unique ordering (`:518-524`). Therefore `approved_aliases=()` is valid.

The correct meaning is: **this snapshot elects not to use any alias for matching**. It does
not assert that the product has no short names or aliases in the world. No alias-specific
approval receipt is needed for an empty tuple. A non-empty entry still requires an
`ApprovedAliasV1(value, approval_receipt_sha256)` (`:500-502`) and may not be manufactured
from the observed `险种简称` text. This removes aliases as a blocker to a snapshot whose
policy deliberately uses no aliases.

## 2. Keep three authorities separate

1. **Published G2 field state remains unchanged.** In candidate
   `bdc806e2084a...`, `product_code`, `product_name`, and `product_short_name` remain the
   exact published `unknown/null` assertions. No C preparation may rewrite those G2 pages
   or describe them as previously populated.
2. **Served identity is authoritative for IDs only.** After a fresh exact-scope Head read,
   the approved candidate's `/request/entity_versions` is authoritative for the two pairs
   `ping-an-e-sheng-bao -> ...@596-1` and
   `ping-an-e-sheng-bao-hui-xiang -> ...@594-1`. The suffixes do not establish product
   codes.
3. **Source evidence to typed C identity is a new, reviewable projection.** G2 `unknown`
   does not forbid a later C snapshot from using verified official source observations for
   `issuer/name/product_code/version_label/filing_or_registration`. Those observations are
   not automatically prior-approved typed identity merely because their raw SourceBlocks
   were part of a reviewed bundle. A deterministic mapping must name the exact source
   bytes/ranges, normalization, field assignment, and Head binding, then be reviewed in the
   existing G3 scope. This is a projection gap, not a requirement for a new registry,
   Product master UUID, or second human master-data registration.

Consequently, the prior report's “cannot produce a valid full snapshot” means **cannot do
so from the saved artifacts without the missing accepted projection and fresh Head gate**.
It is not a claim that the official evidence can never support such a projection.

## 3. `version_label` is not frozen to a year

The current contracts make `version_label` non-empty text but impose no year-only grammar:

- `ExistingEntityV1.version_label: Text` and `EntityCandidateV1.version_label:
  ObservedNormalizedValueV1` (`batch_entity_resolution_830_g3.py:505-516, 666-675`).
- C's version candidate key hashes the normalized label together with the formal
  filing/registration anchor (`lane-c-batch-contract-draft.md:79, 90-94`).
- `docs/insurance-kb/03-knowledge-model.md:58` gives `"2024版"` only as an example.
- Existing OpenSpec 041 treats the persisted `ProductVersion.version_label` as an opaque
  returned identity field (`spec.md:122-130`). The existing registrar assigns it from the
  actual source metadata `ProductMeta.version_no` (`product/register.py:122-138`), so a
  source version number such as `596-1` or `594-1` is structurally valid when that metadata
  is the accepted authority.

The G3 C contract also requires version identity to have actual evidence and forbids
filename or normalization guesses (`lane-c-batch-contract-draft.md:19-23, 75-79, 94`). It
does **not** currently decide which of these observed strings is the canonical label for
the two G2 entities:

- acquisition/API `versionNo`: `596-1` / `594-1` (`dataset/version-materials/manifest.md:
  14,17`),
- product-name wording: `尊享版` / `惠享版`,
- filing-year substring: `2025`.

No value should be selected merely because tests use `2025`/`2026` or a synthetic example
uses `2026版`. The missing narrow semantic decision is whether the actual official
acquisition `versionNo` is the C projection's `version_label`, or whether a different exact
source span is required. Whatever is chosen must remain separate from
`filing_or_registration` and must not be derived by splitting the served entity version.

## Revised gap statement

- `approved_aliases=()` is available now as a truthful no-alias matching policy.
- The actual G2 source set contains plausible exact observations for issuer, formal name,
  product code, filing number, and source version number for both entities.
- The remaining blocker is the unapproved source-to-typed-identity projection (especially
  the exact `version_label` semantic), plus the fresh exact-scope Head/readback receipt.
- This clarification neither approves that projection nor changes G2 serving fields,
  IDs, code, evidence, or publication state.

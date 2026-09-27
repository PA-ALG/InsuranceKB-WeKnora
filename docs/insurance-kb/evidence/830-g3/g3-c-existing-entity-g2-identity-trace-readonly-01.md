# G3 C existing-entity identity trace from actual G2 artifacts (read-only)

Date: 2026-09-07

Scope: only the two medical entities served by the actual G2 Head. No HTTP, DB, model,
or product/evidence mutation was performed. G3 synthetic fixtures were excluded as
identity authority.

## Result

**BLOCKER:** the saved G2 artifacts prove the two logical `entity_id` / `entity_version`
pairs and contain useful official-source identity text, but they do not contain a complete,
approved `ExistingEntitySnapshotV1` identity mapping. The final G2 candidate explicitly
publishes `product_code`, `product_name`, and `product_short_name` as `unknown`; it has no
`version_label`, entity filing/registration field, or entity-alias approval receipt. A fresh
Head read is necessary to bind the base release, but cannot by itself fill those missing
semantic bindings.

The decisive authority chain is:

- `docs/insurance-kb/evidence/830-g2/b-source-complete-candidate-bundle.json`
  SHA-256 `69dd25e29ea771a512cf24c083a52e8347386def68b30d90d379f2b0dfe181d1`.
- `b-source-human-explicit-approval.json` `/candidate_hash` and
  `/candidate_file_sha256` bind candidate `bdc806e2...3d684` and the exact file above;
  lines 14-20 bind the prior Head and whole-candidate approval condition.
- `b-source-publication-execution.json` `/final_head` proves transition to
  `release-9cb493e3-8d27-4a0f-8f29-93e2a078725b`, epoch 5.
- `g2-final-runtime-check.json` `/head` and `g2-closeout.json` `/active` corroborate that
  Head and candidate. These are historical readbacks, not a fresh G3-run Head receipt.

## Exact logical identity that is derivable

From the approved candidate:

- `/request/entity_versions/ping-an-e-sheng-bao` =
  `ping-an-e-sheng-bao@596-1`.
- `/request/entity_versions/ping-an-e-sheng-bao-hui-xiang` =
  `ping-an-e-sheng-bao-hui-xiang@594-1`.

This exact two-row logical mapping is derivable after the fresh Head gate. The suffixes
`596-1` and `594-1` are served entity/product-version identifiers; neither is evidence that
the C `product_code` is `596` or `594`.

## `ping-an-e-sheng-bao` / `ping-an-e-sheng-bao@596-1`

| Snapshot field | Actual saved G2/source trace | Binding conclusion |
|---|---|---|
| `issuer` | Approved candidate `/request/sources/0/text[1424:1438]` = `中国平安人寿保险股份有限公司`; same SourceBlock is page 1, knowledge `f987fc16-...`, revision `ea716014...`, block `block-03fe...`. | Exact source observation exists inside the approved bundle, but G2 defines no entity-identity projection that assigns it to `ExistingEntityV1.issuer`. Not directly derivable as a typed snapshot value. |
| `name` | Frozen G1 input `inputs/c5/preview.json` `/product/{entity_id,entity_version_id,display_name}` binds the entity to `平安e生保（尊享版）医疗保险`; `frozen-inputs.json` `/files/8` fixes that file SHA. Approved candidate `/request/sources/0/text[21:37]` contains spaced text `平安 e 生保（尊享版）医疗保险`. | Strong binding evidence, but no saved rule selects the exact representation. Final candidate `/compile_result/output/fields/2` (`product_name`) is explicitly `unknown/null`. Not an approved typed snapshot value. |
| `product_code` | Approved candidate `/request/sources/0/text[12:20]` = `险种代码：596`; acquisition manifest `dataset/version-materials/manifest.md:14` records official API `planCode 596`. | Source says `596`, but approved output `/compile_result/output/fields/0` is `unknown/null`. Do not derive from `@596-1` or silently override the published unknown state. |
| `version_label` | Frozen G1 input `/product/product_version_id` = `596-1`; source filing string contains `2025`. | Neither value is designated as C `version_label`; `596-1` is an internal served version ID and `2025` is part of a filing number. Missing. |
| `filing_or_registration` | Approved candidate `/request/sources/0/text[1218:1238]` = `平安人寿〔2025〕医疗保险 172 号`; acquisition manifest line 14 labels the normalized form as `备案号`. | Exact official text and likely `kind=filing_number` evidence exist, but no G2 typed entity field or approved mapper binds it. Not directly derivable. |
| `approved_aliases` | Approved source `/request/sources/0/text[0:11]` = `险种简称：e 生保尊享`. Frozen G1 `/fields/1` (`product_short_name`) is `unknown`; final candidate `/compile_result/output/fields/1` is also `unknown`. | The text is an observed short name, not an `ApprovedAliasV1`. No per-alias `approval_receipt_sha256` exists. Must remain unconstructed; concept-definition `aliases: []` is unrelated to entity aliases. |

## `ping-an-e-sheng-bao-hui-xiang` / `...@594-1`

| Snapshot field | Actual saved G2/source trace | Binding conclusion |
|---|---|---|
| `issuer` | Exact source PDF `dataset/version-materials/esb_huixiang_594-1_tiaokuan.pdf` SHA-256 `7bfac182...c9ce5`; saved read-only source snapshot `/private/tmp/g2-b-source-recovery-prep/database-snapshot.private.json` `/chunks/1/content[54:68]` = `中国平安人寿保险股份有限公司`. The PDF/custody identity is also fixed by `b-second-snapshot-preflight-v2.json` `/verified_b_custody/documents/0`. | Official source observation exists, but it is absent from the final candidate's selected Hui-Xiang SourceBlocks and no typed entity mapping/approval assigns it. Missing as approved snapshot value. |
| `name` | `b-external-material-preview.json` `/product_identity_evidence` binds page-1 block `8bdec5c0-...`, range `[35,69)`, quote `险种代码：594\r\n平安 e 生保（惠享版）长期医疗保险（费率可调）`; `/b_bounded_proposal/{entity_id_proposal,entity_version_proposal}` supplies the proposed logical pair. `b-input-provider-closure-preflight.json` lines 16-25 replays the same auxiliary binding. Approved final candidate `/request/sources/20/text[198:222]` independently contains the full name. | Actual input and source evidence are strong, but the first artifact is explicitly `PREVIEW_NOT_REQUEST_NOT_CANDIDATE_NOT_RELEASED` and the preflight calls it `AUXILIARY_IDENTITY_ONLY_NOT_COMPILE_REQUEST_SOURCE`. Final `/compile_result/output/fields/69` (`product_name`) is `unknown/null`. Not an approved typed snapshot value. |
| `product_code` | Same auxiliary page-1 evidence quote contains `险种代码：594`; the source snapshot `/chunks/0/content[12:20]` repeats it, and dataset manifest line 17 records official API planCode `594`. | The input was authorized for G2 model processing (`b-deepseek-external-authorization.json`), but that authorization explicitly was not candidate approval. Final `/compile_result/output/fields/67` is `unknown/null`. Do not derive from `@594-1`. |
| `version_label` | Logical `entity_version` ends in `594-1`; source filing string contains `2025`. | No artifact designates either as `version_label`. Missing. |
| `filing_or_registration` | Exact source snapshot `/chunks/0/content[1102:1122]` = `平安人寿〔2025〕医疗保险 170 号`; dataset manifest line 17 calls it `备案号` and fixes the same source PDF SHA at line 65. | The text is not carried in the final approved candidate request and no typed mapping/approval exists. Missing as snapshot value. |
| `approved_aliases` | Source snapshot `/chunks/0/content[22:33]` = `险种简称：e 生保惠享`; approved candidate `/request/sources/20/text` says `简称 e 生保惠享`. Final `/compile_result/output/fields/68` (`product_short_name`) is `unknown/null`. | No alias approval receipt exists. Do not infer `[]` from absence and do not promote the observed short name to `ApprovedAliasV1`. |

## Can a binding table be produced?

- **Yes, partial evidence map only:** the two logical entity/version rows, source hashes,
  source block/page/ranges, observed issuer/name/code/filing/short-name strings, and the
  whole-candidate approval/publication chain can be recorded deterministically.
- **No, not a valid full `ExistingEntitySnapshotV1`:** `ExistingEntityV1` requires non-null
  `issuer`, `name`, `product_code`, `version_label`, and `filing_or_registration`, while
  `ApprovedAliasV1` requires an alias-specific approval receipt. The saved G2 serving
  contract never establishes those complete typed values. Treating the approved raw
  SourceBlocks as approval of arbitrary new semantic fields would contradict the approved
  candidate's explicit unknown states.
- No manual product-master registration is implied by this finding. The gap is a missing
  accepted projection/binding from existing official G2 source evidence to the newer C
  snapshot contract, not a requirement to create another registry or authority.

## Mandatory fresh Head gate before any actual snapshot

1. Read current Head under exact tenant/space/raw-KB/wiki-KB scope and require release
   `release-9cb493e3-8d27-4a0f-8f29-93e2a078725b`, epoch `5`, and candidate
   `bdc806e2084afde6651e85c83a88e3d5395487398bea9b4b2c509473a663d684`.
2. Bind the fresh Head receipt, pinned release manifest/pages, and exact two
   `entity_versions` rows; fail on any drift.
3. Re-read the cited source revisions/blocks and verify exact text slices and source hashes.
4. Only after an accepted deterministic identity projection supplies every required typed
   field may the snapshot and its hash be constructed. Fresh Head success is necessary but
   not sufficient to close the identity gaps above.

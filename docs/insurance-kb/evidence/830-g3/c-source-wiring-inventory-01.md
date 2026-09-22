# G3 C SourceRevision / SourceBlock 只读接线盘点

结论：现有代码已有严格校验与哈希公式，但没有一条已签入的通用构造器能仅凭“backfill HTTP 回执 + W1 descriptor/chunks + saved native capture”生成完整 `LiveRevisionSourceReceiptV1` 和任意 C `SourceBlock`。01、02 可复用既有 G1/C5 admission 三元组后与当前 W1/source row 重新绑定；03、04 未找到 admission 三元组，是当前完整 C corpus 输入的 BLOCKER。SourceBlock 的 actual W1 身份材料已齐，页码/quote 必须按已验证的 Unicode quote join 取得，不能直接搬 native global offset。

## 可复用代码地图

- `harness/src/insurance_harness/knowledge_compiler/schema_wiki_candidate_evidence_join_596_1.py`
  - `knowledge_revision_source_id`: 与 Go 相同的 source ID 公式。
  - `LiveRevisionSourceReceiptV1`、`live_revision_source_receipt_sha256`: 完整 DTO、自校验和 wire hash。
  - `build_schema67_candidate_evidence_authority_596_1`: 能验证 admitted artifact/live receipt/chunk/native join，但固定 `terms/brochure/rate_table` 三角色，不是 15 材料通用构造器。
- `internal/types/knowledge_revision.go`
  - `ComputeKnowledgeRevisionSourceID`、`ComputeLiveRevisionSourceReceiptSHA256`、`ValidateLiveRevisionSourceReceiptV1`: Go 同源公式。
- `internal/application/service/schema_wiki_citation_revision.go`
  - `validateSchemaWikiCitationCoordinateAuthorityReceipt`: 现有服务端权威重绑定先例。它从 actual repository `KnowledgeRevisionSource`/`KnowledgeRevision` 取得 source/resource/W1 字段，从既有 coordinate receipt 取得 `evidence_parse_attempt_id`、`parsed_document_sha256`、`parse_manifest_sha256`，重建并逐字比较 live receipt。它是校验器，不是供 C 输入准备调用的独立公开 adapter。
- `harness/src/insurance_harness/knowledge_compiler/concept_free_wiki_830_g2.py`
  - `SourceBlock`、`Evidence`、`evidence_for`、`verify_evidence`: C 实际复用；Python 字符串索引即 Unicode code point，quote hash 是 UTF-8 SHA256。
- `internal/application/service/concept_source_authority_830_g2.go`
  - `ConceptSourceAuthorityService830G2.verifyEvidence`: actual source row + revision + 全 W1 chunks 重算 manifest，要求 `revision_id=source.RevisionSourceID`、`parse_hash=revision.ManifestDigest`，并用 `[]rune` 校验 block 内 offset。
  - `resolveConceptNativeQuote830G2`: 严格校验 native projection/parser/page/char boxes，在指定 native page 内按 Unicode code point 寻找唯一 quote；只返回 bbox。函数未导出，生产 `verifyEvidence` 会从 fixed PDF 调 Docreader，不能把已保存 capture 注入为 no-reparse 构造器。
  - 已运行证据 `docs/insurance-kb/evidence/830-g2/b-source-recovery-native-validation.json` 证明 3 个真实 quote 的 captured-native resolver 正/反例通过；只保留 overlay/log SHA，没有可复用的已签入执行器字节。
- 已运行 actual 数据先例：
  - `docs/insurance-kb/evidence/830-g2/inputs/a-native-source-blocks.json`: 01 的 4 个 actual W1 SourceBlocks 与 8 个 quote；`parse_hash=f2190b...`，`revision_id=ea7160...`。
  - `docs/insurance-kb/evidence/830-g2/b-selected-sourceblocks-preflight.json`: 03/04 的 3 个 actual SourceBlock/Evidence locators，含 block 内 codepoint offsets、native global offsets、bbox。

## 三种哈希域和 offset 规则

- `SourceBlock.revision_id = actual revision_source_id`（即 source ID）。
- `SourceBlock.parse_hash = actual W1 chunk manifest digest`；绝不能填 native SHA、`parsed_document_sha256` 或 admission `parse_manifest_sha256`。
- `CorpusEntry.native_capture_sha256` 单独保存 native projection hash；`parser_identity_sha256` 填 native parser identity。
- `Evidence.start/end` 是 exact W1 `SourceBlock.text` 内 codepoint offset。native `global_codepoint_start/end` 是 saved native markdown 内的另一套 codepoint 坐标，仅用于 page/charbox 证明。
- 真实 01 示例：同一 quote 在 W1 block 从 105 开始，在 native markdown 从 111 开始；差 6 是前置 6 个 LF 在 native 中为 CRLF。故不得把 native global offset 当 block offset。正确 join 是：先在 exact W1 chunk 切出 quote，再在指定 native page 中唯一匹配该 quote；保留两套坐标。

## 字段来源与缺口

`LiveRevisionSourceReceiptV1` 的 actual W1/source 字段来源：scope；target source row 的 `resource_id`/source ID；backfill 回执的 file/size/mime/page；W1 descriptor/chunks 重算后的 algorithm/digest/count。注意 `internal/handler/knowledge_revision_source.go` 的单件 backfill HTTP safe receipt不返回 `resource_id`，仓库也没有 revision-source GET 路由；必须用 target source-row readback或现有服务端 repository seam，不能从 source ID 反推、也不能手填。

另外三个必填 admission 字段不来自上述三种资产：`evidence_parse_attempt_id`、`parsed_document_sha256`、`parse_manifest_sha256`。saved builtin native capture也不等于 `AdmittedParseArtifactV1`。只有已有 admission/coordinate authority receipt可以提供这些值；不得取 native/capture/markdown hash凑四域 distinct 校验。

| material | actual source/W1/native/blocks | admission 三元组 | C live receipt 状态 |
|---|---|---|---|
| 01 | 齐：source `ea7160...`，resource `46ea68...`，W1 `f2190b...`/162，native `8f735c...`，parser `ddb9e3...`；actual SourceBlock/quote 先例已保存 | 齐：既有 G1/C5 `ec01-terms-parse-attempt-2`，parsed `92926b...`，parse-manifest `790a50...` | 可确定性重绑定并用现有 hash函数重算；旧 C5 整份 receipt 的 W1 digest 是 `776949...`，不可整份复用 |
| 03 | 齐：source `d82d39...`，resource `ea1399...`，W1 `0ffe45...`/37，native `5a6488...`，parser `ddb9e3...`；2 个真实 locators已验证 | 未找到 | BLOCKER：只能形成 SourceBlock/source-seal材料，不能形成完整真实 C live receipt |
| 04 | 齐：source `aed62b...`，resource `10d8ea...`，W1 `7c9bf9...`/9，native `64dc87...`，parser `ddb9e3...`；1 个真实 locator已验证 | 未找到 | BLOCKER：同 03 |

01 的“可重绑定”只复用既有 G1 admission identity；不得把旧 C5 W1 receipt、旧 locator或 native hash冒充当前 W1 authority。target clone readback仍应逐字段确认 scope/source row。

## 02 在 target backfill 后必须补齐

1. 保存服务器实际返回的 `revision_source_id`；旧 C5 值 `89944f...`只能在实际返回并按 source-ID 公式验证相等后接受，不能预写。
2. 从 target source row readback保存 `resource_id`、binding digest、retention state，并与 file/size/mime/page/attempt核对；HTTP 回执本身缺 `resource_id`。
3. 使用 actual W1 descriptor/chunks重算并绑定 `9995d0...`/79；旧 C5 live receipt 的 W1 digest `b7fe2c...`已过期，不可整份复用。
4. 02 已有既有 G1/C5 admission 三元组：`ec01-brochure-parse-attempt-1`、parsed `081bc1...`、parse-manifest `108535...`；仅作为既有 admission 输入，与 target actual source/W1重新计算 current live receipt hash。
5. SourceBlock必须取 current 79 chunks 的 actual block ID/text，以 saved native `a94120...`、parser `ddb9e3...`做 quote/page 唯一 join；不能复用旧 C5 locator。保存 `native_capture_sha256` 与 W1 `parse_hash`为不同字段。
6. C `CorpusEntryV1` 另需真实 `SourceProvenanceV1` declaration/acquisition receipt；当前 corpus inventory只是文件清单，不等于该声明。此项不影响 source seal，但在组完整 C corpus 前仍需现有摄取账本提供，不能由 proposal生成。

最小接线边界：upload runner可先完成/核验 15 个 actual W1 revisions、source seals、source-row readback和 saved native identities；不要在同一步宣称已生成完整 C corpus。随后用既有 admission对象重绑定 01/02；03/04及其余没有 admission 三元组的材料必须先接上现有 parsed-document admission路径，不能新增第二协议或用占位 hash。

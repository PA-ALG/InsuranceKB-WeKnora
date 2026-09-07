# C/D 原文多行兼容修订 7

状态：DESIGN_PENDING_INDEPENDENT_REVIEW。实际旧 base 的 21 SourceBlock / 134 fields 中发现 27 个含正文换行的值；C 的 CorpusEntry/Proposal Evidence 同样内联正文。当前 `schema_wiki_canonical_bytes` 拒绝全部控制字符，不能处理这些已存在的合法 G2 数据。本修订回到有界合同设计，不改写、删减或规范化原文。原独立 56/root73 软件测试记录保留，但 C 真实多行输入及 D 完整 fixture 暂时 BLOCKED。

## 唯一选择：复用已有 G2 正文 canonical，保留 G3 域

仅为 C/D 增加 `batch_canonical_830_g3.py` 内的 `batch_canonical_bytes_830_g3(object_type, payload)` 与 `batch_sha256_830_g3(object_type, payload)`：

- bytes 直接复用现有 `concept_canonical_bytes(object_type, payload)`，不重写 JSON canonical，不使用会追加 `.830.g2.v1` 的 G2 `digest(kind, value)`。
- SHA 为上述 bytes 的 SHA-256。前缀仍为 `schema-wiki-canonical.v1\x00`，随后是原冻结的完整 G3 object_type ASCII bytes、一个 NUL 和 canonical JSON；所有 C/D 域、排除自身 hash 的规则、各 hash 字段名称不变。
- 仅正文 string value 允许既有 G2 的 TAB/LF/CR；其他 U+0000—001F 控制字符和 U+007F 拒绝；NFC、无 binary float、UTF-8、对象键严格 control-free 和排序均直接沿 G2 helper。LF 与 CRLF 不转换，相同文字使用不同换行时必须产生不同 hash。
- C/D 的结构化 `Text` 字段继续 control-free：在 C `_text` 明确拒绝全部 U+0000—001F 及 U+007F。这使 material_id、proposal_ref、rule_id、queue_id、scope、名称/代码/版本等结构化文本继续遵守此前 hash 入口隐含的拒绝边界。D 复用该 Text。原文 `SourceBlock.text`、`Evidence.quote`、G2 FieldAssertion/value/unknown_reason/free page、ExecutionRecord.raw 使用既有 G2 类型及正文 canonical，不借此修改正文内容。
- 不修改共享 `schema_wiki_contracts.py`、G2 helper、Catalog/Profile 或原 release；原 Catalog/hash/两条 unknown alignment exact fixture 不重生。对同时被旧 helper 和新 helper 接受的 payload，两者 preimage/hash 必须逐字相等；非法 map key 不属于兼容承诺，继续按 G2 拒绝。

## Python / Go / 合同接线

- C 所有 G3 hash 调用改用新的 `batch_sha256_830_g3`，涵盖 source provenance、corpus entry/batch、proposal/receipt binding、existing snapshot、policy、decisions、candidate 和 batch。不改变算法字段或 C 处置逻辑。真实正文此前没有可用旧 hash，禁止把这项扩展宣称为已跑真实批次。
- D v2 文本中用于 **G3 新对象** 的 `schema_wiki_sha256(domain,payload)` 公式统一按本修订解释为 `batch_sha256_830_g3(domain,payload)`；binding/request/carry context/model execution/manifest/member/bundle 等原域全部不变。G2 对象自身 hash/ExecutionRecord 原形、Catalog 自身重算仍调用各自原 helper。
- Go 在现有 D types 文件中复用同包 `conceptCanonicalJSON830G2` 生成正文 JSON，加原 G3 domain 与同一 prefix/NUL 后 SHA-256；不得调用追加 G2 suffix 的 `conceptDigest830G2`。G3 结构化文本校验继续拒绝控制字符，原 G2 raw 字段保留原规则。
- 没有 full payload 改成引用 hash 的新协议，没有第二权威，没有正文清洗步骤。

## 首个修复切片及有界验证

唯一 Owner 仍为 g3_catalog_impl。根先冻结修订和 owner matrix，再开放新 common helper/test 与原 C 两文件的兼容修复；原 D 写域不扩大到 handler/service/UI。

1. 保存实际旧 base 与 C 多行 payload 在旧 helper 上失败的原始检查，环境/import 错误不算 RED。
2. C 多行 SourceBlock/Evidence 的真实类型 round trip、hash、现有处理流程通过；不同 LF/CRLF hash 不同，正文逐字保留。G3 结构化标识符含 TAB/LF/CR/NUL/DEL 都拒绝；正文 NUL/DEL、非 NFC、binary float、控制字符对象键均拒绝。
3. control-free 旧 C 向量及全部 A/C 回归继续通过；既有 Catalog、旧 G2 数据、两条 alignment exact fixture hash 不变。
4. D actual134 carry / 完整342 fixture 使用原文，通过 Python/Go 同一 canonical 跨语言向量，三 raw 与所有 source closure 纳入真实 serializer 容量测量。8 MiB 门禁及真实执行分层不变。
5. 先独立复核 C/common 兼容修复并冻结精确 SHA，再恢复完整 D DTO/fixture；不把同一问题继续堆叠为未审补丁。

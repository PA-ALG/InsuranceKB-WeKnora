# C 消费当前来源登记回执：兼容修订 8

状态：DESIGN_PENDING_INDEPENDENT_REVIEW。依据 `c-source-receipt-contract-correction-01.md`：现有 596-1 LiveReceipt 的三个 admission 字段没有被 C 身份/分类规则消费；仓库没有通用 W1/native→596-1 admission 路径。不得给 G3 新建 admission/Q0 前置，也不得用 native/markdown hash 冒充 parsed document/parse manifest。本修订只接上现有来源登记 HTTP 数据，source-only 上传执行器继续按原范围执行。

## 唯一输入变化

在原 C 模块增加严格的 `RegisteredSourceReceipt830G3V1`，它逐字段镜像现有 `internal/handler/knowledge_revision_source.go` 的 `knowledgeRevisionSourceReceiptV1`，不产生新服务端合同或来源权威：

```text
contract = knowledge-revision-source.v1
knowledge_id: Text
parse_attempt: positive strict int
revision_source_id: Hash
file_sha256: Hash
object_sha256: Hash
size: positive strict int
mime_type: Text
page_count: positive strict int
manifest_algorithm = weknora.chunk_manifest.v1
manifest_digest: Hash
chunk_count: positive strict int
binding_digest: Hash
retention_state: Text
```

全部键必传、禁止额外键，结构化字符串按修订7递归拒绝控制字符。字段值从 actual HTTP data 保存，不加 resource_id、C5 admission 字段或虚构的 service self-hash。它的完整 exact 内容由已有 CorpusEntry.entry_sha256 和 frozen capture/provenance 绑定；revision_source_id 和 binding_digest 是实际服务器给出的不透明身份，C 不反推 resource_id，不假称重算了服务器 source ID/binding digest。

`CorpusEntryV1.receipt` 扩展为由 `contract` 明确区分的两种既有合同：原 `LiveRevisionSourceReceiptV1` 或新增镜像 `RegisteredSourceReceipt830G3V1`。原 receipt 格式及其校验原样保留供已冻结历史向量/已存在 C5 输入复用，不为新材料构造旧格式。当前 G3 15 件真实批次统一优先消费新镜像。外层 Corpus/Entry/output 的 v1 合同、hash 域、字段名和现有 control-free 旧向量保持；这是首次真实批次前的 tagged leaf 兼容扩展，不能让一个 contract 字符串同时对应两种不同形状。

不得放宽为任意 dict、凭字段存在猜格式、把某类缺键补空值，或把两个 receipt 字段混成一份。已存在的 legacy receipt 自校验、scope 比较和行为继续原样；未知 receipt contract 或混合 shape 在输入阶段拒绝。

## C 的实际检查与 scope

两种 receipt 只通过显式分支提取已有规则需要的知识 ID、attempt、source ID、原文件 SHA、W1 manifest、页数和 chunk count。Registered 分支用 parse_attempt/manifest_digest；Legacy 分支继续用 weknora_parse_attempt/weknora_manifest_digest。禁止将 native_capture hash 或 C5 parse_manifest 填到 W1 parse_hash。

- 所有 SourceBlock 的 tenant/space/raw KB 必须与 BatchCorpus exact scope 相等；knowledge_id/parse_attempt/revision_id/source_hash/parse_hash/page bounds/parser identity 必须与对应 receipt/native binding 精确一致。Legacy 额外保留 receipt 自带四维 scope 比较。
- Registered receipt 本身不带 tenant/KB，不能声称 HTTP 返回了这些字段。冻结真实 corpus 的摄取方必须实际读取对应知识/版本信息并核实 authenticated tenant、RAW KB、knowledge ID 与 Batch scope；将该读取与 backfill、完整 W1 manifest 重算、native 捕获 identity 一起保存在 acquisition receipt，SourceProvenance.acquisition_receipt_sha256 指向其 exact bytes。模型不得生成 provenance 声明，也不得给另一个 scope 的回执套本批 scope。
- Registered 的 object_sha256 必须等于 file_sha256，retention_state 必须为 pinned；不符属于单材料 SOURCE_RECEIPT_MISMATCH/QUARANTINE，不能静默使用。其余 hash/计数字段先通过严格结构校验。现有结构合法单材料失败与整个合同失败的边界不变。
- C 只消费已冻结实际摄取快照并生成候选，不替代服务端权限或 source authority。D prepare/review/activate 必须从现有服务端 source/revision/knowledge/chunks 权威重新读取 scope 和完整 Registered receipt 各字段进行比较，并沿原 native quote/custody 验证；不能仅信任客户端 hash 或未经重开的 receipt。无需新增 HTTP 路由、数据库列/表或 serving Head。
- D 旧 base 的 G1/C5 carryover 权威链仍按原方案重开；新 C 来源登记格式不改写历史 source/locator，也不免除该链。

`CorpusEntry.native_capture_sha256`/parser binding/SourceProvenance 仍各司其职；captured native 只是来源定位材料，不冒充 admitted parse 或 source seal。Unicode W1 block offset 与 native global offset 必须通过 unique quote join 对齐，不能直接互搬。

## 写域、顺序与验证

Owner 仍为 g3_catalog_impl，仅在修订7 C/common修复闭合后更改原 C 模块/test；不改既有 LiveReceipt/shared helper 或来源服务。D 恢复时在已授权 types/fixture 中消费两个明确 receipt tags，Go 与 Python 必须一致，不得忽略新分支。

最小 RED/GREEN：旧 C DTO 拒绝 actual 当前 HTTP data；镜像回执 round-trip 原字节字段/值相等；已冻结 legacy 向量继续通过；未知 contract/缺键/额外 admission 字段/混合 shape 拒绝；scope/attempt/source/hash/page/parser 错配仍 QUARANTINE；Registered object/file mismatch 或非 pinned 仍 QUARANTINE；有效 Registered 来源可走相同 MATCH/CREATE/MULTI 规则且语义实体/版本 key 不因 receipt 类型改变。新镜像中的控制字符按修订7拒绝。至少一项 exact 已有来源的实际 HTTP receipt 可作结构向量，但不得把软件 fixture 宣称为目标 G3 已实际读取。

完成后先独立复核 C source 兼容切片，才冻结真实 C corpus/Seed/Policy。阈值、具名队列、source provenance、实际模型窗口仍各自待真实冻结。上传和来源登记不必等待本修订，不能把完成 source-only 工作写成 C 全输入完成。

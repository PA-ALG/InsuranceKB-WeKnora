# 017 增量设计

权威设计：`docs/insurance-kb/20-enterprise-runtime-foundation.md` §4。

## 包边界

新增 `insurance_harness/sources/`：

- `models.py`：SourceDocument、SourceChunk、SourceRevision；
- `protocol.py`：DocumentSource；
- `directory.py`：fixture/Golden 回放；
- `weknora.py`：只组合 adapter 暴露的领域中性方法，不写 URL；
- `lineage.py`：quote→chunk 的纯逻辑映射。

adapter 新增 metadata/download/chunks 能力和宽容响应模型。下载使用 context-managed 临时文件，调用结束清理；大小限制在 settings 配置。三个子步骤组成全有或全无的 materialization：任一步失败都不构造 SourceDocument。幂等 GET 的可重试错误沿用 adapter 退避；chunk 分页外层重试必须从第一页重新开始。

## Pipeline 接入

把 `_node_load` 的 PDF glob 与 page extraction 移入 Directory source；pipeline 只接收已经解析为 pages/chunks 的 SourceDocument。为控制改动，004 后续节点的 `DocPayload` 保持不变，只在 manifest 和最终 evidence 中附加 source identity。

## 修订与幂等

`source_revision` 使用规范化 JSON 后 sha256：file_hash、processed_at、parser fingerprint。ChangeSet external_record_id=knowledge_id，source_revision 使用该值；相同修订短路，变化修订产生 recompile。

## 血缘匹配

quote 与 chunk content 使用现有空白归一化语义；精确唯一包含为 linked，多命中不以 chunk_index 猜测。page evidence 是最低可发布锚点，chunk 是增强锚点。后续若 WeKnora 提供页级 metadata，只能以契约测试确认后作为新 mapping strategy 加入。

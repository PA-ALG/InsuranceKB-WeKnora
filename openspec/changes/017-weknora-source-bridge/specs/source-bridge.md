# 017 规格（验收条件）——SourceDocument Bridge

## B1 WeKnora 契约

- B1.1 WeKnoraKnowledge 消费 tenant_id、knowledge_base_id、file_name/type/hash、processed_at/updated_at、parse_status；
- B1.2 WeKnoraChunk 消费 id、knowledge_id、knowledge_base_id、chunk_index、start_at、end_at、content 与可用 metadata；
- B1.3 adapter 支持 `GET /api/v1/knowledge/{id}/download` 流式下载，限制最大文件大小并使用安全临时文件；
- B1.4 knowledge、download、chunks 三次响应均受同一已绑定 scope 约束；不匹配 fail closed。
- B1.5 metadata/download/chunks 的 timeout、408、429、5xx 按现有幂等 GET 退避策略重试；其他 4xx 为永久失败；流截断/hash mismatch 在完整重试预算耗尽后为永久失败；
- B1.6 chunk 分页任一页失败时丢弃本次已收集页面，整体重试从第 1 页开始，不向上层返回部分列表；下载失败或取消始终关闭响应并删除临时文件。

## B2 SourceDocument

- B2.1 SourceDocument 冻结 scope、knowledge identity、source_revision、original file digest、pages、chunks；
- B2.2 source_revision 至少由 file_hash、processed_at 与 parser fingerprint 构成，同输入可复现；
- B2.3 DocumentSource 协议有 WeKnora 与 Directory 两个实现；生产 CLI 必须显式 `--source weknora`，不得因配置缺失回退本地目录；
- B2.4 knowledge 未 completed、下载 hash 不符、扫描件无法解析时进入明确失败/死信，不开始语义抽取。
- B2.5 SourceDocument 只在 metadata、完整下载/hash、全部 chunks 和 PDF pages 成功后构造；失败 dead-letter 幂等键为 `space_id+knowledge_id+source_revision_or_unknown+stage`。

## B3 Compiler 接入

- B3.1 pipeline load 节点消费 SourceDocument，不自行 glob 生产目录；
- B3.2 004 之后的 split/route/extract/verify 行为保持兼容，replay fixture 结果不变；
- B3.3 run manifest 增加 space/knowledge/source revision/file hash/parser fingerprint；
- B3.4 同一 source revision 重跑幂等，不产生重复 ChangeSet。

## B4 Evidence 血缘

- B4.1 page/quote 仍由原 PDF 回验；禁止从 chunk_index 推断页码；
- B4.2 quote 在 chunks 中唯一归一化命中时写 chunk_id/chunk_hash；零命中写 `page_only`，多命中写 `ambiguous`；
- B4.3 ClaimEvidence 冻结 knowledge_id、raw_kb_id、source_revision、file_hash、parser_version、chunk_id/hash、lineage_status；
- B4.4 发布页面的 source_refs/chunk_refs 只能来自已验证映射，placeholder 文件名不得冒充 knowledge_id。

## B5 来源变化

- B5.1 同 knowledge_id 的 source_revision 变化后，旧 Evidence 标 stale；
- B5.2 创建幂等 recompile ChangeSet，旧 published snapshot 在新结果审核发布前保持在线；
- B5.3 来源删除沿用 retract 语义，但必须按 scope+knowledge_id 处理，不得跨空间撤回。

## B6 验收

- B6.1 respx 契约覆盖 metadata/download/chunks、分页、timeout/429/5xx、非重试 4xx、截断流、分页中途失败、临时文件清理、hash/scope/parse failure，并断言零半成品 SourceDocument；
- B6.2 live 测试完成 PDF upload→parse→bridge→compiler→pred/import，断言 evidence 可回链；
- B6.3 Ruff、mypy、非 live pytest 全绿；无 live 环境时 live 用例只可显式 skip，不得伪造成功。

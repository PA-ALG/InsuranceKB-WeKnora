# 007 · Claim 落库、增量合并 ChangeSet 与 WeKnora 发布（S2→S3 主链）

> 设计权威：docs/insurance-kb/03（Claim/Evidence/ChangeSet/版本模型、六级权威序五步裁决、三层页面模型、WeKnora 发布契约）。本提案把 03 的模型变成可运行的主链，是 master plan P0-3/P0-4 在插件架构下的落点。

## 为什么做

004 的产出还停在 pred JSONL（管道内部格式）。要成为"知识"，必须走完：**事实落库（带证据与版本）→ 第二批材料增量合并（新增/一致/冲突）→ 裁决与审核 → 编译成 wiki 页发布到 WeKnora**。这条链是"可进化知识库"命题的主干，也是回答业务问题 6/7/11（验证更新、回退、冲突采信）的实体。

## 做什么（四段，可按段拆 PR）

1. **Claim 落库**：003 的 DB 基础上加 claims / claim_evidence / change_sets / change_items / conflicts / release_snapshots 表（03 §7 剩余部分，Alembic 迁移）；pred JSONL → Claim 导入器（绑定 product_version，evidence 关联 chunk/页码；confidence 与 pending_judge 保留）；
2. **增量合并引擎**：新一批 Claim vs 已有 → add / enrich（同值追加证据，可信度上升）/ supersede / conflict / retract 五种 ChangeItem；冲突裁决严格按 03 §5 顺序（权威等级→生效时间→完整度仅排序→LLM 裁决附理由→人工），全部留痕可翻案；ChangeSet 不可变；
3. **审核与发布门禁**：ReviewItem（内容稳定 ID + 受限动作集）落表；只有 published Claim 参与页面编译；低风险 enrich 可按阈值自动通过（阈值可配，初始保守）；
4. **页面编译与 WeKnora 发布器**：published Claims → 三层页面（产品限定页为主，概念主页/义项索引首版可简化为产品页内锚点）→ Markdown 渲染 → 经 adapters/weknora 写入寿险 Wiki KB（source_refs/chunk_refs/page_metadata 按 03 §6 填法；slug 串行化；发布记录 release_snapshot，支持回滚=重发布旧快照）。

## 验收（端到端故事）

用样本构造两批材料：第一批（产品说明书）导入发布后，第二批（条款，权威更高）导入 → 断言：空字段被补全（add/enrich）、说明书与条款矛盾的字段产生 conflict 并按权威序自动裁决为条款值（留痕）、发布后 WeKnora Wiki 页可见且证据引用可跳转、回滚到第一批快照后页面内容一致恢复。全程门禁绿。

## 不做什么

- 不做审核工作台 UI（008 候选：workbench 最小版）；不做 QA 对象（P1-2 后续）；不做批量并发调度（P0.5）；WeKnora 侧仍零改动（乐观锁未合入前靠客户端串行化）。

## 依赖

003（DB/产品主数据）、004（pred 来源）；需要一个跑起来的 WeKnora 测试实例（docker compose，用于发布器 live 契约测试——无实例时 respx mock 验收，live 列遗留清单）。

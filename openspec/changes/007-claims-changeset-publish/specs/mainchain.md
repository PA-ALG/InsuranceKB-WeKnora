# 007 规格（验收条件）——S2→S3 主链：Claim 落库、增量合并、审核门禁、页面发布

> 由 proposal.md「做什么」四段推导；数据模型与裁决序以 docs/insurance-kb/03 为唯一权威
> （本 change 对 03 的修订：claims.pending_judge/schema_version 串、change_sets 幂等键列名
> source_kind、release_snapshots.rendered_pages 物化、④ LLM 裁决 claude-session 队列化）。
> 测试名引用条款编号（10 §2）。

## K1 知识域表与迁移（proposal 段 1）

- K1.1 `alembic upgrade head` 在 0001 基础上建出 claims / claim_evidence / claim_revisions /
  change_sets / change_items / conflicts / review_items / release_snapshots / snapshot_claims /
  current_release；`downgrade` 至 0001 干净回退（sqlite 测试兼容边界沿用 003 声明，db/README.md）。
- K1.2 关键约束与 03 §8 一致：claims 发布态部分唯一索引
  (product_version_id, concept_id, predicate, effective_from) WHERE status='published'
  （NULL 维度不去重，由合并引擎应用层兜底）；claim_revisions UQ(claim_id, revision_no)；
  change_sets UQ(source_kind, external_record_id, source_revision)；review_items UQ(review_key)；
  snapshot_claims UQ(snapshot_id, claim_id)。
- K1.3 claims 字段齐备：三态 value_state、状态机 status（draft/candidate/published/superseded/
  retracted）、superseded_by 自引用、confidence、pending_judge、current_revision。

## K2 pred JSONL → Claim 导入器（proposal 段 1）

- K2.1 导入绑定 product_id / product_version_id；每条 present/absent_explicitly 记录 →
  Claim + ≥1 ClaimEvidence（含页码；doc_role → authority_level 按 03 §6.1 映射）；
  confidence high/medium/low → 0.9/0.6/0.3；pending_judge 原样保留且该 Claim 永不自动通过门禁。
- K2.2 unknown 记录只落 draft 占位 Claim（禁止发布），供后批 enrich 补全；不产生审核项。
- K2.3 幂等：记录级幂等键 product+field+value_hash+source_doc——重导同批零新增
  Claim/Evidence/ChangeItem；批级幂等键落 change_sets(source_kind, external_record_id,
  source_revision)，重复批直接短路。
- K2.4 无证据的 present/absent_explicitly 记录拒绝入库（03 原则 2），计入报告。

## K3 增量合并引擎（proposal 段 2）

- K3.1 五种 ChangeItem 语义（03 §2.5）：add（库中无同主语同谓词）；enrich（同值追加证据、
  confidence 上调，或补 unknown 占位）；supersede（裁决序判新值胜，旧 Claim → superseded 且
  superseded_by 回填）；conflict（矛盾且未分胜负，或低权威新值——低权威新值只进 conflict 记录，
  不得 supersede 高权威旧值，也不落新 Claim）；retract（来源删除按证据引用计数：仍有其他证据 →
  仅移除 Evidence；证据清零 → Claim 转 retracted），全部经 ChangeSet。
- K3.2 裁决序严格 03 §6.2 逐级短路：① 权威等级 → ② 生效时间（同级且双方有 effective_from 时
  新者胜）→ ③ 完整度仅写入 completeness_cmp 排序参考、永不决定胜负 → ④ claude-session 裁决
  队列（复用 compiler judge-queue 的 JSONL 形态，零真实模型调用；回写 ConflictJudgement 后按
  llm_verdict 裁决并留痕）→ ⑤ ReviewItem。高风险字段（risk_level=high）跳过④直接⑤，且
  supersede 一律进审核（03 §2.5/§6.2）。
- K3.3 全留痕：每次应用写 ClaimRevision（before/after/actor/change_item_id/reason）；
  decision_basis 记 authority_cmp / effective_cmp / completeness_cmp / llm_verdict / reviewer；
  ChangeSet 的 source_batch 字段不可变（只允许 status 流转）。
- K3.4 冲突未决期间旧 Claim 保持 published（生产不中断），新值停 candidate。
- K3.5 可翻案：对已决审核项翻案 = 生成新 ChangeSet（manual_edit）执行反向/正向应用并留痕，
  原 ChangeSet 与原 decision_basis 不改写。（008 W2.3 对齐，2026-07-17：翻案入口为
  **两阶段**——`request_review_overturn` 先登记 pending ChangeSet + 翻案审核项走审核，
  原 ReviewItem.resolution 同样不改写；本条的反向/正向应用在翻案审核项被 approve 时执行。）

## K4 审核门禁（proposal 段 3）

- K4.1 ReviewItem 内容稳定 ID：review_key 由 sha256(type::subject_ref::predicate::value_hash)
  派生；同一逻辑审核项重复出现不重建、已决状态不丢失。
- K4.2 受限动作集 approve/reject/defer：approve 应用变更（发布新 Claim / 完成 supersede）；
  reject 拒绝（候选 Claim → retracted，旧值保持 published）；defer 保持 open；
  动作集外一律拒绝执行。
- K4.3 只有 published Claim 参与页面编译：candidate/draft/superseded/retracted 不出现在渲染产物。
- K4.4 低风险 enrich 自动通过阈值可配（HarnessSettings.merge_auto_apply_enrich +
  merge_enrich_auto_min_confidence → MergePolicy）；默认关闭 = 全部走审核（保守）；开启后仅
  risk=low 且 confidence ≥ 阈值 且非 pending_judge 的 enrich 才 auto_applied。

## K5 页面编译与发布器（proposal 段 4）

- K5.1 published Claims → 产品限定页 Markdown：按组分组渲染（基本信息/保险责任/费率与费用/
  免责与核保/理赔与服务/合同管理/疾病释义，组序沿用 compiler GROUP_ORDER 语义），每字段带证据
  角标（footnote：文档 + 页码 + 引文）；absent_explicitly 渲染为「无（文档明确说明）」并引用证据。
- K5.2 发布契约按 03 §7：slug = `product/{product_code}/{version_label}/overview`；
  source_refs = `knowledge_id|标题` 去重聚合；chunk_refs 去重聚合；page_metadata =
  {entity_ids, snapshot_id, claim_ids, compiled_at, harness_version, schema_version}；
  写入走 adapters/weknora 既有 slug 串行化客户端（已存在页面 → update，404 → create）。
- K5.3 每次发布记录 ReleaseSnapshot：冻结 (claim_id, revision_no) 集合 + 物化渲染产物
  rendered_pages，并移动 current_release 指针。
- K5.4 回滚 = 按快照重发布：页面内容与快照物化产物一致恢复、current_release 指针回切、
  生成 rollback ChangeSet 留痕（回滚本身可审计）。
- K5.5 发布器测试全部 respx mock（无 live 实例假设）；live 契约用例以 `-m live` 标记留遗留清单。

## K6 端到端故事（proposal「验收」段）

- K6.1 第一批（产品说明书，official_desc/权威2）：导入 → 全量走审核 approve → 发布；
  WeKnora 收到 create 页面调用；快照1记录且 current_release 指向它。
- K6.2 第二批（条款，terms/权威1，权威更高）：第一批的空字段被补全（add / enrich 补 unknown）；
  说明书与条款矛盾的低风险字段产生 Conflict 记录并按权威序**自动**裁决采信条款值
  （decision_basis.authority_cmp 留痕，旧 Claim → superseded）；高风险矛盾进 ReviewItem
  （旧值保持 published、新值 candidate）。
- K6.3 再发布：WeKnora 收到 update 调用，内容含条款新值；快照2成为 current。
- K6.4 回滚到快照1：重发布页面内容与首次发布逐字一致、current_release 指回快照1、
  rollback ChangeSet 留痕。
- K6.5 全程零真实模型调用、零真实 WeKnora 调用（respx 断言调用序列）。

## K7 工程门禁

- K7.1 不修改 compiler/ 与 goldenset/ 既有文件；`cd harness && uv run ruff check . &&
  uv run mypy src tests && uv run pytest -m "not live" -q` 全绿，既有测试零破坏。

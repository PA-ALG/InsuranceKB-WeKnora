# 010 任务（TDD 顺序；测试名引用条款号）

> 五版（2026-07-16，按 PR #11 四轮封板清单固定）：快照 v2 正式版本化 + 批次指纹 + mapping manifest。**T1~T4 即刻；T5 起基于 021 合入后的 main**（018→021→020 关键路径不变）。执行者 C3；knowledge 域全量 **Owner-A 复审**。
> **实现文件域（固定清单）**：`knowledge/tables.py`、`knowledge/models.py`、`knowledge/merge.py`、`knowledge/pages.py`、`knowledge/snapshots.py`、`knowledge/reader.py`、迁移 `0007`、structured importer/mapping 新模块，及对应 SQLite+PostgreSQL migration tests / domain tests / snapshot tests / MCP tests。

- [ ] T1 Space 作用域接线：显式 space fail-closed 与跨 space 不可见（I6）
- [ ] T2 通道一 bootstrap：meta → 003 注册（幂等、dry-run），零 Claim/Evidence 断言（I1）
- [ ] T3 来源登记表：加载 fail-fast + 未登记来源拒绝（I1/I3；authority_level 表达可信度，无 data_quality）
- [ ] T4 映射加载 + 规范化 + 候选草案 + **mapping_manifest 四元组与 effective_mapping_version**（I2/I4）
- [ ] T5 迁移 0007（**基于 021 后 main**）：structured_source_records（id PK、无批次外键、UPDATE+DELETE 双方言触发器拒绝）+ **structured_import_batch_records 关联表（append-only，双方言拒 UPDATE/DELETE）** + claim_evidence 三值 source_kind（nullable→回填→收紧）+ **ChangeSet 增列、CHECK（structured_import ⇒ 三字段非空）与两条精确 predicate 的 partial unique index** + **read_model_version CHECK (0,1,2)** + 有条件 downgrade（I4/I9）
- [ ] T6 领域模型：ProposedEvidence kind 分支 + 既有 weknora/legacy 行为不变回归；merge 接线（持久化/去重键含 structured 身份+mapping_version/space 一致性 fail-closed）（I4）
- [ ] T7 发布/冻结 v2：pages structured 验证（canonical hash 重算；篡改/缺失拒发；legacy 不可发布）+ FrozenEvidence v2 判别联合 + Reader 严格读 v1/v2（无 extra=ignore）+ **v2 writer rollout gate** + 回滚仅指针 + 冻结后源表不可访问仍可读（I4）
- [ ] T8 通道二导入：双轴幂等 no-op / 同键异 hash collision / **mapping 变化→新 fingerprint 新 ChangeSet、复用原 record 追加关联行 + 同值 enrich 不 skip** / 一批 N 记录一个 ChangeSet+N 关联+重试关联零新增 / per-source 并发单一有效结果（对齐 021 模式）（I5/I9/I6）
- [ ] T9 批次报告/错误隔离 + dry-run 默认与 apply 一致性（I5）
- [ ] T10 产品对齐一对多 + FAQ → qa_staging（I7）
- [ ] T11 端到端：bootstrap + 双 revision 冲突 + 碰撞/重算 + 发布链回溯（冻结 provenance 全套、零回查、零伪引用）（I8）
- [ ] T12 收尾：validation-report（含下方七组验收矩阵逐项证据 + Q020 合规 + Owner-A 复审记录）→ HANDOFF 更新

## 验收矩阵（七组，逐项可运行；validation-report 按此对账）

1. **Migration**：source_kind 回填正确；三分支 CHECK；源表与**批次关联表** UPDATE/DELETE 拒绝；ChangeSet structured_import 三字段非空 CHECK 与精确 predicate 双 partial index；version CHECK(0,1,2)；空数据可 downgrade、有 structured/v2 数据 downgrade fail-closed——SQLite 与 PostgreSQL 都跑（I4/I9）
2. **Identity/幂等**：同键同 hash 同 mapping no-op；同键异 hash collision；同 hash 新 mapping 新 ChangeSet；**同一 source record 关联两个不同 mapping 的 ChangeSet 且 id/raw_payload 不变**（`test_i9_same_record_linked_to_two_mapping_changesets_immutable`）；同值 enrich 新 Evidence 不 skip；一批 N 记录一个 ChangeSet+N 关联、重试关联零新增；并发同源仅一个有效结果（I5/I9/I6）
3. **Domain/租户**：weknora/legacy 既有接受与拒绝语义不变；structured 跨 Space 拒绝；aggregate/enrich 不丢 structured 身份（I4）
4. **Publish/冻结**：篡改 hash 拒发；legacy 不可发布；v2 冻结后源表不可访问仍返回相同 locator/hash/version；零伪 page/chunk（I4）
5. **兼容/回滚**：v1 历史严格可读；v2 可读；v2→v1 回滚可读；混合历史可枚举；v2 writer gate 有测试或显式部署检查（I4）
6. **MCP**：structured 证据返回冻结 locator/revision/hash/mapping_version、无虚构页码；真实 WeKnora 挂载未跑标 NOT RUN（013 M1/M5 联测）
7. **Spec gates**：openspec strict 全绿；diff --check 全绿；旧承诺（data_quality/unknown-fields-tolerated/旧排序）残留扫描为零

约束：零模型调用；不改 compiler/ 与 goldenset/；Evidence 不伪造页码/chunk；源记录表 insert-only；合规删除须另立 purge change。
状态：**可认领**（T1~T4 即刻；T5 起等 018+021 合入）。依赖：003/007/016/017 已合入。

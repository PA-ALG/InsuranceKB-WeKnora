# 018 任务

- [x] T1 先写 `R1.1～R1.4` migration/legacy/freeze-marker/immutability/零事实投影 RED，再实现 `0005`、SnapshotFact 与完整 Space 投影构建器
- [x] T2 先写 `R2.1～R2.4` current/filter/effective-date/五类 gap/scope RED，再实现 SnapshotReader
- [x] T3 先写 `R2.3/R6.1` frozen fact renderer 与产品 A/B 完整性 RED，再切换页面编译数据源
- [x] T4 先写 `R3.1～R3.6` 状态机、lease recovery、多页失败、collision、attempt、service-owned Session RED，再实现 ReleaseOperation/PublishAttempt 与 plan executor
- [x] T5 先写 `R4.1～R4.5/R6.2～R6.3` 回滚失败、same-plan retry、补偿、managed ownership 与并发 RED，再实现 reconciliation
- [x] T6 先写 `R5.1～R5.3` curated-first/same-scope raw fallback RED，再实现 provider protocol 与 policy（不实现搜索引擎）
- [x] T7 按 `R6.4` 完成 PostgreSQL integration、真实 Wiki V1→V2→rollback live gate、Runbook、validation-report、HANDOFF/13/16/20 对账

## PR review hardening（2026-07-15）

- [x] RH1 `R3.7` 使 007 legacy support 对三个退休 helper 自包含，删除仅由测试 import 存活的 production helpers，并补 production boundary 测试
- [x] RH2 `R6.4/R2.1` 启用 deterministic SQLite FK、以复合 FK 失败验真，并构造真实跨 Space pointer target
- [x] RH3 `R3.1` 补 failed plan base 已变化时零 retry/attempt/Wiki/current 副作用的回归测试
- [x] RH4 `R3.4/R4.2` 区分首动作 collision 的零补偿语义，并统一 rollback lease recovery ChangeSet 为 partially_applied
- [x] RH5 `R6.4` 将 0005 合约测试固定到 revision 0005、移除 018 live search_path 的 public fallback，刷新 validation-report 实测计数
- [x] RH6 运行 OpenSpec strict、Ruff、mypy strict、deterministic、PostgreSQL integration，并以 023 受信环境运行 5-node WeKnora live 零 skip门禁

状态：018 已随 PR #9 合入 `main`（merge `b093a447`）。最终实现 head `44d5d7df` 通过 OpenSpec strict、Ruff、mypy strict 201 files、deterministic `1504 passed / 7 deselected`、PostgreSQL `2 passed / 1509 deselected / skipped=0`、clean-SHA VLM OCR=1/Caption=1 与本机受控 5-node `5 passed / tests=5 / skipped=0`；同 head 的两组 deterministic 与两组 PostgreSQL GitHub CI 均绿。正式 GitHub exact-SHA live 的 run URL、JUnit 与 cleanup 只记录在收尾 PR check/comment，避免提交证据后改变被验收 SHA。018 独占 migration `0005`，现已解锁 021。

裁决记录（2026-07-15）：

- Alembic 多 revision downgrade 在 SQLite 上不是整条命令原子执行；`head → 0002` 若等到 `0003` 才校验，会先永久删除 `0005` 的四张表。`0005` 因此仅在最终目标跨过 `0003` 时镜像执行 0003 兼容性预检，拒绝后 schema 与 `alembic_version` 均停在 head；直接 `0005 → 0004` 不触发该预检，保留 R1.4 的安全降级能力。
- T4 已由 PR #9 PostgreSQL 16 零 skip job验收；T7 最终五节点包含 001/007/017/018 共五个真实节点，结果 `tests=5 skipped=0`。
- live 首次执行暴露 WeKnora 将空 `in_links/out_links` 返回为 `null`；先补 `test_s2_4_wiki_response_normalizes_null_link_lists` RED，再仅规范化为空列表，随后全量门禁与五节点复跑全绿。

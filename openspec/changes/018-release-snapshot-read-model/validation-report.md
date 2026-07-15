# 018 ReleaseSnapshot 统一读模型验证报告

> 日期：2026-07-15。本报告区分 deterministic、PostgreSQL integration 与真实 WeKnora live；collection、mock、skip 或更早 commit 的绿灯均不替代当前外部证据。

## 1. 当前状态

| 层级 | 状态 | 证据/下一步 |
|---|---|---|
| T1～T3 | PASS | `0005`/SnapshotFact/guard、pointer-only Reader、frozen renderer 已完成 |
| T4 | 软件实现完成，外部证据待跑 | publish state machine、attempt/job、retry/lease、Engine+Space lock、write-readback 与 final commit failure 已覆盖；新增 PostgreSQL caller-transaction 节点 |
| T5 | PASS | rollback/reconciliation、legacy/successor/historical slug 与 R6.1～R6.3 组合故事已完成 |
| T6 | PASS | typed gap-only RAW、same-scope、`unreviewed_raw`、零 writeback |
| PostgreSQL 16 integration | `NOT RUN` | 本机未提供 `HARNESS_TEST_POSTGRES_URL`；不得把显式 fail 或 collection 当成功，待当前 SHA 的 CI job |
| WeKnora live | `NOT RUN` | 本机缺受控 `HARNESS_LIVE_*`；精确节点结果为 skip，待 `harness-live` workflow 零 skip 证据 |
| T7 文档/本地门禁 | PASS | Runbook、13/16/20/HANDOFF 已对账；OpenSpec strict、Ruff、mypy strict、deterministic 全量门禁通过；whole-change spec/quality 双审通过，待外部 lane |

## 2. 实现与风险闭环

- SnapshotFact 冻结产品展示、revision/value/effective date 与完整 017 Evidence；legacy rows 保留为 read-model v0，不伪造历史投影。
- SnapshotReader 只沿当前 v1 pointer，提供五类 typed gap、稳定过滤/排序，并以 SQL spy 禁止读取 mutable Claim/Evidence。
- ReleasePublisher 使用注入的 SessionFactory 分阶段提交；计划先冻结、Wiki 全成功且 base 未变后才移动 pointer。失败保留 attempt/job，可 same-plan retry 或按执行时 current 精确 reconciliation。
- managed ownership 要求 `managed_by/space_id/snapshot_id`；create/update 后 GET 回读，静默错写会让 operation/snapshot 失败且 pointer 不动。
- `(Engine, space_id)` 进程内共享锁覆盖多个 publisher 实例与 lease recovery；多实例互斥仍不在 018 声明范围。
- reconciliation 覆盖无 current、version-0 legacy、历史非 current managed slug、DELETE 404、failed child requeue 与 changed-current successor；过期 child 只更新原 source job，禁止嵌套工单。
- RAW fallback 只消费 typed gap；任何跨 `space_id/raw_kb_id` hit 整体 fail closed，curated facts 永不调用或合并 RAW。

## 3. TDD 与自检修复

实施按 schema/migration/guard、projection、reader、renderer、plan、saga、reconciliation、fallback 小闭环执行。主代理和两次 10 分钟只读审计发现并补 RED 的关键问题包括：migration 默认伪 legacy、metadata DDL 重复执行、旧读侧覆盖丢失、publisher 实例锁不共享、缺写后回读、缺 snapshot ownership、recovery 绕锁、过期 reconcile child 嵌套工单，以及 legacy replay 被新 managed 回读规则误伤。

首次全量 deterministic 另发现 7 个 016 migration 回归：新增 `0005` 后，`head → 0002` 会在 `0003` 拒绝前先删除 018 表，且一个旧测试写死 head=`0004`。保留这些 RED 后，将 0003 兼容性预检前移到跨版本命令的首个 DDL 之前，并把 head 断言改为动态解析；聚焦复验 `7 passed`。

whole-change 规格复核发现旧 caller-Session `publish_product_version/rollback_to_snapshot` 仍从生产包公开，可绕过完整 Space projection、durable saga 与 pointer-last。两个 package contract 用例先 RED，再把历史行为完全移到 `tests/support/legacy_publisher_007.py`，并从生产模块、包 import 与 `__all__` 同时移除；规格复审结果为 `Spec compliant: yes`。

独立 quality review 的五项意见均经精确 RED 验证并闭环：新快照默认 `building` 且 pointer 必须指向 published/v1/frozen 投影；共享锁覆盖 build/activate/Wiki/finalize 整个 saga；退休实现不再存在于生产模块；成功 reconciliation 从原 plan snapshot 返回一致 pages；现有 PostgreSQL 节点追加 pointer、SnapshotFact、frozen operation 与 published snapshot 触发器验收。随后全量门禁发现并修正两个依赖旧发布默认值的 017 fixture，精确回归 `2 passed`。

本次长时间零产出事故与强制止损规则已写入 `HANDOFF.md` 0g/坑 11～13：30 分钟产出时钟、60 秒无输出处理、10 分钟黑盒上限、主会话接管和真实 RED/GREEN 状态语言。

## 4. 当前本地证据

以下均为当前工作树的 fresh 本地证据：

```text
pytest tests/test_*_018.py -m "not live and not integration_postgres" -q
73 passed, 2 deselected, 26 warnings in 6.86s

pytest tests/test_release_snapshot_migration_018.py tests/test_scope_migration_016.py -q
29 passed

openspec validate 018-release-snapshot-read-model --strict
Change '018-release-snapshot-read-model' is valid

uv run ruff check .
All checks passed

uv run mypy src tests
Success: no issues found in 171 source files

uv run pytest -m "not live and not integration_postgres" -q
1035 passed, 7 deselected, 235 warnings in 98.92s

pytest tests/test_ci_lanes_022.py::test_p0_4_three_collections_are_disjoint_exhaustive_and_precise -q
1 passed

pytest tests/test_release_snapshot_live_018.py -q -rs
1 skipped（缺 HARNESS_LIVE_*；NOT RUN）
```

PostgreSQL 节点在缺 URL 时被 lane contract 验证为显式失败而非 skip。尚无当前 SHA 的 PostgreSQL 16 run URL，也无受控 WeKnora live run URL，因此两层均保持 `NOT RUN`。

## 5. 独立复审与待完成

whole-change 规格复审：`Spec compliant: yes`。最终只读质量复审：`Quality approved: yes`，无剩余 Critical、Important 或 Minor。

仅余推送后等待当前 SHA 的 deterministic 与 PostgreSQL 16 zero-skip CI；真实 WeKnora 仍需单独手工受控 workflow。

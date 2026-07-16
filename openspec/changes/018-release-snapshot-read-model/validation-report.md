# 018 ReleaseSnapshot 统一读模型验证报告

> 日期：2026-07-16。本报告区分 deterministic、PostgreSQL integration 与真实 WeKnora live；collection、mock、skip、更早 commit 或未提交工作树的本地证据均不替代最终 PR head 的 CI/live 证据。

## 1. 当前状态

| 层级 | 状态 | 证据/下一步 |
|---|---|---|
| T1～T3 | PASS | `0005`/SnapshotFact/guard、pointer-only Reader、frozen renderer 已完成 |
| T4 | PASS | publish state machine、attempt/job、retry/lease、Engine+Space lock、write-readback 与 final commit failure 已覆盖；PostgreSQL 16 service-owned Session/DB guards 零 skip 验收通过 |
| T5 | PASS | rollback/reconciliation、legacy/successor/historical slug 与 R6.1～R6.3 组合故事已完成 |
| T6 | PASS | typed gap-only RAW、same-scope、`unreviewed_raw`、零 writeback |
| PostgreSQL 16 integration | PASS（本地工作树） | `postgres:16` healthy 容器上两节点零 skip：`2 passed, 1229 deselected`；最终 PR head 仍须 CI 重跑 |
| PR review hardening RH1～RH5 | PASS | retired helper boundary、SQLite FK、stale-base retry、collision/recovery、migration/live schema isolation 均按 TDD 完成并通过 task-level spec/quality 双审 |
| WeKnora live | `NOT RUN` | PR #10 仍为 Draft/open；本批未在最终 PR #9 head 上运行受控 5-node live，PostgreSQL 与本机 deterministic 不替代该证据 |
| T7 文档/本地门禁 | PARTIAL | Runbook/report/HANDOFF 与 software/PostgreSQL 门禁已刷新；T7/RH6 继续等待 PR #10 合入和最终 head 的真实 WeKnora `tests=5 skipped=0` |

## 2. 实现与风险闭环

- SnapshotFact 冻结产品展示、revision/value/effective date 与完整 017 Evidence；legacy rows 保留为 read-model v0，不伪造历史投影。
- SnapshotReader 只沿当前 v1 pointer，提供五类 typed gap、稳定过滤/排序，并以 SQL spy 禁止读取 mutable Claim/Evidence。
- ReleasePublisher 使用注入的 SessionFactory 分阶段提交；计划先冻结、Wiki 全成功且 base 未变后才移动 pointer。失败保留 attempt/job，可 same-plan retry 或按执行时 current 精确 reconciliation。
- managed ownership 要求 `managed_by/space_id/snapshot_id`；create/update 后 GET 回读，静默错写会让 operation/snapshot 失败且 pointer 不动。
- `(Engine, space_id)` 进程内共享锁覆盖多个 publisher 实例与 lease recovery；多实例互斥仍不在 018 声明范围。
- reconciliation 覆盖无 current、version-0 legacy、历史非 current managed slug、DELETE 404、failed child requeue 与 changed-current successor；过期 child 只更新原 source job，禁止嵌套工单。
- RAW fallback 只消费 typed gap；任何跨 `space_id/raw_kb_id` hit 整体 fail closed，curated facts 永不调用或合并 RAW。
- review hardening 将三个 007-only helper 移到 test support；deterministic `kb_session` 对每个 SQLite 连接启用 FK，真实跨 Space pointer 与不受 trigger 遮蔽的复合 FK 均由数据库拒绝。
- stale-base retry 在 current 已变化时不修改 retry/attempt/Wiki/current/job；ownership collision 仅在整个 operation 历史可证明零 mutation 时省略 reconciliation job。
- rollback lease recovery 与在线失败统一把 ChangeSet 记为 `partially_applied`；0005 合约测试不再漂移到未来 head，018 live PostgreSQL search path 不再回退 `public`。

## 3. TDD 与自检修复

实施按 schema/migration/guard、projection、reader、renderer、plan、saga、reconciliation、fallback 小闭环执行。主代理和两次 10 分钟只读审计发现并补 RED 的关键问题包括：migration 默认伪 legacy、metadata DDL 重复执行、旧读侧覆盖丢失、publisher 实例锁不共享、缺写后回读、缺 snapshot ownership、recovery 绕锁、过期 reconcile child 嵌套工单，以及 legacy replay 被新 managed 回读规则误伤。

首次全量 deterministic 另发现 7 个 016 migration 回归：新增 `0005` 后，`head → 0002` 会在 `0003` 拒绝前先删除 018 表，且一个旧测试写死 head=`0004`。保留这些 RED 后，将 0003 兼容性预检前移到跨版本命令的首个 DDL 之前，并把 head 断言改为动态解析；聚焦复验 `7 passed`。

whole-change 规格复核发现旧 caller-Session `publish_product_version/rollback_to_snapshot` 仍从生产包公开，可绕过完整 Space projection、durable saga 与 pointer-last。两个 package contract 用例先 RED，再把历史行为完全移到 `tests/support/legacy_publisher_007.py`，并从生产模块、包 import 与 `__all__` 同时移除；规格复审结果为 `Spec compliant: yes`。

独立 quality review 的五项意见均经精确 RED 验证并闭环：新快照默认 `building` 且 pointer 必须指向 published/v1/frozen 投影；共享锁覆盖 build/activate/Wiki/finalize 整个 saga；退休实现不再存在于生产模块；成功 reconciliation 从原 plan snapshot 返回一致 pages；现有 PostgreSQL 节点追加 pointer、SnapshotFact、frozen operation 与 published snapshot 触发器验收。随后全量门禁发现并修正两个依赖旧发布默认值的 017 fixture，精确回归 `2 passed`。

本次长时间零产出事故与强制止损规则已写入 `HANDOFF.md` 0g/坑 11～13：30 分钟产出时钟、60 秒无输出处理、10 分钟黑盒上限、主会话接管和真实 RED/GREEN 状态语言。

2026-07-16 review hardening 按 RH1～RH5 分成独立闭环。关键 RED 包括：production 暴露退休 helper；SQLite `PRAGMA foreign_keys=0`；首动作 collision 错建工单；过期 rollback ChangeSet 遗留 pending；live search path 含 `public`。stale-base guard 已存在，因此用临时 mutation 绕过 guard，测试按预期因 `retry_no` 变化失败，恢复后 publisher 文件哈希一致。开启 SQLite FK 后，完整 deterministic 还发现两个 016 防御测试无法再制造历史损坏态；测试现只在局部 context 中显式关闭 FK，验证 application fail-closed 后在 `finally` 恢复 FK=1，未削弱全局 fixture。

## 4. 当前本地证据

以下均为分支 `codex/018-release-snapshot-read-model`、base HEAD `8df6c3cf` 上未提交工作树的 fresh 本地证据；因此可用于提交前验收，不能冒充远端 PR #9 新 SHA 的 CI 结果：

```text
openspec validate 018-release-snapshot-read-model --strict
Change '018-release-snapshot-read-model' is valid

.venv/bin/python -m ruff check .
All checks passed

.venv/bin/python -m mypy src tests
Success: no issues found in 181 source files

.venv/bin/python -m pytest -m "not live and not integration_postgres" -q
1224 passed, 7 deselected, 235 warnings in 96.78s

HARNESS_TEST_POSTGRES_URL=<redacted> .venv/bin/python -m pytest -m integration_postgres -q
2 passed, 1229 deselected in 1.75s

focused RH1/RH2/RH3/RH4/RH5
45 passed + 1 existing skip；14 passed；13 passed；27 passed；9 passed + 1 live deselected
```

GitHub PR #9 当前仍为 Draft，远端 head 为旧 SHA `8df6c3cf`；其 deterministic/integration checks 虽为绿灯，但不覆盖本批工作树。PR #10 当前也为 Draft/open。提交并 push 新 SHA 后必须等待 PR #9 两个新 checks 通过；PR #10 合入后再从受控 workflow 运行精确 5-node live 并取得 `tests=5 skipped=0`，才可把 T7/live 从 `NOT RUN` 改为 PASS。

## 5. 独立复审与待完成

RH1～RH5 及 016 corruption fixture 修正均已通过 task-level spec compliance 与 code quality review。最终 whole-change 规格复核结论为 `Spec compliant`：RH1～RH5 与 018 条款一致，RH6 仍如实保留外部门禁未完成。最终 whole-change 质量复核结论为 `Approved`，无剩余 Critical、Important 或 Minor finding；复核聚焦回归为 `82 passed, 1 deselected`。该结论只覆盖当前本地工作树的软件改动，不替代 PR #9 新 SHA CI、PR #10 合入或真实 WeKnora live 证据。

剩余顺序：人工复核工作树 → commit/push PR #9 新 SHA → 新 deterministic/integration checks 全绿 → PR #10 合入 → 受控 5-node WeKnora live `tests=5 skipped=0` → 更新最终证据且 Ready for review。任何 preflight failure、skip 或旧 SHA 绿灯都不能跳过该顺序。

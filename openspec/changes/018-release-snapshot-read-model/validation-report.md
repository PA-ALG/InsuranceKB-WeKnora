# 018 ReleaseSnapshot 统一读模型验证报告

> 日期：2026-07-17。deterministic、PostgreSQL integration、本机受控 live 与 GitHub exact-SHA live 分层记录；collection、mock、skip、旧 SHA 或 dirty 工作树均不能替代最终证据。

## 1. 最终状态

| 层级 | 状态 | 证据 |
|---|---|---|
| T1～T3 | PASS | `0005`、SnapshotFact/guard、pointer-only Reader、frozen renderer |
| T4 | PASS | service-owned Session、plan/attempt/job、retry/lease、Engine+Space lock、write-readback 与 PostgreSQL DB guards |
| T5 | PASS | rollback/reconciliation、legacy/successor/historical slug 与 R6.1～R6.3 |
| T6 | PASS | typed gap-only RAW、same-scope、`unreviewed_raw`、零 writeback |
| Review hardening | PASS | RH1～RH5 均按 TDD 完成；两轮独立复审与 Claude Code 跟进无剩余 finding |
| PostgreSQL 16 | PASS | 本机 `2 passed / 1509 deselected / skipped=0`；最终 head 两组 GitHub integration jobs 均绿 |
| 本机 WeKnora | PASS | ordinary PDF provision/verify、clean-SHA VLM OCR=1/Caption=1、5-node `5 passed / tests=5 / skipped=0` |
| GitHub exact-SHA live | 合并前强制 PASS | run URL、head SHA、JUnit `tests=5 skipped=0` 与 cleanup 结果记录在收尾 PR check/comment；该 PR 未通过不得合入本报告 |

018 已随 PR #9 合入 `main`，merge commit `b093a447`；最终实现 head 为 `44d5d7dfc0d121fcc51a4fb66b4c57747ddeeda6`。

## 2. 实现与风险闭环

- SnapshotFact 冻结展示值、版本/effective date 与完整 017 Evidence；legacy rows 保留为 read-model v0，不伪造历史投影。
- SnapshotReader 只沿当前 v1 pointer，提供 typed gap、稳定过滤/排序，并禁止回查 mutable Claim/Evidence。
- ReleasePublisher 使用 SessionFactory 分阶段提交；计划先冻结，Wiki 全成功且 base 未变后才移动 pointer。失败保留 attempt/job，可 same-plan retry 或按执行时 current reconciliation。
- managed ownership 强制 `managed_by/space_id/snapshot_id`；create/update 后 GET 回读，静默错写令 operation/snapshot 失败且 pointer 不动。
- `(Engine, space_id)` 进程内共享锁覆盖多个 publisher 实例与 lease recovery；021 之前不声明多进程/不同 revision ordering 安全。
- reconciliation 覆盖无 current、version-0 legacy、历史非 current slug、DELETE 404、failed child requeue 与 changed-current successor；过期 child 只更新原 source job。
- RAW fallback 只消费 typed gap；任何跨 `space_id/raw_kb_id` hit 整体 fail closed，curated facts 不合并 RAW。
- review hardening 关闭 production legacy helper 旁路，启用 SQLite FK，证明 stale-base retry 零副作用，并固定 collision/recovery、0005 与 isolated search path 合同。

## 3. 真实环境发现

最终五节点第一次执行为 2 pass / 3 fail，三项失败都来自同一个真实 API 合同：WeKnora 创建 Wiki 页时把空 `in_links/out_links` 返回为 `null`，而 Harness 模型要求 list。先新增 `test_s2_4_wiki_response_normalizes_null_link_lists` 并得到精确 RED，再仅将这两个字段的 `null` 规范为 `[]`；非空值与错误类型仍由 Pydantic 校验。修复提交 `44d5d7df` 后，完整 deterministic、PostgreSQL、VLM 与五节点全部复跑。

## 4. 最终软件与本机证据

```text
openspec validate 018-release-snapshot-read-model --strict
Change '018-release-snapshot-read-model' is valid

uv run ruff check .
All checks passed

uv run mypy src tests
Success: no issues found in 201 source files

uv run pytest -m "not live and not integration_postgres" -q
1504 passed, 7 deselected, 235 warnings

uv run pytest -m integration_postgres -q
2 passed, 1509 deselected
junit counts: tests=2 skipped=0

local_live.py provision --pdf <ordinary-insurance-pdf>
resources=11 status=provisioned

local_live.py verify
resources=11 status=verified

local_live.py smoke-vlm
dirty=false evidence=exact status=completed image_ocr_chunks=1 image_caption_chunks=1

local_live.py run-local
5 passed
status=passed tests=5 skipped=0
```

同一实现 head 的两组 deterministic 与两组 PostgreSQL CI 均为 SUCCESS。正式 GitHub live 由收尾 PR 对其 exact head 运行，外部证据不再写回提交，以免改变被验收 SHA。

## 5. 复审与交接

whole-change 规格复核结论为 `Spec compliant`，质量复核结论为 `Approved`，Claude Code 已确认历史 finding 全部关闭。真实 live 新发现也按 RED→GREEN 收口，无已知 merge blocker。

018 完成后解锁 021（migration `0006`）、013 实现与 008 W4。执行事故及强制止损规则保留在 `HANDOFF.md` 0g.1 与“踩过的坑”，后续 change 必须继续遵守。

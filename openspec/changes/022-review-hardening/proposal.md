# Change 022-review-hardening：复审意见健壮性收口

## 背景

Claude 对 016/017/022 的实现提出六项复审意见。逐项取证后，部分意见是真实缺口，部分是已完成事项或有意的 fail-closed 边界。直接按评论改代码会破坏已批准的 numeric tenant/knowledge identity、Directory eval-only 和分层测试语义。

## 目标

1. 回滚在任何 Wiki 写之前完成本地审计/指针 savepoint flush，DB 失败时零外部副作用；
2. 让“已成功处理但零 Evidence”的同 revision 通知保持幂等；
3. 明确 Directory replay 只用于评估，同时消除大小写 PDF 的静默漏发现；
4. 按字段角色收紧 WeKnora KB identity，不破坏合法 numeric tenant/knowledge identity；
5. 固化 live 测试拆分已经完成的事实，不重复迁移 node ID；
6. 修正 CLAUDE.md 与 deterministic/PostgreSQL/live 三 lane 的门禁漂移，不凭 coverage overlap 删除隔离证明。

## 非目标

- 不实现 `processed_at`、不同 revision 并发/乱序、SourceHead/CAS；这些仍归 021/B23；
- 不在本 change 内实现跨 PostgreSQL/WeKnora 的完整 saga、最终 commit failure reconciliation 或页面恢复；这些仍归 018；
- 不让 Directory replay 伪造 `knowledge_id`/`raw_kb_id`，也不把 eval artifact 降格为 legacy import；
- 不因行数、测试数或 coverage overlap 自动删除 016 scope 隔离测试；
- 不重复重命名已经只包含一个真实 live node 的 `test_source_bridge_live_017.py`。

## 交付

- `specs/review-hardening/spec.md` 中 RH1～RH6 条款；
- 每个行为变更遵循 RED→GREEN，新增/修改测试名包含对应 `rhN_M` 条款号；
- Ruff、mypy strict、deterministic pytest 全绿；PostgreSQL 由独立 CI lane 验证；
- validation report、tasks 与 HANDOFF/PR 状态对账。

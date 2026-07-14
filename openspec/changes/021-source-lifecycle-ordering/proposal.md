# 021 提案：Source Lifecycle Ordering

状态：`proposed / pending`。本变更尚未实施，不是 017 T7 已完成能力。

## 背景

017 T7 以 `(space_id, source_kind, external_record_id, source_revision)` 保证同一修订通知幂等，并可阻止同一已删除修订的迟到导入；但它没有持久化来源顺序。上游 `SourceRevision` 包含 `processed_at`，进入 `SourceImportIdentity`、Evidence 与 ChangeSet 后只剩不可排序的 SHA-256 revision。

因此，不同 revision 的并发或乱序通知、以及 delete/import 跨 key 竞争，无法仅靠现有唯一键正确裁决。锁可以串行，却不能判断迟到事件是否比当前 head 更旧。

## 目标

- 将可信 `processed_at` 或单调 `generation` 贯穿 source identity 与持久化审计。
- 为每个 `(space_id, knowledge_id)` 建立唯一、可锁定、可 CAS 的 durable SourceHead。
- 让 notify、import、retract/delete 共用同一 per-source 临界区和状态机。
- 明确定义删除 tombstone、新修订重新激活、重复/迟到/并发事件的结果。
- 用真实 PostgreSQL 竞争测试证明顺序、幂等、回滚与作用域隔离。

## 非目标

- 不改变 017 的 PDF 解析、quote-to-chunk 或 Compiler 语义。
- 不用 revision hash 字典序推断新旧。
- 不把 SQLite 锁行为当作 PostgreSQL 并发证据。

## 依赖与迁移边界

018 已预留 Alembic `0005`。021 不得占用或重排该编号；实施前须与 018 的实际合入顺序协调，选择后续串行 revision，并更新 downgrade/roll-forward 说明。

# 050 · Validation report

## Candidate identity

- base：`130e73d1607cc256c7ce956456873ca0567433d8`
- branch：`codex/050-postgres-embeddings-forward-repair`
- state：`GREEN COMPLETE / FROZEN FOR EXTERNAL REVIEW`

## Frozen root cause

- PostgreSQL 17.9；`vector=0.8.1`、`pg_search=0.22.2`、`pg_trgm=1.6`；
- current drivers：`DB_DRIVER=postgres`、`RETRIEVE_DRIVER=postgres`；
- official ledger 75 clean，`public.embeddings` absent；
- production repository INSERT/DELETE 返回 SQLSTATE `42P01`；
- ODL parse/chunk 已完成，失败只发生在 vector-store write。

## RED → GREEN

- RED：在隔离库 `weknora_embeddings_repair_test` 中先推进 official 75 与
  enterprise 2；canonical runner 返回后 `to_regclass('public.embeddings')`
  仍为null，`require.True`按预期失败。
- GREEN：enterprise `000003` 在 `app.skip_embedding=false` 且表缺失时创建
  累计schema；原四个子场景全部通过：缺表修复、健康已有表no-op、skip不误建、
  conservative down/up保留。
- corrective RED：健康表删除 `tag_id` 及其索引并保留sentinel后，旧candidate的
  SQL与canonical runner都错误接受，enterprise ledger从2推进到3。
- corrective GREEN：000003 direct branch返回SQLSTATE `55000`；canonical runner
  返回typed `MigrationSafetyError`；enterprise ledger保持2，sentinel与partial表
  字节语义不变。完整五场景matrix PASS。
- production repository：合成1024维 `BatchSave` 在真实事务中成功，rollback后
  持久行数为0。

## Fresh gates

- PostgreSQL 17.9 focused migration matrix：PASS；legacy与repair组合PASS。
- `go test ./internal/database -count=1`：PASS（PostgreSQL nodes在无DSN时按合同skip）。
- repository package compile：PASS（该包无独立test files）。
- `go vet`（database + postgres repository）：PASS。
- OpenSpec050 strict / gofmt / diff-check：PASS。
- Ruff/mypy：NOT APPLICABLE（十一条路径无Python文件）。
- exact十一路径 / private / secret：PASS；temp-index tree由交付报告绑定。
- full / provider / live / existing WeKnora DB / PDF upload/reparse：`NOT RUN`。

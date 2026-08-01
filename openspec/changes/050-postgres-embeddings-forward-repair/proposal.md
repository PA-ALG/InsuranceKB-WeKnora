# 050 · PostgreSQL embeddings forward repair

## 状态

`SPEC + TDD / IMPLEMENTATION IN PROGRESS`

## 为什么做

本地可信 WeKnora runtime 已确定使用 PostgreSQL retrieval，但 official migration
ledger 已到 75 且 `public.embeddings` 不存在。两个已解析知识在实际生成 1024 维
向量后，生产 repository 批量 INSERT 均以 SQLSTATE `42P01` 失败。

历史 `000002` 在 `app.skip_embedding=true` 时成功返回并推进 official ledger；
后续改回 PostgreSQL retrieval 不会重跑它，`000059` 也在表缺失时跳过。因此正常
重启、改模型或重解析不能修复当前 schema。

## 本 Change 做什么

- 在项目现有独立 enterprise migration ledger 增加一个 forward repair；
- 仅当 `app.skip_embedding=false` 且 `embeddings` 缺失时，按当前 accumulated
  official schema 创建表、列和索引；
- 已存在且符合当前列/类型/关键索引合同的健康表无损no-op；已有表不完整时在
  enterprise ledger推进前typed fail closed，不做partial schema自动补齐；
- down migration 保守 no-op，避免无法区分历史表与本 migration 新建表时误删
  embeddings 数据；
- 用隔离 PostgreSQL 证明 legacy ledger、skip、数据保留、1024 维 repository
  transaction rollback 与 restart 边界。

## 不做什么

- 不修改 official `000002`、`000007`、`000059` 或任何 migration ledger；
- 不枚举或自动修复partial schema历史组合；
- 不做 startup auto-heal、通用 repair framework 或 backend health 平台；
- 不更换 PostgreSQL、模型、维度、KB 配置，不重传或重解析 PDF；
- 不修改现有本地 WeKnora 数据库，不执行 provider/live/full。

## 路径预算

严格十一路径：README、OpenSpec 四文件、实施计划、enterprise up/down、enterprise
head 常量、既有 ledger-origin classifier、现有 PostgreSQL migration matrix test。
classifier 这一独立生产路径是让合法 enterprise predecessor `2` 能升级到 `3` 的
必要安全边界；出现第十二条实现路径即停机。

# PostgreSQL Embeddings Forward Repair Specification

## ADDED Requirements

### Requirement: E1 已推进 ledger 必须可前向修复缺失表

系统 SHALL 在 official ledger 已到当前冻结 head、enterprise ledger 位于本修复
之前、`app.skip_embedding=false` 且 `public.embeddings` 缺失时，通过标准
enterprise migration 创建当前生产 PostgreSQL repository 所需的完整
accumulated schema。修复 SHALL 不 force、回退或改写 official/enterprise
ledger 历史。

#### Scenario: legacy PostgreSQL retrieval 数据库缺表

- **WHEN** official migration 2 曾因 skip 成功返回，ledger 后续已推进，当前
  PostgreSQL retrieval 生效
- **THEN** forward migration 创建 `embeddings`，migration ledger clean，1024 维
  repository insert 可在事务内成功

### Requirement: E2 schema 必须来自当前生产合同

新建表 SHALL 包含当前 `pgVector` 和 accumulated official migrations 所需的
identity、content、dimension、halfvec、tag 与 enabled 列，并创建 unique source、
BM25、knowledge-base、tag、enabled，以及 3584、798、1024 维 HNSW partial
indexes。不得凭空增加新列、通用表或新的存储抽象。

#### Scenario: 1024 维 repository 写入

- **WHEN** 生产 repository 对一个合成、非业务 `IndexInfo` 批量写入1024维向量
- **THEN** INSERT 成功；验证事务 ROLLBACK 后无持久 row

### Requirement: E3 已有表必须验证健康合同且非 PostgreSQL 部署不得误建

当 `embeddings` 已存在时，migration SHALL 在 enterprise ledger 推进前有限验证当前
repository 必需的完整列名、类型、nullability和关键索引合同。健康表 SHALL 无损
no-op；任一必需对象缺失或不匹配 SHALL typed fail closed，ledger不得推进，且不得
ALTER补齐、drop或重建表。`app.skip_embedding=true` 时 SHALL 不创建表或索引。

#### Scenario: 健康表包含历史数据

- **WHEN** migration 在已有表和 sentinel row 上运行或重启重复检查
- **THEN** row identity/content/vector bytes 不变且不产生重复索引

#### Scenario: 已有表不符合当前合同

- **WHEN** `embeddings` 存在但缺 `tag_id`、`is_enabled` 或任一当前必需关键索引
- **THEN** migration typed拒绝，enterprise ledger保留在predecessor，sentinel和表
  均不修改

#### Scenario: 非 PostgreSQL retrieval

- **WHEN** migration session 设置 `app.skip_embedding=true`
- **THEN** migration 成功推进但不创建 `embeddings`

### Requirement: E4 down 必须保守且不误删

由于 migration 无法可靠区分本次新建表与部署中历史已存在表，down SHALL 为明确
的 no-op，只回退 enterprise ledger version，不删除表、索引或数据。再次 up SHALL
保持幂等。

#### Scenario: down 后仍保留数据

- **WHEN** 已有 sentinel row 的数据库执行本 migration down
- **THEN** 表、索引和 row 均保留；再次 up 仍保持相同内容

### Requirement: E5 验证必须与现有本地运行态隔离

PostgreSQL focused test SHALL 只使用显式测试 DSN，并拒绝非测试数据库身份。
不得删除、重建或写入现有 WeKnora runtime database，不得调用 provider、模型、
上传或 reparse。

#### Scenario: 测试 DSN 指向非测试库

- **WHEN** database name 不符合本 Mission 的隔离测试身份
- **THEN** test 在任何 schema mutation 前 fail closed

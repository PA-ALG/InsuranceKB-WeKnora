# 018 · ReleaseSnapshot 单一读取模型与可恢复发布

## 为什么做

现有回滚重放旧 Wiki 页面并移动全局指针，但 Claim 状态不会回退。未来 MCP 若直接查询 published Claims，会在回滚后与 Wiki 返回不同事实；SnapshotClaim 也没有冻结当时 Evidence，无法提供完整版本证据链。

## 做什么

1. 新增不可变 SnapshotFact，冻结值、有效期、产品展示身份与 Evidence；
2. 每次发布构建完整 Space 快照，建立 SnapshotReader，使 Wiki/MCP/Agent 统一从当前空间快照读取；
3. 发布改为 building/publishing/published/failed 状态机，采用独立 operation 记录并最后移动指针；
4. 记录 PublishAttempt 和 reconciliation 工单，恢复部分外部写入；
5. 回滚与正常发布走同一冻结计划执行机制；
6. 定义 curated-first、RAW 受控回退协议及 typed coverage gap。

## 不做什么

- 不在本 change 实现完整 MCP server（013）；
- 不承诺跨 PostgreSQL 与 WeKnora HTTP 的分布式事务；通过指针、幂等与补偿恢复一致；
- 不开放 RAW 结果覆盖已发布 SnapshotFact。
- 不把 Space 级 CurrentRelease 改造成产品级指针；单产品参数仅作为发起发布的兼容入口，生成物仍是完整 Space 快照。

## 影响面与文件域

- 组件：知识域 snapshot/publisher/pages、新 read model；
- 硬边界：WeKnora upsert 仍经 adapter；不在 Go/Vue 注入寿险发布逻辑；
- Schema/Golden：不改字段 schema/Golden 口径；SnapshotFact 复制发布时的 schema_version；
- 主要文件域：`knowledge/tables.py`、新 `knowledge/snapshots.py`/`reader.py`/`reconcile.py`、publisher/pages、migration 与 tests；
- 与其他 change：依赖已合入的 016/017；018 独占 migration `0005`，021 必须排在其后。

## 依赖

硬依赖已交付的 007、016 和 017。SnapshotFact 必须冻结 017 定义的 source_revision、file_hash、original_digest、parser_version、chunk hash、lineage_status 与 stale 状态；新发布拒绝 placeholder、legacy-null-lineage 或 stale Evidence。

## 验收故事

发布 snapshot 1、再发布 snapshot 2，随后回滚 1；SnapshotReader、Wiki page metadata 和未来 MCP adapter 均返回 snapshot 1 的值与证据。模拟第二页发布失败时 CurrentRelease 仍指向旧快照，重放补偿后 WeKnora 页面恢复。

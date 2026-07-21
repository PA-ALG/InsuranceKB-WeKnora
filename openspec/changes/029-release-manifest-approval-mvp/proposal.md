# 029 · ReleaseManifest + Human Approval MVP

> 状态：MVP K0，规格与实施计划已独立复核。北极星 C3/C5；复用 018，不实现 P-1。

## 为什么做

018 已有 ReleaseSnapshot/SnapshotFact/CurrentRelease 和可恢复 publish/rollback，但缺少完整制品 manifest、绑定完整 hash 的授权人批准和明确的 MVP serving contract。没有它，人和 Agent 同快照与“人工最终审核”无法成为可验证主链。

## 做什么

- 对 SnapshotFact、页面/目录/关系等 MVP 已有制品生成 canonical ReleaseManifest/hash；
- `ReleaseApproval` 由显式 Space 授权人绑定完整 manifest hash；
- 只有有效 approval + expected current CAS 才能移动 Harness CurrentRelease；
- Harness Reader 与 MCP 通过同一 SnapshotReader 返回 snapshot/manifest hash；
- 逻辑回滚只切向仍有效批准的旧 snapshot，不调用模型；
- 提供独立的人控治理 CLI，把 028 compilation bundle 经真人 review、candidate、完整 hash approval、CAS promote 后封存；命令不执行编译，也不自动生成批准决定；
- P-1 前所有生产 WeKnora Wiki UI 写入 fail closed。

## 不做

不实现 WeKnora namespace/seal/active alias、物理 pin/GC、批准撤销全矩阵或完整发布 UI；这些进入 M2。

## 文件域

`knowledge/`、029 tests、唯一 migration 0013；MCP/workbench 只消费公开 service contract，不由本 change 修改。

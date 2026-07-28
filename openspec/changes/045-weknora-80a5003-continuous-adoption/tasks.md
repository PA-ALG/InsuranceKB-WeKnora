# 045 · Thin Adoption Tasks

## 执行原则

- 当前 target 全部从 manifest 读取；`80a5003...` 是数据，不是通用代码常量。
- 使用 standard Git exact-SHA merge/replay，不生成 patch bundle 或 receipt。
- thin check 只做 identity、两组 registered W1 overlap、official migration 与
  plugin contract 验证；不做自动语义裁决。
- official migration byte-exact；enterprise migration 使用独立 source/ledger。
- `source_reader` authority 保持 blocked；P4a/P4c 不冒充 ready。
- Code 与 Artifact 分离；Artifact 只能从已合入 main 的 source 构建。

## Task 1A · Target manifest 与 immutable discover

- [x] 记录当前 repository/commit/tree/release ancestor/required ancestors/
  official migration head。
- [x] `discover latest-stable|mainline-head` 只输出 immutable proposal。
- [x] 拒绝 mutable ref 自动覆盖 manifest。
- [ ] 在 thin check 中验证 target checkout clean、origin、HEAD、tree 与
  ancestors。

## Task 1B · Slim plugin contract（已提交）

- [x] 保留 machine-readable Harness plugin contract 与 semantic digest。
- [x] 保留 public REST、principal、Space/ACL、zero-write、readiness 与
  validation nodes。
- [x] 删除 enterprise schema object inventory、generic DDL parser 及其测试。
- [x] 删除 Python 中重复 canonical truth source，以 YAML+digest 为合同。
- [x] Task 1B states 保持 false，planned code node 保持 planned。

## Task 1C · 实现有限 thin check

- [ ] RED：wrong origin/HEAD/tree/ancestor、dirty target 必须 `block`。
- [ ] RED：runtime lock 不得被用作 project↔target merge-base。
- [ ] RED：project merge-base→target 与 runtime→target 两组 registered W1
  overlap 分别输出；任一 overlap 只产生 `manual_review_required`。
- [ ] RED：official migration filename/head/checksum 漂移必须 `block`。
- [ ] RED：plugin digest、existing/planned node 或 false states 漂移必须
  `block`。
- [ ] GREEN：输出最小 deterministic JSON，verdict 仅
  `pass|manual_review_required|block`。
- [ ] 证明 comment/format/mapping reorder 不改变结果，list/path semantic
  mutation 改变 verdict。
- [ ] 保留既有 timeout/retry/node mutation tests，不引入通用 collision API。

## Task 2 · Exact upstream merge 与受控 replay

- [ ] 从 official remote fetch manifest exact SHA 并验证 tree/ancestors。
- [ ] 使用 Git 计算真实 project merge-base，创建标准 merge commit。
- [ ] 人工 review thin-check 列出的 registered W1 overlaps。
- [ ] 用普通 replay commits 恢复 W1 与既有 logger redaction。
- [ ] 每个 project-owned production path 都在 W1 inventory 登记。
- [ ] 不生成 `w1-*.patch`、bundle、verify-bundle、receipt 或 apply DSL。
- [ ] 验证 merge history 可证明 official ancestry，target files 与 Git tree
  一致。

## Task 3 · Dual migration 与 legacy 000066 bridge

- [ ] RED：official filenames/head/SHA256 与 target tree byte mismatch。
- [ ] RED：legacy W1 66、pre-66、upstream-66-plus、fresh-target 与
  unknown/dirty/partial origins。
- [ ] 保留 legacy W1 `000066` byte/checksum fixture。
- [ ] 建立 enterprise migration source 与 `enterprise_schema_migrations`。
- [ ] 在 advisory lock/transaction 内重验并无损桥接 known legacy state。
- [ ] 顺序执行 official→enterprise migration；unknown/dirty/partial 零写失败。
- [ ] 在 disposable PostgreSQL 16/17 验证 crash/restart、data preservation 与
  双 ledger clean。

## Task 4 · Targeted compatibility

- [ ] 运行 W1 revision descriptor/chunk/manifest/race tests。
- [ ] 落地 planned in-progress-with-prior `last_committed` 真实测试并把对应 node
  从 planned 改为 existing；在此之前 Code final gate 不得通过。
- [ ] 验证 public REST envelope、typed errors、ACL denied 与 zero-write。
- [ ] 验证 Wiki 单页 history、line diff、manual edit optimistic locking、
  revert-new-revision 与未授权零写；这些证据不改变 Harness plugin authority。
- [ ] 运行 focused frontend type/test、Go、Python、OpenSpec 与 diff/scope gates。

## Task 5 · Trusted workflow 与 multi-image

- [ ] workflow 仅从已合入 main 的 exact source/lock 构建。
- [ ] server、worker、frontend 等 images 使用相同 commit/tree/lock。
- [ ] 构建前运行 thin check、migration 与 targeted compatibility gates。
- [ ] 发布 image digest、provenance 与 SBOM。
- [ ] workflow 不下载或 apply project patch bundle。

## Task 6 · Artifact

- [ ] 从 trusted workflow 构建并固定 multi-image digests。
- [ ] 在 backup clone/disposable PostgreSQL 验证 bridge 与 dual migration。
- [ ] 验证 plugin/readiness/ACL/zero-write probes。
- [ ] 验证产品 history/diff/edit/revert smoke。
- [ ] 只有 image identity、migration、W1/plugin 与产品 probes 全通过才闭合
  Artifact；consumer/source-reader/P4a/P4c 仍按各自真实状态报告。

## 明确不创建

- `deploy/upstream/weknora-enterprise-schema-objects.yaml`
- `deploy/upstream/weknora-adoption-report.json`
- generic DDL/schema-object/collision report engine
- W1 patch/bundle/receipt、`bundle`、`verify-bundle` 或 patch DSL
- 任意仓库/任意 patch engine

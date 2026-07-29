# 045 · WeKnora Immutable Upstream Thin Adoption

## 状态

`SOURCE + MIGRATION BRIDGE + TRUSTED IMAGES + DIGEST PIN COMPLETE /
FULL ARTIFACT PROBES OPEN`

2026-07-29 exact 状态：

- upstream capability：
  `80a5003cc99a427098afe184eee6601916d3d156`；
- trusted image build source：
  `a8bf55ae18441abd380e594afba5000c51cc9633`；
- current main：
  `529d72c994369750b26e352a70fd6284e8b0fd9d`；
- exact source merge、W1/logger replay、legacy `000066` bridge、trusted
  app/frontend/docreader images 与 digest pin 已合入；
- Full Artifact/W1 runtime probes 仍 open；
- `source_reader` authority 仍 blocked。

上述三个 Git identity 不能合并成“镜像由 current main 构建”。digest pin
也不等于 Full Artifact closure。

本 change 定义一条薄升级轨道：尽快把当前 manifest 指定的 Tencent WeKnora
不可变 identity 合入项目，同时让下一次升级只需批准并替换 manifest，而不再
建设一套项目自有的 patch、report 或 schema-analysis 平台。

当前 manifest 数据是 commit
`80a5003cc99a427098afe184eee6601916d3d156`、tree
`18fcf68e7a008ce69929e32233f0b6914040c223`，release ancestor
`v0.7.1@c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`。这些值属于 manifest，
不得硬编码进通用检查或合并逻辑。后续 target 通过 manifest 变更进入相同轨道。

## 用户价值

- 尽快采用 exact 官方 source、官方 migration 和当前 snapshot 的产品能力；
- 保留 W1 revision manifest、现有 logger redaction 与 PostgreSQL 数据；
- 继续以公开 REST、principal、Space/ACL 和零写规则隔离 Harness；
- 让下一次固定 upstream identity 升级仍由 manifest、标准 Git 和少量定向
  检查完成，而不是维护一套任意仓库 patch engine。

当前 snapshot 的 Wiki 单页 history、diff、manual edit、optimistic locking 与
revert 是产品验收项。它们不是 Harness W1 plugin contract 的 endpoint 或权限。
它们也不等于 Enterprise LLM Wiki 的整版 Release 或 release-managed 正式页面
编辑闭环。

## 保留的机制

1. exact target manifest，以及只产生 immutable proposal 的
   `discover latest-stable|mainline-head`；
2. machine-readable Harness plugin contract：公开 REST、principal、
   authoritative Space binding、RAW-KB ACL、allowed reads、denied mutations、
   zero-write、readiness 与 validation nodes；
3. 标准 Git exact-SHA merge，以及 W1/logger 的受控 replay commits；
4. W1 planned path inventory，用于限定人工审查范围，不承载 patch；
5. 官方 migration 的 byte-exact filename、head 与 checksum；
6. enterprise migration 独立 source/ledger，以及 legacy W1 `000066`
   compatibility bridge；
7. targeted compatibility、PostgreSQL、multi-image 与 trusted Artifact gates；
8. 一个有限 `check`，验证 identity、两组 Git overlap、migration 与 plugin
   contract，并输出简短 deterministic JSON。

`check` 的 verdict 只有 `pass`、`manual_review_required`、`block`。registered
W1 path overlap 只要求人工 review；工具不得自动做 SQL 或业务语义裁决。

## 删除或拒绝的机制

- enterprise schema object inventory 与 generic SQL DDL parser；
- schema semantic collision engine 或通用 collision report platform；
- `weknora-adoption-report.json`；
- patch bundle、`verify-bundle`、receipt、patch DSL 或任意仓库 patch engine；
- `w1-*.patch`/bundle receipt 作为 045 的 replay 载体。

因此 045 不生成或维护
`deploy/upstream/weknora-enterprise-schema-objects.yaml`，也不要求
`deploy/upstream/weknora-adoption-report.json`。标准 Git
history、merge commit 与受控 replay commit 是唯一 patch 承载。

## 安全与就绪边界

- 不清空或重建现有数据库，不自动 force migration version；
- `source_reader` authority 仍 blocked，不因采用 upstream 而提权；
- W1 runtime、Harness consumer、source-reader authority 与 Artifact 状态独立；
- P4a/P4c 未实现时不得冒充 ready；
- 不实现 P2d、P3 ACL-inspection、P11/P13/P14、provider 或 full；
- mutable branch、runtime lock 或显示版本都不能替代 manifest identity；
- Code 完成不等于 Artifact 已构建或生产已采用。

## 交付切片

1. **Task 1B Slim**：删除 schema inventory/parser/tests，保留 plugin contract；
2. **Thin check**：实现有限 identity/overlap/migration/plugin 检查；
3. **Code adoption**：exact upstream merge，受控 replay W1/logger；
4. **Dual migration**：official + enterprise ledger 与 legacy `000066` bridge；
5. **Compatibility**：targeted Go/frontend/PostgreSQL 验收；
6. **Workflow/images**：main-only trusted multi-image build；
7. **Artifact**：从已合入 main 的代码构建、固定 digest 并闭合运行证据。

任何 identity、migration checksum、plugin digest 或既有 validation node 不可
证明时 verdict 必须为 `block`。只有 registered W1 path overlap 时可进入
`manual_review_required`，由人决定 replay，不由工具生成补丁。

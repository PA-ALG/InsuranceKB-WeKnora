# S7d-2b · 删除 G3 平台路由及只为它们服务的代码（Go）

> 状态：Claude 2026-10-22 提出；用户同日同意删除 G3 产品导入链并要求先备份（已备份：标签 `archive/pre-s7-legacy-20261022`）｜ 作者：Claude Code
> 依据：蓝图 §10、§11 S7；S7d-1（#305）删除 Harness 产品导入服务，S7d-2a（#307）删除 Go 侧产品导入桥
> 实现方：Claude ｜ 审核方：Codex（Go 平台，删除路由与服务）｜ 真实模型调用：0
> 后续：S7d-2c 删除 830、SchemaWiki 与旧发布家族，原生候选写入策略与 G3 范围的去留在 2c 决定

## 1. 目标与现状

**`/platform` 路由**：`routes_g3_platform_{snapshots,release}.go` 注册的路由是 G3 产品导入流水线的平台接口，只有 Harness 的 `product_ingestion/platform_client.py` 调用。后者已在 S7d-1 删除，这些路由从此没有调用方。包括：

- 上传与文件读取、重解析；
- 源快照与原生发现；
- 基线快照；
- 自动草稿、自动审核与自动激活。

**只为这些路由服务的代码**：

- 处理器 `handler/g3_platform_*.go`；
- 服务 `g3_platform_{base_snapshot,candidate_transfer,machine_access,snapshot_signer}.go`、`g3_native_discovery.go`；
- 系统自动化策略与自动发布 `system_policy_decision.go`、`wiki_release_automated.go`；
- 类型 `types/g3_platform_candidate_transfer.go`。

**与企业链路共用、必须保留的部分**：

- `g3_platform_source_snapshot.go` 中的分块页码映射 `g3PlatformChunkPageMapping`、快照摘要 `g3PlatformSnapshotDigest` 与范围校验 `validG3PlatformScope`。它们被首次解析采集（`knowledge_model_dispatch.go`）与引用定位（`concept_source_locator_830_g3.go`）使用，本片整文件保留，S7d-2c 再迁移。
- `config.G3PlatformProcessing` 及其解码：企业来源路由的 G3 回退与 `releasestore.reservedScopes` 仍读它。
- 原生候选写入策略：`ProductIngestionConfig` 的范围字段。

## 2. 设计

1. **路由与注册**：删除 `routes_g3_platform_{snapshots,release}.go`；`router.go` 删除 `G3PlatformSnapshotsHandler`、`G3PlatformReleaseHandler` 参数及 `registerConfiguredG3PlatformRoutes`。
2. **处理器**：删除 `handler/g3_platform_{composition,native_discovery,release,snapshots}.go`。`container.go` 删除 G3 平台处理器的 Provide。
3. **服务与类型**：删除第 1 节列出的服务与类型。
   - `WikiReleaseService` 删除只给自动发布用的 `SystemPolicyProvider`、`SystemDecisionVerifier` 选项与字段；
   - `container.schemaWikiReleaseVerifierProviders` 不再装配系统策略。
4. **测试**：
   - 删除被删代码的测试，以及只给其中签名测试用的 Harness 夹具 `harness/tests/fixtures/product_ingestion/python-signing-v1.json`；
   - 两处保留测试随之调整：
     - `g3_published_provenance_restart_test.go`：删除只测已删基线快照服务的两个用例，保留"签名空见证"用例；
     - 企业测试 `internal/router/enterprise_sources_test.go`：G3 配置的模式改用字面量 `"ISOLATED_NOT_FOR_PRODUCTION"`，与配置校验所认的值相同，不再引用已删的服务常量。
5. **补丁登记**：`docs/design/upstream-patches.md` 追加 S7d-2b 回退行，涉及 `router.go`、`container.go`。

不做：

- 不删重解析在 `knowledge_process.go`、`repository/knowledge.go` 等上游文件里的部分，它们与首次解析采集交织，放到 S7d-2c 统一处理；
- 不删原生候选写入策略与 G3 范围配置。

## 3. 上游补丁

只减少已有接缝，不新增文件（G10 不变）。

## 4. 验收（RED，Claude 编写，受保护）

`tests/architecture/test_g3_platform_routes_retired.py` 检查：

- 上述路由、处理器、服务与类型文件不存在；
- `router.go`、`container.go` 不再出现 `G3PlatformSnapshotsHandler`、`G3PlatformReleaseHandler`、`registerConfiguredG3PlatformRoutes`、`ConfiguredG3PlatformSystemOptions`、`NewConfiguredG3PlatformHandlers`；
- `wiki_release.go` 不再有 `SystemPolicyProvider`、`SystemDecisionVerifier`；
- 共用文件 `g3_platform_source_snapshot.go` 仍在，企业链路依赖它。

## 5. 改动范围

- `internal/router/`、`internal/handler/`、`internal/application/service/`、`internal/types/`：删除上述文件与测试；
- 编辑：
  - `router.go`、`container.go`、`wiki_release.go`；
  - `g3_published_provenance_restart_test.go`、`enterprise_sources_test.go`；
- `harness/tests/fixtures/product_ingestion/python-signing-v1.json`（删除）；
- `docs/design/upstream-patches.md`（追加回退行）、`tests/architecture/baseline.json`（脚本下调）。

## 6. 上线与验证

- 换 App 镜像，无迁移。部署另开 Issue，需用户确认，可与 S7b、S7d-2a 一起。
- 部署后企业来源与出处照常，`/platform/...` 路由返回 404。

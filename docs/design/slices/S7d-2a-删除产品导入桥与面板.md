# S7d-2a · 删除产品导入桥与知识库页产品导入面板（Go 与前端）

> 状态：Claude 2026-10-22 提出；用户同日同意删除 G3 产品导入链并要求先备份（已备份：标签 `archive/pre-s7-legacy-20261022`）｜ 作者：Claude Code
> 依据：蓝图 §10、§11 S7；S7d-1（#305）删除 Harness 侧产品导入服务
> 实现方：Claude ｜ 审核方：Codex（Go 平台与前端，改动上传入口）｜ 真实模型调用：0
> 后续：S7d-2b 删除 G3 平台路由与原生候选写入策略；S7d-2c 删除 830、SchemaWiki 与旧发布家族

## 1. 目标与现状

Go 侧有一条到 Harness 产品导入服务的"桥"，路径是 `/api/v1/knowledgebase/:id/product-ingestions...`，包括：

- `service/product_ingestion_bridge.go`；
- `handler/product_ingestion{,_composition}.go`；
- `router/routes_product_ingestion.go`；
- 容器与路由中的注册。

前端相关部分：

- `api/product-ingestion.ts`；
- 产品导入状态面板 `components/knowledge-base/product-ingestion-status.vue`；
- 知识库页 `KnowledgeBase.vue`：
  - 打开时查询能力并在开启时显示面板；
  - 上传文件时先问能力接口，只有明确"未开启"才打开原生上传对话框，能力接口出错还会阻止上传。

Harness 侧服务已在 S7d-1 删除，本机也从未部署这套服务。桥只会返回 `NOT_CONFIGURED`，却让每次上传多一次请求，还多一个失败点。

## 2. 设计

1. **删除 Go 桥**：上述 4 个文件及其测试；`router.go` 去掉 `ProductIngestionHandler` 参数与注册，`container.go` 去掉对应 Provide。
2. **配置**：`ProductIngestionConfig` 删除只给桥用的字段：`BaseURL`、`Credential`、`TimeoutSeconds`、`MaxResponseBytes`、`MaxUploadFiles`、`MaxUploadBytes`。
   - 保留 `WikiProducerPolicy`、`Enabled`、`TenantID`、`SpaceID`、`RawKBID`、`WikiKBID`，因为原生候选写入策略 `NativeWikiWritesDisabled` 与 G3 平台配置校验仍读它们，要到 S7d-2b 才删除；
   - 部署配置里遗留的键会被忽略。
3. **删除前端**：`api/product-ingestion.ts`、产品导入面板及三个测试（含 `views/knowledge/productIngestionUpload.spec.ts`）。
4. **`KnowledgeBase.vue`**：
   - 删除能力查询、面板与产品上传分支；
   - `handleUploadSourceFiles` 恢复为上游原样：先确认知识库可上传，有文件就打开原生上传对话框，不再多发能力请求。
5. **补丁登记**：`docs/design/upstream-patches.md` 追加一行 S7d-2a 回退，涉及 `router.go`、`container.go`、`KnowledgeBase.vue`。补丁文件数不变（G10 不变），各文件的改动只减少。

## 3. 上游补丁

只减少已有接缝，不新增文件。

## 4. 验收（RED，Claude 编写，受保护）

- **`tests/architecture/test_product_ingestion_bridge_retired.py`**（Go 侧静态检查）：
  - 4 个桥文件不存在；
  - `router.go`、`container.go` 不再出现 `ProductIngestionHandler`、`RegisterProductIngestionRoutes`、`NewConfiguredProductIngestionHandler`；
  - `ProductIngestionConfig` 不再有 `BaseURL`、`Credential` 等桥字段。
- **`frontend/src/enterprise/productIngestionRemoved.spec.ts`**：
  - `api/product-ingestion*` 与 `components/knowledge-base/product-ingestion-status*` 没有源文件；
  - `KnowledgeBase.vue` 不再出现 `product-ingestion`、`ProductIngestion`、`uploadProductBatchIfEnabled`；
  - `handleUploadSourceFiles` 与上游一致：确认可上传、空列表返回、打开原生上传对话框。

## 5. 改动范围

- Go：
  - 删除 `internal/application/service/product_ingestion_bridge*.go`、`internal/handler/product_ingestion*.go`、`internal/router/routes_product_ingestion*.go`；
  - 编辑 `internal/router/router.go`、`internal/container/container.go`、`internal/config/product_ingestion.go`。
- 前端：
  - 删除 `frontend/src/api/product-ingestion*.ts`、`frontend/src/components/knowledge-base/product-ingestion-status*`、`frontend/src/views/knowledge/productIngestionUpload.spec.ts`；
  - 编辑 `frontend/src/views/knowledge/KnowledgeBase.vue`。
- `docs/design/upstream-patches.md`（追加回退行）、`tests/architecture/baseline.json`（脚本下调）。

## 6. 上线与验证

- 换 App 与 UI 镜像，无迁移。部署另开 Issue，需用户确认，可与后续 UI 改动合并部署。
- 浏览器核对：在原生知识库上传文件，只出现原生上传对话框，不再多发能力请求。

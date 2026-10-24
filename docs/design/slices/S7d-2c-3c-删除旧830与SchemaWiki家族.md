# S7d-2c-3c · 删除旧 830 与 SchemaWiki 家族

> 状态：Claude 2026-10-24 提出；用户 2026-10-22 同意删除旧 830/G3 代码（备份标签 `archive/pre-s7-legacy-20261022`），2026-10-23 决定 S7d-2c 一并退役 ｜ 作者：Claude Code
> 依据：蓝图 §10（旧数据与旧代码删除，不迁移，不保留只读 adapter）、§11 S7；S7d-2c-3a（#323）、3b（#325）已切断企业链路对旧家族的依赖
> 实现方：Claude ｜ 审核方：Codex（Go 平台大规模删除；上游文件 `router.go`、`routes_knowledge.go`、`container.go`）｜ 真实模型调用：0
> 后续：3d 字段目录 JSON 迁出 `internal/handler/`，删除前端抽屉的固定版本分支与无用翻译键

## 1. 目标

3a/3b 之后，旧 830 / SchemaWiki 家族没有任何企业调用方。本片一次删除它们的服务、处理器、路由、类型、测试数据与装配。

**必须保留**（企业链路在用）：

| 保留 | 原因 |
|---|---|
| `repository/wiki_release.go`、`types/wiki_release.go` | 企业 Space 的 Head、Release、成员、回执存储，迁移 000002 建表，`releasestore` 读写，`managed` 判定读 Head |
| `handler/schema_pack_catalog_830_g3.generated.json`（数据文件） | Harness 发布产品页与导航时按路径读取；3d 迁出 |
| `service/g3_first_parse.go` 中的 `G3FirstParseStore`、`failG3FirstParse` | 企业首次解析采集与来源页 |
| `config` 中的签名配置与 `DecodeSchemaWikiCitationTokenSigningRing` | 采集密钥（3b）与 `releasestore.LoadSpaces` 在用 |
| `knowledge_revision_source.go` 与其回填路由 | 修订来源固定接缝，企业发布的来源固定依赖它 |

## 2. 删除范围

1. **服务**（`internal/application/service/`）：
   - `concept_free_wiki_830_g2/_g3`、`concept_source_authority_830_g2`、`concept_source_locator_830_g3`、`concept_source_reuse_830_g3`、`concept_source_reuse_legacy_830_g3`、`entity_page_graph_830_g1`；
   - `g3_platform_source_snapshot`、`g3_product_bindings`、`g3_published_legacy_baseline`、`g3_published_provenance`、`g3_published_read_reuse`、`g3_published_source_reuse`；
   - `schema_wiki`、`schema_wiki_citation_content`、`schema_wiki_citation_revision`、`schema_wiki_golden_successor_status`、`wiki_release`；
   - 以及它们的测试与 `testdata/` 向量。
2. **类型**（`internal/types/`）：
   - `concept_free_wiki_830_g2/_g3`（含 `identity_v2/v3`、`issuer_alias`）、`entity_page_graph_830_g1`、`schema_wiki`；
   - `knowledge_content_provenance`、`knowledge_quality`、`product_concept_relation`：这三个只被上述类型使用；
   - 以及它们的测试与 `testdata/`。
3. **仓库**：`schema_wiki_formal_candidate_preview.go`、`schema_wiki_c5_revision_manifest.go`。`wiki_release.go` 保留。
4. **处理器与路由**：
   - 删除 `handler/schema_wiki.go`、`wiki_release.go`、`concept_free_wiki_830_g2.go`、`entity_page_graph_830_g1.go`、`schema_pack_catalog_830_g3.go`、`g3_product_bindings.go`；
   - 删除 `router/routes_schema_wiki.go`；
   - 删除 `router.go`、`routes_knowledge.go` 中旧发布范围（`/knowledgebase/:kb_id/wiki/release-scopes/...`）的注册与参数；
   - `knowledge_revision_source` 处理器用到的 `ensureWikiReleaseJSONEOF` 移入该处理器文件。
5. **装配**：`container.go` 删除旧家族的全部 Provide，包括引用令牌编解码器、发布服务与其校验器、概念与实体页服务、预览注册表等。
6. **其他**：
   - 删除 `cmd/release-proof-596-1/`、`scripts/deployment/g3_replace_app.py`；
   - `config.go` 只删除仅被旧家族使用的配置段（冻结发布范围、Golden 后继状态），签名配置保留。
7. **`g3_first_parse.go`**：只保留采集存储与失败处理，删除旧家族用的类型别名与辅助函数。

**不做**：
- 不删 `wiki_release_*` 表与仓库方法。仓库中只给旧家族用的方法（`CreateDraft`、`ReviewDraft` 等）留到 S7e 统一清理。
- 不动前端（3d），不动 Harness。

## 3. 上游补丁

- 只减少：`router.go`、`routes_knowledge.go`、`container.go` 删除旧家族的注册与装配；
- 若某文件因此回到上游原样，G10 下降；
- `docs/design/upstream-patches.md` 追加一行 S7d-2c-3c 回退记录，并注明随之失效的登记行。

## 4. 验收（RED，Claude 编写，受保护）

**`tests/architecture/test_legacy_schema_wiki_family_retired.py`**：

1. §2 列出的非测试文件都不存在；
2. `router.go`、`routes_knowledge.go`、`container.go` 不再出现 `SchemaWiki`、`WikiReleaseService`、`ConceptSourceAuthority`、`ConceptFreeWiki`、`EntityPageGraph`、`release-scopes`；
3. `g3_first_parse.go` 不再出现 `830`；
4. 保留项仍在：`repository/wiki_release.go`、`types/wiki_release.go`、字段目录 JSON。

**更新已有守卫**：
- `test_legacy_platform_routes_retired.py`：
  - `test_the_release_service_drops_the_automation_policy` 原来读取 `service/wiki_release.go`，该文件删除后改为检查文件不存在；
  - `test_the_helpers_enterprise_capture_shares_stay` 原来要求 `g3_platform_source_snapshot.go` 存在，3b 之后它已不再被企业采集使用，改为要求它不存在。
- `test_legacy_reparse_chain_retired.py`：`TOUCHED` 中已删除的文件视为"不再引用"，跳过读取。

**行为回归**：企业链路全部测试照常通过：

- `internal/enterprise/...`、`router/enterprise_*`；
- 企业采集与来源页；
- Agent / Q1 问答；
- `managed`、`releasestore`；
- `container` 装配测试。

## 5. 改动范围

§2 列出的删除，加上：

- `internal/router/router.go`、`routes_knowledge.go`；
- `internal/container/container.go`；
- `internal/config/config.go`；
- `internal/handler/knowledge_revision_source.go`；
- `internal/application/service/g3_first_parse.go`；
- 只引用被删代码的测试辅助（同包测试中引用旧夹具的测试一并删除；只借用夹具的企业测试改用企业夹具，断言不变）；
- `docs/design/upstream-patches.md`（只追加一行）；
- `tests/architecture/`（§4 的守卫与基线）。

## 6. 上线与验证

- 换 App 镜像，无迁移；部署另开 Issue，需用户确认。
- 部署后：演示 Space 的发布版本、出处、问答、专家编辑、抽检照常；旧发布范围接口返回 404。

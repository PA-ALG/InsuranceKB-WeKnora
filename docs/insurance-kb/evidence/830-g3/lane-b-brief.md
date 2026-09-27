# G3 首切片 B · 有权限的 Schema Catalog 浏览

状态：待 A 独立代码复核；未派写。唯一结果 Owner=root。实施 Owner 将由总控派工后记入 startup.json。共同截止 2026-09-08 18:00+08，D1，镜像构建/拉取/模型/DB 写均 0。

本记录替代首计划中 B 的前端内联配置方案，A 的已冻结合同不变。追加审查发现前端静态文件匿名可读，完整字段说明不得进入前端资源。新方案只复用现有 Handler、路由和双 KB ACL，不新增服务、数据库表或第二目录权威。

## 共同合同与集成顺序

- 权威输入：`catalog/catalog.json`，706985 bytes。
- exact wire file SHA：`0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9`。
- catalog content hash：`b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd`。
- Catalog ID/version：`schema_catalog_insurance_product` / `2026-08-12-v5`。
- contract：`schema-pack-catalog.830.g3.v1`；完整 shape 以该 exact JSON 和 A 严格模型为向量。数值 usage_frequency 必须保留 int。
- 状态仅 `PENDING_PRODUCT_OWNER_CONFIRMATION`、`REGISTERED_NOT_QUALITY_ADMITTED`，不创建审核决定或生产内容。
- A 冻结→独立 Spec/代码复核→总控逐字节投影服务端 asset→B RED/GREEN→只读独立复核→总控集成和 D1 实际目录观察。若 A 输出变化，B 暂停直到重冻向量；总控裁决共享合同，两个 lane 不互改。

## exact 写域

总控仅机械复制（不手编）服务端资产：
`internal/handler/schema_pack_catalog_830_g3.generated.json`。

B 独占生产文件：

- 新增 `internal/handler/schema_pack_catalog_830_g3.go`。
- 修改 `internal/router/routes_schema_wiki.go`。
- 新增 `frontend/src/api/schema-wiki/schemaPackCatalog830G3.ts`。
- 新增 `frontend/src/views/knowledge/schema-wiki/SchemaPackCatalog830G3.vue`。
- 修改 `frontend/src/views/knowledge/schema-wiki/SchemaWikiCatalogEntry830G2.vue`。

B 独占测试：

- `internal/handler/schema_pack_catalog_830_g3_test.go`。
- `internal/router/routes_schema_pack_catalog_830_g3_test.go`（复用同 package 现有 helpers）。
- `frontend/src/api/schema-wiki/schemaPackCatalog830G3.spec.ts`。
- `frontend/src/views/knowledge/schema-wiki/SchemaPackCatalog830G3.spec.ts`。
- `frontend/src/views/knowledge/schema-wiki/SchemaWikiCatalogEntry830G2.spec.ts`。

未列文件只读；测试 scratch 位于 `/private/tmp/g3-catalog-b-*`；无 commit/push/数据库/provider/镜像构建权。复用已建立的 ignored frontend/node_modules 链接，不安装或更新依赖。

## 具体行为

1. 在既有 `activeGET` 下挂 `.../schema/catalogs/:catalog_id/versions/:catalog_version`。沿原 Viewer→Wiki KB ACL→exact current scope→RAW KB ACL→seal，不放宽无 Head 权限模型。
2. `SchemaWikiHandler.ReadSchemaPackCatalog830G3` 嵌入服务端 exact asset，核对冻结 file SHA 和顶层 ID/version/hash 后返回 `{success:true,data:<catalog>}`，并设 `Cache-Control: private, no-store`。使用既有 requestIdentity + ContextWikiReleaseAccessVerifier 复核 seal；无匹配权限直接拒绝，不依赖调用者提供正文。不新增 service/repository。未知 ID/version 404；权限/路径范围漂移 403。
3. 前端只从已有 scope bootstrap 后的受权 GET 读取，严格校验整个 catalog/pack/Profile/field 语义 hash、交叉绑定、集合/状态。复用 schema-wiki-canonical.v1 域分隔及 Python 向量，不把读取字符串长得像 SHA 当成校验。
4. 同一个通用组件展示 11 包、各自有序节点、完整字段与11列 metadata。采用包选择和节点/字段展开，界面中文。状态清楚标示“结构待确认”“业务质量待评估”，hash 放详细信息，既有已发布知识目录仍保留。原值为空时显示“工作簿未填写”，避免把配置空格解释成实体断言“无”。
5. 不提供新的修改/批准/发布入口，不把 Catalog 当 Release member、不改 current、不改已有字段页和来源链。人类结构确认在完整可审包形成后由真实具名决定记录承接。

## RED 与检查

- 旧路由返回404，新增期望授权目录200的最小测试先RED。
- 匿名、缺单边KB ACL、无seal、跨scope、错误ID/version拒绝；合法双ACL得到exact catalog及no-store。
- 前端真实向量11包/801字段/7或8节点；篡改hash/字段/Profile绑定/状态拒绝；组件选择和字段元数据可查看，旧G2目录回归。
- 静态输入检查：frontend内没有完整 generated catalog/真实801行说明，受保护源资产仅在Go handler。
- 只跑受影响 package focused Go tests、相关Vitest和局部类型检查。Go环境错误不计行为RED；若需共享cache权限走工具实际审批，不建新镜像或清缓存。

YELLOW 已预审：整个首切片达到5生产文件/500行阈值，只触发总控范围复核；本次增面源于明确权限边界，不用更少文件换取公开元数据。出现新表/服务/第二权威、接口变化或越域立即报告并停该写线。

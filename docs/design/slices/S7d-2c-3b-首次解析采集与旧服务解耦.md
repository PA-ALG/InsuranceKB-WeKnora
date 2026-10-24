# S7d-2c-3b · 首次解析采集与旧服务解耦

> 状态：Claude 2026-10-24 提出；用户 2026-10-23 决定 S7d-2c 退役旧 830/G3 家族，企业 Space 不受影响 ｜ 作者：Claude Code
> 依据：S7d-2c-1（#312）把采集内核迁入 `internal/enterprise/capture`；S7d-2c-3a（#323）
> 实现方：Claude ｜ 审核方：Codex（企业来源的持久化读写路径、上游文件 `knowledge_process.go`、`container.go`）｜ 真实模型调用：0
> 后续：3c 删除旧发布服务与 SchemaWiki 家族；3d 字段目录迁移与前端抽屉

## 1. 目标与现状

S7d-2c-1 之后，采集的格式、签封与校验都在企业包里，但还有三处借道旧 830 代码。3c 要整体删除旧家族，必须先切断这三处：

| 位置 | 现状 |
|---|---|
| `G3FirstParseStore` | 结构体里存放旧的 `conceptSourceReuseStore830G3`。构造时传入旧的 `SchemaWikiCitationTokenCodec`，每次调用再从它的根目录和密钥构造 `capture.Store` |
| 容器 | 签名密钥来自旧编解码器：`config.DecodeSchemaWikiCitationTokenSigningRing` → `NewSchemaWikiCitationTokenCodec` → `NewG3FirstParseStore`。`NewConceptSourceAuthorityService830G2WithFirstParse` 再把采集存储借给旧引用服务 |
| `knowledge_process.go` 的首次解析校验 | 用旧的 `conceptNativeHeader830G2` 读解析器指纹，用 `prepareConceptNativeQuoteIndex830G2` 校验原生结构，错误用 `ErrConceptSourceAuthorityUnavailable830G2`（它已是 `capture.ErrUnavailable` 的别名） |

`config.DecodeSchemaWikiCitationTokenSigningRing` 已经完成全部密钥校验：

- 密钥 ID 不能为空，不能有首尾空白或控制字符，不能重复；
- 私钥长度和编码正确；
- 公钥材料不能重复，也不能与审核、发布签名域混用；
- 当前启用的密钥必须存在。

旧编解码器在此基础上没有额外约束。

## 2. 设计

1. **采集存储**：`G3FirstParseStore` 改为持有采集根目录与 `*capture.Keys`，不再依赖任何旧类型。
   - `NewG3FirstParseStore(keys *capture.Keys)` 使用 `capture.DefaultRoot()`；
   - 读写都经 `capture.NewStore(root, keys)`；
   - 行为与 S7d-2c-1 相同：每次调用按当时的根目录与密钥构造，测试可替换根目录；
   - 类型名暂不改，减少改动面。
2. **容器**：
   - 新增一个 Provide：由 `config.DecodeSchemaWikiCitationTokenSigningRing(cfg)` 得到密钥环，返回 `capture.NewKeys(ring.ActiveKeyID(), ring.SigningKeys())`；
   - `NewG3FirstParseStore` 改为依赖它；
   - 删除 `NewConceptSourceAuthorityService830G2WithFirstParse`，旧引用服务改用 `NewConceptSourceAuthorityService830G2`。它自带同一根目录、同一编解码器的复用存储，3c 删除前旧家族照常编译、照常读取。
3. **首次解析校验**（`knowledge_process.go`，已登记的上游文件）：
   - 解析器指纹改由 `capture.ParserIdentitySHA256(result)` 读取（导出现有的 `parserIdentityOf`）；
   - 原生结构校验改为 `capture.ValidateNative(result, sourceSHA, parserIdentity)`，S7d-2c-1 已核对它与旧校验逐条等价；
   - 错误改为 `capture.ErrUnavailable`；
   - 失败时的阶段记录、错误码 `G3_FIRST_PARSE_ARTIFACT_UNAVAILABLE` 和提示文案不变。
4. **磁盘格式不变**：采集内核不改，`Contract`、签封域、键推导都不动。

**不做**：
- 不删旧 830 家族，它由 3c 删除；
- 不改密钥环的 YAML 键名 `schema_wiki_signing.citation_token_signing_keys` / `active_citation_token_key_id`，部署配置不需要改。

### 2.1 测试调整

只换构造方式，断言不变：

- `source_pages_test.go`、`enterprise_capture_test.go`、`enterprise_capture_boundaries_test.go`：
  - 采集存储改用 `captureTestKeys(t)`，新增测试辅助文件 `capture_keys_test.go`，按固定种子生成密钥；
  - `store.reuse.root` / `store.reuse.codec` 改为 `store.root` / `store.keys`；
- `g3_first_parse_test.go`：同上；与旧引用服务共用存储的两处，改为用同一根目录、同一把密钥构造采集存储。

## 3. 上游补丁

- 不新增上游文件，G10 不应上升；
- `knowledge_process.go`、`container.go` 的改动只是把调用对象从旧服务换成企业包；
- `docs/design/upstream-patches.md` 追加一行 S7d-2c-3b 记录。

## 4. 验收（RED，Claude 编写，受保护）

**`tests/architecture/test_capture_independent_of_legacy.py`** 检查：

1. `g3_first_parse.go` 不再出现 `conceptSourceReuseStore830G3`、`SchemaWikiCitationTokenCodec`、`NewConceptSourceAuthorityService830G2WithFirstParse`；
2. `knowledge_process.go` 不再出现 `prepareConceptNativeQuoteIndex830G2`、`conceptNativeHeader830G2`、`ErrConceptSourceAuthorityUnavailable830G2`，并调用 `capture.ValidateNative(` 与 `capture.ParserIdentitySHA256(`；
3. `container.go` 不再出现 `NewConceptSourceAuthorityService830G2WithFirstParse`，并用 `capture.NewKeys(` 从密钥环构造采集密钥。

**`internal/enterprise/capture/parser_identity_test.go`**：`ParserIdentitySHA256` 读出 testdata 中原生结构的解析器指纹；缺少原生结构或 JSON 无效时返回 `ErrUnavailable`。

**行为回归**：以下测试照常通过（按 §2.1 换构造方式后）：

- `internal/enterprise/capture` 验收（磁盘格式逐字节不变）；
- `enterprise_capture*_test.go`、`source_pages_test.go`、`g3_first_parse_test.go`；
- `router/enterprise_space_sources_test.go`；
- `releasestore` 全部。

## 5. 改动范围

- `internal/enterprise/capture/native.go`（导出 `ParserIdentitySHA256`）；
- `internal/application/service/g3_first_parse.go`、`knowledge_process.go`；
- `internal/container/container.go`；
- §2.1 列出的测试，以及新增的 `capture_keys_test.go`；
- `docs/design/upstream-patches.md`（只追加一行）；
- `tests/architecture/baseline.json`（若下降，按脚本下调）。

## 6. 上线与验证

- 换 App 镜像，无迁移，与 3a 一起部署。部署另开 Issue，需用户确认。
- 部署后：
  - 演示 Space 的出处照常，旧采集仍可读；
  - 上传或重解析一份企业 PDF，能生成新采集并通过校验。会产生一次真实解析，但不调用模型。

# S4c-2c · 企业 Space 解析产物必存：RAW KB 的 PDF 首次解析落盘，页接口按 Space 读取

> 状态：用户已定方向（2026-10-16 选定全部推荐方案，见 §1） ｜ 作者：Claude Code
> 依据：蓝图 §4.1、§5.4、§7.4，硬边界 5、7；S4c-1 Spec §3.1；S4c-2a Spec §3.2（`ENTERPRISE_SPACES`）；2026-10-16 调研与本地探针（结论摘入 §2）
> 分支：`slice/s4c2c` ｜ 工作目录：`.worktrees/s4c2c` ｜ 实现方：Codex（以 Go 平台为主） ｜ 审核方：Claude

S4c-2 的拆分：2a 候选发布（已合并）、2b 证据逐字回验与回跳、**2c 本片**、2d Source lifecycle event。

## 1. 目标

S4c-1 的页接口只对隔离的 G3 scope 有数据；S4c-2a 的企业 Space（`ENTERPRISE_SPACES`）里上传的材料没有解析产物，Harness 读不到
按 attempt 的页文本，发布的 Evidence 也无从回验。本片：

1. 企业 Space RAW KB 中上传的 PDF 一律用 builtin pdfium 原生捕获解析，首次解析产物按精确 parse attempt 签名落盘，之后才切块；
2. 扫描件（任一页没有可用文本层）留在 KB、解析正常完成、不存产物，页接口对其返回 `PARSE_ARTIFACT_NOT_CAPTURED`；
3. 页接口 `GET /api/v1/enterprise/spaces/:space_id/sources/:knowledge_id/attempts/:attempt/pages` 先按企业 Space 解析，再回落到
   G3 scope，鉴权与隔离和今天一致；
4. 配置了 `ENTERPRISE_SPACES` 而缺少封存产物所需的 citation token 签名密钥环时，进程拒绝启动。

用户决定（2026-10-16，最终）：企业 RAW KB 的 PDF 强制 builtin pdfium，替换用户选择的引擎（如 MinerU）、不存图片——原始材料只作
证据（硬边界 5）；扫描件不捕获、不作证据，直到 S10 OCR；来源事件拆到 S4c-2d；存量文档的回填方式是重新解析（新 attempt），
旧 attempt 继续返回 `PARSE_ARTIFACT_NOT_CAPTURED`。

## 2. 现状（`main@da3a8a831`）

- 捕获闸门 `g3FirstParseScope`（`g3_first_parse.go:132–138`）只认 G3 配置（Enabled + tenant + RAW KB + pdf），在 `ProcessDocument`
  （`knowledge_process.go:3938`）与 `convert`（`:4470`）各判定一次。命中时 PDF 强制 builtin，overrides 只留
  `pdf_native_structure_capture=builtin-pdfium-charbox-v1`，校验原生结构（`:4567–4591`），切块前 `G3FirstParseStore.save`
  落盘（`:4333–4368`），任一步失败则文档失败。产物在 `$LOCAL_STORAGE_BASE_DIR/.concept-source-reuse-v1/`，write-once，
  用 citation token 活动私钥 ed25519 封存。
- **既有缺陷**：`ProcessDocument` 在切块前对全文做 `NormalizeLineEndings` 与 `NormalizeHTMLTables`（`:4223–4228`，v0.8.2 升级
  带入）。pdfium `get_text_range()` 的页文本通常含 `\r\n`（S4c-1 §3.2），归一后全文摘要与原生结构不符，保存校验失败、文档被标为
  失败；只含 `\n` 的文本能通过。现有测试没有覆盖 `ProcessDocument` 的捕获成功路径（2026-10-16 本地探针确认 G3 同样失败）。
- docreader 捕获分支遇到扫描页抛 `ValueError("page {n} is scanned")`（`docreader/parser/pdf_parser.py:1674`，消息由
  `docreader/tests/test_pdf_router.py:717` 固定），gRPC 以 `ReadResult.Error` 原样返回（`docreader/main.py:224`）；Go 端走
  `result.Error` 分支把文档标为失败（`knowledge_process.go:4554`）。
- 页接口装配 `registerEnterpriseRoutes`（`router.go:416–438`）只映射 G3 scope：先解码 G3 策略（无效即 400），再核对 tenant/Space。
- `releasestore.Register`（`production.go:34`）只提供 `*release.Service`；`Spaces` 不在 DI 中。未配置密钥环时 citation codec
  为空且启动不报错（`schema_wiki_citation_content.go:113` 起），保存产物时才失败。
- `g3_first_parse.go` 已 494 行（G3 守卫 500 行）；新增非测试 Go 文件只能在 `internal/enterprise/`（G11）。
  `knowledge_process.go`、`knowledge.go`、`router.go` 已在 G10 基线内，本片不增加上游文件数。

## 3. 设计

### 3.1 捕获范围（冻结接口）

- `internal/enterprise/source`（`types.go`）：

  ```go
  // CaptureScope reports the RAW knowledge bases whose uploads must capture their first parse.
  type CaptureScope interface {
      RawKB(tenantID uint64, knowledgeBaseID string) bool
  }
  ```

- `internal/enterprise/releasestore`：
  - `func (s Spaces) RawKB(tenantID uint64, knowledgeBaseID string) bool`：只有某个已配置 Space 的 `raw_kb_id` 且 tenant 相同时为
    true；wiki KB、Space ID、空串、零值 `Spaces{}` 一律 false。`Spaces` 实现 `source.CaptureScope`。
  - `func LoadSpaces(cfg *config.Config, raw string) (Spaces, error)`：`ParseSpaces(raw, reservedScopes(cfg)...)`；结果非空时
    `config.DecodeSchemaWikiCitationTokenSigningRing(cfg)` 必须成功且 `ActiveKeyID() != ""`，否则返回错误（§3.5）。
  - `Register` 另外提供 `Spaces`（`LoadSpaces(cfg, os.Getenv(SpacesEnv))`）与 `source.CaptureScope`（即该 `Spaces`）。
    `*release.Service` 的提供方式与 `Production` 签名不变。
- `internal/application/service`：`knowledgeService` 新字段 `captureScope source.CaptureScope`；`NewKnowledgeService` 末尾新增参数
  `captureScope source.CaptureScope`，由上一条经 DI 注入，`container.go` 不改。nil 等同于没有企业 Space。
- 捕获判定（`ProcessDocument` 与 `convert` 用同一判定）：文件类型为 pdf（大小写不敏感）、不是 URL 导入，且 G3 闸门命中
  **或** `captureScope.RawKB(knowledge.TenantID, knowledge.KnowledgeBaseID)`。
- G3 闸门命中时一切按 G3 现有规则（扫描件失败、DocReader 复用恢复、模型调度日志），这些 G3 专属机制不扩展到企业 Space。
  企业 Space 不得复用 G3 的 RAW KB（用户 2026-10-15 决定企业发布使用独立的 Space、RAW KB 与 wiki KB）：`ParseSpaces` 的保留
  检查在 Space 与 wiki KB 之外加上 RAW KB，复用即启动失败，因此一个 RAW KB 只受一套捕获规则约束。

### 3.2 文本 PDF：解析与保存

- 与 G3 同一路径：builtin pdfium + 只含捕获 override；KB、租户、上传级的引擎规则与 overrides 都不传给解析器；不解析、不存图片。
  原生结构校验失败或保存失败 → 文档失败（沿用 `failG3FirstParse`），不写任何 chunk。
- 产物身份、合同名、文件格式、目录与封存方式不变（`g3FirstParseIdentity{TenantID, RawKBID, KnowledgeID, ParseAttempt,
  SourceSHA256}`）；不改 `g3_first_parse.go` 的存储与校验逻辑。
- 捕获的全文从 docreader 返回到保存、切块**逐码点不变**：捕获路径跳过 `NormalizeLineEndings` 与 `NormalizeHTMLTables`（修复 §2
  缺陷，G3 一并修复）；非捕获路径行为不变。chunk 的 `StartAt/EndAt` 是该全文的码点区间（`g3ExactSourceChunks` 已保证）。
- 读取仍是 S4c-1 的 `G3FirstParseStore.ReadSourceArtifact`：只读、按精确 attempt、读不到不补解析。

### 3.3 扫描件

- 信号：企业 RAW KB（非 G3）的捕获请求返回 `ReadResult.Error`，且**整串**匹配 `^page [1-9][0-9]* is scanned$`。其他任何解析
  错误、G3 scope 下的同一信号，一律按现状失败关闭。
- 处理：docreader 阶段正常结束（输出 `first_parse_saved: false`、`not_captured_reason: "scanned_page"`）；不换引擎重解析、不渲染
  页面、不调 VLM/OCR、不存图片；不写首次解析记录，也不留临时文件；以**零 chunk** 进入与其他文档相同的完成路径
  （`processChunks`，提交该 attempt 的 KnowledgeRevision，状态 completed，`ErrorMessage` 为空）。之后页接口对该 attempt 返回
  409 `PARSE_ARTIFACT_NOT_CAPTURED`。
- 部分页是扫描页的混合 PDF 同样整份不捕获（产物要求每页有文本层）。信号是 docreader 项目补丁里的现有消息，已有测试固定；改消息须
  同时改 Go 判定与两端测试。S10 以 typed OCR 产物替代本判定（退出条件）。

### 3.4 页接口路由

- `RouterParams` 新增 `EnterpriseSpaces releasestore.Spaces`（DI 由 §3.1 提供）。
- `registerEnterpriseRoutes` 的 store：先 `params.EnterpriseSpaces.Scope(scope.TenantID, scope.SpaceID)`，命中即用该
  `types.WikiReleaseScope` 调 `ReadSourceArtifact`；未命中才走现有 G3 映射（代码与行为不变，包括策略无效时 400）。G3 策略无效
  不影响企业 Space。同步更新 `router.go:417–419` 的注释。
- 失败关闭与今天一致：只接受全权限且不限 KB 的服务密钥（Mount 现有策略）；tenant 来自认证上下文，与 Space 精确匹配；Knowledge
  必须属于该 Space 的 RAW KB 且未删除；修订按精确 attempt 存在。未配置的 Space、跨 tenant 一律 404 且不查库；响应不含 RAW KB 等
  内部标识。

### 3.5 启动校验

`ENTERPRISE_SPACES` 非空而 citation token 签名密钥环缺失、不完整或活动密钥不存在 → `LoadSpaces` 报错 → DI 构造失败 → 进程不启动。
未配置 `ENTERPRISE_SPACES` 时不要求密钥环，行为与今天相同。

### 3.6 存量回填（只写说明，不写代码）

企业 RAW KB 里已有的文档，由运维对其调用现有重新解析（`POST /api/v1/knowledge/:id/reparse`，分配新 attempt），新 attempt 被捕获；
旧 attempt 继续返回 `PARSE_ARTIFACT_NOT_CAPTURED`，不改写历史。PR 中写明操作说明；执行另开 Issue。

### 3.7 不在本片

Source lifecycle event（S4c-2d）、证据逐字回验与字符框回跳（S4c-2b）、扫描件 OCR（S10）、Office 定位（S11）、前端、部署与回填执行。

## 4. 验收

- 受保护验收（Claude 写，RED 单独提交）：
  - `internal/application/service/enterprise_capture_test.go`：捕获判定（企业 RAW KB 的 pdf → builtin + 捕获；他 tenant 同 ID 的 KB、
    他 KB、非 pdf、无 Space → 保留 KB 引擎；G3 与企业并存各自捕获；G3 停用不捕获）；`ProcessDocument` 文本 PDF（含 `\r\n`）→
    产物与页文本逐码点一致、chunk 区间指向原文、他 attempt 与他 RAW KB 读不到；扫描件 → 只解析一次、不失败、零 chunk 进入完成路径、
    无记录、页服务返回 `PARSE_ARTIFACT_NOT_CAPTURED`；其他解析错误、近似消息、G3 扫描件 → 仍失败；保存失败 → 文档失败且无 chunk。
    chunk 写入在 `CreateChunksAtRevision` 处以 superseded 截停，证明到达完成路径，不需要向量库与模型。
  - `internal/router/enterprise_space_sources_test.go`：企业 Space 解析到其 RAW KB 并按精确 attempt 查修订（409）；他 Space 的
    RAW KB、未配置 Space、他 tenant、无修订的 attempt → 404；KB 受限密钥、只有能力的密钥 → 403 且不查库；与 G3 并存时互不越界；
    G3 策略过期不影响企业 Space，仍阻断 G3 Space。
  - `internal/enterprise/releasestore/capture_scope_test.go`：`RawKB` 只认已配置 RAW KB 与其 tenant；`LoadSpaces` 有 Space 时要求
    完整密钥环、无 Space 时不要求、保留 G3 Space；`Register` 提供 `Spaces` 与 `source.CaptureScope`，缺密钥环时两者都构造失败。
  - 验收复用同包既有夹具（`firstParseNative`、`firstParseReader`、`sourcePagesRepository`、`enterpriseSourceConfig`、`oneSpace`
    等），实现方不改其行为。
- Go：`go test ./internal/enterprise/... ./internal/application/service/... ./internal/router/... ./internal/container/...`
  相对 S0 失败清单不新增；`golangci-lint`（lll 120、gofumpt）通过；守卫通过（`g3_first_parse.go` 不超 500 行、无旧目录新文件、
  G10 数不增）；CI 全绿。
- 真实运行（可选，实现方本地有 docreader 时做，不入仓库）：一份含换行的文本 PDF 与一份扫描 PDF 上传到企业 RAW KB，前者页接口
  200 且与 Harness `read_pdf` 逐页一致，后者 409；PR 写摘要。

## 5. 改动范围

- 允许：
  - `internal/enterprise/source/types.go`（只加 `CaptureScope`）；
  - `internal/enterprise/releasestore/spaces.go`（含保留检查加 RAW KB）、`production.go` 及其非受保护测试；
  - `internal/application/service/knowledge_process.go`（捕获判定、扫描件分支、捕获全文不归一）、`knowledge.go`（字段与构造参数）；
  - `internal/application/service/g3_first_parse.go`：原则上不改；确需改闸门时净增不超过 6 行；
  - `internal/router/router.go`（`RouterParams.EnterpriseSpaces` 与 `registerEnterpriseRoutes`）；
  - 其他非受保护测试文件；`docs/design/upstream-patches.md` 追加 `knowledge_process.go`、`knowledge.go`、`router.go` 三行
    （不改已有行）。
- 不改：`internal/container/container.go`、docreader、`internal/infrastructure/docparser/`、迁移、`contracts/`、前端、Harness。
- 受保护：本片三份验收文件、既有受保护验收、`docs/design/`（除上述追加）、蓝图。

## 6. 依赖与环境

- 依赖 S4c-1（页接口）与 S4c-2a（`ENTERPRISE_SPACES`），均已在 `main`。
- 无模型调用、无数据库迁移、不改 docreader 镜像。行为变化只出现在配置了 `ENTERPRISE_SPACES` 的部署；换行修复同时作用于 G3。
- 部署与存量回填另开 Issue 由用户批准；部署前须为该环境配置 citation token 签名密钥环，否则进程按 §3.5 拒绝启动。

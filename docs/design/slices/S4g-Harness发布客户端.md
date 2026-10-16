# S4g · Harness 发布客户端：编译结果 → 候选包 → 决定、激活、读回

> 状态：用户已同意（2026-10-16，S4f 合并后接 S4g） ｜ 作者：Claude Code
> 依据：蓝图 §5.1–§5.3、§7.1、§7.4、§9；S3a（合同）、S3b（接收）、S4c-1（页文本）、S4c-2a（发布）、S4f（选段编号）
> 分支：`slice/s4g`（叠在 `slice/s4f` 上，S4f 合并后 merge main） ｜ 工作目录：`.worktrees/s4g` ｜ 实现方：Claude ｜ 审核方：Codex（跨组件合同与新模块）

## 1. 目标与最小机制

编译（S4d–S4f）、平台接收与发布（S3b、S4c-2a）、页文本读取（S4c-1）都已各自完成，但还没有连起来：Harness 不能把编译结果
提交成候选包。本片补上这一段，最小机制：

1. **每个字段一条 Claim 成员**（`kind=claim`）。证据由选段编号从页文本切出，带 `source:v1` 引用与 `PDF_TEXT_SPAN` 定位
   （页码 + 页内码点起止），按构造可回验。
2. **`member_digest` 与 Go 逐字节一致**：两种语言共用一份由 Go 生成的规范化样例，任何一侧漂移都会失败。
3. **平台客户端**：提交、决定、激活、读回，失败返回 typed error；激活后读回并逐成员核对摘要。
4. **编译与发布读同一份页文本**：两者都可以按 source map 从 WeKnora 读页，保证段落编号、偏移与平台保存的解析产物一致。

本片不调用模型，不改 Go 运行时代码。连到真实 WeKnora 的端到端演示依赖企业 Space 的解析产物必存（S4c-2c），另行进行。

## 2. 设计

### 2.1 规范化与摘要（新增 `bundle/canonical.py`）

- `canonical_json(value) -> bytes` 等于 Go 的 `json.Marshal(json.Unmarshal(x))`（S3b 冻结的 digest 口径）：
  - 对象键按 UTF-8 字节序排序，紧凑输出；
  - 字符串转义：`"`、`\`、`\b`、`\f`、`\n`、`\r`、`\t` 用短转义，其余小于 0x20 的字符写成 `\u00XX`；`<`、`>`、`&` 写成
    `\u003c`、`\u003e`、`\u0026`；U+2028、U+2029 写成 `\u2028`、`\u2029`；其他非 ASCII 字符按 UTF-8 原样输出；
  - 数字按 float64：绝对值在 [1e-6, 1e21) 内写定点最短形式（`1.0` → `1`、`-0.0` → `-0`），否则写指数形式且指数不补零
    （`1e-7`、`1e+21`）；
  - 拒绝 NaN、无穷、超出 ±2^53 的整数和孤立代理字符（Go 会改写这些值，摘要无法对齐）。
- `member_digest(payload) = sha256(canonical_json(payload))` 的十六进制。
- 不复用现有 `insurance_harness.canonical`：那是旧 OpenSpec 034 的 CanonicalEnvelopeV1（带域分隔哈希、Decimal 与哨兵值），与 S3b 冻结的 Go `json.Marshal` 口径是两份不同的合同，按蓝图在 S7 随旧链路退役。
- 共用样例：`internal/enterprise/release/testdata/canonical_vectors.json`（`name`、`payload`、`canonical`、`digest`），
  由 Go 的 `encoding/json` 生成。Go 测试断言 `canonicalDigest` 与样例一致，Python 测试断言 `canonical_json`、`member_digest` 与样例一致。

### 2.2 候选包（新增 `compilers/schema_fields/claims.py`、`bundle/assemble.py`、`evidence/source_ref.py`；`evidence/segments.py` 增加 `spans`）

- `SegmentedSource.spans(ids) -> list[EvidenceSpan]`：与 `evidence(ids)` 相同的合并规则（同页相邻段落合并），另带页内码点
  起止 `start`、`end`；`evidence` 改为由 `spans` 生成。
- `candidate_bundle(output, source, sources, *, compiler_identity, base: Head | None) -> CandidateBundle`：
  - `sources` 把文件名映射到 `(knowledge_id, parse_attempt)`；
  - 每个字段先核对 `segment_ids` 能切出保存的证据（S4f 的信任规则），否则报错，不猜；
  - Claim：`claim_id = logical_key = "<entity_id>/<field_key>"`、`subject_ref = entity_id`、`predicate = field_key`、`state`、`value`；
    present 与 absent_explicitly 每个证据片段一条 Evidence（`source_ref = source:v1:<knowledge_id>:<attempt>:<file_sha256>`、
    `file_sha256`、`locator = PDF_TEXT_SPAN{page, start, end}`、`quote = 页文本[start:end]`、`match = EXACT`、`access_scope = "space"`）；
    unknown 不带证据，`unknown_reason = NOT_IN_MATERIAL`；`origin = SOURCE_SUPPORTED`；`provenance` 记录编译器、卡片版本与模型；
    卡片版本取编译时写入 `CompileOutput.cards_version` 的值（审核 PR #169 第 1 项），不取发布时安装的版本；没有该值的旧产物拒绝发布；
  - 成员：`kind = "claim"`、`logical_slug = logical_key`、`payload = Claim 的 JSON`、`member_digest`、`evidence_refs`（去重排序）、
    `access_scope = "space"`；
  - 包：`contract_version = "1"`、`origin = compile`、`compiler_identity`、`base_release_id`/`base_epoch` 取调用方给的当前 Head；
    `removals` 为空（整版替换在 S5）；
  - 序列化结果须通过 `contracts/candidate_bundle.schema.json` 校验，且不超过 2 MiB，否则报错。

### 2.3 平台客户端（新增 `bundle/client.py`）

- `PlatformClient(base_url, api_key, transport=None)`：`submit(space, bundle) -> Candidate`、`decide(space, candidate_id, decision) -> Decision`、
  `activate(space, candidate_id, decision_id) -> Release`、`release(space, release_id="") -> Release`。
- 与 S4c-1 读取端同样加固：只接受 http(s)、不带 userinfo/query/fragment；不跟随重定向；不读环境代理；超时 30 秒；
  严格 JSON（拒绝重复键与 NaN）；响应体上限 32 MiB。
- 错误：`PlatformError(code)`，`code` 取平台返回的已知错误码；没有错误码的 401 → `UNAUTHENTICATED`、403 → `RELEASE_ACCESS_DENIED`，
  其余 → `SERVICE_UNAVAILABLE`；不把响应正文或传输诊断放进异常。
- `publish(...)`：读当前 Head → 生成候选包 → 提交 →（显式给出时）决定 →（显式要求时）激活 → 读回该 Release，逐成员核对
  `member_digest` 与提交时一致，不一致报错。**不自动批准**：决定必须由调用方显式给出（"先发布后抽检"的自动门槛在 S12）。

### 2.4 从 WeKnora 读页（新增 `ingest/source_map.py`；`eval/compile_run.py` 增加 `--source-map`）

- source map 文件：`{"space_id": "...", "products": {"<产品>": [{"knowledge_id": "...", "parse_attempt": 2}, ...]}}`。
- `load_pages(reader, space_id, entries) -> (pages, sources)`：经 S4c-1 读取端逐个文档读页，返回页文本与"文件名 → 修订"映射；
  同名文件重复、读取失败一律报错。
- `compile_run --source-map <file>`：页文本改为从 WeKnora 读取（地址与密钥来自环境变量 `HARNESS_WEKNORA_BASE_URL`、
  `HARNESS_WEKNORA_API_KEY`），其余流程不变。
- 发布命令：`python -m insurance_harness.compilers.schema_fields.publish --run-root <dir> --product <id> --source-map <file>
  [--decide human --reason <文本> | --decide machine --policy-ref <标识>] [--activate]`。失败只输出稳定错误码与可公开的字段位置，
  不输出异常正文、本机路径或输入内容（审核 PR #169 第 2 项）。

## 3. 验收（受保护，RED 单独提交）

> 模块按蓝图 §4.2 的目标目录放置（RED 后修正，见 PR）：`bundle/` 负责 CandidateBundle 组装与提交，只依赖合同（核心目录不得依赖 `compilers`，守卫 G1）；把编译结果转成 Claim 属于编译器自己的职责；读 SourceRevision 并重建页文本属于 `ingest/`。

- `internal/enterprise/release/canonical_vectors_test.go`、`internal/enterprise/release/testdata/canonical_vectors.json`。
- `harness/tests/bundle/test_canonical.py`：共用样例逐条一致；NaN、无穷、超界整数、孤立代理字符被拒。
- `harness/tests/bundle/test_bundle.py`：每个字段一条成员；证据偏移切出原文；引用格式；unknown 无证据；包通过合同 schema 校验；
  `member_digest` 与规范化结果一致；编号与证据对不上、文件不在 source map 中时报错。
- `harness/tests/bundle/test_client.py`：提交、决定、激活、读回的正常路径；平台错误码映射；拒绝重定向与重复键 JSON；
  读回摘要不一致时报错；未显式给出决定时不决定、不激活。

## 4. 改动范围

- 允许：`harness/src/insurance_harness/bundle/`（新）、`ingest/`（新）、`evidence/source_ref.py`（新）、`evidence/segments.py`、`compilers/schema_fields/claims.py` 与 `publish.py`（新）、`compilers/schema_fields/engine.py`（`CompileOutput.cards_version`）、`eval/compile_run.py`、`eval/product_sources.py`、
  对应实现方测试；Go 只加本片验收测试与 testdata，不改运行时代码。
- 受保护：本片验收文件、既有受保护验收、`docs/design/`、蓝图、`contracts/`。

## 5. 真实调用与环境

- 无模型调用。客户端测试用 httpx MockTransport；连真实 WeKnora 的端到端演示依赖 S4c-2c，另行申请环境。

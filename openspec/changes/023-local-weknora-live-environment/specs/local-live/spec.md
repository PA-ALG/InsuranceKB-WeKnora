# 023 本机 WeKnora live 环境验收规格

## ADDED Requirements

### Requirement: R1.1 模型角色必须独立可配置且零泄漏

WeKnora Chat、Embedding、ReRank 与 Harness extraction SHALL 是独立 profile。Harness extraction SHALL 使用 `HARNESS_LLM_BASE_URL`、`HARNESS_LLM_API_KEY`、`HARNESS_LLM_MODEL_WEAK`，初始 profile SHALL 支持百炼 OpenAI-compatible `deepseek-v4-flash`；切换配置 SHALL NOT 改变代码、数据库 schema 或 KB identity。模型 provider 与长期管理员凭据 SHALL 只存在 mode `0600` 本地文件，SHALL NOT 进入 Git、GitHub、runner 或日志。controller MAY 按 R5.1 将七项 per-run `HARNESS_LIVE_*` 临时值注入 runner，但 SHALL 按 R5.2 清理；短时 runner registration token SHALL 不得持久化或进入日志。

#### Scenario: 切换抽取模型

- **WHEN** 只修改 Harness extraction 的 base URL/key/model
- **THEN** extraction probe 使用新 profile
- **AND** WeKnora 三个 profile、Space 与 KB identity 均不变化

#### Scenario: 配置或探针失败

- **WHEN** 文件权限、必填值、HTTPS 或响应形态无效
- **THEN** provision 在任何持久 mutation 前失败
- **AND** 输出只含字段/角色与 `SET`、`EMPTY` 或 invalid，不含 URL、token、password、response body

### Requirement: R1.2 百炼五角色必须使用显式 provider/protocol 并在 mutation 前零泄漏直探

WeKnora Chat、Embedding、ReRank、VLLM 与 Harness extraction 五个 profile SHALL 分别显式声明 provider 与 protocol。四个初始 WeKnora 模型 SHALL 使用 `source=remote`、`provider=aliyun`，且 type SHALL 仅为并按角色映射到 `KnowledgeQA`、`Embedding`、`Rerank`、`VLLM`。Chat SHALL 使用 `openai_compatible` chat completions protocol；Embedding SHALL 使用 `openai_compatible` embeddings protocol；VLLM SHALL 使用 `openai_compatible` vision chat completions protocol；ReRank SHALL 使用 `dashscope_native`。只有 VLLM MAY 声明 `supports_vision=true`。初始百炼 profile SHALL 分别为 Chat `deepseek-v4-flash`、Embedding `qwen3.7-text-embedding`、ReRank `qwen3-rerank`、VLLM `qwen3.7-plus` 和 extraction `deepseek-v4-flash`；各角色的 model、endpoint、key、provider 与 protocol SHALL 独立，不得从共用 key 推导其他角色配置，也 SHALL NOT 把 `siliconflow` 硬编码为 source 或 provider。

全部五个 direct probe SHALL 在任何 tenant/model/KB/knowledge 持久 mutation 前成功：Chat/extraction SHALL 返回非空 completion content；Embedding SHALL 返回非空有限数值向量，且维度 SHALL 由实际向量长度取得；VLLM SHALL 读取已提交的非敏感 visual-canary fixture 并在响应中命中 canary，非空文本不足以通过。ReRank SHALL 使用 `dashscope_native` protocol 与精确 endpoint `https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank`；probe 与持久模型 SHALL 共用同一 resolved endpoint、含 `model`、`input.query`、`input.documents`、`parameters` 的 request envelope 和 `output.results` response。实现 SHALL NOT 追加 legacy `/rerank`，也 SHALL NOT 探测与持久配置不同的 compatible endpoint。`output.results` 的 index SHALL 是唯一、输入范围内的整数，score SHALL 是有限数，并达到配置的最小结果数。

五角色 fault injection SHALL 分别断言 exception、logs、stdout 和 stderr 不含任一已配置 URL、API key、Authorization 值、prompt、request body、response body 或解析文档内容。HTTP 客户端 SHALL 使用 `trust_env=False`；测试名 SHALL 使用 `test_r1_2_*` 以指向本条款。

#### Scenario: 五个 direct probe 全部成功

- **WHEN** 五个 profile 合法，Chat/extraction 正文非空、Embedding 向量合法、native ReRank 结果合法且 VLLM 命中 visual canary
- **THEN** provisioning MAY 进入四个 WeKnora 模型 ensure 阶段
- **AND** Embedding 维度使用本轮 probe 实际观测值

#### Scenario: provider/type/native ReRank 合同不合法

- **WHEN** source 不是 `remote`、初始 provider 不是 `aliyun`、角色 protocol 不匹配、type 不在合法集、source/provider 被硬编码为 `siliconflow`，或 ReRank endpoint、envelope、`output.results` 任一不匹配
- **THEN** provisioning SHALL fail closed
- **AND** tenant/model/KB/knowledge 持久 mutation 为零

#### Scenario: 任一角色探针失败或返回敏感内容

- **WHEN** 五个 direct probe 中任一失败，或 fault injection 使供应商把请求/响应内容带入错误
- **THEN** provisioning SHALL 在持久 mutation 前失败
- **AND** exception、logs、stdout 与 stderr 均 SHALL 满足五角色零泄漏合同

### Requirement: R2.1 本机服务必须 loopback-only 且版本固定

app、frontend 与 Harness PostgreSQL 的宿主端口 SHALL 显式绑定 `127.0.0.1`；其他依赖 SHALL 不发布宿主端口。WeKnora、依赖镜像与 runner package SHALL 固定版本及 digest/checksum。app SHALL NOT 使用旧发布 digest、`latest`、固定本地 tag 或其他可漂移引用；它 SHALL 由受信 workflow 从 source lock 指定的 clean exact revision 构建，发布到企业 registry，并以 manifest digest 消费。构建 SHALL 产出可验证 provenance 与 SBOM，source lock SHALL 固定 repository、commit、tree、Dockerfile digest、目标平台及所需安全祖先；app source SHALL 同时包含 scoped tenant API key route 与 model-debug access-log 脱敏。`local_live.py up` 只 SHALL 验明并拉取固定 digest，不得在持久服务启动路径内隐式构建 dirty checkout。Docker build context SHALL 排除 `.env` 与全部 `.env.*` 本地配置，尤其是 `.env.local-live` 与 `.env.local-live.runtime`，使模型 key、管理员密码、数据库密码与 AES key 不进入 daemon context、builder layer 或 cache。

Harness PostgreSQL SHALL 使用随机本地密码而非示例值。ignored mode-`0600` runtime SHALL 分别生成并持久保存非空、恰好 32-byte 的 `TENANT_AES_KEY` 与 `SYSTEM_AES_KEY`；两者 SHALL 独立生成、作为 secret 注入 rendered app，且 SHALL NOT 出现在 repr、logs、stdout 或 stderr。缺少 `TENANT_AES_KEY` 的既有 current runtime SHALL 原子迁移并保留其余合法字段；任一 AES key 缺失、为空或 byte 长度不等于 32 时启动 SHALL fail closed。

#### Scenario: rendered Compose 出现宽监听或漂移

- **WHEN** rendered Compose 含 bare port、`0.0.0.0`、`::`、host network、`latest` 或 lock 不匹配
- **THEN** 启动 SHALL fail closed
- **AND** 不创建或重建持久卷

#### Scenario: app artifact 缺少固定来源或运行时能力

- **WHEN** app 未固定 manifest digest、provenance/source lock 不匹配、缺少 scoped tenant API key route 或缺少 model-debug 日志脱敏
- **THEN** 启动 SHALL fail closed
- **AND** app、依赖服务与持久卷 SHALL 保持未启动、未重建

#### Scenario: source build context 包含本机凭据

- **WHEN** `.dockerignore` 未同时排除 `.env` 与 `.env.*`，或受信构建的 source identity 与 source lock 不一致
- **THEN** artifact 发布与 app attestation SHALL fail closed
- **AND** 本机配置 SHALL NOT 进入 Docker daemon context、layer 或 cache

#### Scenario: 首次 bootstrap 或既有 runtime 缺少 tenant 加密 key

- **WHEN** 创建新本机 runtime，或读取只含合法 `SYSTEM_AES_KEY` 而缺少 `TENANT_AES_KEY` 的既有 current runtime
- **THEN** SHALL 在启动或管理员首次注册前持久得到两个分别生成、非空且恰好 32-byte 的 AES key
- **AND** rendered app SHALL 同时接收两 key，迁移 SHALL 原子、mode-`0600` 且零 secret 输出

### Requirement: R3.1 WeKnora 资源必须幂等且验证所有权

bootstrap SHALL 只在 R2.1 已验明 app 的固定 digest/provenance/source lock，且 rendered app 同时收到合法 `TENANT_AES_KEY` 与 `SYSTEM_AES_KEY` 后，建立明确的初始管理员、专用 tenant、三种 WeKnora 模型、KB-RAW、KB-WIKI、最小权限 Tenant API Key 与绑定 KnowledgeSpace。app source SHALL 包含 scoped tenant API key routes；若 route 缺失或返回 404，provision SHALL fail closed，SHALL NOT 降级创建、复用或暴露 legacy full-access API key。稳定名称资源只有 environment marker、tenant、模型角色、Embedding 维度及 KB 角色全匹配时 SHALL 复用，否则 SHALL fail closed。

#### Scenario: 重复运行相同配置

- **WHEN** 对同一环境重复 provision
- **THEN** SHALL 返回同一 tenant/model/KB/Space identity
- **AND** 不产生重复资源或扩大权限

### Requirement: R3.2 原始 PDF 必须按 SHA-256 管理

KB-RAW SHALL 仅复用 KB identity 与 SHA-256 均匹配的唯一 completed knowledge；否则 SHALL 上传一次并等待非空 chunks。KB-WIKI SHALL 不接收源 PDF，只允许本环境 ownership marker 页面，未知页面 SHALL fail closed。

#### Scenario: 同一 PDF 重复 provision

- **WHEN** 选定 PDF 的 SHA-256 与已完成 knowledge 匹配
- **THEN** SHALL 复用该 knowledge
- **AND** 不重复上传或清空无关页面

### Requirement: R3.3 存储模型验证、KB 默认关闭与显式 VLM smoke 必须 fail closed

只有 R1.2 全部 direct probe 通过后，provisioning 才 SHALL 在 R3.1 原三模型范围之外新增 VLLM，并创建或复用 Chat、Embedding、ReRank、VLLM 四个 WeKnora 模型。模型 identity SHALL 包含 environment marker、tenant、role、type、provider、model name 与 endpoint fingerprint。fingerprint SHALL 是 canonical endpoint URL 的 SHA-256。canonicalization SHALL 小写 scheme/host、删除默认 port、把空 path 规范为 `/`、拒绝 user-info/query/fragment、拒绝 `.`/`..` dot segment 与重复斜杠、把 percent-encoding 的十六进制字母大写，并除 root 外删除尾随斜杠。实现 SHALL 分别从本地 desired URL 和 WeKnora 返回 URL 按该算法重算 digest。ignored mode-`0600` runtime state 只 MAY 保存 canonical endpoint fingerprint，SHALL NOT 保存 raw endpoint，也 SHALL NOT 保存 API secret/key 原文或 digest/fingerprint；它 SHALL 保存稳定资源 identity，包括 provisioned VLLM model ID。

四个 model ensure 后 SHALL 通过 `PUT /models/:id/credentials` 刷新本轮凭据且保持稳定 model ID，不保存 key 或 key digest/fingerprint。Chat、Embedding 与 ReRank SHALL 不重发 key，而是分别通过 multipart `POST /models/:id/debug` 验证存储模型。HTTP 200 或外层 `success=true` 不足以通过；`data.ok` SHALL 严格为 true，且角色级 `raw_response` SHALL 满足：Chat 含非空 content；Embedding 含非空有限数值向量，且维度等于 R1.2 direct probe；ReRank 满足 R1.2 的 native `output.results` index/score/最少数量合同。`data.error` 与 `raw_response` SHALL NOT 进入 logs、stdout、stderr 或 evidence。任一 credential refresh 或 stored-model debug 失败时，KB/knowledge mutation SHALL 为零；已幂等创建的 model record 或已刷新 credential MAY 保留供下次复用。

KB-RAW 创建与复用 SHALL 都从真实 create/list/get REST response 验明 `embedding_model_id` 等于本轮已验明的 Embedding model ID、`vlm_config.enabled=false` 且 `vlm_config.model_id=""`；任一差异 SHALL fail closed。上传客户端 SHALL 接受 optional typed process configuration，只有存在时才 SHALL 将它串行化为 multipart `process_config`；省略时，既有 multipart 字段名称/值、文件 tuple（文件名、content、media type）与 metadata SHALL 语义等价，不要求 boundary 或其他易变传输字节相同。选定的普通寿险 PDF SHALL 只在该 KB 禁用态验明后上传，且 multipart payload SHALL NOT 发送 `enable_multimodel` 或 `process_config`。

只有独立的非敏感 visual-canary smoke SHALL 显式发送 multipart `enable_multimodel=true` 与串行化 `process_config`，其值 SHALL 等于 `{"enable_multimodel":true,"vlm_config":{"enabled":true,"model_id":"<provisioned-vllm-id>"}}`。smoke knowledge SHALL 按 KB identity + fixture SHA-256 内容寻址，并使用 typed/paginated 请求获取 `image_ocr` 与 `image_caption` 子 chunks。至少一个 `image_ocr` SHALL 具有非空 `parent_chunk_id`，且其内存 content assertion SHALL 命中 visual canary；任一存在的 `image_caption` SHALL 具有非空 `parent_chunk_id`。canary 文本与模型输出 SHALL NOT 写入 evidence。

失败、取消或 incomplete 的 smoke record SHALL 保留，且 SHALL NOT 自动 retry 或重复上传。只有操作员显式执行一次 `cd harness && uv run python scripts/local_live.py retry-vlm --knowledge-id <id>` 时，才 SHALL 对同一 knowledge ID 发送单次 `POST /knowledge/:id/reparse`，且 JSON `process_config` SHALL 与原显式 VLM override 完全相同；空 body reparse 禁止。命令 SHALL 在发出 API 请求前于 ignored mode-`0600` runtime state 持久记录该 knowledge 的 retry 已消费；已有已消费记录的第二次调用 SHALL 在发出 API 请求前 fail closed。retry SHALL 复用已存 knowledge/source，增加 attempt 并等待 terminal state；第二次失败 SHALL 保留记录并只报告 knowledge ID、attempt、status 与 sanitized error class，不循环、不上传副本。测试名 SHALL 使用 `test_r3_3_*` 以指向本条款。

#### Scenario: 四模型 credential refresh 与 stored debug 全部验明

- **WHEN** 五个 direct probe 通过，四个模型 identity/fingerprint 匹配，凭据已刷新，且 Chat/Embedding/ReRank debug 的 `data.ok` 与 role-level `raw_response` 合法
- **THEN** provisioning MAY 进入 KB-RAW 创建或复用
- **AND** KB-RAW SHALL 绑定本轮 Embedding ID 并精确禁用 VLM

#### Scenario: stored-model 验证失败

- **WHEN** endpoint fingerprint、credential refresh、`data.ok` 或任一 role-level `raw_response` 验证失败
- **THEN** provisioning SHALL fail closed
- **AND** KB/knowledge mutation SHALL 为零，且输出不得含 `data.error` 或 `raw_response`

#### Scenario: 普通 PDF 保持文本解析

- **WHEN** KB-RAW 的本轮 Embedding 绑定与精确 VLM 禁用态已从 REST 验明
- **THEN** 普通 PDF upload SHALL 不包含 `enable_multimodel` 与 `process_config`
- **AND** 原有 multipart 字段名称/值、文件 tuple 与 metadata SHALL 语义等价，不比较 boundary 或其他易变传输字节，且普通 PDF 完成后 SHALL 具有非空 chunks

#### Scenario: 独立 VLM smoke 成功

- **WHEN** visual-canary fixture 以本轮 VLLM ID 的精确 multipart opt-in 上传并达到 completed
- **THEN** typed/paginated chunk 获取 SHALL 找到具有 parent 且命中 canary 的 `image_ocr`
- **AND** 任一 `image_caption` SHALL 具有 parent，且 evidence 不含 canary 或模型输出

#### Scenario: VLM smoke 失败后显式单次重解析

- **WHEN** 一条失败/取消/incomplete smoke record 被操作员显式执行 `cd harness && uv run python scripts/local_live.py retry-vlm --knowledge-id <id>`
- **THEN** 系统 SHALL 在 API 前持久记录 retry 已消费，并只对原 knowledge 发送一次同配置 `reparse`
- **AND** 不自动再试、不重复上传，重复失败时保留 sanitized attempt/status evidence

#### Scenario: VLM smoke retry 不得消费两次

- **WHEN** mode-`0600` runtime state 已记录该 knowledge 的 retry 已消费，操作员再次执行完整 `retry-vlm` 命令
- **THEN** 命令 SHALL 在发送 `POST /knowledge/:id/reparse` 前 fail closed
- **AND** SHALL 不发出其他 retry/reparse 或重复上传，只报告 sanitized knowledge ID、attempt 与状态

### Requirement: R4.1 live workflow 必须来自受信 main 并锁定 PR SHA

`workflow_dispatch` SHALL 接收 `pr_number`、完整 `head_sha` 与随机 `runner_nonce`。无 live secret 的 GitHub-hosted preflight SHALL 验证 PR open、来自同仓且 head 精确相等；live job SHALL detached checkout 该 SHA；GitHub-hosted postflight SHALL 再验证 head 未变化。该 workflow SHALL 在 PR #9 live acceptance 前先合入 `main`。

#### Scenario: fork、过期或变化的 SHA

- **WHEN** PR 来自 fork、已关闭、输入不是完整 SHA、输入与 PR head 不同或运行中 head 改变
- **THEN** run SHALL 失败
- **AND** 不把该 run 记为 live evidence

### Requirement: R4.2 live collection 与 JUnit 必须精确冻结

受信 manifest SHALL 精确包含以下五个 node ID，执行前 collection SHALL 与其 exact set equality；JUnit SHALL 包含相同 identity 且 `tests=5 skipped=0 failures=0 errors=0`：

1. `tests/test_knowledge_publisher.py::test_k5_5_live_publish_and_rollback_roundtrip`
2. `tests/test_live.py::test_live_knowledge_endpoint_shape`
3. `tests/test_live.py::test_live_wiki_page_crud_roundtrip`
4. `tests/test_release_snapshot_live_018.py::test_r6_4_live_release_v1_v2_rollback_roundtrip`
5. `tests/test_source_bridge_live_017.py::test_live_source_bridge_compiler_import_evidence_backlink`

#### Scenario: 数量相同但节点被替换

- **WHEN** collection 或 JUnit 仍为五项但任一 identity 缺失、重复或被替换
- **THEN** gate SHALL 失败
- **AND** 不得以 pytest exit 0 冒充成功

### Requirement: R5.1 public repo runner 必须隔离且一次性

runner SHALL 使用固定 version/checksum、随机唯一 name/label、非 root 与 `--ephemeral`，最多执行一个 job；SHALL 不挂载 Docker socket、宿主 home 或持久 workspace，只加入 WeKnora app 与 Harness PostgreSQL 内网。runner SHALL 只接收两个 secret 与五个 variable 的七项 `HARNESS_LIVE_*` 值。

#### Scenario: runner 配置扩大宿主访问

- **WHEN** runner 缺少唯一 label/ephemeral、以 root 运行、存在宿主/Docker 挂载或收到模型/管理员凭据
- **THEN** controller SHALL 拒绝注册或启动

### Requirement: R5.2 任意退出路径必须清理临时资源

成功、失败或取消时，controller SHALL 尝试删除七个 GitHub environment 值、撤销 per-run Tenant key 与 PostgreSQL role、注销 runner，并删除唯一容器、匿名卷、workspace 与诊断日志，且 SHALL 保留原始失败。

#### Scenario: live job 失败且部分 cleanup 也失败

- **WHEN** live job 抛出主错误且一个 cleanup action 失败
- **THEN** 其余 cleanup actions 仍 SHALL 执行
- **AND** 最终报告保留主错误并列出 sanitized cleanup failure

### Requirement: R6.1 live evidence 必须分层、可溯源且覆盖最终 SHA

local 与 GitHub evidence SHALL 分别记录 exact node identities、SHA、时间、JUnit 计数和 sanitized cleanup 状态。skip/NOT RUN SHALL NOT 描述为成功。证据文档提交后 SHALL 冻结 PR #9，并对最终 SHA 重新运行 `cd harness && uv run ruff check .`、`cd harness && uv run mypy src tests`、`cd harness && uv run pytest -m "not live and not integration_postgres" -q`、`openspec validate 023-local-weknora-live-environment --strict`、PostgreSQL、完整五节点 live 与独立 VLM smoke。VLM smoke SHALL 使用稳定命令 `cd harness && uv run python scripts/local_live.py smoke-vlm`；它 SHALL 是 final-SHA local acceptance，SHALL NOT 添加到冻结的 PR #9 五 node collection。dirty worktree 运行 SHALL 记录 `HEAD`、`dirty=true` 与 diff digest，且只能作 provisional evidence；只有 clean commit 且上述 final-SHA 门禁全部通过时 SHALL 记为 exact accepted SHA。最终 run 与 VLM/JUnit/cleanup proof SHALL 外置于 PR comment/check summary，之后 SHALL 不再改变 head。

#### Scenario: 实现 SHA 通过但证据提交改变 head

- **WHEN** 第一次 live 后提交 validation/HANDOFF 形成新 SHA
- **THEN** PR Ready 前 SHALL 对新 SHA 重跑 Ruff、mypy strict、not-live pytest、OpenSpec strict、PostgreSQL、冻结五节点 live 与稳定命令 VLM smoke
- **AND** 最终 live 后不得再提交分支变更

#### Scenario: dirty worktree 执行 VLM smoke

- **WHEN** VLM smoke 在存在未提交差异的 worktree 上执行
- **THEN** evidence SHALL 标记 `dirty=true`、当前 `HEAD` 与 diff digest，并且 SHALL 标记为 provisional
- **AND** 该运行 SHALL NOT 充当 exact final-SHA acceptance 或 PR #9 第六个 node

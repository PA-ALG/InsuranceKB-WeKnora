# 023 本机 WeKnora live 环境设计

## 1. 两个数据面与一个执行面

WeKnora Compose 拥有平台 PostgreSQL、Redis、docreader、app、frontend；`docker-compose.harness.yml` 拥有独立 PostgreSQL 16。宿主只将 app/frontend/Harness PostgreSQL 绑定到 `127.0.0.1`。一次性 GitHub runner 容器只加入 WeKnora app 与 Harness PostgreSQL 内网，不挂载宿主 home、持久 workspace 或 Docker socket。

官方 `wechatopenai/weknora-app:v0.6.3` digest 早于 scoped tenant API key routes，不能承担本轮真实 provision。固定本地 tag 与 dirty checkout build 也不能形成企业级可复现证据。最终 app 由受信 workflow 从 source lock 指定的 clean exact revision 构建并发布到 GHCR；source lock 固定 repository、commit、tree、Dockerfile digest、目标平台与必须包含的安全祖先，构建产出 provenance/SBOM，Compose 与 `images.lock` 只消费 manifest digest。`local_live.py up` 不承担构建。

根 `.dockerignore` 同时排除 `.env` 与 `.env.*`，避免 `.env.local-live`/runtime 的模型、管理员、数据库与 AES secret 进入 build context、layer 或 cache。app source 必须同时包含 scoped tenant API key routes 与 `/models/:id/debug` access-log 响应省略；前者缺失时禁止退回 legacy full-access key，后者缺失时禁止把 prompt、provider error、raw response 或 reasoning 写入日志。固定 app digest 未发布并写回 lock 前，T7 保持 `NOT RUN`。

ignored mode-`0600` runtime 独立生成并持久保存 `TENANT_AES_KEY` 与 `SYSTEM_AES_KEY`，两者都必须非空且 UTF-8 byte 长度恰好为 32，并只作为 secret 注入 app。`TENANT_AES_KEY` 供 tenant API key 生成路径使用，不能以 `SYSTEM_AES_KEY` 代替；管理员首次注册前 rendered Compose 必须验明两者。既有 current runtime 若仅缺 `TENANT_AES_KEY`，以 mode-`0600` 临时文件 + `fsync` + `os.replace` 原子加入新 key并保留其他合法字段；其他缺失、空值、示例值或长度异常一律 fail closed。repr、logs、stdout、stderr 和 evidence 只允许字段已设置状态，不得包含任一 key。

## 2. Provider-aware 模型配置与五个 direct probe

`.env.local-live` 是 mode `0600` 的本地输入。五个角色的首个百炼 profile 是：WeKnora Chat `deepseek-v4-flash`、Embedding `qwen3.7-text-embedding`、ReRank `qwen3-rerank`、VLLM `qwen3.7-plus`，以及 Harness extraction `deepseek-v4-flash`。每个角色的 model、base URL、API key、provider 和 protocol 均独立；即使本地配置使用相同凭据，代码也不推断凭据共享。Harness extraction 继续使用既有 `HARNESS_LLM_BASE_URL`、`HARNESS_LLM_API_KEY`、`HARNESS_LLM_MODEL_WEAK`；切换 profile 只改配置，不改代码、schema 或 KB identity。

四个初始 WeKnora 远程模型都显式使用 `source=remote` 与 `provider=aliyun`，合法 type 仅为 `KnowledgeQA`、`Embedding`、`Rerank`、`VLLM`，并按角色一一映射；只有 VLLM 可声明 `supports_vision=true`。Chat 使用 `openai_compatible` chat completions，Embedding 使用 `openai_compatible` embeddings，VLLM 使用 `openai_compatible` vision chat completions，ReRank 使用 `dashscope_native` 与精确 endpoint `https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank`。probe 与注册共用同一 resolved endpoint、`model`/`input.query`/`input.documents`/`parameters` envelope 与 `output.results` 响应，不追加旧 `/rerank`。配置与 provisioning 不得把 `siliconflow` 硬编码为 source 或 provider。

任何持久 WeKnora mutation 前运行全部五个 direct probe。Chat/extraction 需要非空 completion content；Embedding 需要非空有限数值向量并以实际长度为维度；ReRank 需要 native `output.results`、唯一且范围内的整数 index、有限 score 与最少结果数；VLLM 必须读取已提交的非敏感 visual-canary fixture 并在响应中命中 canary。五角色故障注入覆盖 exception、log、stdout 和 stderr，均不得含 URL、key、Authorization、prompt、request/response body 或文档内容；HTTP 客户端保持 `trust_env=False`。

## 3. 四模型幂等性、凭据刷新与存储模型验证

管理员 bootstrap 及全部 direct probe 只能在 app digest/provenance/source lock、runtime 与 rendered app 的两个 32-byte AES key 全部验明后执行。scoped tenant API key route 缺失或 404 是 source/runtime 不满足合同，必须停止，不能退回 legacy full-access key。全部 direct probe 通过后，provisioning 创建或复用 Chat、Embedding、ReRank、VLLM 四个 WeKnora 模型。模型复用需要 environment marker、tenant、role、type、provider、model name 和 endpoint fingerprint 全匹配。fingerprint 是 canonical URL 的 SHA-256：canonicalization 小写 scheme/host、删除默认 port、把空 path 规范为 `/`、拒绝 user-info/query/fragment、拒绝 `.`/`..` dot segment 与重复斜杠、把 percent-encoding 的十六进制字母大写，并除 root 外删除尾随斜杠。desired URL 与 WeKnora 返回 URL 都按该算法重算 fingerprint。ignored mode-`0600` runtime state 只保存 canonical endpoint fingerprint，不保存 raw endpoint，也绝不保存 API secret/key 原文或 digest；它必须保存稳定资源 identity，包括本轮 VLLM model ID。

每个模型 ensure 后都经 `PUT /models/:id/credentials` 刷新当前 API key，保持稳定 model ID 且不保存 key 或 key digest/fingerprint。Chat、Embedding 和 ReRank 再通过 multipart `POST /models/:id/debug` 验证，不重发 key；除 HTTP 成功与外层 `success=true` 外，`data.ok` 必须严格为 true，并按角色解析 `raw_response`：Chat 正文非空；Embedding 向量为有限数值且维度等于 direct probe；ReRank 满足同一 native results 合同。`data.error` 和 `raw_response` 不记日志、stdout/stderr 或 evidence。任一失败禁止后续 KB/knowledge mutation，但允许本次幂等 model record 或已刷新 credential 留作下次复用。

KB-RAW 创建与复用都必须从真实 REST response 验明 `embedding_model_id=<本轮 Embedding ID>`、`vlm_config.enabled=false` 与 `vlm_config.model_id=""`；任一不匹配就 fail closed。其他稳定名称资源仍只在 tenant、角色、Embedding 维度和 environment ownership marker 全匹配时复用。KB-RAW 以 SHA-256 + KB identity 复用唯一 completed knowledge 且要求非空 chunks；KB-WIKI 不上传原始文档，只接受带本环境 marker 的 Harness 页面，未知页面禁止自动清理。KnowledgeSpace 必须绑定真实 tenant/raw/wiki IDs。

## 4. 普通 PDF 默认关闭，VLM smoke 显式 opt in

上传客户端接受 optional typed process configuration，仅在调用方传入时将其串行化为 multipart `process_config`；省略时必须保持原有 multipart 字段名称/值、文件 tuple（文件名、content、media type）与 metadata 的语义等价，不要求 boundary 或其他易变传输字节相同。选定的普通寿险 PDF 在 KB 禁用态验明后上传，multipart payload 不包含 `enable_multimodel` 也不包含 `process_config`，因而保持现有文本解析路径。只有独立、非敏感、内容寻址的 visual-canary fixture 通过 multipart 显式发送 `enable_multimodel=true` 与串行化 `process_config={"enable_multimodel":true,"vlm_config":{"enabled":true,"model_id":"<provisioned-vllm-id>"}}`。

smoke 以 typed/paginated API 获取 `image_ocr` 和 `image_caption` 子 chunks：至少一个 `image_ocr` 必须有非空 `parent_chunk_id`，并仅在内存断言内命中 canary；任一存在的 `image_caption` 也必须有非空 parent。evidence 只记录计数、stable IDs、fixture SHA、attempt 和 sanitized status，不记 canary 或模型输出。失败、取消或未完成记录保留且不自动 retry/re-upload；只有操作员显式执行一次 `cd harness && uv run python scripts/local_live.py retry-vlm --knowledge-id <id>` 时，才对同一 knowledge ID 执行单次 `POST /knowledge/:id/reparse`，JSON `process_config` 必须是相同 VLM override。命令在发出 API 请求前于 ignored mode-`0600` runtime state 持久记录该 knowledge 的 retry 已消费；第二次调用必须在发出 API 请求前拒绝。重复失败保留记录并报告 sanitized 类别，不循环重试或上传副本。

## 5. 受信 workflow

public repo 的 `workflow_dispatch` 定义来自 `main`，输入 `pr_number`、完整 `head_sha`、随机 `runner_nonce`。GitHub-hosted、无 live secret 的 preflight 验证 open same-repository PR、当前 head 精确相等和 nonce；live job detached checkout 该不可变 SHA，并只接收两个 secret 与五个 variable。GitHub-hosted postflight 再检查 PR head 未变化。

live collection 冻结为规格中的五个完整 node ID；执行前做 exact set equality，JUnit 必须 `tests=5 skipped=0 failures=0 errors=0` 且 identity 集完全相同。VLM smoke 为独立的 final-SHA 本机 provisioning acceptance，不添加到 PR #9 五节点 manifest/JUnit。

## 6. Runner 与清理

官方 Actions runner 版本与 checksum 固定在 lockfile。每次运行使用随机 `insurancekb-live-<nonce>` 名称/label、非 root、`--ephemeral`、最多一个 job。controller 临时创建最小权限 Tenant API Key 与 PostgreSQL role，只把七个 live 值放入 GitHub environment。

成功、失败、取消都执行 cleanup：删除七个 GitHub 值、撤销 Tenant key/DB role、注销 runner、删除唯一容器/匿名卷/workspace/诊断日志。模型密钥、管理员凭据、runner registration token 永不写入 GitHub 或持久 runtime 文件。持久业务卷不自动删除。

## 7. 验收与 SHA 自引用

先对实现 SHA 跑 live 并把证据写入 018 文档；证据文档提交后冻结分支，再对最终 SHA 重跑 Ruff、mypy strict、not-live pytest、OpenSpec strict、PostgreSQL、冻结五节点 live 与独立 VLM smoke。VLM smoke 的稳定本机入口是 `cd harness && uv run python scripts/local_live.py smoke-vlm`。该命令在 dirty worktree 上必须记录 `HEAD`、`dirty=true` 和 diff digest，只能作 provisional evidence；只有 clean commit 且上述门禁全部通过才能记为 exact accepted SHA。最终 run URL/JUnit/VLM smoke/cleanup proof 写 PR comment/check summary，避免为记录证据继续改变 SHA。

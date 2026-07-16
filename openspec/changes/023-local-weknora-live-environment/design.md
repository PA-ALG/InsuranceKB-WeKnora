# 023 本机 WeKnora live 环境设计

## 1. 两个数据面与一个执行面

WeKnora Compose 拥有平台 PostgreSQL、Redis、docreader、app、frontend；`docker-compose.harness.yml` 拥有独立 PostgreSQL 16。宿主只将 app/frontend/Harness PostgreSQL 绑定到 `127.0.0.1`。一次性 GitHub runner 容器只加入 WeKnora app 与 Harness PostgreSQL 内网，不挂载宿主 home、持久 workspace 或 Docker socket。

## 2. 模型配置边界

`.env.local-live` 是 mode `0600` 的本地输入。WeKnora Chat、Embedding、ReRank 各自拥有明确的 provider/base URL/API key/model profile。Harness 抽取继续使用既有 `HARNESS_LLM_BASE_URL`、`HARNESS_LLM_API_KEY`、`HARNESS_LLM_MODEL_WEAK`；首个 profile 是百炼 OpenAI-compatible `deepseek-v4-flash`。切换抽取 provider/model 只改配置，不改代码、schema 或 KB identity。

本机启动前分别探测四个角色。Chat/抽取验证非空 `content`；推理模型按现有 `max_tokens>=4096`/截断重试语义；Embedding 由响应向量长度取得维度；ReRank 验证排序响应形态。HTTP 客户端 `trust_env=False`，日志只报告角色、模型、状态、耗时和 Embedding 维度，不输出 URL、密钥或响应正文。

## 3. 幂等资源与所有权

稳定名称资源仅在 tenant、角色、Embedding 维度和 environment ownership marker 全匹配时复用，否则 fail closed。KB-RAW 只保存选定 PDF；以 SHA-256 + KB identity 复用唯一 completed knowledge，并要求非空 chunks。KB-WIKI 不上传原始文档，只接受带本环境 marker 的 Harness 页面；未知页面禁止自动清理。KnowledgeSpace 必须绑定真实 tenant/raw/wiki IDs。

## 4. 受信 workflow

public repo 的 `workflow_dispatch` 定义来自 `main`，输入 `pr_number`、完整 `head_sha`、随机 `runner_nonce`。GitHub-hosted、无 live secret 的 preflight 验证 open same-repository PR、当前 head 精确相等和 nonce；live job detached checkout 该不可变 SHA，并只接收两个 secret 与五个 variable。GitHub-hosted postflight 再检查 PR head 未变化。

live collection 冻结为规格中的五个完整 node ID；执行前做 exact set equality，JUnit 必须 `tests=5 skipped=0 failures=0 errors=0` 且 identity 集完全相同。

## 5. Runner 与清理

官方 Actions runner 版本与 checksum 固定在 lockfile。每次运行使用随机 `insurancekb-live-<nonce>` 名称/label、非 root、`--ephemeral`、最多一个 job。controller 临时创建最小权限 Tenant API Key 与 PostgreSQL role，只把七个 live 值放入 GitHub environment。

成功、失败、取消都执行 cleanup：删除七个 GitHub 值、撤销 Tenant key/DB role、注销 runner、删除唯一容器/匿名卷/workspace/诊断日志。模型密钥、管理员凭据、runner registration token 永不写入 GitHub 或持久 runtime 文件。持久业务卷不自动删除。

## 6. 验收与 SHA 自引用

先对实现 SHA 跑 live 并把证据写入 018 文档；证据文档提交后冻结分支，再对最终 SHA 重跑 deterministic、PostgreSQL 和完整 live。最终 run URL/JUnit/cleanup proof 写 PR comment/check summary，避免为记录证据继续改变 SHA。

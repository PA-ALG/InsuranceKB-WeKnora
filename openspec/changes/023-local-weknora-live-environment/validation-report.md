# 023 本机 WeKnora live 环境验证报告

> 最后更新：2026-07-16。本文严格区分软件门禁、本机基础设施、供应商模型、WeKnora app 制品与真实 live；失败、skip、dirty-worktree provisional 与 `NOT RUN` 均不记为成功。

## 1. 当前状态

当前 follow-up 分支为 `codex/023-live-model-supply-chain`，基于 `origin/main@9d84f942`。PR #10 已将 T1～T5 合入 main；本分支承接后续五角色/VLM、双 AES key、供应链 app 制品与最终 live 收口。当前仍是未提交 worktree，因此下列本机软件/模型证据是 provisional，不是 final-SHA acceptance。

| 层级 | 状态 | 证据/下一步 |
|---|---|---|
| PR #10 T1～T5 | PASS / 已合入 | loopback Compose、原 provisioning/controller、受信 exact-SHA 五节点 gate、ephemeral runner/FIFO 均已在 PR #10 合入 |
| 百炼五角色 direct probe | PASS / provisional | Chat/extraction `deepseek-v4-flash`、Embedding `qwen3.7-text-embedding`（1024 维）、ReRank `qwen3-rerank`、VLLM `qwen3.7-plus`；`trust_env=False`，未输出 key/body |
| 本机 Compose 与 Harness PostgreSQL | PASS / provisional | WeKnora 服务与 Harness PostgreSQL healthy；宿主仅 `127.0.0.1:8080/8081/5442`；integration PostgreSQL `1 passed / 1400 deselected` |
| 双 AES bootstrap | PASS / provisional | runtime 独立持久 `TENANT_AES_KEY`/`SYSTEM_AES_KEY`，均 exact 32-byte；旧 runtime 原子迁移，rendered app 实机验明 32/32 |
| 官方 app digest | BLOCKED / 已定位 | 官方 v0.6.3 app 构建早于 scoped Tenant API Key routes；真实 `GET /tenants/10001/api-keys` 返回 404；禁止 legacy full-access key fallback |
| T6d.1 source-lock/workflow | PASS / 未提交 | exact upstream/tree/Dockerfile/security ancestors/platform/patch lock；trusted-main GHCR workflow；供应链契约 6 passed；R3.3 Go test通过 |
| T6d.2 GHCR app artifact | `NOT RUN` | 高权限 workflow 必须先人工复核并合入 main；尚无 manifest digest、provenance/SBOM/registry attestation，不得写回 `images.lock` |
| 完整 provision | INCOMPLETE | 已幂等留下 `user=1 / tenants=2 / models=4 / KBs=2`；在 scoped-key route 404 处 fail closed；未完成 Space/PDF/live acceptance |
| 独立 VLM smoke | `NOT RUN` | 等待 T6d.2 app digest 与完整 provision |
| 本机冻结五节点 | `NOT RUN` | 等待 T6d.2 app digest 与完整 provision；不能用 deterministic/Compose healthy 替代 |
| GitHub exact-SHA live / 018 T7 | `NOT RUN` | 等待 bootstrap workflow 合入 main、候选 SHA 冻结、T7 本机 acceptance |

## 2. T6a/T6b 模型与 VLM 增量

- 五个 profile 独立声明 provider/protocol/source/model/endpoint/key；WeKnora 四模型使用 `source=remote` 与合法 `KnowledgeQA`/`Embedding`/`Rerank`/`VLLM` 类型。
- ReRank 使用 DashScope native exact endpoint/envelope/result contract，不拼接 legacy `/rerank`。
- 五个 direct probe 全部发生在 persistent mutation 前；Embedding 维度从实际向量取得；VLLM 必须命中提交的非敏感 visual canary。
- 四个 WeKnora model identity 加入 provider/model/canonical endpoint fingerprint；每次 refresh credential 后，Chat/Embedding/ReRank 走 stored-model debug 严格验明 `data.ok` 与角色响应形态。
- KB-RAW 创建和复用都验明本轮 Embedding ID、`vlm_config.enabled=false`、`model_id=""`；普通 PDF 不发送 multimodal override。
- 独立 VLM smoke 显式发送 exact `process_config`；失败记录不自动重传，只允许 mode-0600 runtime 在 API 前消费一次的显式 reparse。

这些能力已有 deterministic contract 覆盖，但真实 VLM/完整 provision 仍受 app artifact 阻塞，保持 `NOT RUN`。

## 3. T6d.1 受信 app 供应链

### 3.1 根因与拒绝方案

固定官方 digest不包含 scoped Tenant API Key routes。曾尝试的 dirty checkout + mutable local tag 不能提供企业级 manifest identity/provenance，也会把 Harness SHA 与 WeKnora runtime 源混在一起，已经撤回；`local_live.py up` 继续只消费固定 digest，不隐式 build。

### 3.2 source lock

`deploy/local-live/weknora-app-source.lock.json` 固定：

- repository：`https://github.com/Tencent/WeKnora.git`
- commit：`5eefa70e6fc8f9ec27958779f91ece6cf685598c`
- tree：`a44f7eaeb40cf156d2893398046ffcb3094e5940`
- Dockerfile：`docker/Dockerfile.app`
- Dockerfile SHA-256：`be66005765bbc7db61851b07cd65529b0ee3c35d75f0eff84366d83a4cca3a32`
- target：`linux/arm64`
- 六个完整 scoped-key/security ancestor SHA
- checksum-locked downstream security patch
- GHCR repository：`ghcr.io/pa-alg/insurancekb-weknora-app`

补丁在 exact upstream checkout 上通过 `git apply --check` 与 `git diff --check`，并包含：

1. `/api/v1/models/:id/debug` response envelope 从 access log 整包省略；普通 response 保留既有字段脱敏。
2. 实际 upstream Docker context 排除 `.env.*`，不是只修改 Harness fork 的无效防线。
3. `golang-migrate` 固定为 go.mod 已声明的 `v4.19.1`。
4. uv 固定 `0.9.26`，执行安装脚本前校验 SHA-256。

### 3.3 trusted workflow

`.github/workflows/weknora-app-local-live-image.yml` 只允许 `workflow_dispatch` 且 job 要求 `refs/heads/main`；caller 不能传 repository/commit/platform。权限仅为 `contents: read`、`packages: write`、`id-token: write`、`attestations: write`，全部 GitHub/Docker Actions 使用完整 SHA pin，只使用 `github.token` 登录 GHCR。

工作流从 source lock emit 单行受验值，隔离 checkout exact upstream，复核 repository/commit/tree/Dockerfile/ancestor/patch，应用 patch并运行 R3.3 Go test，然后在原生 arm64 runner 构建 app。BuildKit启用 `provenance: mode=max`、SBOM 和 GHA cache；GitHub registry attestation以 build digest 为 subject。

该 workflow 尚未在 trusted main 执行，因此本节只能证明软件合同，不证明 GHCR artifact 已存在。

## 4. 安全事件与处理

本次在沙箱内首次重跑 PostgreSQL 时，loopback 被 `Operation not permitted` 拒绝；psycopg exception 展开了本机 Harness 测试库密码。该值不是模型/API key且未进入 Git，但已经视为泄漏：随后用参数化 psycopg SQL原地轮换 `harness` role password，并原子更新 mode-0600 runtime。最终 integration 使用临时 mode-0600 `PGPASSFILE`、无密码 URL，测试后立即删除 passfile。

候选差异审计扫描 33 个 modified/untracked files，对 12 个本机已知 secret 值结果为 `leaks=0`。后续所有数据库失败路径必须使用 passfile/无密码 URL，禁止让 DSN password进入异常 repr。

## 5. Fresh 本机门禁

在 `origin/main@9d84f942` 派生分支的当前未提交 worktree 上：

```text
OpenSpec strict
Change '023-local-weknora-live-environment' is valid

Ruff
All checks passed!

mypy strict
Success: no issues found in 181 source files

023 focused（含供应链）
232 passed

供应链 focused
6 passed

deterministic
1396 passed, 5 deselected

PostgreSQL integration（临时 pgpass，无 password DSN）
1 passed, 1400 deselected

Go R3.3
ok github.com/Tencent/WeKnora/internal/middleware

workflow YAML / lock-patch digest / verifier emit / diff check
PASS

known-secret candidate scan
files=33, known_secrets=12, leaks=0
```

这些是 fresh 软件与本机 PostgreSQL证据。未运行项仍包括 GHCR build/attestation、manifest digest write-back、完整 provision、普通 PDF、VLM smoke、本机冻结五节点、GitHub exact-SHA live 与 018 T7。

## 6. 正确收口顺序

1. 人工复核当前 follow-up diff；按 `CLAUDE.md` 由人 commit/push 并创建 bootstrap PR。
2. bootstrap PR 的 deterministic 与 PostgreSQL CI 在新 SHA 上通过后合入 main。
3. 从 trusted main dispatch WeKnora app workflow，核验 GHCR manifest、platform、provenance、SBOM 与 registry attestation。
4. 首次启动新 app 前备份 WeKnora PostgreSQL；新源码包含较官方 v0.6.3 更新的 migrations，旧镜像不是数据库回滚方案。
5. 用单独小变更把 manifest digest 同时写回 `images.lock` 与 Compose override，验证两处 exact equality。
6. 在最终 clean SHA 上跑五 direct probe、四 stored models、完整 provision、普通 PDF、`smoke-vlm`、PostgreSQL 与冻结五节点；要求 JUnit `tests=5 skipped=0 failures=0 errors=0`。
7. 再 dispatch trusted GitHub live 并完成 018 T7；最终证据写 PR comment/check summary，不为记录证据继续改变 SHA。

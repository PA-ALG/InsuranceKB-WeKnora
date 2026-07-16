# 023 任务

- [x] T1 R1.1：本地配置、四角色模型探针与零泄漏 RED→GREEN
- [x] T2 R2.1：loopback Compose、随机 Harness DB 密码、镜像/runner lock RED→GREEN
- [x] T3 R3.1/R3.2：管理员/tenant/原三 WeKnora 模型/KB/Space/PDF SHA 幂等 provisioning RED→GREEN
- [x] T4 R4.1/R4.2：受信 main exact-SHA workflow、五节点 manifest/JUnit guard RED→GREEN
- [x] T5 R5.1/R5.2：隔离 ephemeral runner、故障注入与全路径 cleanup RED→GREEN
- [ ] T6 R6.1：Runbook、Ruff/mypy strict/not-live pytest/OpenSpec strict/PostgreSQL/冻结五节点 live/独立 VLM smoke final-SHA 门禁、双审与基础设施 PR；未真实运行的门禁保持 `NOT RUN`
- [ ] T6a R1.2：先用 `test_r1_2_*` 命名的 RED 测试锁定五角色显式 profile；初始 WeKnora 固定 `source=remote`/`provider=aliyun`，Chat/Embedding/VLLM 分别是 `openai_compatible` chat/embeddings/vision chat，ReRank 是 `dashscope_native` exact endpoint/envelope/`output.results`，source/provider 不得硬编码 `siliconflow`，并覆盖 VLM visual canary 与 exception/log/stdout/stderr 零泄漏，再 GREEN
- [ ] T6b R3.3：先用 `test_r3_3_*` 命名的 RED 测试锁定 canonical endpoint fingerprint、runtime state 只存 endpoint fingerprint 而不存 secret/key 原文或 digest、稳定 VLLM model ID、四模型 credential refresh/stored debug、零 KB mutation、KB-RAW exact 绑定/禁用态、optional typed process config 省略时字段/文件 tuple/metadata 语义等价且无两个 override、普通 PDF 无 override、独立 VLM smoke typed/paginated child 验收，以及 `cd harness && uv run python scripts/local_live.py retry-vlm --knowledge-id <id>` 的 mode-`0600` 一次性消费与第二次调用在 API 前拒绝，再 GREEN
- [x] T6c R2.1/R3.1 P0：用命名引用 R2.1/R3.1 的 RED 测试锁定新 runtime 独立持久生成两个 32-byte AES key、缺 `TENANT_AES_KEY` 的既有 current runtime 原子迁移、rendered app 双 key 验明、异常 key fail closed 与全路径零 secret 输出，再最小 GREEN
- [ ] T6d R2.1/R3.1 P0：固定 clean source lock，受信 workflow 构建 app 并发布 GHCR provenance/SBOM，`images.lock`/Compose 写回 manifest digest；scoped tenant API key route 缺失时禁止 legacy full-access 降级，model-debug access log 不得记录 prompt/raw response/error/reasoning
  - [x] T6d.1：固定 Tencent repository/commit/tree、真实 `docker/Dockerfile.app` SHA-256、六个 scoped-key/security ancestor、`linux/arm64` 与 checksum-locked security patch；受信 main-only workflow 固定全部 action SHA，只发布 GHCR，启用 BuildKit max provenance、SBOM 与 GitHub registry attestation；补丁同时覆盖 model-debug 整包日志省略、实际 upstream build context 的 `.env.*` 排除、`golang-migrate@v4.19.1` 及 uv 0.9.26 安装脚本 SHA-256 校验。供应链契约 6 passed，锁定上游 checkout patch apply/diff check 与 R3.3 Go test 已实跑通过。
  - [ ] T6d.2：由人工复核并合入 bootstrap diff 后，从 trusted `main` dispatch 构建，核验 GHCR manifest/provenance/SBOM/attestation，再以小批次把 manifest digest 写回 `images.lock`/Compose；在此之前不得把 T6d 或 T7 标记完成。
- [ ] T7 真实本机 provision、五角色 direct probe/四 WeKnora 模型验明、普通 PDF、以 `cd harness && uv run python scripts/local_live.py smoke-vlm` 执行独立 final-SHA VLM smoke、五节点本地零 skip 与 sanitized evidence；final SHA 还须通过 Ruff、mypy strict、not-live pytest、OpenSpec strict 与 PostgreSQL，dirty 运行只记 provisional，未运行保持 `NOT RUN`
- [ ] T8 023 workflow 合入 main 后，对 PR #9 实现 SHA及最终证据 SHA各跑一次，清理临时值并关闭 018 T7

## 裁决记录

- Harness 抽取模型与 WeKnora 三类平台模型独立；默认百炼 `deepseek-v4-flash`，不安装 Ollama。
- R3.1/T3 保留原三 WeKnora 模型已完成范围；R1.2/R3.3 才扩展为五个独立配置角色与四个 WeKnora 远程模型。全部 direct probe 后才允许模型 ensure，stored-model debug 失败时允许幂等模型/凭据留存，但禁止任何 KB/knowledge mutation。
- runtime state 必须保存稳定 VLLM model ID；只保存 canonical endpoint fingerprint，不存 raw endpoint，也绝不保存 API secret/key 原文或 digest/fingerprint。
- ignored mode-`0600` runtime 必须分别持久生成恰好 32-byte 的 `TENANT_AES_KEY` 与 `SYSTEM_AES_KEY`，并在管理员首次注册前验明 rendered app 同时收到两者；缺 tenant key 的既有 current schema 只允许原子补 key，任一异常 key fail closed 且两者永不输出。
- KB-RAW 默认严格禁用 VLM；普通 PDF 不发送 multimodal override，只有独立 visual-canary smoke 显式 opt in；失败后只允许操作员通过 `cd harness && uv run python scripts/local_live.py retry-vlm --knowledge-id <id>` 显式执行一次同配置 reparse，mode-`0600` runtime state 在 API 前记录已消费，第二次调用在 API 前拒绝。
- public repo 不使用宿主用户态常驻 runner；只使用唯一 label 的隔离一次性容器。
- 受信 workflow 必须先合入 main，不能由 PR #9 自己提供要执行的 workflow 定义。
- 最终 SHA 的 live 证据只写外部 PR comment/check summary，避免证据提交产生无限 SHA 循环。
- VLM smoke 是独立 final-SHA local acceptance，不改动 PR #9 冻结的五节点；dirty worktree 证据只能 provisional，clean commit 才能记 exact SHA，最终 sanitized evidence 外置。
- 021 ordering 明确不在本 change。
- 2026-07-15 对齐 `main@4d9c84e2` 后，T1/T2/T4 软件门禁通过；T3 的 REST/provisioning primitives 已有测试，但真实 Space/CLI mutation 接线未闭环，因此保持未勾。T5 目前只有隔离计划与 cleanup 合同，具体 GitHub/Docker mutation controller 未闭环，保持未勾。真实模型与五节点仍为 `NOT RUN`。
- 2026-07-15 T3 已闭环：原四角色探针先于 mutation，原三 WeKnora 模型、真实 Compose controller 固定 project、等待六服务 healthy 并复核三端口 loopback；WeKnora 资源图与 Harness `KnowledgeSpace` 持久化、PDF SHA、runtime state、五节点本机 gate 已完成接线。真实六服务 `up` 通过；供应商模型探针与真实 provision 仍归 T7，当前 `NOT RUN`。
- 2026-07-15 T5 已闭环：controller 对 open/same-repo/exact-SHA 做前后双验，临时创建 scoped Tenant key 与最小权限 PostgreSQL role，只向 `harness-live` environment 写 2 secret + 5 variable；runner 固定 checksum、非 root、无宿主/Docker socket mount、唯一 label、双内网、单 job。任意成功/失败/取消路径尝试清理七项 GitHub 值、Tenant key、DB role、runner registration、容器和匿名卷且保留主错误。真实本机 PostgreSQL 已完成临时角色 create→权限验明→drop→不存在复核；GitHub workflow 尚未 dispatch，归 T8。
- 2026-07-15 runner 镜像已真实构建：arm64/non-root/固定 entrypoint 元数据符合锁定合同，镜像层 runner archive SHA-256 `OK`；无网络容器通过真实 entrypoint 完成 tmpfs FIFO stdin 注入、删除、ephemeral/once 参数链与 exit 0，随机 token 不在 container metadata/logs。T6 仍等待新 SHA deterministic/integration CI 与 Claude 双审，不因该 smoke 单独勾选；GitHub 注册/dispatch 仍归 T8。
- 2026-07-16 T6d 实机发现官方 v0.6.3 app digest 缺少 scoped tenant API key route，provision 在最小权限 key discovery 处 404；禁止降级为 legacy full-access key。曾验证的 dirty local-tag source-build 方案经安全复核被否决并撤回：它不能替代 registry manifest digest/provenance，且不应修改正常 `up` 为隐式构建。保留 `.dockerignore` 的 `.env.*` 防泄漏修复；model-debug access-log 脱敏已 RED→GREEN。T6d 重新保持未勾，等待 clean source lock、受信 GHCR build 与 digest 写回，T7 继续 `NOT RUN`。
- 2026-07-16 T6d.1 已按 TDD 落地：source lock 固定 `Tencent/WeKnora@5eefa70e...`、tree `a44f7eae...`、真实 `docker/Dockerfile.app` digest、scoped-key/security ancestor、arm64 与 patch digest；专用 trusted-main workflow 不接受 caller source 输入，使用 GHCR/GITHUB_TOKEN、全 action SHA pin、max provenance、SBOM、registry attestation。发现并修正“只改 fork `.dockerignore` 不会进入 upstream build context”的边界，`.env.*` 现由受锁 patch 应用于真实 context；同时固定 migrate/uv 构建工具链输入。fresh 证据：供应链 6 passed、023 focused 232 passed、Ruff、mypy 181 files、deterministic 1396 passed/5 deselected、PostgreSQL 1 passed/1400 deselected、OpenSpec strict、R3.3 Go 和 known-secret scan 0 leaks；GHCR publish/digest write-back 仍是 T6d.2 `NOT RUN`，需 bootstrap 先人工合入 main。

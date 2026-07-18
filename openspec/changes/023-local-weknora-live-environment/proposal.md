# Change 023：本机真实 WeKnora live 环境与受信门禁

## 背景

018 的软件、deterministic 与 PostgreSQL 16 门禁已通过，但五个真实 WeKnora live 节点没有可复现环境，仍为 `NOT RUN`。仓库为 public，不能把 PR 代码直接交给宿主机用户态常驻 runner；模型凭据也不得进入 GitHub。

## 目标

1. 搭建可重复、loopback-only、版本固定的本机 WeKnora 与独立 Harness PostgreSQL；
2. 让 WeKnora Chat/Embedding/ReRank/VLLM 与 Harness extraction 五个角色拥有独立、provider-aware 的百炼 profile；初始 WeKnora profile 固定 `source=remote`、`provider=aliyun`，Chat/Embedding/VLLM 分别使用 `openai_compatible` chat/embeddings/vision-chat 协议，ReRank 使用 `dashscope_native`，且在持久 mutation 前完成五个零泄漏 direct probe；source/provider 不得硬编码为 `siliconflow`；
3. 幂等创建 tenant、四个 WeKnora 模型、KB-RAW、KB-WIKI、KnowledgeSpace 与一份按 SHA-256 管理的真实寿险 PDF，并在全部 direct probe 后刷新模型凭据、验明存储模型与 canonical endpoint fingerprint；mode-`0600` runtime state 只保存 endpoint fingerprint，绝不保存 API secret/key 原文或 digest；
4. KB-RAW 默认禁用 VLM；上传客户端接受 optional typed process config，省略时保持原有 multipart 字段/值、文件 tuple 与 metadata 语义且不发送两个多模态 override，只有独立 visual-canary smoke 显式 opt in，并验明 OCR/caption 子 chunk 的 parent 关系与 canary；失败后的唯一人工 retry 使用稳定命令 `cd harness && uv run python scripts/local_live.py retry-vlm --knowledge-id <id>`；
5. 由受信 `main` workflow 对同仓 PR 的完整 SHA 执行冻结的五个 live node；VLM smoke 是独立 final-SHA 本机验收，不是 PR #9 的第六个 node；
6. 使用无宿主目录/Docker socket 的一次性容器 runner，并在任意退出路径撤销全部临时凭据与资源。

## 非目标

- 不安装或依赖本地 Ollama；
- 不把模型密钥、管理员凭据或模型响应上传 GitHub；
- 不为普通文档做自动 VLM 路由、文件名启发式、静默 fallback 或无界重试；
- 不修改 upstream WeKnora Go/Vue；只有另起设计并证明现有 `VLLM` 与 per-upload `process_config` 合同不足时，才可重新评估；
- 不改变 018 发布语义，也不实现 021 的 `processed_at`、SourceHead、CAS 或乱序处理；
- 不开放公网端口，不提供常驻 self-hosted runner，不自动删除持久卷；
- 不因环境验收而修改抽取业务行为。

## 依赖与交付

本 change 的受信 workflow 必须先独立合入 `main`，PR #9 才能取得 exact-SHA live 证据。交付包含本地五角色配置/探针、DashScope native ReRank 合同、Compose override、四模型与选择性 VLM 幂等 provisioning、冻结 live manifest/JUnit guard、隔离 runner/controller、Runbook 与分层 validation evidence。VLM 本机验收使用稳定命令 `cd harness && uv run python scripts/local_live.py smoke-vlm`。dirty worktree 的 VLM smoke 只能记为 provisional；只有 clean commit 并通过 Ruff、mypy strict、not-live pytest、OpenSpec strict、PostgreSQL、冻结五节点 live 与独立 VLM smoke，才可作为 exact final-SHA 验收，最终证据写入 PR comment/check summary 而不再改变 SHA。

# Change 023：本机真实 WeKnora live 环境与受信门禁

## 背景

018 的软件、deterministic 与 PostgreSQL 16 门禁已通过，但五个真实 WeKnora live 节点没有可复现环境，仍为 `NOT RUN`。仓库为 public，不能把 PR 代码直接交给宿主机用户态常驻 runner；模型凭据也不得进入 GitHub。

## 目标

1. 搭建可重复、loopback-only、版本固定的本机 WeKnora 与独立 Harness PostgreSQL；
2. 让 WeKnora Chat/Embedding/ReRank 与 Harness 抽取模型独立配置，抽取首个 profile 为百炼 `deepseek-v4-flash`；
3. 幂等创建 tenant、模型、KB-RAW、KB-WIKI、KnowledgeSpace 与一份按 SHA-256 管理的真实寿险 PDF；
4. 由受信 `main` workflow 对同仓 PR 的完整 SHA 执行冻结的五个 live node；
5. 使用无宿主目录/Docker socket 的一次性容器 runner，并在任意退出路径撤销全部临时凭据与资源。

## 非目标

- 不安装或依赖本地 Ollama；
- 不把模型密钥、管理员凭据或模型响应上传 GitHub；
- 不改变 018 发布语义，也不实现 021 的 `processed_at`、SourceHead、CAS 或乱序处理；
- 不开放公网端口，不提供常驻 self-hosted runner，不自动删除持久卷；
- 不因环境验收而修改抽取业务行为。

## 依赖与交付

本 change 的受信 workflow 必须先独立合入 `main`，PR #9 才能取得 exact-SHA live 证据。交付包含本地配置/探针、Compose override、幂等 provisioning、冻结 live manifest/JUnit guard、隔离 runner/controller、Runbook 与分层 validation evidence。

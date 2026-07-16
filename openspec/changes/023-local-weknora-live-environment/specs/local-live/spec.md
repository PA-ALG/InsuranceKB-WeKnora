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

### Requirement: R2.1 本机服务必须 loopback-only 且版本固定

app、frontend 与 Harness PostgreSQL 的宿主端口 SHALL 显式绑定 `127.0.0.1`；其他依赖 SHALL 不发布宿主端口。WeKnora、依赖镜像与 runner package SHALL 固定版本及 digest/checksum，Harness PostgreSQL SHALL 使用随机本地密码而非示例值。

#### Scenario: rendered Compose 出现宽监听或漂移

- **WHEN** rendered Compose 含 bare port、`0.0.0.0`、`::`、host network、`latest` 或 lock 不匹配
- **THEN** 启动 SHALL fail closed
- **AND** 不创建或重建持久卷

### Requirement: R3.1 WeKnora 资源必须幂等且验证所有权

bootstrap SHALL 建立明确的初始管理员、专用 tenant、三种模型、KB-RAW、KB-WIKI、最小权限 Tenant API Key 与绑定 KnowledgeSpace。稳定名称资源只有 environment marker、tenant、模型角色、Embedding 维度及 KB 角色全匹配时 SHALL 复用，否则 SHALL fail closed。

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

local 与 GitHub evidence SHALL 分别记录 exact node identities、SHA、时间、JUnit 计数和 sanitized cleanup 状态。skip/NOT RUN SHALL NOT 描述为成功。证据文档提交后 SHALL 冻结 PR #9，并对最终 SHA 重新运行 deterministic、PostgreSQL 与完整 live；最终 run SHALL 记录在 PR comment/check summary，之后 SHALL 不再改变 head。

#### Scenario: 实现 SHA 通过但证据提交改变 head

- **WHEN** 第一次 live 后提交 validation/HANDOFF 形成新 SHA
- **THEN** PR Ready 前 SHALL 对新 SHA 重跑三条门禁
- **AND** 最终 live 后不得再提交分支变更

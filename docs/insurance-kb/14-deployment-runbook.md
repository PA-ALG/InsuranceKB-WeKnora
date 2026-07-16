# 14 · 部署与联调方案（WeKnora 双库 + Harness 全链路 Runbook）

> 目标：让接手方从零把"WeKnora 平台 + Harness 插件"跑成一个可演示的整体，并打通 live 契约测试（遗留 B10 的执行指引）。架构与边界见 02；本文只讲怎么跑起来与怎么验。

## 1. 组件拓扑（单机开发/演示形态）

```
docker compose（上游自带）: WeKnora app + Postgres + Redis + docreader + 前端
docker-compose.harness.yml : Harness Postgres（003 已提供）
本机进程                    : harness CLI / workbench(008) / mcp server
可选                        : Langfuse（共用实例）
```

生产形态：WeKnora 用上游 Helm；Harness 出独立镜像与 chart（列 B10 后续项）；两套 Postgres 可同实例不同库。

## 2. WeKnora 启动与初始化（一次性）

1. `docker compose up -d`（仓库根上游 compose；固定镜像 digest，02 §8）；
2. 建租户与两个 KB（管理界面或 API）：
   - **KB-RAW 原始资料库**：`wiki_enabled=false`；解析/分块/向量按默认；所有原始文档只进这里；
   - **KB-WIKI 寿险知识 Wiki**：`wiki_enabled=true`；**纪律：此库永不上传任何原始文档**（内置 wiki ingest 无从触发，规避 P-3 补丁缺位——02 §4.1 过渡方案），只接受 Harness 发布器写入；
3. 签发 Harness 专用 Tenant API Key：能力域 `retrieve + ingest`（最小权限）；
4. 把 base_url / api_key / 两个 KB id 写入 `harness/.env`（`HARNESS_WEKNORA_*`，变量名与无密钥示例见已纳入仓库的 `.env.example`）。

## 3. Harness 启动

```bash
docker compose -f docker-compose.harness.yml up -d   # Harness Postgres
cd harness && uv sync
uv run alembic upgrade head                           # 0001～0004
```

迁移后不要立即启动产品注册或其他业务任务。先按 §3.1（存量非空库）或 §3.2（新装空库）完成 Space 准备并确认其为 bound，再执行 §3.3。

### 3.1 从 0001/0002 存量库升级

如果旧库已有任一产品或知识业务行，0003 会把历史行回填到 `legacy-default`，并故意将该 Space 保持为 `unbound`。此时产品注册、路由、Source Bridge、发布等普通业务入口都会 fail closed；**升级完成后、启动任何业务任务前必须执行一次显式绑定**：

```bash
uv run python -m insurance_harness.db.scope_cli show legacy-default \
  --db-url "$HARNESS_DB_URL"
uv run python -m insurance_harness.db.scope_cli bind legacy-default \
  --tenant-id "$HARNESS_TENANT_ID" \
  --raw-kb-id "$HARNESS_RAW_KB_ID" \
  --wiki-kb-id "$HARNESS_WIKI_KB_ID" \
  --db-url "$HARNESS_DB_URL"
export HARNESS_SPACE_ID=legacy-default
```

三个绑定值必须对应第 2 节实际创建的同一租户、KB-RAW 与 KB-WIKI。`bind` 是一次性、事务化操作；失败时仍保持 unbound，不要通过直接 SQL 绕过。旧库没有任何业务行时不会创建 `legacy-default`，因此也不执行这一步。

### 3.2 新装空库的 Space provisioning

新装空库按设计不会创建默认 Space，当前 `scope_cli` 也只提供 `list/show/bind`，没有 `create`。因此在 B10 交付“幂等双 KB/Space 初始化脚本”前，必须由受控管理员 provisioning 创建一个 bound KnowledgeSpace，并把其 ID 写入 `HARNESS_SPACE_ID`；不得假设 `legacy-default` 存在，也不得让业务进程直接写表。完成后用以下命令验明 `binding_status=bound` 及三个绑定值，再继续：

```bash
uv run python -m insurance_harness.db.scope_cli show "$HARNESS_SPACE_ID" \
  --db-url "$HARNESS_DB_URL"
```

这是一项仍未自动化的部署前置，不应被记录为“仓库可从零一键初始化完成”；自动创建/绑定由本文 §7 的双 KB 初始化脚本交付物承接。

### 3.3 绑定完成后注册产品

```bash
uv run python -m insurance_harness.product.cli register-products \
  ../dataset/shouxian_product --space-id "$HARNESS_SPACE_ID"
```

## 4. 联调验收路径（按序，每步都有断言）

| 步 | 动作 | 断言 |
|---|---|---|
| L1 | 上传 1 份样本 PDF 到 KB-RAW，`wait_for_parsed` 轮询 | parse_status=completed；chunk 可列取 |
| L2 | `pytest -m live`（001 适配层用例，指向真实实例） | 全绿——REST 契约与真实 WeKnora 一致 |
| L3 | 004 管道对该文档跑抽取（真实弱模型或 Replay） | pred 产出；evidence 的 chunk/页码可在 KB-RAW 解引用 |
| L4 | 007 导入→合并→审核（CLI approve）→发布到 KB-WIKI | `pytest -m live` 发布器用例全绿；WeKnora 前端能看到产品限定页、source_refs 可跳原文 |
| L5 | 第二批材料重复 L3-L4 | ChangeSet 产生 enrich/conflict；审核后页面更新；回滚快照后页面还原 |
| L6 | WeKnora Agent 挂 KB-WIKI 问答 | 回答引用发布页；（MCP server 就绪后）历史版本问题走 harness 工具 |

L1~L5 即演示脚本；L6 是"给 Agent 用的知识基础设施"的最终验收形态。

## 5. integration / live 契约测试约定

- deterministic：每个 PR 运行 `pytest -m "not live and not integration_postgres"`；
- PostgreSQL integration：每个 PR 的独立 PostgreSQL 16 service job 运行 `pytest -m integration_postgres`；缺 `HARNESS_TEST_POSTGRES_URL` 时测试失败而非 skip，JUnit 必须证明 tests > 0 且 skipped = 0；
- WeKnora live：本地可用 `uv run pytest -m live` 调试，无实例时保持 skip；正式证据只来自绑定 `harness-live` environment 的手工 `harness-live` workflow，preflight 缺变量会在 pytest 前失败，JUnit 必须证明 tests > 0 且 skipped = 0；
- **版本列车挂钩**（02 §8）：升级 WeKnora tag 时，L2/L4 的 live 套件是第一道门禁，金标回归（05）是第二道；
- 双库 ACL 一致性检查纳入 L4（同租户同权限，02 §4.1）。

三条 pytest collection 必须互斥且并集等于全量 collection。状态语言固定为：deterministic 绿可记 `software complete`；只有带 run URL/commit SHA/时间且零 skip 的 PostgreSQL 16 Actions job 可记 `integration verified`；只有带同等证据的受控 WeKnora workflow 可记 `live verified`。本地通过、skip 或 `NOT RUN` 均不得升级状态。

### 5.1 OpenSpec 017 T8：Source Bridge → Compiler → pred/import

T8 专用用例只接受显式 live 配置：

- `HARNESS_LIVE_BASE_URL`
- `HARNESS_LIVE_API_KEY`
- `HARNESS_LIVE_DB_URL`（必须是已迁移的真实 PostgreSQL，SQLite 会被拒绝）
- `HARNESS_LIVE_SPACE_ID`（数据库中已绑定的 Space）
- `HARNESS_LIVE_KNOWLEDGE_ID`（该 Space 的 KB-RAW 内一份真实、可下载 PDF knowledge）
- `HARNESS_LIVE_PARSER_FINGERPRINT`
- `HARNESS_LIVE_KB_ID`（publisher roundtrip 使用的真实 KB-WIKI ID）

当前 Harness adapter 没有上传 API，因此本用例走规格允许的“显式 knowledge ID”分支：先对真实端点执行 `wait_for_parsed`，再下载 PDF、读取 chunks、物化 bridge、用本地确定性 scripted client 跑 Compiler，并把 `pred.jsonl` 导入 Harness PostgreSQL。它不调用真实 LLM，也不把既有 knowledge 分支解释成 upload 创建覆盖。测试通过事务回滚清理临时产品、ChangeSet、Claim 与 Evidence；client、Session、Engine、物化文件及 run 目录均显式关闭/清理。

从仓库根目录运行精确命令：

```bash
cd harness && .venv/bin/pytest tests/test_source_bridge_live_017.py -m live -q -rs
```

本地调试缺少变量时用例可 `pytest.skip` 并逐项列出缺失变量；受控 workflow 的 preflight 则必须失败且只输出缺失变量名，不得回显值。不得用 respx/mock、Directory source、SQLite 或 PostgreSQL service job 代替 WeKnora live 证据。API key 不写入日志、断言或测试产物。

### 5.2 OpenSpec 023：本机真实环境与受信 exact-SHA gate

023 取代本章 §2/§3.2 中尚未自动化的本机初始化步骤。所有命令从仓库根目录执行；填值文件与生成的 runtime 文件都必须保持 mode `0600`，不得提交。

```bash
cp .env.local-live.example .env.local-live
chmod 600 .env.local-live
harness/.venv/bin/python harness/scripts/local_live.py check
harness/.venv/bin/python harness/scripts/local_live.py probe-models
harness/.venv/bin/python harness/scripts/local_live.py up
harness/.venv/bin/python harness/scripts/local_live.py provision \
  --pdf 'dataset/shouxian_product/平安创享盛世金越（尊享版26）终身寿险（分红型）/产品说明书.pdf'
harness/.venv/bin/python harness/scripts/local_live.py verify
harness/.venv/bin/python harness/scripts/local_live.py run-local
```

四个模型角色必须分别探测成功，且 `provision` 会在任何资源 mutation 前再次探测。Harness extraction 使用独立的百炼 OpenAI-compatible profile；切换 `HARNESS_LLM_BASE_URL/API_KEY/MODEL_WEAK` 不改变 WeKnora 三角色、KB 或 Space identity。输出只允许角色状态、数量和 sanitized error；不得粘贴响应正文排错。

`up` 在 mutation 前校验 Compose render、镜像 digest 与 runner checksum，固定使用 `insurancekb-local-live`、`insurancekb-harness-live` 两个 project；六个服务 healthy 后再复核 app、frontend、Harness PostgreSQL 的 published address 均为 `127.0.0.1`。`provision` 幂等创建或复用带 ownership marker 的 tenant、三模型、KB-RAW、KB-WIKI、scoped Tenant key、bound KnowledgeSpace 与 PDF SHA identity；同名但所有权不匹配时 fail closed。

只有 023 workflow 已合入 `main`、本机 `run-local` 五节点 `tests=5 skipped=0 failures=0 errors=0`，且目标 PR 是 open same-repository PR 时，才允许发起 GitHub gate：

```bash
harness/.venv/bin/python harness/scripts/github_live.py \
  --pr-number 9 \
  --head-sha '<40位PR head SHA>' \
  --runner-nonce '<16位小写十六进制随机值>' \
  --confirm-dispatch
```

controller 会在写入临时值前验 PR，并在 workflow 完成后再次验 head；workflow 固定从 `main` 读取受信定义，只 detached checkout 指定 SHA。一次性 runner 不挂宿主目录或 Docker socket，只接收两项 secret 与五项 variable。成功、失败和取消都应尝试删除七项 GitHub environment 值、撤销 per-run Tenant key/DB role、注销 runner，并删除容器与匿名卷；如 cleanup 不完整，命令必须失败并只列 sanitized cleanup kind。run URL、SHA、时间、JUnit 计数与 cleanup 状态写 PR comment/check summary，不再为最终证据修改 head。

日常停止默认保留持久卷：

```bash
harness/.venv/bin/python harness/scripts/local_live.py down
```

删除持久卷是破坏性操作，必须同时给出 `--delete-volumes --confirm-delete-volumes`。不要手工删除同名资源、改 runtime state 或绕过 ownership 校验。

## 6. 已知风险与规避

1. **KB-WIKI 误传文档** → 内置 wiki ingest 会与发布器争用 slug：除纪律约束外，Harness 发布器启动时校验该 KB 文档数为 0，非 0 告警拒发（实现挂在 B10）；
2. Wiki REST 并发覆盖（P-1 缺位）：多 Harness 实例部署前必须确认 slug 串行化升级为跨进程锁（Postgres advisory lock，P0.5 项）；
3. 解析完成靠轮询（P-2 缺位）：批量导入时控制轮询并发与间隔（config 已有参数）；
4. 本机代理变量坑（HANDOFF #9）同样影响容器内外网络排查，联调失败先查代理。

## 7. 交付物清单（B10 执行完成的定义）

- [ ] `.env.example`（全变量注释版）
- [ ] 双 KB + bound KnowledgeSpace 初始化脚本（幂等，API/admin provisioning 版）
- [ ] L1~L5 演示脚本（一条命令跑通并输出断言结果）
- [ ] 受控 `harness-live` workflow 全绿记录（run URL/commit SHA/时间、tests > 0、skipped = 0）+ 双库 ACL 检查
- [ ] 发布器"KB 文档数为 0"守卫
- [ ] 本文档按实际情况修订（发现与设计不符先改文档）

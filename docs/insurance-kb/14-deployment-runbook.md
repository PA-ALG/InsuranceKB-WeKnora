# 14 · 部署与联调方案（WeKnora RAW / STAGING / target 分阶段 + Harness Runbook）

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
2. 建租户与安全分离的 KB（管理界面或 API）：
   - **KB-RAW 原始资料库**：`wiki_enabled=false`；解析/分块/向量按默认；所有原始文档只进这里；
   - **KB-WIKI-STAGING（P-1 前）**：`wiki_enabled=true`，不上传原始文档；ACL 只给 release 管理员，禁普通用户/Agent/生产检索。Harness 只能把 snapshot 制品写到这里并由只读 current-release reader 预览；
   - **KB-WIKI 寿险知识 Wiki（目标态）**：只有 P-1 release namespace/active alias 与 P-3 manual ingest 均合入并通过 live 契约后才启用。P-1 前禁止逐页写入这个生产 KB；“不上传原文”只规避内置 ingest，不能解决原子可见性；
3. 签发 Harness 专用 Tenant API Key：能力域 `retrieve + ingest`（最小权限）；
4. 把 base_url/api_key、`HARNESS_RAW_KB_ID`、目标 `HARNESS_WIKI_KB_ID` 写入现有配置。NS-C 还必须新增独立的 `HARNESS_STAGING_WIKI_KB_ID`/`WikiPublicationCapability`；它必须与目标 Wiki ID 不同，并在签发 capability 时实测 ACL 隔离、普通 list/get/search/RAG 不可达。当前代码/`.env.example` 尚无该 capability，因此 P-1 前发布器应保持 production-disabled，不能把目标 ID 临时当 staging ID。

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

三个 Space 绑定值必须对应第 2 节实际创建的同一租户、KB-RAW 与**目标** KB-WIKI；数据库强制 `(tenant_id, target_wiki_kb_id)` 跨 Space 唯一。STAGING 不替代 `wiki_kb_id`，由单独、可撤销的 `WikiPublicationCapability(space_id, tenant_id, staging_wiki_kb_id, target_wiki_kb_id, mode, acl_probe_hash, retrieval_probe_hash)` 管理；有效 capability 还强制 `(tenant_id, staging_wiki_kb_id)` 唯一。P-1 前 publisher 只能接受 `mode=isolated_staging` 且两 ID 不同、归属/ACL/RAG 探针全绿的 capability。`bind` 是一次性、事务化操作；失败时仍保持 unbound，不要通过直接 SQL 绕过。

### 3.2 新装空库的 Space provisioning

新装空库按设计不会创建默认 Space，当前 `scope_cli` 也只提供 `list/show/bind`，没有 `create`。因此在初始化脚本补齐 RAW/STAGING/WIKI 与 publication capability 前，必须由受控管理员 provisioning 创建一个 bound KnowledgeSpace，并把其 ID 写入 `HARNESS_SPACE_ID`；不得假设 `legacy-default` 存在，也不得让业务进程直接写表。完成后用以下命令验明 `binding_status=bound` 及目标绑定，再继续；这仍不代表 publisher 已获得 staging capability：

```bash
uv run python -m insurance_harness.db.scope_cli show "$HARNESS_SPACE_ID" \
  --db-url "$HARNESS_DB_URL"
```

这是一项仍未自动化的部署前置，不应被记录为“仓库可从零一键初始化完成”；自动创建/绑定由本文 §7 的 RAW/STAGING/WIKI + publication capability 初始化脚本交付物承接。

### 3.3 绑定完成后注册产品

```bash
uv run python -m insurance_harness.product.cli register-products \
  ../dataset/shouxian_product --space-id "$HARNESS_SPACE_ID"
```

### 3.4 审核工作台启动（change 008，T1~T5/T7 波次）

```bash
# 1) 配置 token→(principal + 允许 Space 集合)：未配置=启动失败（fail-closed）
export HARNESS_WORKBENCH_TOKENS_JSON='{"<随机token>": {"principal": "审核人甲", "space_ids": ["'$HARNESS_SPACE_ID'"]}}'
# 2)（可选）显式指定 schema 基线目录；缺省时在仓库根/harness 目录下启动即可自动发现
# export HARNESS_WORKBENCH_SCHEMA_BASELINE_DIR=docs/insurance-kb/schema-baseline
# 3)（可选）会话签名密钥：不配则进程内随机（单进程可用；重启即全员重新登录）
# export HARNESS_WORKBENCH_SESSION_SECRET=<随机长串，勿入库>
# 4) 起服（loopback；生产置于内网反代之后。uvicorn 为声明依赖，uv sync --locked 后即有）
uv run uvicorn --factory --host 127.0.0.1 --port 8090 \
  insurance_harness.workbench.app:create_app_from_settings
```

`create_app_from_settings` 读取 `HARNESS_DB_URL` / `HARNESS_WORKBENCH_TOKENS_JSON` /
schema 基线目录，**任一缺失/损坏启动即失败**（不吞错、不降级）。CI 的 `wheel-smoke`
job 持续证明 wheel 装进空 venv 后模板与 HTMX 静态资源随包可用。

使用方式两条通道：

- **浏览器**：访问 `http://127.0.0.1:8090/login`，粘贴 token 登录（签发短期 HttpOnly
  会话 cookie，内含 token 摘要而非明文；写操作带 CSRF 双提交防护）→ 首页列出可访问
  Space。页面：`/spaces/<space>/queue`（审核队列：筛选/分页/approve/reject/defer/
  批量/翻案入口）、`/spaces/<space>/changes`（冲突与变更+翻案）、`/spaces/<space>/timeline`
  （G8 变更流）、`/spaces/<space>/matrix`（产品×schema 全字段五态格+下钻+缺口 CSV/JSONL 导出）。
- **自动化**：直接带 `Authorization: Bearer <token>` 调页面/动作端点，无需登录与 CSRF。

**W4 发布/回滚页：018 已合入 main（依赖解锁），以独立 follow-up PR 交付（跟踪：008 tasks.md T6）。**

## 4. 联调验收路径（按序，每步都有断言）

先分清两条互不冒充的路径：P-1 前只有隔离 staging/预览验证；P-1 + P-3 的 seal/active-alias live 合同通过后，才允许目标 KB、WeKnora UI/RAG/Agent 验收。

| 步 | 阶段 | 动作 | 断言 |
|---|---|---|---|
| L1 | 共用 | 上传 1 份样本 PDF 到 KB-RAW，`wait_for_parsed` 轮询 | parse_status=completed；chunk 可列取 |
| L2 | 共用 | `pytest -m live`（001 适配层用例，指向真实实例） | REST 契约与真实 WeKnora 一致；不代表发布已生产就绪 |
| L3 | 仅在 `NS-RIGHTS=recorded + 027 verified + applicable admission READY` 后 | 028 runtime 对该文档跑批准弱模型或独立 Replay | candidate/Evidence 产出；chunk/页码可在 KB-RAW 解引用；第一方旧能力只经 provenance/重构后的 TemplatePackage 加载 |
| L4-pre | P-1 前 | 导入→合并→审核后，只把冻结制品写入 ACL 隔离 KB-WIKI-STAGING；由 Harness current-release reader/MCP 预览 | 普通 WeKnora UI/list/get/search/RAG/Agent 均不可达；target KB 不变。现有 018 逐页 publisher live 只算历史 adapter/staging 地基，不证明原子发布 |
| L5-pre | P-1 前 | 第二批材料形成候选 ChangeSet，但不向 target KB 发布 | staging 失败不改变当前批准 snapshot；Harness 预览可比较差异；无“前端已上线”声明 |
| L4-post | P-1 + P-3 后 | 在 target KB 的 release namespace staging→回读→`seal-release`→批准→`activate-release` | seal 后写/删被拒；active alias 单次 CAS；UI/RAG/MCP 同一 release；跨 Space/KB 与 TOCTOU 故障 fail closed |
| L5-post | P-1 + P-3 后 | 第二批材料生成新 release；执行更新与旧 release 回滚 | 批准有效性、pin/GC 与物理 hash preflight 全绿；页面/QA/关系/目录/MCP/index 同步切换，不重新模型生成 |
| L6 | P-1 + P-3 后 | WeKnora Agent 挂 target KB 问答 | 回答引用 active release 页；历史版本问题走同 snapshot Harness MCP |

L1-L3 加 L4-pre/L5-pre 只是**预生产演示**；只有 L4-post～L6 的受控 live 证据才是“给人和 Agent 用的生产 Wiki”验收。

## 5. integration / live 契约测试约定

- deterministic：每个 PR 运行 `pytest -m "not live and not integration_postgres"`；
- PostgreSQL integration：每个 PR 的独立 PostgreSQL 16 service job 运行 `pytest -m integration_postgres`；当前精确包含 008 工作台双会话、015 飞轮同批 exactly-once、017 source 并发与 018 service-owned Session 四个节点；缺 `HARNESS_TEST_POSTGRES_URL` 时全部失败而非 skip，JUnit 必须证明 tests > 0 且 skipped = 0；
- WeKnora live：本地可用 `uv run pytest -m live` 调试，无实例时保持 skip；正式证据只来自绑定 `harness-live` environment 的手工 `harness-live` workflow，preflight 缺变量会在 pytest 前失败，JUnit 必须证明 tests > 0 且 skipped = 0；
- **版本列车挂钩**（02 §8）：升级 WeKnora tag 时，L2 与当前阶段对应的 L4-pre/L4-post live 套件是第一道门禁，金标回归（05）是第二道；
- P-1 前验证 RAW/STAGING/target 三库权限与 staging 不可达；P-1 后再验证 Space 独占 target/staging 绑定、seal/active alias 与同快照读取。

三条 pytest collection 必须互斥且并集等于全量 collection。状态语言固定为：deterministic 绿可记 `software complete`；只有带 run URL/commit SHA/时间且零 skip 的 PostgreSQL 16 Actions job 可记 `integration verified`；只有带同等证据的受控 WeKnora workflow 可记 `live verified`。本地通过、skip 或 `NOT RUN` 均不得升级状态。

### 5.1 OpenSpec 017 T8：Source Bridge → Compiler → pred/import

T8 专用用例只接受显式 live 配置：

- `HARNESS_LIVE_BASE_URL`
- `HARNESS_LIVE_API_KEY`
- `HARNESS_LIVE_DB_URL`（必须是已迁移的真实 PostgreSQL，SQLite 会被拒绝）
- `HARNESS_LIVE_SPACE_ID`（数据库中已绑定的 Space）
- `HARNESS_LIVE_KNOWLEDGE_ID`（该 Space 的 KB-RAW 内一份真实、可下载 PDF knowledge）
- `HARNESS_LIVE_PARSER_FINGERPRINT`
- `HARNESS_LIVE_KB_ID`（017/018 历史逐页 roundtrip 专用、ACL 隔离且可销毁的 legacy test Wiki KB；绝不能填生产 target KB，也不等同 P-1 staging capability）

当前 Harness adapter 没有上传 API，因此本用例走规格允许的“显式 knowledge ID”分支：先对真实端点执行 `wait_for_parsed`，再下载 PDF、读取 chunks、物化 bridge、用本地确定性 scripted client 跑 Compiler，并把 `pred.jsonl` 导入 Harness PostgreSQL。它不调用真实 LLM，也不把既有 knowledge 分支解释成 upload 创建覆盖。测试通过事务回滚清理临时产品、ChangeSet、Claim 与 Evidence；client、Session、Engine、物化文件及 run 目录均显式关闭/清理。

从仓库根目录运行精确命令：

```bash
cd harness && .venv/bin/pytest tests/test_source_bridge_live_017.py -m live -q -rs
```

本地调试缺少变量时用例可 `pytest.skip` 并逐项列出缺失变量；受控 workflow 的 preflight 则必须失败且只输出缺失变量名，不得回显值。不得用 respx/mock、Directory source、SQLite 或 PostgreSQL service job 代替 WeKnora live 证据。API key 不写入日志、断言或测试产物。

### 5.2 OpenSpec 018：PostgreSQL Session 隔离与真实发布/回滚

018 的 PostgreSQL integration 节点为：

```bash
cd harness
uv run pytest tests/test_release_publisher_postgres_018.py -m integration_postgres -q -rs
```

用例在随机 schema 内建立完整 Harness 表，caller Session 先 `flush` 一条未提交业务写，再调用只接收 `SessionFactory` 的 `ReleasePublisher`。验收要求是 saga 成功提交 release pointer，而 caller rollback 后该业务写不存在；这条证据不能由 SQLite 或函数签名检查替代。用例创建/删除随机 schema，CI 数据库账号必须具备 `CREATE/DROP SCHEMA` 权限。

018 的真实 WeKnora 节点为：

```bash
cd harness
uv run pytest tests/test_release_snapshot_live_018.py -m live -q -rs
```

用例使用随机 PostgreSQL schema 和上述**隔离 legacy test KB**执行逐页 V1→V2→rollback V1，只证明 018 adapter/saga 与 SnapshotReader 旧范围；它不证明 release namespace、seal、active alias、staging 不可见或生产回滚。退出时删除测试页并 `DROP SCHEMA ... CASCADE`。任何 ACL 探针显示普通用户/Agent/RAG 可达时立即失败；绝不允许把生产 target ID 传入该变量。
### 5.3 OpenSpec 023：本机真实环境与受信 exact-SHA gate

023 只取代本章 §2/§3.2 的**历史双库 live 地基**初始化，不交付独立 STAGING、`WikiPublicationCapability`、P-1 seal/alias 或三库生产 provisioning。所有命令从仓库根目录执行；填值文件与生成的 runtime 文件都必须保持 mode `0600`，不得提交。

```bash
cp .env.local-live.example .env.local-live
chmod 600 .env.local-live
harness/.venv/bin/python harness/scripts/local_live.py check
harness/.venv/bin/python harness/scripts/local_live.py probe-models
harness/.venv/bin/python harness/scripts/local_live.py up
harness/.venv/bin/python harness/scripts/local_live.py provision \
  --pdf 'dataset/shouxian_product/平安创享盛世金越（尊享版26）终身寿险（分红型）/产品说明书.pdf'
harness/.venv/bin/python harness/scripts/local_live.py verify
harness/.venv/bin/python harness/scripts/local_live.py smoke-vlm
harness/.venv/bin/python harness/scripts/local_live.py run-local
```

五个配置角色必须分别探测成功：WeKnora Chat/Embedding/ReRank/VLLM 四模型，加上 Harness extraction。该 probe 只证明连接性，不验证 027 allowlist/不可变 identity，也**不解除 027 或适用 admission**。`provision` 会在任何资源 mutation 前再次探测；切换 extraction profile 不改变 WeKnora 四模型、KB 或 Space identity。输出只允许角色状态、数量和 sanitized error；不得粘贴响应正文排错。

`up` 在 mutation 前校验 Compose render、镜像 digest 与 runner checksum，固定使用 `insurancekb-local-live`、`insurancekb-harness-live` 两个 project；六个服务 healthy 后再复核 app、frontend、Harness PostgreSQL 的 published address 均为 `127.0.0.1`。当前 `provision` 只幂等创建历史 tenant、四模型、KB-RAW、单个 legacy KB-WIKI、scoped Tenant key、bound KnowledgeSpace 与 PDF SHA identity；同名但所有权不匹配时 fail closed。它没有创建独立 STAGING/target 一一绑定或签发 capability，因此不能用于 P-1 前生产发布；NS-C 必须补三库 provisioning 后才能取代这条限制。

`smoke-vlm` 只对 visual canary 显式启用 VLM；普通 PDF 仍走文本解析。失败、取消、`incomplete`、`pending` 或 `processing` 都会保留 sanitized evidence JSON 并以非零退出；只有字面终态 `failed`、`cancelled`、`incomplete` 可由操作员执行一次 `retry-vlm --knowledge-id <id>`。`pending`/`processing` 不得 reparse，以免与在途解析竞态。retry marker 在 API 请求前以 mode `0600`、`O_EXCL` 持久化；若进程在 marker 成功后、请求结果确认前退出，该状态与“请求已发出但响应丢失”不可区分，因此不得自动删除 marker 或再次 reparse，应按 knowledge ID 和 WeKnora attempt 做人工事故核对。

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

1. **KB-WIKI/STAGING 误传文档** → 内置 wiki ingest 会与发布器争用语义：P-3 前启动时校验文档数为 0，非 0 告警拒写；P-3 后强制 `ingest_mode=manual`；
2. **P-1 缺位** → 当前逐页 REST、draft 状态和 slug 锁都不能原子隐藏/激活整套页面；只允许写 ACL 隔离的 KB-WIKI-STAGING。per-slug/advisory lock 仅防 staging 写竞争，不构成生产发布安全；
3. 解析完成靠轮询（P-2 缺位）：批量导入时控制轮询并发与间隔（config 已有参数）；
4. 本机代理变量坑（HANDOFF #9）同样影响容器内外网络排查，联调失败先查代理。

## 7. 交付物清单（B10 执行完成的定义）

- [ ] `.env.example`（全变量注释版）
- [ ] RAW + ACL 隔离 STAGING + 目标 Wiki（P-1/P-3 后启用）与 bound KnowledgeSpace 初始化脚本
- [ ] L1~L5 演示脚本（一条命令跑通并输出断言结果）
- [ ] 受控 `harness-live` workflow 全绿记录（run URL/commit SHA/时间、tests > 0、skipped = 0）+ RAW/STAGING/WIKI ACL 检查 + P-1 staging 不可见/active alias CAS/rollback/MCP alias 核对
- [ ] 发布器"KB 文档数为 0"守卫
- [ ] 本文档按实际情况修订（发现与设计不符先改文档）

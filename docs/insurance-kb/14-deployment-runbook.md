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
4. 把 base_url / api_key / 两个 KB id 写入 `harness/.env`（`HARNESS_WEKNORA_*`，样例见 `.env.example`——**接手时需补建该样例文件，含全部变量名与注释、不含真实密钥**）。

## 3. Harness 启动

```bash
docker compose -f docker-compose.harness.yml up -d   # Harness Postgres
cd harness && uv sync
uv run alembic upgrade head                           # 0001 产品域 + 0002 知识域
uv run python -m insurance_harness.product.cli register-products ../dataset/shouxian_product
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

## 5. live 契约测试约定

- 触发：`uv run pytest -m live`，从 env 读实例地址；CI 不跑（无实例则 skip，001 已实现）；
- **版本列车挂钩**（02 §8）：升级 WeKnora tag 时，L2/L4 的 live 套件是第一道门禁，金标回归（05）是第二道；
- 双库 ACL 一致性检查纳入 L4（同租户同权限，02 §4.1）。

### 5.1 OpenSpec 017 T8：Source Bridge → Compiler → pred/import

T8 专用用例只接受显式 live 配置：

- `HARNESS_LIVE_BASE_URL`
- `HARNESS_LIVE_API_KEY`
- `HARNESS_LIVE_DB_URL`（必须是已迁移的真实 PostgreSQL，SQLite 会被拒绝）
- `HARNESS_LIVE_SPACE_ID`（数据库中已绑定的 Space）
- `HARNESS_LIVE_KNOWLEDGE_ID`（该 Space 的 KB-RAW 内一份真实、可下载 PDF knowledge）
- `HARNESS_LIVE_PARSER_FINGERPRINT`

当前 Harness adapter 没有上传 API，因此本用例走规格允许的“显式 knowledge ID”分支：先对真实端点执行 `wait_for_parsed`，再下载 PDF、读取 chunks、物化 bridge、用本地确定性 scripted client 跑 Compiler，并把 `pred.jsonl` 导入 Harness PostgreSQL。它不调用真实 LLM，也不把既有 knowledge 分支解释成 upload 创建覆盖。测试通过事务回滚清理临时产品、ChangeSet、Claim 与 Evidence；client、Session、Engine、物化文件及 run 目录均显式关闭/清理。

从仓库根目录运行精确命令：

```bash
cd harness && .venv/bin/pytest tests/test_source_bridge_live_017.py -m live -q -rs
```

缺少变量时只允许 `pytest.skip`，输出会逐项列出缺失变量；不得用 respx/mock、Directory source 或 SQLite 代替 live 证据。API key 不写入日志、断言或测试产物。

## 6. 已知风险与规避

1. **KB-WIKI 误传文档** → 内置 wiki ingest 会与发布器争用 slug：除纪律约束外，Harness 发布器启动时校验该 KB 文档数为 0，非 0 告警拒发（实现挂在 B10）；
2. Wiki REST 并发覆盖（P-1 缺位）：多 Harness 实例部署前必须确认 slug 串行化升级为跨进程锁（Postgres advisory lock，P0.5 项）；
3. 解析完成靠轮询（P-2 缺位）：批量导入时控制轮询并发与间隔（config 已有参数）；
4. 本机代理变量坑（HANDOFF #9）同样影响容器内外网络排查，联调失败先查代理。

## 7. 交付物清单（B10 执行完成的定义）

- [ ] `.env.example`（全变量注释版）
- [ ] 双 KB 初始化脚本（幂等，API 版）
- [ ] L1~L5 演示脚本（一条命令跑通并输出断言结果）
- [ ] live 套件全绿记录 + 双库 ACL 检查
- [ ] 发布器"KB 文档数为 0"守卫
- [ ] 本文档按实际情况修订（发现与设计不符先改文档）

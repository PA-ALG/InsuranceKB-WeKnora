# insurance-harness

> [!IMPORTANT]
> 当前 serving Release 方向以
> [Sole Serving Active Release Authority ADR](../docs/superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md)、
> [Authority Amendment 2](../docs/superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)
> 和适用 OpenSpec 为准。现有 `ReleasePublisher`/reader 仅保留作测试、审计和
> 定向移植输入；P3 生产 Worker 未注册发布业务 Handler，当前状态为
> `NO_PRODUCTION_ACTIVE_RELEASE`。不得从公开导出或历史架构文档推导为生产
> serving 已启用。

寿险知识编译 Harness——WeKnora 的插件式扩展（插件边界与历史背景见 [docs/insurance-kb/02-architecture.md](../docs/insurance-kb/02-architecture.md)，ADR-001）。
与 WeKnora **只通过 REST/MCP 交互**：零 import、零共库、不直连其数据库与队列（三条硬边界，02 §3）。

## 布局（src 布局；子包职责见各自 README）

```
harness/
├── pyproject.toml            # uv 管理；ruff/mypy(strict)/pytest 配置
├── src/insurance_harness/
│   ├── config.py             # Pydantic Settings（HARNESS_ 前缀，零硬编码）
│   ├── adapters/weknora/     # WeKnora REST 适配层（全仓库唯一 API 感知点）
│   ├── compiler/             # 抽取/校验/合并/发布管道（docs 04）——占位
│   ├── goldenset/            # 金标注 Agent 与 eval runner（docs 05）——占位
│   ├── workbench/            # 审核/缺口/完整度工作台（docs 03/master plan P1-1）——占位
│   ├── mcp/                  # insurance MCP server（docs 02 §2）——占位
│   └── schemas/              # schema 注册表加载（docs 07）——占位
└── tests/                    # spec 编号 ↔ 测试一一对应（docs 10 §2）
```

## 快速开始

```bash
cd harness
uv sync                        # 安装依赖（含 dev 组）
uv run ruff check .            # 风格检查
uv run mypy src tests          # 严格类型检查
uv run pytest -m "not live and not integration_postgres" -q # deterministic 软件门禁
```

打真实 WeKnora 测试实例的契约测试（版本列车升级门禁，docs 02 §8）：

```bash
export HARNESS_LIVE_BASE_URL=http://<weknora-host>
export HARNESS_LIVE_API_KEY=sk-xxx
export HARNESS_LIVE_DB_URL=postgresql+psycopg://<user>:<password>@<host>/<db>
export HARNESS_LIVE_SPACE_ID=<bound-space-id>
export HARNESS_LIVE_KB_ID=<wiki-kb-id>
uv run pytest -m live
```

PostgreSQL integration 与受控 WeKnora live 的零 skip 证据要求见
[`14-deployment-runbook.md`](../docs/insurance-kb/14-deployment-runbook.md) §5；本地 skip 不代表 live 成功。

## 配置

全部经环境变量（前缀 `HARNESS_`），见 `src/insurance_harness/config.py`。
必填：`HARNESS_WEKNORA_BASE_URL`、`HARNESS_WEKNORA_API_KEY`（缺失时启动即报错）。

# insurance-harness

寿险知识编译 Harness——WeKnora 的插件式扩展（架构见 [docs/insurance-kb/02-architecture.md](../docs/insurance-kb/02-architecture.md)，ADR-001）。
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
uv run pytest -m "not live" -q # 单元 + mock 契约测试
```

打真实 WeKnora 测试实例的契约测试（版本列车升级门禁，docs 02 §8）：

```bash
export HARNESS_LIVE_BASE_URL=http://<weknora-host>
export HARNESS_LIVE_API_KEY=sk-xxx
export HARNESS_LIVE_KB_ID=<kb-id>
uv run pytest -m live
```

## 配置

全部经环境变量（前缀 `HARNESS_`），见 `src/insurance_harness/config.py`。
必填：`HARNESS_WEKNORA_BASE_URL`、`HARNESS_WEKNORA_API_KEY`（缺失时启动即报错）。

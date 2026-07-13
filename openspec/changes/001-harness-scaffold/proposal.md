# 001 · Harness 脚手架与 WeKnora 适配层

## 为什么做

一切保险知识能力（02-architecture.md ADR-001）都运行在 `harness/` 插件里，但该目录尚不存在。本 change 建立可运行、可测试、可被后续 change 依赖的最小骨架，并交付第一个有业务价值的组件：**WeKnora REST 适配层 + 契约测试**（全仓库唯一允许感知 WeKnora API 细节的模块）。

## 做什么

1. `harness/` Python 项目脚手架：uv + pyproject.toml + ruff/mypy/pytest 配置 + 各子包占位与 README（目录布局按 02 §7）；
2. `harness/adapters/weknora/`：REST 客户端，覆盖首批四类调用——鉴权（Tenant API Key）、知识/解析状态查询（轮询 parse_status）、chunk 读取、wiki 页与目录 CRUD；每个调用有 respx 契约测试；对 slug 写入做进程内串行化（P-1 补丁合入前的规避，02 §4.3）；
3. `harness/config.py`：Pydantic Settings 统一配置（WeKnora 地址/Key、模型网关、数据库 DSN），零硬编码；
4. CI（GitHub Actions）：ruff + mypy + pytest，仅针对 `harness/**` 与 `docs/insurance-kb/**` 路径触发，不碰上游 Go CI；
5. `dataset/shouxian_product/` 样本登记为测试语料（13 产品，业务方 2026-07-11 提供并确认入库）。

## 不做什么

- 不实现抽取管道、金标、数据库迁移（后续 change：002 金标子系统 S0、003 产品主数据 S1）；
- 不改任何 WeKnora Go/Vue 代码；不引入 MCP server。

## 影响面

- 新增目录：`harness/`、`.github/workflows/harness-ci.yml`；
- 三条硬边界（02 §3）：全部满足——纯新增，Go 零触碰；
- 不影响 schema/金标版本。

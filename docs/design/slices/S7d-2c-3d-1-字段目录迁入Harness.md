# S7d-2c-3d-1 · 字段目录迁入 Harness

> 状态：Claude 2026-10-24 提出；用户 2026-10-22 同意删除旧 830/G3 代码，2026-10-23 决定 S7d-2c 一并退役 ｜ 作者：Claude Code
> 依据：蓝图 §4.2（险种 Schema 只在 Harness，`catalog/` 存版本化数据）、§10、§11 S7；S7d-2c-3c（#328）删除了读取它的 Go 处理器
> 实现方：Claude ｜ 审核方：Claude 自审（简单改动：数据文件原样迁移与路径常量收敛，不改行为，净改动约 100 行以内）｜ 真实模型调用：0
> 并行：S7d-2c-3d-2（前端）写域不重叠

## 1. 目标

11 个 SchemaPack 的字段目录（catalog v5）至今放在 Go 目录 `internal/handler/schema_pack_catalog_830_g3.generated.json`。3c 之后 Go 平台不再读取它，只剩 Harness 在用。蓝图要求险种 Schema 只在 Harness，所以本片把它原样迁入 Harness 的 `catalog/`，并把 6 个模块各自写死的路径收敛为一个常量。

## 2. 改动

1. **迁移数据文件。** `git mv internal/handler/schema_pack_catalog_830_g3.generated.json harness/src/insurance_harness/catalog/schema_packs.json`：
   - 字节不变，SHA-256 仍为 `0d5ed6a5789362f1c72ebad5bbc47a64e1d71bc122890da96d976ec01256a3f9`；
   - 声明摘要 `catalog_declared_sha256`、`catalog_version` 等内容不变。
2. **单一常量。** `insurance_harness/catalog/__init__.py` 定义 `SCHEMA_PACK_CATALOG`，值为仓库相对路径 `harness/src/insurance_harness/catalog/schema_packs.json`：
   - 调用方照旧按传入的仓库根解析（`repo / SCHEMA_PACK_CATALOG`），测试仍可自带仓库；
   - 6 个模块删除各自的路径常量，改为导入：`catalog/navigation.py`、`compilers/schema_fields/publish.py`、`publish_changes.py`、`eval/compile_run.py`、`annotate.py`、`review_run.py`；
   - 命令行参数与默认值语义不变，例如 `navigation.py` 的 `--catalog` 默认仍指向本仓库内的目录。
3. **测试。** `harness/tests/` 中写死旧路径的测试改为导入同一常量：
   - 读取真实目录的，用 `REPO / SCHEMA_PACK_CATALOG`；
   - 在临时仓库里伪造目录的，用 `root / SCHEMA_PACK_CATALOG`；
   - 断言不变。
4. **数据集清单。** `dataset/golden/v1/manifest.json`、`v2/manifest.json` 的 `catalog_file` 改为新路径，其余字节不变：
   - 该字段只是说明，Harness 不读取它；
   - 两个清单的摘要在仓库内没有被固定；
   - 已有评测报告记录的清单摘要属于历史元数据，不因此失效。

**不做**：
- 不改目录内容与版本；
- 不改字段卡、提示词与评测口径；
- 不改历史文档、证据与 openspec 中的旧路径（历史背景）；
- 不动 Go 与前端。

## 3. 验收（RED，Claude 编写，受保护）

**新守卫 `tests/architecture/test_schema_pack_catalog_in_harness.py`**：

1. 旧路径 `internal/handler/schema_pack_catalog_830_g3.generated.json` 不存在；
2. 新路径文件存在，SHA-256 等于 §2.1 的值；
3. `harness/src`、`harness/tests`、`tests/acceptance`、`dataset/` 中不再出现 `internal/handler/schema_pack_catalog`；
4. `harness/src` 中只有 `catalog/__init__.py` 写出目录文件名 `schema_packs.json`，其余模块都经常量引用。

**更新已有守卫**：`test_legacy_schema_wiki_family_retired.py` 的保留项改为新路径（3c 守卫要求"字段目录仍在"，位置随本片变化）。

**行为回归**：`harness/` 下 `uv run pytest`、`ruff`、`mypy` 照常通过；相对 `main` 不新增失败。

## 4. 改动范围

- §2 列出的数据文件、6 个模块、`catalog/__init__.py`；
- `harness/tests/` 中引用旧路径的测试；
- `dataset/golden/v1/manifest.json`、`dataset/golden/v2/manifest.json`（只改 `catalog_file`）；
- `tests/architecture/`（§3 的守卫与基线）。

## 5. 上线

不涉及镜像：3c 之后 App 不再读取这个文件，Harness 从仓库读取，合并即生效。

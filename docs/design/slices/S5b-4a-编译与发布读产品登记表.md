# S5b-4a · 编译与发布读产品登记表

> 状态：Claude 2026-10-25 提出 ｜ 作者：Claude Code
> 依据：
> - S5b-1 §0 的拆分：归属变化后只编译、发布受影响的产品；
> - S5b-2：产品登记表 `ingest/registry.py` 取代手写来源映射，`source_map()` 导出同样的来源映射，`facts(product_id)` 给出名称与险种包；
> - 2026-10-25 对编译与发布链路的只读盘点（见 §1）。
>
> 实现方：**Codex** ｜ 审核方：Claude ｜ 真实模型调用：0（测试用假模型与假平台）

## 0. S5b-4 的拆分

| 片 | 内容 |
|---|---|
| **S5b-4a（本片）** | 编译与发布命令能直接读产品登记表：材料来自 `source_map()`，名称与险种包来自 `facts()`。上传后新建的产品因此可以编译和发布 |
| S5b-4b | 编排命令：对登记表中的产品编译、审核打分、发布变化；每轮有调用上限，可演练 |

## 1. 现状

- 编译（`eval/compile_run.py`）和两个发布命令（`compilers/schema_fields/publish.py` 首次发布、`publish_changes.py` 发布变化）都从数据集目录读产品名称：
  - `source_directory(repo, product)` 加 `display_name`；
  - 编译还用 `declared_pack` 取险种包。
- 上传归属新建的产品（登记表中 `origin="created"`）在数据集里没有目录：
  - 编译会因 `ValueError` 停下；
  - 发布会以 `PRODUCT_META_MISSING` 停下。
- 材料来源目前只能用 `--source-map <文件>`。登记表的 `source_map()` 产出同样的 `SourceMap`，但没有命令能直接用它。
- 对种子产品，登记表的名称与险种包和数据集一致：种子正是从同一组数据集函数生成的。

## 2. 改动

### 2.1 `eval/compile_run.py`

- `compile_products(..., facts: Callable[[str], tuple[str, str]] | None = None)`：
  - 给了 `facts` 时，产品的名称与险种包取 `facts(product)` 返回的 `(name, pack)`，不读数据集；
  - 这时必须同时给 `page_source` 或 `revision_page_source`：没有数据集目录，也就没有本地 PDF。两者都没给时报 `ValueError`；
  - 已存的 `output.json` 与 `facts` 的险种包不一致时，与现在一样报 "stored output does not match the product"。
- 命令行增加 `--registry PATH`，与 `--source-map` 二选一：
  - 材料用 `registry.source_map()`，取页方式与 `--source-map` 相同（固定版本、按 `(knowledge_id, parse_attempt)` 排序）；
  - 名称与险种包用 `registry.facts(product)`；
  - 登记表中没有的产品：`registry.facts` 报 `PRODUCT_UNKNOWN`，命令按现有的错误输出方式停下，不调用模型。
- 不给 `facts` 和 `--registry` 时，行为与现在完全相同。

### 2.2 `compilers/schema_fields/publish.py` 与 `publish_changes.py`

- 增加 `--registry PATH`，与 `--source-map` 二选一，两个都给或都不给报 `INVALID_ARGUMENTS`。用 `--registry` 时：
  - 来源映射用 `registry.source_map()`；
  - 产品名称用 `registry.facts(product).name`，不读数据集；
  - `output.pack_id` 必须等于 `registry.facts(product).schema_pack_id`，否则以 `OUTPUT_MISMATCH` 停下，在任何平台请求之前；
  - 登记表中没有该产品：以 `PRODUCT_UNKNOWN` 停下；
  - 登记表读取失败：以 `RegistryError` 的错误码（`REGISTRY_INVALID`、`REGISTRY_IO_ERROR`）停下；
  - 输出照旧只含错误码，不含路径或材料内容。
- 其余流程不变：路由、首次发布与变化发布的判断、抽检样本提交、`--dry-run`。
- 不用 `--registry` 时，行为与现在完全相同。

### 2.3 依赖

- `eval/`、`compilers/` 导入 `ingest.registry` 符合守卫 G1（这些目录都是 Harness 目标目录，只禁止核心目录导入 `compilers`）。
- `compile_products` 的 `facts` 参数用普通的 `(name, pack)` 元组，编译核心不依赖登记表的类型。

**不做**：

- 不做编排、调用上限与演练（S5b-4b）；
- 不改编译、审核打分、路由与发布本身的规则；
- 不改登记表格式；
- 不调用真实模型，不部署。

## 3. 验收（RED，Claude 编写，受保护）

`harness/tests/eval/test_compile_registry.py` 与 `harness/tests/compilers/schema_fields/test_publish_registry.py`，沿用现有编译与发布测试的假模型、假平台和夹具：

1. **编译**：
   - 只在登记表中的新建产品（数据集里没有它），用 `facts` 和页面来源编译成功，记录登记表给的名称与险种包；
   - 种子产品用 `facts` 编译，得到的名称、险种包与不用 `facts` 时相同；
   - 给了 `facts` 却没有页面来源：`ValueError`，不调用模型；
   - 已存输出的险种包与 `facts` 不一致：停下。
2. **编译命令**：
   - `--registry` 与 `--source-map` 不能同时给；
   - 登记表里没有的产品不调用模型。
3. **首次发布**：
   - 数据集里没有产品目录时，`--registry` 仍能发布，实体页上的名称是登记表的名称；
   - 险种包与输出不符：`OUTPUT_MISMATCH`，不发平台请求；
   - 登记表里没有该产品：`PRODUCT_UNKNOWN`；
   - `--registry` 与 `--source-map` 同时给或都不给：`INVALID_ARGUMENTS`；
   - 输出不含路径。
4. **变化发布**：
   - `--registry` 时只用登记表的材料与名称：没有变化时不提交；数据集缺产品目录时仍能运行；
   - 险种包不符：`OUTPUT_MISMATCH`。
5. **不用登记表时**：现有编译与发布测试全部照旧通过。

**门禁**：
- 在 `harness/` 下运行 `uv run pytest`（相对 main 不新增失败）、`uv run ruff check .`、`uv run mypy src tests`；
- 架构守卫。

## 4. 改动范围

- `harness/src/insurance_harness/eval/compile_run.py`；
- `harness/src/insurance_harness/compilers/schema_fields/publish.py`、`publish_changes.py`；
- 两个发布命令共用的参数或读取辅助函数，可以放在已有的共享模块中（如 `changes/options.py`），不新建目录；
- §3 的测试；
- `tests/architecture/`（基线只降）。

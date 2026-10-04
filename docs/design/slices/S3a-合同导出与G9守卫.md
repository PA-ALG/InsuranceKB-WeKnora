# S3a · 合同导出：`contracts/` 的 pydantic 定义与 G9 守卫

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §5、§8（G9）、§4.2、§11（S3）
> 分支：`slice/s3a` ｜ 工作目录：`.worktrees/s3a` ｜ 开工方式：写完计划即开工 ｜ 真实模型调用：**不需要**
> S3b（Go 通用接收/校验/预览/决定/激活）、S3c（前端按数据生成页面）另开一片，不在本片范围。

## 1. 目标

把蓝图 §5 的知识模型与编译治理模型变成**唯一的技术合同**：`harness/src/insurance_harness/contracts/` 下的
pydantic 定义，用一条导出命令生成仓库根 `contracts/*.schema.json`；G9 守卫保证两者**逐字节一致**（导出产物
不是手工编辑的，也不能过期）。之后 Go 用 JSON Schema 校验结构，前端据此生成类型，三方对"一份 bundle 长什么样"
只有一处定义。

## 2. 现状

- 仓库根 **`contracts/` 不存在**（`git ls-tree -r origin/main | grep '^contracts/'` 为空）。
- `tests/architecture/` 里 **没有 G9**：只有 G1、G2（两条）、G3、G4、G5、G6、G10、G11，共 9 条。
- 蓝图 §4.2 的目标目录在 Harness 中**都还不存在**：`contracts/`、`catalog/`、`ingest/`、`identity/`、`compile/`、
  `compilers/`、`evidence/`、`review/`、`changes/`、`governance/`、`bundle/`、`models/`。本片只建 `contracts/`。
- Go 侧已有依赖 `github.com/santhosh-tekuri/jsonschema/v6 v6.0.2`（`go.mod:54`），S3b 直接用；本片不需要 Go 改动。
- 现有实体（Claim/Entity/Relation 等）散落在旧目录（`knowledge_compiler/`、`product_ingestion/`、`goldenset/`、
  `schemas/`），键与字段各有出入；本片**不迁移**旧模型，只按 §5 建立新定义，旧模型按 §10 在 S7 退役。

## 3. 设计

### 3.1 模块划分（`harness/src/insurance_harness/contracts/`）

| 文件 | 内容 |
|---|---|
| `knowledge.py` | `Evidence`、`Locator`（§5.1 的 9 种 kind）、`Entity`、`Claim`、`Relation`、`QAItem`、`ExpertRevision`、`SchemaSnapshot` |
| `compile.py` | `PageText`、`CompileTask`、`CompileResult`、`GapTask`、`ReviewItem`（§5.3） |
| `bundle.py` | `CandidateBundle`、`BundleMember`、`ReviewPlan`（§5.3 末条） |
| `enums.py` | 三态 `ClaimState`、`SourceClass`、`LocatorKind`、`Origin`、`ChangedBy`、`ReviewMode`、`MemberKind`、`CompileTaskKind` 等 |
| `__init__.py` | 只做再导出，不含逻辑 |

要求：

- **只依赖 `pydantic`**（已是依赖）。不 import 旧目录（守卫 G1）；需要的比较键、枚举值在 `enums.py` 里重新声明。
- 全部模型 `model_config = ConfigDict(extra="forbid", frozen=True)`；枚举用 `Literal`/`StrEnum`，不用裸字符串。
- 字段名与蓝图 §5 逐条对齐；蓝图里的 `...` 与中文说明括注要落实成具体类型。**不确定的类型**（如 `applicability`
  的维度集合、`locator` 的 k/字段）在 PR 中列出，由 Claude 定，不自行发明。
- 三态不变量用 `model_validator` 表达：`present` 必须有值且至少一条已回验 Evidence；`absent_explicitly` 值必须为空
  且有否定原文；`unknown` 无值无证据且带 typed reason。与 `eval/golden.py` 的既有规则保持一致（那里已实现同类校验，
  可参考但**不 import**）。
- `Claim.maintenance.changed_by`、`Claim.origin`、`Evidence.match` 等取值用枚举收口。

### 3.2 导出命令

```sh
uv run python -m insurance_harness.contracts.export           # 写仓库根 contracts/
uv run python -m insurance_harness.contracts.export --check    # 只校验，不写；不一致退出码 1
```

**冻结 API（验收测试按此断言）**：

```python
# insurance_harness.contracts.export
def export(destination: Path) -> list[Path]      # 写出全部合同，返回写出的路径（按文件名排序）
def check(destination: Path) -> list[str]        # 返回与定义不一致的文件名（内容不同/缺失/多余），空表示一致
```

- `export` 只写 `destination` 下的文件，不碰仓库其它位置；目录不存在则创建。
- `check` **不写任何文件**（内部用 `tempfile`），返回漂移的文件名列表。
- CLI：默认目标为仓库根 `contracts/`（由 `Path(__file__).resolve().parents[4]` 推断，与 `eval/annotate.py` 同法）；
  `--check` 时打印漂移文件名并以退出码 1 结束，无漂移则 0。
- 输出 `contracts/<model>.schema.json`，文件名 = 模型名转 snake_case，`$id` 用
  `https://pa-alg.github.io/InsuranceKB-WeKnora/contracts/<name>.schema.json`（仅标识，不联网解析）。
- 序列化必须**确定性**：`json.dumps(..., ensure_ascii=False, sort_keys=True, indent=2)` + 末尾换行；
  `$defs` 内的引用用 `$ref`，不用内联展开。
- `--check` 与 CI 用的同一条路径；G9 守卫内部复用 `--check` 的实现（不得各写一遍）。
- 版本：仓库根 `contracts/README.md` 声明 `contract_version`，`CandidateBundle.contract_version` 必须等于它；
  本片填 `"1"`。

### 3.3 G9 守卫

- 位置 `tests/architecture/checks_contracts.py`，在 `guards.py` 的 `ACTIVE_GUARDS` 中登记 `G9_contract_drift`。
- **沿用既有计数式守卫模型**（`Results = dict[guard, dict[key, int]]`），不要为它另造一套机制：
  G9 返回 `{合同文件名: 1}`，每个与导出产物不一致的文件记 1（内容不同、多出、缺失都算）。
- 因为没有基线键，`allowed_count(G9, key, base)` 对任何新键都返回 0，任何漂移即
  `regressions()` 报违规——**不需要例外，也不需要给 G9 加容差**（不要动 `GROWTH_ALLOWANCE`）。
- `baseline.json` **不记录 G9 的任何键**。实现后确认 `record_baseline.py` 不会把 G9 的键写进基线：
  `lowered()` 对基线里没有的键取 `count` 本身，若此时 count 非 0 就会写进去——因此 G9 的键写不进基线的
  前提是**导出产物始终与定义一致**（即 CI 绿）；这一点在 PR 中说明即可，不必给守卫加特例。
- 自测：`tests/architecture/test_guards.py` 里补 3 条（内容改一个字节要报违规；删一个文件要报违规；
  多出一个 `.schema.json` 要报违规），用 `tmp_path` 构造，不依赖真实仓库状态、不读真实 `contracts/`。

## 4. 交付物

- `harness/src/insurance_harness/contracts/{__init__,enums,knowledge,compile,bundle,export}.py`。
- 仓库根 `contracts/*.schema.json`（由导出命令生成）与 `contracts/README.md`。
- `tests/architecture/checks_contracts.py`、`test_guards.py` 的新增自测。
- 单测：`harness/tests/contracts/` 下覆盖三态不变量、`extra="forbid"`、`$ref` 解析、导出确定性（同输入两次导出
  逐字节相同）、`--check` 的退出码。

## 4.1 Claude 提供的受保护验收测试

`harness/tests/contracts/test_contract_export.py`（受保护，随本片推送，当前 RED）——实现必须让它通过，不得修改。
它只使用上面的公开 API，不读仓库根 `contracts/`、不联网。

## 5. 验收

- `harness/tests/contracts/test_contract_export.py`（受保护）全过；
- `uv run pytest tests/contracts tests/architecture -q` 全过；`uv run ruff check .`、`uv run mypy src tests` 通过。
- `uv run python -m insurance_harness.contracts.export --check` 退出码 0。
- 手改 `contracts/` 里任一文件后，G9 失败；还原后通过（PR 中贴这两条证据）。
- 仓库根架构守卫全过，基线**不回升**（G9 走新增即失败，不入基线）。
- CI 全绿。

## 6. 改动范围

- 允许新增：`harness/src/insurance_harness/contracts/`、`harness/tests/contracts/`、
  `tests/architecture/checks_contracts.py`、仓库根 `contracts/`。
- 允许修改：`tests/architecture/guards.py`（登记 G9）、`tests/architecture/test_guards.py`（补自测）、
  `tests/architecture/checks_contracts.py`（新增，G9 实现）、
  `tests/architecture/baseline.json`（**只**允许因新增 G9 导致的必要调整，且不得给 G9 记任何键）。
- 不得修改：蓝图、`docs/design/` 其他文件、`harness/tests/eval/test_judge_*.py`、`test_golden_evaluation.py`、
  `contracts/` 之外的其它既有目录、旧目录。不新增依赖（`pydantic` 已有）。

## 7. 非目标

- 不做 Go 侧接收、校验、预览、决定、激活（S3b）。
- 不做前端类型生成与页面（S3c）。
- 不迁移旧模型，不改 `eval/`（S2b 在用）。
- 不接 CI 合同门以外的流程；不调用真实模型。

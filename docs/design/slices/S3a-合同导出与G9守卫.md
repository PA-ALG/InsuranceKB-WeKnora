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

## 8. 合同参数裁决（2026-10-05，Claude；实现按此冻结，不要再猜）

以下是 Codex 在 #146 提出的待裁决参数。**以本节为准**；与 §3 冲突时以本节为准。

### 8.1 G9 必须在 baseline 里留一个空映射（修正 §3.3 的措辞）

§3.3 原写"baseline.json 不记录 G9 的任何键"——**这句是错的**：`test_baseline_file_is_readable` 断言
`set(ACTIVE_GUARDS) <= set(doc["guards"])`，G9 进了 `ACTIVE_GUARDS` 就必须在 baseline 里有键。正确做法：

- `guards` 下写 `"G9_contract_drift": {}`（空映射，**没有任何文件键**），`totals` 下写 `0`；
- 因为没有任何文件键，`allowed_count("G9_contract_drift", 任意文件名, {})` 恒为 0，任何漂移都是新增违规；
- **不要**给 G9 任何文件键，也不要给容差。Codex 暂存里的写法是对的。

### 8.2 Locator：单模型 + 按 kind 校验，保留 `Locator(kind=..., ...)` 构造

不改成 discriminated union（受保护验收按关键字构造，union 会破坏调用面）。一个 `Locator` 模型，
`extra="forbid"`，字段全部可选，用 `model_validator` 按 `kind` 强制必填项：

| kind | 必填字段 | 口径 |
|---|---|---|
| `PDF_TEXT_SPAN` | `page`, `start`, `end` | `page` 1 起；`start`/`end` 为 0 起、半开区间的**码点**偏移（该页文本内） |
| `OCR_REGION` | `page`, `bbox` | `bbox` = `{x, y, w, h}`，0..1 归一化浮点，左上原点（S10 用） |
| `DOCX_BLOCK` | `block_index` | 0 起（S11 用） |
| `DOCX_TABLE_CELL` | `table_index`, `row`, `column` | 均 0 起（S11 用） |
| `PPTX_SHAPE` | `slide`, `shape_id` | `slide` 1 起；`shape_id` 非空字符串（S11 用） |
| `XLSX_CELL_RANGE` | `sheet`, `cell_range` | `sheet` 非空；`cell_range` A1 风格字符串（S11 用） |
| `CHUNK_SPAN` | `chunk_id`, `start`, `end` | 历史片段，无原件 |
| `STRUCTURED_PATH` | `path` | 非空字符串列表 |
| `EXPERT_REVISION` | `revision_record_id` | 非空字符串 |

九种**现在一次定义完**，避免 S10/S11 再改合同。

### 8.3 Claim 的值与元数据

- `value: str | int | float | bool | list[str] | None`（§5 的"typed"在 v1 收敛到这几种；复杂结构按 V5 规则
  转成语义完整的字符串）。`present` 时非 None；其余状态必须为 None。`unit: str | None = None`。
- `applicability`：四个维度**都是字符串列表**，各自默认空：`region`、`channel`、`population`、`scenario`。
  模型 `extra="forbid"`。
- `unknown_reason`：**闭集枚举**，值用大写串：`NOT_IN_MATERIAL`、`MATERIAL_AMBIGUOUS`、`LOCATOR_UNSUPPORTED`、
  `EXTRACTION_FAILED`、`OUT_OF_SCOPE`。`state="unknown"` 时**必填**，其余状态必须为 None。
- `provenance`：封闭小模型，可默认：`compiler: str`、`compiler_version: str`、`model: str | None = None`、
  `run_id: str | None = None`、`call_receipt_ref: str | None = None`。
- `maintenance` 默认（验收里最小 Claim 不传也要通过）：`revision_no: int = 0`、`changed_at: str | None = None`、
  `changed_by: ChangedBy = ChangedBy.COMPILE`、`reason: str | None = None`、`first_release_id: str | None = None`、
  `last_changed_release_id: str | None = None`。
- `review` 默认：`mode: ReviewMode = ReviewMode.MACHINE`、`score: float | None = None`、`reviewer: str | None = None`、
  `reviewed_at: str | None = None`。
- `expert_lock: bool = False`；`effective_from` / `effective_to`: `str | None = None`（半开区间，格式留给 S4 的
  数据层校验，合同只要求字符串）。
- **absence 的"否定原文"**：只要求 `state="absent_explicitly"` 时 `value is None` **且 `evidence` 非空**，
  **不加**任何"领域关键词"结构标记——合同必须与领域无关（G2），"是否是合格否定证据"由证据层判定，不由合同发明规则。

### 8.4 Evidence / ExpertRevision / SchemaSnapshot

- `Evidence.quote_sha256`：用 `default_factory` **从 `quote` 自动生成**（归一化后 sha256，hex），验收不传；
  调用方显式传入时以传入值为准。`source_ref`、`quote`、`access_scope` 均为**非空字符串**；`file_sha256` 必须是
  64 位 hex；`match: EvidenceMatch = EvidenceMatch.EXACT`。
- `ExpertRevision`：`revision_record_id`、`actor`、`role`、`recorded_at`、`target` 均为非空字符串；
  `before: str | None = None`、`after: str | None = None`、`reason: str | None = None`、
  `attachments: list[str] = []`；整模型 `frozen=True`（不可变）。
- `SchemaSnapshot`：`schema_pack_id`、`schema_pack_sha256`（64 hex）、`presentation_profile_ref`、
  `catalog_version` 均为非空字符串。

### 8.5 编译与治理模型

- `PageText`：`source_revision_id`、`parse_artifact_digest`（64 hex）、`document_role` 非空字符串；
  `page_number: int >= 1`；`text: str`；`text_origin: TextOrigin`；`blocks: list[Block]`，
  `Block{block_id: str, start: int >= 0, end: int >= start, locator: Locator}`（均可默认空列表）。
- `CompileTask`：`task_key`、`entity_version`、`config_ref` 非空字符串；`kind: CompileTaskKind`；
  `material_set: list[str] = []`、`targets: list[str] = []`、`budget: int = 0`（>=0）。
- `CompileResult`：`task_key` 非空；`status: CompileStatus`（枚举 `SUCCEEDED`、`FAILED`、`CANCELLED`、`SKIPPED`）；
  `claims: list[Claim] = []`、`relations: list[Relation] = []`、`candidates: list[str] = []`、
  `diagnostics: list[str] = []`、`call_receipts: list[str] = []`。
- `GapTask`：`gap_id`、`target` 非空；`trigger: GapTrigger`；`search_scope: list[str] = []`、
  `attempts: list[str] = []`；`status: GapStatus`（枚举 `OPEN`、`IN_PROGRESS`、`RESOLVED`、`ABANDONED`，默认 `OPEN`）。
- `ReviewItem`：`item_id`、`target` 非空；`kind: ReviewKind`；`evidence: list[str] = []`；
  `status: ReviewStatus`（枚举 `OPEN`、`RESOLVED`、`WAIVED`，默认 `OPEN`）；`resolution_candidate: str | None = None`。
- `Relation`、`QAItem`、`Entity` 按 §5.1：字段名照抄，字符串列表默认空，`evidence: list[Evidence] = []`；
  `Entity.entity_type`、`names` 非空。

### 8.6 Bundle

- `BundleMember`：`kind: str`（`^[a-z][a-z0-9_]*$`，**不做枚举**——成员种类词表属 Catalog/§5，写进合同会碰 G2）、
  `logical_slug: str` 非空、`payload: dict[str, Any]`、`member_digest: str`（64 hex）、`evidence_refs: list[str] = []`。
- `CandidateBundle`：`contract_version: str`、`origin: Origin`、`compiler_identity: str` 非空；
  `base_release_id: str | None = None`、`base_epoch: int | None = None`（首次发布没有 base，用 None；
  **不要**填 `""` 或 `0` 冒充）、`members: list[BundleMember] = []`、`removals: list[str] = []`、
  `review_plan: list[ReviewPlan] = []`（**列表**，受保护验收传 `review_plan=[]`）。
- `ReviewPlan`：`mode: ReviewMode`、`policy_ref: str | None = None`、`sample_size: int | None = None`（>=0）。

### 8.7 验收命令的实际写法（修正 §5 的歧义）

守卫在**仓库根** `tests/architecture/`，合同测试在 **`harness/tests/contracts/`**，两者分开跑：

- 仓库根：`harness/.venv/bin/python -m pytest -q tests/architecture`
- `harness/` 下：`PYTHONPATH=src .venv/bin/python -m pytest -q tests/contracts`
- 导出检查：`cd harness && PYTHONPATH=src .venv/bin/python -m insurance_harness.contracts.export --check`

### 8.8 CI 范围批准（Codex 提的缺口）

**批准修改 `.github/workflows/architecture-guards.yml`**：G9 需要 `pydantic` 与 Harness 源码，而该工作流现在
只装 `pytest`。采用仓库既有做法，不新增依赖：

```yaml
      - uses: astral-sh/setup-uv@v4        # 与 mcp-server.yml 一致；harness-ci 用带 sha 的 v5.4.2，二者皆可
      - name: Install the Harness runtime dependencies
        working-directory: harness
        run: uv sync --locked --no-dev
      - name: Check architecture boundaries and detector self-tests
        env:
          PYTHONPATH: harness/src
        run: python -m pytest -q tests/architecture
```

（`--no-dev` 即可：G9 只需要运行时依赖里的 `pydantic`。）**不得**让 G9 在缺少 pydantic 时静默跳过——那等于
把守卫关掉。若 `uv sync --locked --no-dev` 在 CI 上不可行，改 `uv sync --locked`，但**不允许**绕过 lock。

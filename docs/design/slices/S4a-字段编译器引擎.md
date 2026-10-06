# S4a · 字段编译器引擎：`compilers/schema_fields`（离线、可复现）

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §7.1、§5.3、§4.2、§8（G1/G2/G11）、§11（S4）
> 分支：`slice/s4a` ｜ 工作目录：`.worktrees/s4a` ｜ 开工方式：写完计划即开工 ｜ 真实模型调用：**不需要**
> S4b（`models/` 的 DeepSeek v4 flash 执行器 + 真实调用）与 S4c（`bundle/` 产出 CandidateBundle）另开。

## 1. 目标

把 V5 的**抽取引擎核心**移植成主仓库里第一个字段编译器：按 Catalog 的字段定义组题、严格解析模型输出、
按 `value_spec` 归一取值、逐字回验引文，并且**完全离线可复现**——引擎只依赖一个 `CompletionPort` 抽象，
测试用录制好的响应驱动，因此 CI 不发真实调用、结果每次一致。

本片只做引擎与它的离线评测；**不接生产模型**（S4b）、**不产出 Bundle**（S4c）。

## 2. 现状

- **V5 引擎在另一个仓库**：`silvielala412-lab/InsuranceKB-WeKnora-ingest` 的 `codex/local-v5-preview` 分支，
  `harness/src/insurance_harness/v5_preview/`。本机只读克隆在 `/tmp/v5-ref`（167M）。
- 蓝图 §4.2 的目标目录在主仓库里**只差 `eval/` 已建**：`compilers/`、`models/`、`catalog/`、`ingest/`、
  `identity/`、`compile/`、`evidence/`、`review/`、`changes/`、`governance/`、`bundle/` **都还不存在**。
  本片只建 `compilers/schema_fields/`（以及它必需的 `evidence/`，见 §3.2）。
- **旧实现不退不迁**：`harness/src/insurance_harness/compiler/`（约 11,415 行，38 个模块）与
  `product_ingestion/`、`knowledge_compiler/`、`goldenset/` 都按蓝图 §10 在 S7 退役，本片**不 import、不修改**它们。
- 已有可复用的评测面：`eval/`（S2a/S2b）提供 `GoldenItem`、`compare_value`、`evaluate`/`gate`、report CLI，
  以及 `eval/convert.py:predictions_from_candidate`——它规定了一个**现成的候选形状**：

  ```json
  {"request": {"entity_bindings": [{"entity_id": "…", "display_name": "…", "schema_pack_id": "…"}]},
   "compile_result": {"output": {"fields": [{"entity_id": "…", "field_key": "…",
                                             "state": "present|absent_explicitly|unknown",
                                             "value": "…", "evidence": [ … ]}]}}}
  ```

  本片引擎的产物必须能直接喂给 `predictions_from_candidate`，这样**不需要新写评分器**就能对已有 Golden 打分。
- Catalog（`internal/handler/schema_pack_catalog_830_g3.generated.json`，`catalog_version 2026-08-12-v5`）里每个
  pack 有 67 个字段，字段带 `field_key`、`short_title`、`description`、`source_guidance`、`value_spec`、
  `formation_method`、`knowledge_role`、`schema_category`。`eval/catalog.py` 已经能读它。
- 依赖已够：`httpx`、`pydantic`、`tenacity`、`pdfplumber` 都在 `harness/pyproject.toml` 里；**没有** openai SDK，
  也不需要（S4b 用 httpx 写 OpenAI 兼容客户端）。

## 3. 设计

### 3.1 文件划分（`harness/src/insurance_harness/compilers/schema_fields/`）

| 文件 | 职责 | 移植自 |
|---|---|---|
| `definitions.py` | `FieldDefinition`（Catalog 字段 → 组题所需的最小形状）、按 pack 选取"可原文抽取"的字段 | `v5_preview/contracts.py` 的 `FieldDefinition`／`catalog.py` |
| `prompt.py` | 系统提示词与组题：字段定义 + 带 `[page N]` 的逐页原文；**不含任何期望值** | `v5_preview/llm_plugin.py` 的 `_SYSTEM_PROMPT`、`_schema_prompt`、`_field_extraction_instruction` |
| `parse.py` | 严格解析：**fail closed**，缺字段/多字段/重复/序号错位/三态形状不符一律抛错，绝不静默降级为 `unknown` | `v5_preview/llm_plugin.py` 的 `extract` 校验段 |
| `values.py` | 按 `value_spec` 归一取值（单选/多选/同义、金额与时长归一） | `v5_preview/value_constraints.py` |
| `profiles.py` | 每个字段的抽取档（是否全材料扫描、邻居页、穷举项、语义词、专属指令）**数据化** | `v5_preview/field_profiles.py` |
| `engine.py` | `SchemaFieldsCompiler`：`compile(request, fields) -> CompileOutput`；分批、预算、调用计数 | `v5_preview/llm_plugin.py` + `ingest.py` 的 `V5PreviewCompiler` 去壳 |

`evidence/`（§4.2 目标目录）新增一个模块 `quote_verification.py`：给定页文本与引文，做归一化子串匹配，
返回 `EXACT | NORMALIZED | NOT_FOUND`。**与 `eval/pdf_text.py` 的页文本形状对齐**，但不 import `eval/`（见 §3.3）。

### 3.2 冻结接口（验收测试按此断言）

```python
# compilers/schema_fields/definitions.py
class FieldDefinition(BaseModel):
    field_key: str
    short_title: str
    description: str
    source_guidance: str | None = None
    value_spec: str | None = None
    knowledge_role: str | None = None
    formation_method: str | None = None
    ordinal: int = 0          # 组题与回填的稳定顺序

def pack_definitions(catalog_path: Path, pack_id: str, *, only_source_extractable: bool = True) -> list[FieldDefinition]: ...

# compilers/schema_fields/engine.py
class CompletionPort(Protocol):
    model: str
    def complete(self, *, system: str, user: str) -> str: ...

class FieldResult(BaseModel):
    field_key: str
    state: Literal["present", "absent_explicitly", "unknown"]
    value: str | None = None
    evidence: list[VerifiedQuote] = []

class CompileOutput(BaseModel):
    pack_id: str
    entity_id: str
    model: str
    fields: list[FieldResult] = []
    calls: int = 0

class SchemaFieldsCompiler:
    def __init__(self, completion: CompletionPort, *, batch_size: int = 25, max_calls: int = 10): ...
    def build_requests(self, entity_id: str, definitions: Sequence[FieldDefinition],
                       pages: Sequence[PageTextLike]) -> list[JudgeLikeRequest]: ...
    def compile(self, entity_id: str, definitions: Sequence[FieldDefinition],
                pages: Sequence[PageTextLike]) -> CompileOutput: ...
```

- `build_requests` 不调用模型、不占预算；**同一输入必得同一请求**（不含时间戳、批次序号以外的随机量）。
  验收测试用它的 `user` 文本断言组题内容。
- 预算在**每次调用前**检查，超出抛 `CompileBudgetExceeded`（不发送）。
- **产物必须能转成 §2 的候选形状**：`CompileOutput` → `{"request": {...}, "compile_result": {"output": {...}}}`，
  由 `to_candidate(output, *, display_name, schema_pack_id)` 负责，好让 `predictions_from_candidate` 直接吃。

### 3.3 边界（守卫）

- `compilers/` 与 `evidence/` 都是 §4.2 目标目录，**可以 import 彼此的兄弟模块与 `pydantic`/`httpx`**；
  **不得 import** 旧目录（`compiler/`、`product_ingestion/`、`knowledge_compiler/`、`goldenset/`、`eval/`、
  `model_policy/`）——G1 会拦；需要的能力**移植**过来并在文件头注明来源与"原件在 S7 删除"。
- `evidence/` 在 G2 的 `HARNESS_CORE_DIRS` 里，**不得出现险种名、field_key 字面量、Schema67、Golden**；
  `compilers/` **不在** core 目录里，允许出现 pack/字段语义，但仍受 G2 的通用词表约束。
- 单文件 ≤ 500 行（已超限的旧文件别有负担，但**新文件**必须守）。
- 不新增依赖。

## 4. 交付物

- `harness/src/insurance_harness/compilers/schema_fields/{__init__,definitions,prompt,parse,values,profiles,engine}.py`
- `harness/src/insurance_harness/evidence/quote_verification.py`
- `harness/tests/compilers/schema_fields/` 下的单测（含 1 个**离线录制回放**夹具：596 的一批响应 JSON）
- `harness/tests/evidence/test_quote_verification.py`

## 5. 验收

- Claude 提供的受保护验收 `harness/tests/compilers/schema_fields/test_engine_contract.py`（随本片推送，当前 RED）全过。
  它只使用 §3.2 的公开接口与一个假 `CompletionPort`，覆盖：字段顺序与"不发明字段"；组题含定义与页码标记、
  **不含期望值**；严格解析的 6 种失败；引文回验失败即拒绝该字段；值归一；预算在调用前检查；同一输入产出同一请求；
  `to_candidate` 形状可被 `predictions_from_candidate` 接受。
- **离线评分（回归底线，非质量门）**：用仓库里已有的 596 Golden（`dataset/golden/v1/596.jsonl`）与录制响应，
  经 `eval` 的 `evaluate` 打出 precision/recall，**数字写进 PR**；本片只要求"能跑通且数字可复现"，
  质量下限的比较放在 S4b（真实调用）。
- `uv run pytest tests/compilers tests/evidence -q`、`ruff check .`、`mypy src tests`（在 `harness/`）通过；
  仓库根 `pytest -q tests/architecture` 通过且基线不回升；CI 全绿。

## 6. 改动范围

- 允许新增：`harness/src/insurance_harness/compilers/`、`harness/src/insurance_harness/evidence/`、
  `harness/tests/compilers/`、`harness/tests/evidence/`。
- 允许修改：无。**不得**改 `eval/`（S2b 在用）、`contracts/`（S3a）、蓝图、`docs/design/`、`tests/architecture/`、
  任何旧目录。
- 若发现必须动 `tests/architecture/`（新目录需要登记），停下在 PR 说明，由 Claude 处理。

## 7. 非目标

- 不接生产模型、不发真实调用（S4b）。
- 不产出 CandidateBundle、不接平台接收链（S4c）。
- 不做 PageText 的真实重建（`ingest/` 从 ParseArtifact 重建属 S4b）；本片由调用方传入页文本。
- 不做发现/概念/QA 编译器（S6）；不做增量（S8）。
- 不迁移旧 `compiler/`、`goldenset/`；不改它们的任何文件。

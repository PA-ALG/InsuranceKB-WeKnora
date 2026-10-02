# S2a · 质量标尺：Golden 数据模型、fail-closed Evaluator 与第一份真实评分

> 状态：待用户批准 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §7.7、§11（S2）
> 分支：`slice/s2a` ｜ 开工方式：写完计划即开工 ｜ 真实模型调用：**不需要**
> S2b（评判模型校准、7 款产品 Golden、与 V5 对比）另开一片，需要模型调用预算。

## 1. 目标

建立项目的质量标尺，并用它产出第一个真实数字：主项目 G3 epoch9 的字段结果，在已批准的 596 产品 Golden 上的
逐字段 precision / recall。之后每个切片的质量变化都用同一把尺子量。

## 2. 现状

- **已有评测代码** `harness/src/insurance_harness/goldenset/`（records、eval、normalize、keypoints）能力较全，但：
  - `eval.py:60,64` 零分母时 precision/recall 返回 1.0，空集会被当成满分；
  - 证据页码允许 ±1 页（`_evidence_pages_adjacent`），与蓝图"不跨页拼接"冲突；
  - 键是 `(product_id, field_id)`，没有 pack，旧 field_id 是 schema v1.1 的 key；
  - 被 `knowledge/`、`product/`、`flywheel/` 等旧模块引用，属蓝图 §10.1 待退役区。
- **已批准 Golden** `dataset/goldenset/gs-s0q-596-v1/596.jsonl`：1 款产品（596 平安e生保尊享版医疗险）、60 条、
  schema v1.1 旧 key，与 v5 Catalog 的 154 个 field_key **一个都对不上**；按中文字段名对照，**40 条**能映射到
  v5 医疗险 pack（present 30、unknown 8、absent_explicitly 2），20 条是 v1.1 独有字段。
- **主项目结果** G3 epoch9 candidate（7 款产品、493 个字段）在仓库外的私有证据目录，`fields[]` 已是 v5 key，
  证据带 `page_number` 与 `quote`。
- V5 的提取结果与 30 条业务反馈表不在仓库内（在同事机器上），本片不涉及，归 S2b。

## 3. 设计

新代码全部放在蓝图 §4.2 的目标目录 `harness/src/insurance_harness/eval/`。按守卫 G1，`eval/` 不得 import
旧目录（含 `goldenset/`），需要的规范化与比较逻辑**移植**过来，并在文件头注明来源与"`goldenset/` 在 S7 退役后
删除原件"。

| 模块 | 职责 |
|---|---|
| `eval/golden.py` | `GoldenEvidence`、`ValueComponent`、`GoldenItem`、`Prediction` 数据模型与三态不变量 |
| `eval/normalize.py` | 从 `goldenset/normalize.py` 移植：空白/全半角/标点归一、数字与日期等价 |
| `eval/compare.py` | 值判定：组成要素全部命中 / 无组成要素时归一后相等；含禁用词即判错 |
| `eval/evaluator.py` | `evaluate(golden, predictions) -> Report`；`gate(report, pack_id) -> GateVerdict` |
| `eval/catalog.py` | 读取 Catalog JSON，按中文名解析 pack_id 与 field_key |
| `eval/convert.py` | `golden_from_legacy(...)`、`predictions_from_candidate(...)` |
| `eval/report.py` | CLI：`python -m insurance_harness.eval.report --golden ... --candidate ... --out ...`，输出 JSON 与 Markdown |

### 3.1 数据模型（验收测试按这些名字断言）

```text
GoldenEvidence  document, document_sha256(64位hex), page(≥1), quote(非空)
ValueComponent  name, accepted: tuple[str, ...]    # 任一同义写法命中即该要素命中
GoldenItem      pack_id, product_id, field_key, state(present|absent_explicitly|unknown),
                value, evidence[], components[], forbidden: tuple[str, ...], judged_by, note
Prediction      pack_id, product_id, field_key, state, value
```

三态不变量（蓝图 §5.1）：present 必须有值且有证据；absent_explicitly 值为 None 且有证据；unknown 无值、无证据。
`judged_by` 取值形如 `human:<who>`、`legacy:<golden-set-id>`、`model:<model-id>`，用于区分来源。

### 3.2 计分规则

| Golden | 预测 | 结果 | 计入 |
|---|---|---|---|
| present | present 且值正确 | correct | tp |
| present | present 但值错误 | mismatch | fp + fn |
| present | 缺失或非 present | missed | fn |
| unknown | present | **hallucination** | fp，`hallucinations += 1` |
| absent_explicitly | present | **contradiction** | fp，`contradictions += 1` |
| unknown / absent | 同状态 | correct | `correct_non_present += 1`，不进 P/R 分母 |
| 不在 Golden 中 | 任意 | unscored | `unscored_predictions += 1`，不算幻觉 |

- 值正确：有 `components` 时每个要素都要有一个 `accepted` 写法出现在归一后的预测值里；无 `components` 时归一后
  相等。只要出现任一 `forbidden` 词即判错。缺失的要素名记入 `component_misses["<product>/<field>"]`。
- 本片**不比较证据页码**：主项目与 Golden 的页码口径未对齐，强行比较会产生假错误。证据精确度在 S2b 用评判模型核对。
- Report 字段：`per_field`、`per_pack`、`micro`（每项含 tp/fp/fn/precision/recall）、`hallucinations`、
  `contradictions`、`correct_non_present`、`missing_predictions`、`unscored_predictions`、`component_misses`。
- **零分母返回 None，不返回 1.0。**

### 3.3 质量门（fail closed）

`gate(report, pack_id, min_precision=0.95, min_recall=0.90)` 返回 `GateVerdict(passed, reasons)`：
precision 或 recall 为 None → `precision_undefined` / `recall_undefined`；低于阈值 → `precision_below` /
`recall_below`；`hallucinations > 0` → `hallucination`。任一原因存在即不通过。阈值来自蓝图 §2.5。

### 3.4 转换器

- `golden_from_legacy(path, catalog, pack_display_name, dataset_root) -> LegacyConversion(items, unmapped)`：
  按 `field_name` 精确匹配 pack 字段的 `short_title`；absent_explicitly 的旧值移入 `note`、value 置 None；
  `document_sha256` 用 `dataset_root/<product_name>/<doc>` 实际文件计算；`judged_by="legacy:gs-s0q-596-v1"`。
- `predictions_from_candidate(candidate, product_id_by_name) -> list[Prediction]`：用
  `request.entity_bindings[].display_name`（去掉空白后）查产品 ID，`schema_pack_id` 作 pack_id；遇到未登记的产品名
  **抛 ValueError 并列出名称**，不静默跳过。

## 4. 交付物

1. 上述 7 个模块及测试（验收测试之外的单测自行补充）。
2. **转换后的 Golden** `dataset/golden/v1/596.jsonl`（40 条）与 `manifest.json`（来源 `gs-s0q-596-v1`、catalog
   sha256、条目数、三态分布、20 条未映射字段名清单）。由 `golden_from_legacy` 生成后提交。
3. **第一份真实评分**：用私有证据目录中的 epoch9 candidate
   （`insurancekb-private-evidence/g3-20260912-final-closeout/final-epoch9-and-dns-20260913/epoch9/candidate/candidate.json`）
   在本机运行 report CLI。报告文件**不入库**；PR 描述中贴出 596 的 per-pack 与 40 个字段的逐字段结果表、
   幻觉/矛盾/漏抽数，以及 gate 结论（预计不通过，如实报告）。

## 5. 验收

验收测试 `harness/tests/eval/test_golden_evaluation.py`（Claude 提供，当前 RED）全部通过，另外：

- `uv run pytest tests/eval`、`uv run ruff check .`、`uv run mypy src tests`（在 `harness/`）通过；
- 仓库根 `python -m pytest -q tests/architecture` 通过（`eval/` 是目标目录，新文件不触发 G11；文件名不得含
  版本或 Goal 后缀）；
- PR 描述含第一份真实评分。

## 6. 改动范围

- 允许新增：`harness/src/insurance_harness/eval/`、`harness/tests/eval/`（验收测试文件除外）、`dataset/golden/v1/`。
- 不得修改：`harness/tests/eval/test_golden_evaluation.py`、`goldenset/` 及其他旧目录、蓝图、`docs/design/`、
  `tests/architecture/`、`contracts/`、任何 Go 或前端代码。
- 不新增依赖。

## 7. 非目标

- 不调用任何模型；不重新编译产品；不改 `goldenset/` 的行为。
- 不比较证据页码与引文（S2b）；不做 V5 对比（S2b）；不接 CI 质量门（等 S2b 有多 pack Golden 再接）。

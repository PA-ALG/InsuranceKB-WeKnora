# S2c · 语义评分：G3 的第一份有效质量数字

> 状态：用户 2026-10-07 批准方向 ｜ 作者：Claude Code ｜ 依据：技术蓝图 1001 §2.5、§7.7；S2b Spec §8（2026-10-05 用户裁决）
> 分支：`slice/s2c`（基于 `main@eb0b2ab6b`） ｜ 工作目录：`.worktrees/s2c` ｜ 开工方式：**写完计划即开工**
> 评判模型：**GPT-6 Astra，推理档位 xhigh**，用户新开**一个**独立 Codex 会话，以文件交换答题；不走 API。

## 1. 目标

S2b 交付了 4 款产品的 Golden（`dataset/golden/v1/{1814,1816,1824,1826}.jsonl`，207 条），但 PR #142 里 G3 的分数
（1824 = 12%/12%，其余 0%/0%）**测的不是质量**：`compare_value` 要求每个 component 的 `accepted` 短语归一化后**逐字**
出现在候选值里，而评委写的 `accepted` 是改写过的要点句。**拿 Golden 自己的 value 去对自己的 components，108 个 present
只有 21 个全中（19.4%）**；拿 Golden 自己的原文引文去对，只有 14/108。这把尺子上满分答案也只有约 19%。

这与 596 校准暴露的问题相同（逐字一致 0/19，语义等价 16/19）。用户 2026-10-05 已裁决**按语义等价比较，不要求一模一样**；
S2b Spec §8.2 末尾"4 款走 `evaluate`"的澄清与该裁决冲突，已作废（见该节更正）。

本片把"值对不对"从逐字匹配改为 S2b §8.1 的三层比较，给出 G3 epoch9 在 4 个 pack 上**第一份有效的**逐 pack、逐字段
precision / recall，并把这套评分器留给 S4b（V5 编译器 + DeepSeek v4 flash）直接复用。

## 2. 评分口径（`golden.semantic_comparison.v1`）

### 2.1 每个 Golden 条目的判定

| Golden | 预测 | 判定方式 | `result` | TP / FP / FN |
|---|---|---|---|---|
| present | present，`values_equal` 或 `compare_value(...).correct` | L1 代码 | `correct` | 1 / 0 / 0 |
| present | present，L1 未判定 | L2 `equivalent` | `correct` | 1 / 0 / 0 |
| present | present，L1 未判定 | L2 `insufficient` | `incomplete` | 0 / 1 / 1 |
| present | present，L1 未判定 | L2 `contradicted` | `wrong_value` | 0 / 1 / 1 |
| present | 非 present 或缺失 | 代码 | `missed` | 0 / 0 / 1 |
| unknown | present | 代码 | `hallucination`（计入门槛的幻觉数） | 0 / 1 / 0 |
| absent_explicitly | present | 代码 | `contradiction` | 0 / 1 / 0 |
| 非 present | 非 present / 缺失 | 代码 | 与 `evaluate` 相同（`correct_non_present`、`state_mismatch`、`missing`） | 不计 |

- `incomplete` 与 `wrong_value` 都算错（预测发布出去会误导读者），但分开计数：前者是**缺内容**，后者是**说错了**。
- **L2 是单向的**：只问 Golden 列出的核心事实是否被预测覆盖、是否被预测否定。预测**额外**写出、Golden 没有的事实，
  L2 不核对；这类内容的正确性由来源回跳负责（蓝图 §2.5"已发布事实来源回跳 = 100%"，S4 的严格回验）。报告须写明这一局限。
- 门槛不变：`gate(report, pack_id)`，precision ≥ 95%、recall ≥ 90%、`hallucination` = 0。

### 2.2 L2：复用已有的等价题

- 每道等价题的字段：`field_key`、`reference` = Golden value、`judged` = 预测 value、`components` = `[]`（候选没有 components）。
- system 文本用 `EQUIVALENCE_PROMPT_VERSION`（当前 `"2"`，即 v1 加 S2b §8.4 的单向规则），**不新增 prompt 版本**。
  请求格式、响应格式（`{"fields":[{"field_key","verdict","reason"}]}`）、fail-closed 规则与 S2b §8.2 相同。
- 每款产品一个子目录，`batch_size` 60，每款 `max_calls` 2。按现有数据预计每款 1 题、共 4 题。
- v2 没有在 596 上单独跑过（596 校准用的是 v1 + 两条 L3 裁定）；因此 L3 必须抽检 L2 判 `equivalent` 的条目（§4 第 5 步）。

### 2.3 L3：Claude 回原文裁定

裁定文件 `<run_root>/rulings.json`：`{"entries":[{"product_id","field_key","from","to","reason","by","on"}]}`，
全部非空，`extra="forbid"`。**只允许以下转换**，其他一律 `ValueError`：

| from（当前 `result`） | to | 含义 |
|---|---|---|
| `wrong_value` | `correct` / `incomplete` / `golden_defect` | L2 误判矛盾；或其实是缺内容；或 Golden 本身错 |
| `incomplete` | `golden_defect` | 缺的部分超出字段定义或 Golden 写错。**不允许直接改成 `correct`** |
| `correct`（仅 L2 判定的） | `incomplete` / `wrong_value` | 抽检发现 L2 放水；L1 判定的 `correct` 不可裁定 |
| `hallucination` | `misfiled` / `golden_defect` | 原文有但不属于该字段；或原文有且属于该字段、Golden 漏标 |

- `misfiled`：FP 1，**不计幻觉**（内容有原文依据，只是放错字段）。
- `golden_defect`：不计 TP/FP/FN，单独计数并逐条列出，留给 Golden v2 修正（专家回归后复核，不覆盖原记录）。
- 裁定后的条目 `basis = "L3"`，`reason` 取裁定理由。理由必须写明原文出处（文件、页码或条款号）与判断依据，不写"人工复核通过"。
- 裁定必须指向一个实际存在、且当前 `result` 等于 `from` 的条目；同一条目最多一条裁定；否则 `ValueError`。

## 3. 设计

新代码放 `harness/src/insurance_harness/eval/`，不 import 旧目录。

### 3.1 公开 API（验收测试 `harness/tests/eval/test_semantic_scoring.py` 按此断言）

```python
# eval/semantic.py
class SemanticVerdict(BaseModel):            # frozen, strict, extra="forbid"
    product_id: NonBlank
    field_key: NonBlank
    verdict: Literal["equivalent", "contradicted", "insufficient"]
    reason: NonBlank

class Ruling(BaseModel):                     # frozen, extra="forbid"；JSON 字段名 from / to
    product_id: NonBlank
    field_key: NonBlank
    from_result: Literal["wrong_value", "incomplete", "correct", "hallucination"]   # alias "from"
    to_result: Literal["correct", "incomplete", "wrong_value", "misfiled", "golden_defect"]  # alias "to"
    reason: NonBlank
    by: NonBlank
    on: NonBlank
    # 构造时校验 §2.3 的转换表，不在表内即 ValidationError

def semantic_questions(
    golden: Iterable[GoldenItem], predictions: Iterable[Prediction],
) -> dict[str, list[EquivalenceQuestion]]:
    """product_id -> 需要 L2 的题目（双方 present 且 L1 未判定），按 field_key 排序；无题的产品不出现。"""

def evaluate_semantic(
    golden: Iterable[GoldenItem], predictions: Iterable[Prediction],
    verdicts: Iterable[SemanticVerdict], rulings: Iterable[Ruling] = (),
) -> Report:
    """按 §2 判定；semantic_questions 的每一题必须恰好有一条 verdict。"""
```

- `evaluator.py`：`ItemOutcome.result` 增加 `incomplete`、`wrong_value`、`misfiled`、`golden_defect`；`ItemOutcome` 增加
  `basis: Literal["L1", "L2", "L3"] | None = None` 与 `reason: str | None = None`；`Report` 增加计数
  `incomplete`、`wrong_values`、`misfiled`、`golden_defects`（均默认 0）。**`evaluate` 的逐字口径行为不变**，
  `test_golden_evaluation.py` 必须保持通过——CI 的离线回放与 S4a 的回归底线仍用它。
- **fail closed**：缺 verdict、多出未请求的 verdict、重复 verdict、同一 `(product_id, field_key)` 出现在两个 pack、
  裁定不匹配 → 一律 `ValueError`，错误信息列出相关 `field_key`。不得把缺判的题默认成任何结果。
- 可以在 `equivalence.py` 内抽出逐字段判定的函数供本片使用，但 `compare_equivalence` 等既有公开行为不变，
  `test_equivalence.py` 不得改动。

### 3.2 文件交换 CLI：`python -m insurance_harness.eval.semantic_run`

```text
prepare --golden G [--golden G2 ...] --candidate C --product-map M --run-root R
score   --golden G [--golden G2 ...] --candidate C --product-map M --run-root R --judge-model MODEL --out PREFIX
```

- 预测由 `predictions_from_candidate(candidate, product_map)` 得到，与 `eval.report` 相同。
- `prepare`：`R` 必须在任何 git 仓库之外（`check_run_directory`）；每个有题的产品写 `R/<product_id>/requests/NNN.json`
  （`write_requests`）与 `R/<product_id>/run.json`，并写 `R/AGENTS.md`（评委规则，见 §3.3）。
  `run.json` 绑定：`product_id`、`prompt_version`、`batch_size`、`request_sha256`、每个 Golden 文件的 SHA256、
  candidate 与 product map 的 SHA256。产品目录已存在 → 退出码 2，**不覆盖任何已有文件**。标准输出打印每款题数。
- `score`：按同样输入重建题目，与 `run.json` 不一致 → 退出码 2（"inputs changed since prepare"）；
  逐产品用 `FileJudgeClient` 读答卷，格式不合规、缺题、有未读题 → 退出码 2；读 `R/rulings.json`（可选）；
  调 `evaluate_semantic`，写 `PREFIX.json` 与 `PREFIX.md`（仓库之外、不覆盖，规则同 `eval.report`）。成功退出码 0（不论门槛是否通过）。
- 报告 JSON 至少包含：
  - `metric_definition.metric_id = "golden.semantic_comparison.v1"` 与 §2 的口径说明（含 L2 单向的局限）；
  - `report`（`Report` 全量，含每条 `outcomes` 的 `basis` / `reason`）与 `gates`（逐 pack）；
  - `l2_raw`：每款产品 L3 之前的 `equivalent` / `contradicted` / `insufficient` 数；
  - `literal_diagnostic`：同一输入跑 `evaluate` 的逐 pack `precision` / `recall`，**只作对照，不进门槛**；
  - `provenance`：每个 Golden 文件、candidate、product map 的 SHA256，`judge_model`、`prompt_version`，
    `rulings_sha256`（无裁定文件时为 `null`）与裁定条数。
- 报告 Markdown：逐 pack 表（TP/FP/FN/P/R/幻觉/缺内容/说错/放错字段/Golden 缺陷/门槛），逐 pack 的 `incomplete` 与
  `wrong_value` 字段清单，全部 L3 裁定（理由原文照录），语义口径与逐字口径的对照表。

### 3.3 评委规则（`prepare` 写入 `R/AGENTS.md`）

必须包含：只读本目录及各产品子目录，不打开仓库、PDF、Golden 或其他路径，不联网；一个会话可依次处理全部产品子目录；
按 `requests/` 中 `system_lines` 的规则比较 `user_lines` 中两种表述，答案写入同一产品 `responses/` 的同名文件；
已有答案跳过；如实判定，不为提高或压低分数调整判断；不修改 `requests/`、`run.json` 与本文件，不用脚本批量生成答案。

### 3.4 Golden manifest 顶层整理

`dataset/golden/v1/manifest.json` 顶层仍是 596 的旧单产品元数据（`items: 40`、`product_id: 596`、`pack_id`、`tri_state`、
`unmapped_fields`、`source*`、`generation`、`provenance`、`scope` 等），容易被读成全集合计。
改为：顶层只留数据集级字段（`dataset_version`、`catalog_*`、`files`、`products`）；596 的单产品字段原样移入
`products["596"]`，并加 `"role": "calibration_reference"`；`files` 不变（文件字节不变）。`annotate._pack` 读顶层的分支随之删除
（删除优于兼容），相应的实现方测试同步调整。改完后 596 的 `ingest --calibrate` 仍能读到 pack。

## 4. 运行顺序

1. 实现与单测（只用假评委，CI 不发真实调用）。
2. `prepare`：Golden = 4 款新文件（**不含 596**——596 在 epoch9 没有重新抽取）；candidate = S2a Spec §4.3 指定的 epoch9 存档
   （SHA256 `4e520af314b2481b18193f358ea266f7b1c4d76274bad492d7ef9c8a3685b265`）；product map = S2b 生成的
   `epoch9-product-map.json`（SHA256 `757fbe12ba6390773be00fefba2cf821d8bbc67bfe2289a24477ba219e0b8d11`）；
   run root 建议 `~/judge-runs/s2c-v1`。在 Issue 里贴出每款题数与 `request_sha256`。
3. **用户**在 `~/judge-runs/s2c-v1` **新开一个** Codex 会话（GPT-6 Astra，xhigh），依次答完全部产品，答完告知实际模型与档位。
   这个会话必须是新的：S2b 的标注会话写过 Golden，不能自己评自己。
4. 实现方在**无裁定文件**时跑 `score`，在 Issue 里贴：`l2_raw`、全部 `wrong_value` / `incomplete` / `hallucination` 清单。
5. **Claude** 写 `rulings.json`：
   - 全部 `wrong_value` 与 `hallucination` 逐条回原文裁定（或确认维持）；
   - `incomplete` 逐条看是否因 Golden 超出字段定义（→ `golden_defect`）；
   - **抽检 L2 的 `equivalent`**：每款按 `field_key` 字母序取前 3 条 L2 判定的 `correct`，共 12 条，逐条对照 Golden 与预测；
     **其中错判 ≥ 2 条即停下**，说明 v2 偏宽，交用户决定（不出正式数字）。错判的条目用 `correct → incomplete/wrong_value` 裁定。
6. 实现方跑最终 `score`，开 PR。

## 5. 交付物

- `eval/semantic.py`、`eval/semantic_run.py`、`evaluator.py` 的扩展、manifest 整理及对应测试。
- PR 描述：逐 pack 结果表与门槛结论；语义口径与逐字口径对照；`l2_raw` 与 L3 前后变化；全部 L3 裁定（理由照录）；
  `golden_defect` 清单；评委会话数、模型与档位；明确写出 L2 单向的局限与"epoch9 复用 epoch8、未调用模型，不代表生产模型质量"。
  题目、答卷、裁定文件与报告留在 run root，**不入库**。

## 6. 验收

- Claude 提供的 `harness/tests/eval/test_semantic_scoring.py`（受保护，当前 RED）全部通过；
- `harness/` 下 `pytest tests/eval`、`ruff check .`、`mypy src tests` 通过，`test_golden_evaluation.py`、`test_equivalence.py`、
  `test_judge_annotation.py`、`test_judge_files.py` 不改且通过；
- 仓库根架构守卫通过，基线不回升；CI 全绿；
- 已把最新 `main` merge 进本分支（不 rebase）。

## 7. 改动范围

- 允许新增：`eval/semantic.py`、`eval/semantic_run.py`、对应实现方测试。
- 允许修改：`eval/evaluator.py`、`eval/equivalence.py`（仅抽出内部函数，公开行为不变）、`eval/annotate.py`（仅 §3.4）、
  `dataset/golden/v1/manifest.json`（仅 §3.4）、实现方自己的既有测试（仅为 §3.4 同步）。
- **受保护（Claude 写，实现方不得改）**：`harness/tests/eval/test_semantic_scoring.py`、`test_golden_evaluation.py`、
  `test_equivalence.py`、`test_judge_annotation.py`、`test_judge_files.py`、`docs/design/`、蓝图、`tests/architecture/`、`contracts/`。
- 不得修改：`dataset/golden/v1/*.jsonl`（Golden 文件字节不变）、旧目录。不新增依赖。

## 8. 评判工作量

- 评判模型：GPT-6 Astra（xhigh），用户开 **1 个**新 Codex 会话；与生产编译模型 DeepSeek v4 flash 不同族。**无 API、无密钥。**
- 题目数：预计 4 道（每款 1 道，约 22–33 个字段）；上限每款 2 道、共 **8 道**。
- 外发内容：只有 Golden 与 G3 预测的两段文字，不含 PDF 原文。

## 9. 非目标

- 不重新生成或修改 Golden（`golden_defect` 只记录）；不评 596（epoch9 未重新抽取）；不做 1828。
- 不核对预测中 Golden 未覆盖的额外事实（§2.1 局限）。
- 不调用生产编译模型；不接 CI 质量门；不与 V5 对比。

# RV2b · 审核门槛校准工具：把评委判定与审核分数对上，按 pack 求出满足 95% 精确率的门槛

> 状态：用户已确认开工（2026-10-17：GPT-6 Astra 评委重判；unknown 不打分） ｜ 作者：Claude Code
> 依据：蓝图 §6.3（门槛以"达到门槛的成员在评判集上 precision ≥ 95%"设定）、§7.7（评分口径）；S2c 语义评分；RV1、RV2a Spec
> 分支：`slice/rv2b` ｜ 工作目录：`.worktrees/rv2b` ｜ 实现方：Claude ｜ 审核方：Codex（质量评分口径）

RV2 的第二片，与 RV2a（打分器）写域不重叠，可并行。RV2c 用本片与 RV2a 的工具做真实运行。

## 1. 目标

1. **Golden v2 → 评委输入**：把 `dataset/golden/v2/<product>.json` 转成 `eval.semantic_run` 读取的 GoldenItem JSONL。仓库里目前没有这个转换，过去是仓库外临时转换的。
2. **逐条标签**：
   - 从 `semantic_run score` 的报告中，取每条被审核的 Claim 的对错；
   - 被审核的 Claim 指编译结果为 `present` 或 `absent_explicitly` 的字段（RV2a 只给它们打分）。
3. **门槛**：
   - 把标签与 RV2a 的分数文件对上；
   - 按 pack 与全体汇总，求"分数 ≥ t 的 Claim 精确率 ≥ 95%"的最小门槛 t；
   - 报告每个门槛背后的样本数与置信下界，样本不足时明确写"不足"；
   - 输出供 RV3 写入审核策略的门槛建议。本片不改 `catalog/review_policy.json`。

## 2. 现状（`main@55a36ea59`）

- `eval/golden.py`：`GoldenItem`（`Prediction` 加 `evidence[GoldenEvidence]`、`components`、`forbidden`、`judged_by`）；present 与 absent_explicitly 必须有证据，unknown 不得有证据。
- `eval/segment_score.py`：`load_golden_v2` → `GoldenV2{product_id, cards_version, fields[GoldenV2Field: field_key, state, value, reason, evidence[...]]}`；pack 取自 `dataset/golden/v2/manifest.json`。
- `eval/semantic_run.py`：
  - `prepare` / `score`，通过文件交换由独立会话（GPT-6 Astra）作答；
  - 报告 `report.outcomes[]` 的键：`pack_id, product_id, field_key, golden_state, predicted_state, golden_value, predicted_value, result, basis, reason, tp, fp, fn, partial, …`；
  - `result` 取值：correct、incomplete、wrong_value、hallucination、contradiction、misfiled、missed、state_mismatch、correct_non_present、missing 等（`eval/evaluator.py`、`eval/semantic.py`）。
- 精确率口径（S2c，用户裁定）：incomplete 不算错。

## 3. 设计

### 3.1 Golden 转换（`harness/src/insurance_harness/eval/golden_items.py`）

```text
python -m insurance_harness.eval.golden_items --products P... --out FILE [--repo DIR] [--judged-by model:gpt-6-astra]
```

- 每款产品的每个 Golden 字段一条 GoldenItem：
  - `pack_id` 来自 manifest；`state`、`value` 照搬；
  - `evidence` 由 Golden 证据按 GoldenEvidence 的合同转换（文档、文档 sha256、页码、引文，保持 Golden 中的顺序）；段落编号不在该合同内（`extra="forbid"`），语义评委只比值、不按段落定位，转换时丢弃；
  - `judged_by` 默认取 manifest 记录的评委；`note` 放 `reason`。
- 转换失败（manifest 没有该产品、证据缺字段、违反 GoldenItem 校验）→ 一行 `{"stopped": <code>}` 并退出 2，不写半截文件；输出 JSONL 按产品与字段键排序，可复现。

### 3.2 标签与门槛（`harness/src/insurance_harness/eval/review_calibration.py`）

```text
python -m insurance_harness.eval.review_calibration --report REPORT.json --scores DIR [--precision 0.95] [--min-support 10] --out DIR
```

- **被审核的 Claim**：`predicted_state` 为 `present` 或 `absent_explicitly` 的结果。其余（编译为 unknown，含 missed）不参与。
- **标签**：
  - 对：`correct`、`incomplete`、`correct_non_present`；
  - 错：`wrong_value`、`hallucination`、`contradiction`、`misfiled`、`state_mismatch`，以及 `missed`：在被审核的 Claim 上，它只出现在编译为 `absent_explicitly` 而 Golden 为 `present` 时，即 Claim 断言"没有"而 Golden 有；
  - 排除（不计入门槛、在输出中按结果计数）：`golden_defect`（L3 裁定 Golden 本身有误，无法判对错）、`unscored`（该字段不在 Golden 中）；
  - 其他结果值 → 报错停止（`LABEL_UNKNOWN`），不猜。
- **分数**：
  - 从 `<scores>/<product>/scores.json`（RV1 分数文件格式）按 `<product>/<field_key>` 取；
  - 被审核的 Claim 缺分数 → 停止（`SCORE_MISSING`）；分数文件里多出的键忽略并计数。
- **门槛**：
  - 对每个 pack 与全体，把 Claim 按分数降序；
  - 对每个不同的分数值 t 计算：分数 ≥ t 的条数 n、对的条数、精确率、Wilson 95% 下界；
  - 选满足"精确率 ≥ `--precision` 且 n ≥ `--min-support`"的最小 t；
  - 没有满足的 t → `insufficient`，并写明原因（样本不足或达不到精确率）。
- **输出**：
  - `calibration.json`：逐条表（pack、product、field_key、state、score、label、result）、各 pack 与全体的候选门槛表与选定门槛；
  - `calibration.md`：人读摘要；
  - `thresholds.json`：`{"thresholds": {"<pack_id>": {"default": t}}, "parameters": {"precision", "min_support", "z"}, "sources": {"report_sha256", "scores_sha256": {"<product>": …}}}`。`thresholds` 只含选定了门槛的 pack，形状同审核策略的 `thresholds`，可原样放入；参数与 sha256 放在旁边一层，不与 pack 键混排。
- **一致性检查**：报告与分数涉及的产品集合必须一致，否则停止（`PRODUCT_MISMATCH`）。

### 3.3 不在本片

真实评委与打分调用（RV2c）、写入审核策略与 pack 准入（RV3）、按字段的门槛（样本太少，先按 pack）。

## 4. 验收

- 受保护验收（Claude 写，RED 单独提交）：
  - `harness/tests/eval/test_golden_items.py`：
    - 用最小 Golden v2 夹具（两款产品、两种 pack）转换出的每条都能通过 GoldenItem 校验；
    - 字段与证据逐项正确、输出有序；
    - 缺 manifest、缺证据字段时停止且不写文件。
  - `harness/tests/eval/test_review_calibration.py`：
    - 标签映射逐项正确；
    - unknown 不参与；
    - 未知结果值停止；
    - 缺分数停止；
    - 门槛选择：最小满足 t、样本不足、达不到精确率三种情况；
    - Wilson 下界数值；
    - 输出文件内容与 sha256；
    - 产品不一致停止。
- 门禁：Harness `pytest`、`ruff`、`mypy src tests`；架构守卫；CI 全绿。

## 5. 改动范围

- 允许：新增 `eval/golden_items.py`、`eval/review_calibration.py` 及其测试与夹具（夹具放 `harness/tests/eval/fixtures/` 下，不复制真实 Golden 全文）。
- 不改：`eval/semantic*.py`、`eval/evaluator.py` 的评分口径、Golden 数据、RV1/RV2a 的文件、Go、前端、`contracts/`。
- 受保护：本片验收文件、`docs/design/`、蓝图。

## 6. 依赖与预算

依赖 S2c（语义评分）、RV1（分数文件格式）。无真实调用、无迁移、无部署。

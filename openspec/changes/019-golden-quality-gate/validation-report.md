# 019 验证报告 — Golden 工具、QualityProfile 与自动发布质量闸门

> 本报告只声明**确定性软件验收**，不代表真实数据运行完成。真实 gs-v0.1 与 13 产品 baseline
> 由 020 用同一 assembler/validator/profile/gate API 产出，真实模型调用失败不得靠改夹具掩盖。

## 门禁（交付定义，全绿）

- `uv run ruff check .` → All checks passed
- `uv run mypy src tests` → Success（161 source files，strict）
- `uv run pytest -m "not live and not integration_postgres" -q` → **1044 passed / 5 deselected**
  （019 前基线 961 → +83 新用例）
- 019 专项：`test_goldenset_{assemble,validate,baseline,profile}_019.py` + `test_quality_gate_019.py`
  → **83 passed**（11+10+13+18+31，全部严格 test-first：先桩→RED→实现→GREEN），
  纯 fixture/replay，零真实模型/PDF 凭据（Q1.5/Q5.1）

## 逐条验收（Q1~Q5）

| 条款 | 验收点 | 证据 |
|---|---|---|
| Q1.1 | portable assembler/CLI，显式 workspace/dataset-root/output/schema-dir，无绝对路径 | `assemble.py` + `test_q1_1_*` / `test_q1_5_cli_end_to_end` |
| Q1.2 | per-record annotator 保留，混合标注不被全局常量覆盖；manifest 汇总集合 | `test_q1_2_mixed_annotators_are_not_overwritten` 等 3 例 |
| Q1.3 | 产品齐全 / 每产品 disputed rate / extractable 三态齐全（非 extractable 不计） | `validate.py` + `test_q1_3_*` 三个失败分支 |
| Q1.4 | golden self-eval P/R/F1（+dataset_root 时 evidence）=1.0；发布目录不可变 | `test_q1_4_self_eval_is_one` + `build_release` FileExistsError |
| Q1.5 | 普通 CI 最小 fixture 跑成功 + 各失败分支，无真实凭据 | 全 019 用例无网络/模型/PDF |
| Q2.1 | artifact 记录 run/pred/dead-letter/judge/keypoints/eval，未解决数量不省略 | `baseline.py` `ProductRunStatus.unresolved` + `test_q2_1_*` |
| Q2.2 | 绑定指纹（git/schema/model/prompt/template+source/golden hash）；缺项不能批准 | `test_q2_2_missing_fingerprint_field_blocks_approval` |
| Q2.3 | 批准记录独立、不可改写，只能追加新版本 | `test_q2_3_approval_is_versioned_and_immutable` |
| Q3.1 | 每 field_id 输出 support/value acc/tri-state confusion/hallucination/evidence，绑定指纹 | `profile.py` `build_profile` + `test_q3_1_*` |
| Q3.2 | 版本化 + golden hash/schema/model/prompt 任一不匹配即 stale | `test_q3_2_staleness_on_each_of_four_dims`（+ `_non_staleness_dims_do_not_trigger` 反例） |
| Q3.3 | 全局回归阈值 + 字段自动化阈值；判定逐条列失败指标与实际值 | `test_q3_3_*` + `check_regression` |
| Q4.1 | `auto_apply_supersede_low_risk` 默认 false | `test_q4_1_supersede_low_risk_default_off` |
| Q4.2 | add/enrich/supersede 自动路径均调用同一 gate，不各自绕过 | `merge.py` `_gate_ok` 接入三处 + `test_q4_2_gate_gates_auto_apply_per_field` |
| Q4.3/4.4 | 资格=risk low + 非 pending + profile 匹配已批准 + 达默认阈值（10/0.98/0.01/1.0） | `quality_gate.py` `decide` + `test_q4_3_*` |
| Q4.5 | high 永不自动；缺失/stale/不达标 → ReviewItem，候选不丢弃 | `test_q4_5_*` + 接入测试断言 grace_period 进审核 |
| Q4.6 | 回归 gate 失败阻止 profile 批准，不影响已发布快照 | `check_regression`（纯逻辑，不触快照） |
| Q5.1~5.3 | 纯逻辑全单测；模型层用 replay；门禁全绿；不宣称真实运行；020 复用同一 API | 见门禁 + 本报告顶部边界声明 |

## 边界与未完成项（诚实声明）

- **未产出真实 baseline/画像**：真实 gs-v0.1（2 产品收尾）与 13 产品 baseline/QualityProfile 属 020；
  本 change 只交付确定性工具与合同。
- **online gate 尚未在生产默认启用**：`MergeEngine`/importer 已可注入 `quality_gate`+`run_fingerprint`，
  但默认 `None`（在线治理未启用，回退保守 policy 布尔位）。启用需 020 产出并批准 QualityProfile 后接线。
- **evidence 真实回验**依赖 dataset_root（真实 PDF）；CI 用"是否带证据"的软件代理，020 接真实 PDF 后启用回验。
- `openspec validate 019 --strict` 本机 CLI 未识别该 item；以门禁 + 本报告为准。

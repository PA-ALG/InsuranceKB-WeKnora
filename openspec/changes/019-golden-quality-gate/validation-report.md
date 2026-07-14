# 019 验证报告 — Golden 工具、QualityProfile 与自动发布质量闸门

> 本报告只声明**确定性软件验收**，不代表真实数据运行完成。真实 gs-v0.1 与 13 产品 baseline
> 由 020 用同一 assembler/validator/profile/gate API 产出，真实模型调用失败不得靠改夹具掩盖。

## 门禁（交付定义，全绿）

- `uv run ruff check .` → All checks passed
- `uv run mypy src tests` → Success（161 source files，strict）
- `uv run pytest -m "not live and not integration_postgres" -q` → **1060 passed / 5 deselected**
- 019 专项：`test_goldenset_{assemble,validate,baseline,profile}_019.py` + `test_quality_gate_019.py`
  → **98 passed**（11+12+19+22+34，全部严格 test-first：先桩→RED→实现→GREEN），
  纯 fixture/replay，零真实模型/PDF 凭据（Q1.5/Q5.1）
- **codex review 返工已并入本 head**：9 条（6×P1 + 3×P2）全部修复，见文末「codex review 返工」。

## 逐条验收（Q1~Q5）

| 条款 | 验收点 | 证据 |
|---|---|---|
| Q1.1 | portable assembler/CLI，显式 workspace/dataset-root/output/schema-dir，无绝对路径 | `assemble.py` + `test_q1_1_*` / `test_q1_5_cli_end_to_end` |
| Q1.2 | per-record annotator 保留，混合标注不被全局常量覆盖；manifest 汇总集合 | `test_q1_2_mixed_annotators_are_not_overwritten` 等 3 例 |
| Q1.3 | 产品齐全 / 每产品 disputed rate（默认阈值 0.05，企业设计 ≤5%）/ extractable 三态齐全（非 extractable 不计） | `validate.py` + `test_q1_3_*`（含 `_disputed_default_threshold_is_five_percent`） |
| Q1.4 | golden self-eval P/R/F1=1.0，**默认强制 evidence 回验**（无 dataset_root 判失败，不静默跳过）；发布目录不可变 | `test_q1_4_evidence_required_by_default_without_dataset_root_fails` + `build_release` FileExistsError |
| Q1.5 | 普通 CI 最小 fixture 跑成功 + 各失败分支，无真实凭据 | 全 019 用例无网络/模型/PDF |
| Q2.1 | artifact 记录 run/pred/dead-letter/judge/keypoints/eval，未解决数量不省略 | `baseline.py` `ProductRunStatus.unresolved` + `test_q2_1_*` |
| Q2.2 | 绑定指纹（git/schema/model/prompt/template+source/golden hash）；缺项不能批准 | `test_q2_2_missing_fingerprint_field_blocks_approval` |
| Q2.1 补 | **产物齐全性阻断批准**：pred=0 / keypoints 未 ready-done / 缺 eval 报告任一都拒批 | `ProductRunStatus.completeness_blockers` + `test_q2_1_{zero_pred,pending_keypoints,missing_eval_report}_blocks_approval` |
| Q2.3 | 批准记录独立、不可改写，只能追加新版本；**绑定 profile 内容哈希 + 消费回归 verdict** | `test_q2_3_approval_is_versioned_and_immutable` / `_carries_...profile_hash` / `test_q4_6_failing_regression_blocks_approval` |
| Q3.1 | 每 field_id 输出 support/value acc/tri-state confusion/hallucination/evidence，绑定指纹；**零观测不给满分**（value/evidence 无观测记 0.0，失格） | `profile.py` `build_profile` + `test_q3_1_*` / `test_q4_3_zero_observation_field_is_not_eligible` |
| Q3.2 | 版本化 + golden hash/schema/model/prompt/**template/source profile** 六维任一不匹配即 stale（git_sha 非 staleness 维） | `test_q3_2_staleness_on_each_of_six_dims` / `_git_sha_is_not_a_staleness_dim` |
| Q3.3 | 全局回归阈值 + 字段自动化阈值；判定逐条列失败指标与实际值 | `test_q3_3_*` + `check_regression` |
| Q4.1 | `auto_apply_supersede_low_risk` 默认 false | `test_q4_1_supersede_low_risk_default_off` |
| Q4.2 | add/enrich/supersede 自动路径均调用同一 gate，**fail-closed**：无 gate 不自动、走 ReviewItem | `merge.py` `_gate_ok`（None→False）+ `test_q4_2_no_gate_fails_closed` / `_gate_gates_auto_apply_per_field` |
| Q4.3/4.4 | 资格=risk low + 非 pending + **画像已批准且批准记录内容哈希与画像匹配** + 达默认阈值（10/0.98/0.01/1.0） | `quality_gate.py` `decide` + `test_q4_3_approval_bound_to_other_profile_denied` / `test_q4_3_*` |
| Q4.5 | high 永不自动；缺失/stale/不达标 → ReviewItem，候选不丢弃；**低风险 supersede 进审核不误标 high** | `test_q4_5_*` / `test_k3_2_low_risk_supersede_review_is_not_mislabeled_high` |
| Q4.6 | 回归 gate 失败阻止 profile 批准，不影响已发布快照 | `check_regression`（纯逻辑，不触快照） |
| Q5.1~5.3 | 纯逻辑全单测；模型层用 replay；门禁全绿；不宣称真实运行；020 复用同一 API | 见门禁 + 本报告顶部边界声明 |

## 边界与未完成项（诚实声明）

- **未产出真实 baseline/画像**：真实 gs-v0.1（2 产品收尾）与 13 产品 baseline/QualityProfile 属 020；
  本 change 只交付确定性工具与合同。
- **online gate 为 fail-closed**：`MergeEngine`/importer 未注入 `quality_gate`+`run_fingerprint` 时，
  auto_apply_* 布尔位**不能**触发自动发布，候选一律进 ReviewItem（design.md:17）。启用自动发布需 020
  产出并批准 QualityProfile 后接线；在此之前系统安全地退化为"全人工审核"，不会静默自动发布。
- **evidence 真实回验**依赖 dataset_root（真实 PDF）：无 dataset_root 时证据判为不可信（0.0 / validator
  self-eval 失败），不再用"是否带证据"的 CI 软件代理冒充回验通过。020 接真实 PDF 后为唯一可信来源。
- `openspec validate 019 --strict` 本机 CLI 未识别该 item；以门禁 + 本报告为准。

## codex review 返工（PR #8，head 已并入）

codex 对 f25e738 提 9 条（6×P1 + 3×P2），逐条对照 spec/design/企业设计核实**全部成立**并修复；
所有修复先补失败用例（复现 codex 的反例）再改实现：

| # | 问题 | 修复 | 关键用例 |
|---|---|---|---|
| 1 | gate=None 可被 policy 布尔位绕过自动发布（fail-open） | `_gate_ok` 无 gate→False，全进 ReviewItem（fail-closed） | `test_q4_2_no_gate_fails_closed` |
| 2 | 批准链不可验证（裸 bool，画像可冒充） | ApprovalRecord 绑 `profile_hash`；gate 校验哈希匹配；approve 消费回归 verdict | `test_q4_3_approval_bound_to_other_profile_denied`、`test_q4_6_failing_regression_blocks_approval` |
| 3 | 缺 pred/keypoints/eval 仍可批准 | `completeness_blockers` 逐项阻断 | `test_q2_1_{zero_pred,pending_keypoints,missing_eval_report}_blocks_approval` |
| 4 | 零观测/未回验证据得满分 | value/evidence 零分母记 0.0（失格）；无 dataset_root 证据不可信 | `test_q4_3_zero_observation_field_is_not_eligible` |
| 5 | staleness 漏 source/template profile | is_stale 补全六维（git_sha 除外） | `test_q3_2_staleness_on_each_of_six_dims` |
| 6 | validator 跳过 evidence、disputed 阈值过松 | 默认强制证据回验 + `max_disputed_rate=0.05` | `test_q1_4_evidence_required_by_default_without_dataset_root_fails` |
| 7 | release_hash 不完整 | 覆盖 evidence/schema/annotator/disputed 全语义字段 | `test_q2_release_hash_covers_all_semantic_fields` |
| 8 | 低风险 supersede 误标 high | 非自动 supersede 保留真实 risk | `test_k3_2_low_risk_supersede_review_is_not_mislabeled_high` |
| 9 | HANDOFF 数字陈旧 + 自相矛盾 | 更新 B21（1060 passed，fail-closed）+ 本报告 | — |

**fail-closed 的存量迁移**：自动发布契约收紧后，原先靠 `auto_apply_*` 布尔位自动发布的 ~60 个存量用例
需注入 gate 才继续自动发布。这是**刻意的契约收紧**（非降级）：测试用 `tests/kbhelpers.green_gate`
（真实达标已批准画像）或 `allow_all_gate`（低风险放行的测试替身，仍拒高风险/不可自动化）显式表达
"自动化已获批"，gate 自身判定逻辑由 `test_quality_gate_019.py` 用真实画像全覆盖。

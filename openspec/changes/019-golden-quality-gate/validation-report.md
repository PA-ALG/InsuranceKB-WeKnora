# 019 验证报告 — Golden 工具、QualityProfile 与自动发布质量闸门

> 本报告只声明**确定性软件验收**，不代表真实数据运行完成。真实 gs-v0.1 与 13 产品 baseline
> 由 020 用同一 assembler/validator/profile/gate API 产出，真实模型调用失败不得靠改夹具掩盖。

## 门禁（交付定义，全绿）

- `uv run ruff check .` → All checks passed
- `uv run mypy src tests` → Success（161 source files，strict）
- `uv run pytest -m "not live and not integration_postgres" -q` → **1074 passed / 5 deselected**
- 019 专项：`test_goldenset_{assemble,validate,baseline,profile}_019.py` + `test_quality_gate_019.py`
  → **112 passed**（11+12+30+24+35，含端到端 bypass 负例），纯 fixture/replay，零真实凭据（Q1.5/Q5.1）
- **codex 三轮 review 返工已并入本 head**：首轮 9 条 + 复审 4 条 + 三轮 4 条（按实施计划
  Task3/4 重建 artifact 合同、批准绑 artifact 内容、回归全指标、prior 不可伪造），见文末各返工小节。

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
| Q2.1 补 | **产物内容寻址 + 齐全性阻断批准**：pred=0 / keypoints 未 ready-done / 产物引用缺失或空 sha256 或 count 不符任一都拒批 | `ProductRunStatus.completeness_blockers` + `ArtifactRef` + `test_q2_1_{zero_pred,pending_keypoints,missing_artifact_ref,empty_sha256_ref,pred_ref_count_must_match}_*` |
| Q2.3 | 批准记录独立、不可改写，只能追加新版本；**内部算内容哈希+指纹绑定 + 强制消费回归 verdict** | `test_q2_3_approval_is_versioned_and_immutable` / `test_q2_3_approval_binds_artifact_sha256` / `test_q4_6_regression_failure_blocks_second_approval` |
| Q3.1 | 每 field_id 输出 support/value acc/tri-state confusion/hallucination/evidence，绑定指纹；**零观测不给满分**（value/evidence 无观测记 0.0，失格） | `profile.py` `build_profile` + `test_q3_1_*` / `test_q4_3_zero_observation_field_is_not_eligible` |
| Q3.2 | 版本化 + golden hash/schema/model/prompt/**template/source profile** 六维任一不匹配即 stale（git_sha 非 staleness 维） | `test_q3_2_staleness_on_each_of_six_dims` / `_git_sha_is_not_a_staleness_dim` |
| Q3.3 | 全局回归阈值 + 字段自动化阈值；判定逐条列失败指标与实际值 | `test_q3_3_*` + `check_regression` |
| Q4.1 | `auto_apply_supersede_low_risk` 默认 false | `test_q4_1_supersede_low_risk_default_off` |
| Q4.2 | add/enrich/supersede 自动路径均调用同一 gate，**fail-closed**：无 gate 不自动、走 ReviewItem | `merge.py` `_gate_ok`（None→False）+ `test_q4_2_no_gate_fails_closed` / `_gate_gates_auto_apply_per_field` |
| Q4.3/4.4 | 资格=risk low + 非 pending + **画像已批准且批准记录内容哈希与画像匹配** + 达默认阈值（10/0.98/0.01/1.0） | `quality_gate.py` `decide` + `test_q4_3_cross_approval_binding_denied` / `test_q4_3_*` |
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
| 2 | 批准链不可验证（裸 bool，画像可冒充） | ApprovalRecord 绑 `profile_hash`；gate 校验哈希匹配；approve 消费回归 verdict | `test_q4_3_cross_approval_binding_denied`、`test_q4_6_regression_failure_blocks_second_approval` |
| 3 | 缺 pred/keypoints/eval 仍可批准 | `completeness_blockers` 逐项阻断 | `test_q2_1_{zero_pred,pending_keypoints,missing_eval_report}_blocks_approval` |
| 4 | 零观测/未回验证据得满分 | value/evidence 零分母记 0.0（失格）；无 dataset_root 证据不可信 | `test_q4_3_zero_observation_field_is_not_eligible` |
| 5 | staleness 漏 source/template profile | is_stale 补全六维（git_sha 除外） | `test_q3_2_staleness_on_each_of_six_dims` |
| 6 | validator 跳过 evidence、disputed 阈值过松 | 默认强制证据回验 + `max_disputed_rate=0.05` | `test_q1_4_evidence_required_by_default_without_dataset_root_fails` |
| 7 | release_hash 不完整 | 见复审二轮：改 canonical 全量序列化 | `test_q2_release_hash_covers_full_semantic_model` |
| 8 | 低风险 supersede 误标 high | 非自动 supersede 保留真实 risk | `test_k3_2_low_risk_supersede_review_is_not_mislabeled_high` |
| 9 | HANDOFF 数字陈旧 + 自相矛盾 | 更新 B21（fail-closed）+ 本报告 | — |

**fail-closed 的存量迁移**：自动发布契约收紧后，原先靠 `auto_apply_*` 布尔位自动发布的 ~60 个存量用例
需注入 gate 才继续自动发布。这是**刻意的契约收紧**（非降级）：测试用 `tests/kbhelpers.green_gate`
（真实达标已批准画像）或 `allow_all_gate`（低风险放行的测试替身，仍拒高风险/不可自动化）显式表达
"自动化已获批"，gate 自身判定逻辑由 `test_quality_gate_019.py` 用真实画像全覆盖。

## codex 复审二轮返工（head 已并入）

复审确认首轮 6 项实质关闭，但 #2/#3/#7 只部分关闭（可稳定复现绕过）。核心批评正确：**首轮是"按条目
补 if"，未从"非法状态不可构造"重设计接口**。本轮按此重设计，并补对抗性（bypass）负例：

| 复审# | 可复现的绕过 | 重设计（让非法状态无法构造） | bypass 负例 |
|---|---|---|---|
| 1 | approval 可错绑到别的 baseline/profile（裸 profile_hash + gate 只比 hash） | `approve_baseline(artifact, profile)` **内部**算 hash 并强制 `profile.fingerprint==artifact.fingerprint`；gate 再校验 `approval.fingerprint==profile.fingerprint` | `test_q4_3_profile_must_derive_from_artifact`、`test_q4_3_cross_approval_binding_denied` |
| 2 | 省略 `regression` 参数即可跳过回归 | 该 baseline 已有批准版本时**必须**提供 `prior_profile`，回归由函数**内部**跑，不接受调用方跳过 | `test_q4_6_prior_approval_requires_prior_profile`、`_failing_regression_blocks_approval` |
| 3 | 计数+任意路径字符串即可批准（产物无法证明存在） | `ArtifactRef(path+sha256+count)` 取代裸路径；run_manifest/pred/eval 必须齐备且 `pred_ref.count==pred_count` | `test_q2_1_{missing_artifact_ref,empty_sha256_ref,pred_ref_count_must_match}_*` |
| 7 | 手工拼字段，漏 `doc`/`source_revision`/lineage | 改为对完整模型 `model_dump` 做 **canonical JSON**（sort_keys，JSON 转义避免分隔符碰撞），除易变 `created_at` 外全纳入；新字段自动覆盖 | `test_q2_release_hash_covers_full_semantic_model`、`_ignores_created_at` |

## codex 三轮复审返工（按实施计划合同重建，head 已并入）

三轮复审指出前两轮"欠着实施计划实现"——按 codex 的点补，而非按权威合同建。核对
`docs/superpowers/plans/2026-07-13-golden-quality-gate.md` 后确认 4 条全部成立，按计划 Task3/4 重建：

| 三轮# | 可复现的绕过 | 按计划重建 | bypass 负例（已 live 复跑通过） |
|---|---|---|---|
| 1 | `prior_profile` 可伪造 / 换 `baseline_id` 跳过回归 | 该 baseline 已有批准时，`prior_profile` 必须正是最近批准所绑定的画像（`baseline_approval_sha256==latest.sha256()`），回归内部计算 | `test_q4_6_forged_prior_profile_rejected`、`_baseline_id_swap_cannot_smuggle_regression` |
| 2 | approval 只绑运行配置、不绑 artifact 输出内容 | `BaselineArtifact.sha256()` canonical 内容哈希；`ApprovalRecord.artifact_sha256`；`QualityProfile.{artifact_sha256,baseline_approval_sha256}`；gate 按内容哈希绑定 | `test_q2_3_different_artifact_yields_different_approval`、`test_q4_3_cross_approval_binding_denied` |
| 3 | dead-letter/judge/judgement/keypoints 无内容引用即可批准 | `BaselineProductArtifacts` 每类产物均带 sha256 + 计数，`consistency_errors()` 校验齐全 + 计数自洽 + keypoints 现场 | `test_q2_1_missing_each_required_sha_blocks_approval`（参数化 6 类）+ 4 个计数/keypoints 一致性负例 |
| 4 | 回归只查 value/hallucination，evidence/F1/unresolved 漏检 | `compare_baselines` 覆盖全局 micro/macro F1 + hallucination + evidence + unresolved + 字段阈值，结构化 `{metric,baseline,candidate,allowed}` | `test_q4_6_regression_flags_{evidence_drop,unresolved_increase}`、`_flags_accuracy_drop`（断言结构化字段） |

**与实施计划的对齐**：模型/函数按计划 Task3/4 合同实现（`BaselineProductArtifacts` 全字段、
`compare_baselines` 全指标结构化、`QualityProfile.{artifact,approval}_sha256`、`approve().artifact_sha256
==artifact.sha256()`）。文件上仍并置于 `baseline.py`/`profile.py`（计划建议拆 artifacts/quality/regression.py），
功能等价；如需按文件切分可再拆，不影响合同。

### 已知边界（诚实声明，非"已全部闭环"的空话）

- **approve_baseline 是纯函数**：`prior` 批准列表由调用方（020 的批准存储）如实提供；版本单调/唯一性
  与"批准确由 approve_baseline 从合法 artifact 铸造"由存储层保证。本层保证的是**给定 (artifact, profile,
  prior, prior_profile) 时的全部绑定不变量**：画像须派生自该 artifact、prior_profile 须是最近批准的画像、
  回归退化即拒、产物不齐/不一致即拒。gate 保证 profile↔approval↔artifact 三者内容哈希自洽。
- **产物引用校验是结构性的**：本确定性层校验 sha256 为合法 64 位 hex + 计数自洽；产物文件真实存在、
  字节哈希与 sha256 相符由 020 运行时回验，非本层职责。
- **release_hash 排除 `created_at`**：标注时间戳属溯源、非内容语义（同内容重标不应改变 release 身份）；
  刻意排除并有 `_ignores_created_at` 用例锁定，非遗漏。
- **evidence 真实回验**依赖 dataset_root（真实 PDF）：无 dataset_root 判不可信（0.0）。

# 019 验证报告 — Golden 工具、QualityProfile 与自动发布质量闸门

> 本报告只声明**确定性软件验收**，不代表真实数据运行完成。真实 gs-v0.1 与 13 产品 baseline
> 由 020 用同一 assembler/validator/profile/gate API 产出，真实模型调用失败不得靠改夹具掩盖。

## 门禁（交付定义，全绿）

- `uv run ruff check .` → All checks passed
- `uv run mypy src tests` → Success（161 source files，strict）
- `uv run pytest -m "not live and not integration_postgres" -q` → **1130 passed / 5 deselected**
- 019 专项：`test_goldenset_{assemble,validate,baseline,profile}_019.py` + `test_quality_gate_019.py`
  → **167 passed**（11+12+54+48+42，含 build_profile→approve→gate 端到端 bypass 负例），纯 fixture/replay，
  零真实凭据（Q1.5/Q5.1）
- **codex 五轮 review 返工已并入本 head**：首轮 9 条 + 复审 4 条 + 三轮 4 条 + 四轮 4 条 + 五轮 4 条（按实施
  计划 Task3/4/5 重建 artifact 合同、批准绑 artifact 内容、回归全指标、prior 不可伪造；四轮补批准提交
  **画像内容**哈希、gate 校指纹、换 id 不能跳回归、build_profile 复用 evaluate；五轮补**领域类型合法域**
  Rate/NonNegativeInt、每字段 pred-only 幻觉聚合、gate 校 profile 版本 + 收回 pending_judge、lineage_reset
  须真新 lineage+reason），见文末各返工小节。
- **提交前独立红队自测（R6）已并入本 head**：五轮修完后**不等 codex**、先派 4 支对抗性红队（领域类型
  完备性 / 字段聚合口径 / gate·merge 自动路径 / 批准·lineage_reset）各自写脚本实跑攻击，挖出**1 个真绕过**
  （reset 只查 baseline_id、不查 golden 集，同评测基准换 id 可洗白降级）+ **1 个我五轮自己引入的纵深防御
  倒退**（删了 merge 层 pending 预检查），均已 TDD 复现→修→复跑关闭，见文末「R6」小节。

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
| Q3.1 | 每 field_id 输出 support/value acc/tri-state confusion/hallucination/evidence，绑定指纹；**零观测不给满分**（value 无观测记 0.0；evidence 未回验记 None，均失格） | `profile.py` `build_profile` + `test_q3_1_*` / `test_q4_3_{zero_observation_field,unmeasured_evidence_field}_is_not_eligible` |
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
- **evidence 真实回验**依赖 dataset_root（真实 PDF）：无 dataset_root 时证据判为**未回验（None）**，对自动资格
  fail-closed（不达标），但不当作"测得 0%"参与回归（区分未测量与测得 0，避免回归误报/漏报，四轮红队 #7）；
  不再用"是否带证据"的 CI 软件代理冒充回验通过。020 接真实 PDF 后为唯一可信来源。
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

## codex 四轮复审返工 + 自测闭环（head 已并入）

四轮复审沿调用链复现 4 条 P1，逐条**先在当前 head 跑通复现脚本（"修复前"证据）、按不变量重建、再复跑
证明关闭**——不是"改到测试变绿"，而是让绕过无法构造。四条复现值与 codex 报告一致：

| 四轮# | 修复前复现（live） | 按不变量重建 | 修复后复现（live）| bypass 负例 |
|---|---|---|---|---|
| 1 | `forged_prior_profile_approved=True`：伪 prior 复制公开 `approval.sha256()` 即冒充生产基线 | `ApprovalRecord.profile_content_sha256` **提交画像内容哈希**；`content_hash()` 排除 approval 回指故批准前后稳定；prior 校 `content_hash()==latest.profile_content_sha256` | `=False`（内容哈希不符） | `test_q4_6_forged_prior_copying_public_approval_hash_rejected` |
| 2 | `old_approval_authorizes_new_model_profile=True`：旧 model 批准授权新 model 满分画像 | gate 增校 `approval.profile_content_sha256==profile.content_hash()` 且 `approval.fingerprint==profile.fingerprint` | `=False` | `test_q4_2_old_approval_cannot_authorize_new_model_profile`、`test_q4_3_forged_profile_content_denied_at_gate` |
| 3 | `rotated_baseline_id_skips_regression=True (v1)`：换 `baseline_id` 把退化候选偷渡成新 lineage v1 | 只要 `prior` 非空即须与**当前生产基线**（跨 id 的最近批准）回归；`allow_lineage_reset=True`（人工可审计）才是唯一逃生 | `=False`（须提供 prior_profile 并过回归） | `test_q4_6_rotated_baseline_id_still_regresses_against_production`、`_requires_prior_profile`、`_lineage_reset_is_explicit_and_auditable` |
| 4 | `pred-only micro_f1: evaluate=0.667 / profile=1.0`；`absent-only: 1.0 / 0.0` | `build_profile` 全局 micro/macro F1+幻觉+证据与每字段 P/R/F1 **全部取自 `eval.evaluate`**（含 pred-only FP、空分母口径）；删除重复实现的 `_f1` | `0.667/0.667`、`1.0/1.0` 完全一致 | `test_q3_1_global_micro_f1_matches_evaluator_{with_pred_only_fields,absent_only}`、`_global_metrics_match_evaluator_mixed`、`_per_field_prf_match_evaluator` |

**自测闭环（回应"别再来回，提交前把问题自测修复"）**：除上表逐条复现→关闭外，提交前另跑两组独立对抗性红队
（构造非法状态试破批准链 / 试造 build_profile↔evaluate 语义漂移）。红队**发现并当场修复了 codex 尚未报告的第
5 个洞**（见下），这正是"提交前自测"的价值——不是等下一轮 review 再挨批。

两组红队共报 6 个问题，**已修 4、按理据文档化 2**（均先 live 复现再处置）：

- **[红队 #5，已修] 非有限指标（NaN/±inf）绕过所有数值门槛**：`FieldMetrics`/`GlobalMetrics` 原样接受 NaN；
  `value_accuracy < 0.98`、`base - NaN > 0` 等比较对 NaN 恒 False → `field_verdict` 判"达标"、`compare_baselines`
  判"无回归"，NaN 候选可被批准并进 auto_eligible；`content_hash` 仍确定（JSON 序列化 NaN）故绑定检查全过。
  **修复**：`FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]` 用于所有指标/阈值浮点，**构造期**即拒
  NaN/±inf（让非法状态无法构造）。负例 `test_q4_3_{field,global}_metrics_reject_non_finite*`。
- **[红队 #6，已修] 幻觉率可被伪造字段稀释**：`eval.evaluate` 里"覆盖面之外的 present 预测"只计入 micro FP 与
  幻觉率**分母**、不计分子，伪造大量出界字段反而把 hallucination_rate 拉低，架空 Q4.6 幻觉护栏。**修复**：
  pred-only present 同时计入幻觉分子（`eval.py`）。负例 `test_g4_pred_only_present_counts_as_hallucination`、
  `test_q4_6_fabricated_fields_raise_global_hallucination_and_flag_regression`。
- **[红队 #7，已修] 证据"未测量"与"测得 0%"混同 → 回归误报/漏报**：原 evidence 无 dataset_root 记 0.0，导致
  已测基线 vs 未测候选被误判回归、未测基线掩盖候选真实退化。**修复**：evidence 改 `float | None`，未测记 None、
  回归两侧任一 None 即跳过该维（候选证据绝对达标仍由 gate `field_verdict` fail-closed 兜底）。负例
  `test_q4_6_unmeasured_evidence_not_falsely_flagged`、`test_q4_3_unmeasured_evidence_field_is_not_eligible`。
- **[红队 #8，已修] 每字段证据口径与 evaluator 漂移**：per-field 用 per-record all-or-nothing，global 用 per-quote。
  **修复**：per-field 改用同一 `_evidence_quote_counts` per-quote 原语。负例 `test_q3_1_per_field_evidence_is_per_quote`。
- **[红队 #9，已文档化] 零观测字段 `f1=1.0`（evaluator 空分母约定）与 `value_accuracy=0.0` 并存**：属 `eval` 既有
  三态分类约定，且字段集由**金标**决定、候选无法增删金标字段来刷 macro，故不可对抗性利用；作为约定记录，不改
  evaluator 口径。
- **[红队 #10，已文档化] `support` 含 absent 记录**：Q3.1 定义 support=该字段全部金标观测数（含 absent），是既有
  契约；"present 值观测下限"属 020 可调门槛（enterprise runtime），非本确定性层的正确性 bug。加固用例
  `test_q4_6_per_field_drop_caught_even_when_global_faked_perfect`（伪造满分 global 仍被 per-field 回归拦）。

### 四轮已知边界（诚实声明，不treat为已闭环）

- **在线自动发布路径永不铸造批准**：`approve_baseline`/`allow_lineage_reset` 仅存在于 goldenset 离线层；
  `knowledge`（merge/importer）只**消费** `QualityGate`+`ApprovalRecord`，运行时无法触达 lineage-reset。
- **approve_baseline 信任传入画像的指标数值**：本确定性层绑定"画像↔artifact 身份 + 回归 + 阈值"，但不
  从 artifact 的 pred 原始内容**重算**指标以证其真实——真实性由 020 用 `build_profile(该 artifact 的
  golden/pred)` 产出画像来保证，本层用 `artifact_sha256`/`profile_content_sha256` 把这份画像钉死到该 artifact。
- **ApprovalRecord 可被直接构造**：伪造一条批准记录属存储/授权层（020）完整性范畴；即便如此，gate 仍要求
  它指向一份**真实达标**（field_verdict 通过）且内容哈希自洽的画像，伪造批准无法让不达标候选过闸。
- **per-field evidence 为 profile 专属**（evaluate 无按字段证据）：与全局证据共用同一 `quote_in_page`+PDF
  回验原语，仅聚合粒度不同（按记录 vs 按引文）；真实回验仍依赖 dataset_root。

## 提交前独立红队自测（R6，非 codex 触发，head 已并入）

五轮修完后**不再等 codex**，先自派 4 支对抗性红队各写脚本 live 攻击这轮新面（"提交前完善自测"的落地）。
结果：**2 支无绕过**（领域类型、字段聚合，均逐脚本证明守住），**2 支各挖出真问题**——含 1 个端到端真绕过
与 1 个我五轮自己引入的纵深防御倒退。全部 TDD 复现→修→复跑关闭。

| R6# | 严重度 | 修复前复现（live） | 按不变量重建 | bypass 负例 |
|---|---|---|---|---|
| D-弱点1 | 中（真绕过，端到端） | reset 的"真新 lineage"守卫只查 `baseline_id`；同一 golden 集（`fingerprint` 完全相同）换新 id + reset → 退化画像（value 1.0→0.98）跳过零容差回归，`QualityGate.decide→eligible=True` | reset 须 (a) prior 非空 (b) baseline_id 不在 prior (c) **`golden_release_hash` 与所有 prior 不同**（golden 集才是评测基准，同集必回归）(d) 非空 reason | `test_q4_6_lineage_reset_same_golden_set_rejected`、端到端 `_reset_cannot_launder_same_goldenset_downgrade_end_to_end`（常规回归 + reset 逃生门双双拒） |
| C-2b | 中（五轮自引入的倒退） | 五轮删掉 merge 三路径 `not pending_judge` 预检查后，pending 安全 100% 押注入 gate；注入不 honor pending 的 gate → pending 候选 `status=published` | `_gate_ok` **恢复独立 pending 短路**做纵深防御（gate 仍权威，merge 保留 fail-closed 兜底） | `test_q4_2_pending_short_circuits_even_if_gate_ignores_it`（端到端 merge） |
| C-2a | 低（健壮性） | `_gate_ok` 无条件传 `pending_judge=` 且无 try/except，注入旧签名 gate → `TypeError` 崩整批（fail-loud，非文档自称 fail-closed） | `_gate_ok` 对 gate 异常一律 fail-closed（走 ReviewItem），不崩批 | `test_q4_2_gate_error_fails_closed_not_crash`（端到端 merge，旧签名 gate） |
| D-弱点2 | 低-中（审计卫生） | `baseline_id` 精确串匹配，`'prod-A '`/`'PROD-A'` 被当新 lineage（安全面已被 D-弱点1 覆盖，但审计歧义） | `Identifier` 约束：`baseline_id` 构造期拒空/纯空白/带首尾空白 | `test_q2_1_baseline_id_rejects_surrounding_whitespace`（参数化 6 类） |
| D-弱点3 | 低（审计卫生） | `prior=[]` 传 `allow_lineage_reset=True` 静默吞掉意图、reason 落 None | `allow_lineage_reset and not prior` 直接报错（调用方误用） | `test_q4_6_lineage_reset_without_prior_is_rejected` |

### R6 只文档、不改（附理由，非"已全闭环"的空话）

- **D-弱点4（latest 选取被 `approved_at`+id 字典序操纵）**：依赖弱点1 或伪造 prior 先注入弱基线；弱点1 已修
  堵死注入入口，伪造 prior 属 020 存储完整性边界（本层 `prior` 视为可信）。故不改序，记为放大器边界。
- **B-B（首基线批准不查全局指标）**：`approve_baseline` 仅 `prior` 非空才跑回归，首基线只过结构性 blocker，
  可批准全局幻觉高的画像；但在线 `QualityGate.decide` 是**逐字段** fail-closed，脏字段仍被 `field_verdict`
  绝对阈值拦下，好字段本就应可发——全局指标只用于相对回归。加"全局绝对下限"可能误杀难产品的合法首基线，
  故不加、记为分层设计边界。
- **A-1（`ApprovalRecord.version:int` 可负）**：仅 `prior` 排序 tiebreaker，非指标/计数阈值，且 `prior` 可信；
  非数值假通过，记卫生项。**A-2（bool→int 强转）**：0/1 在域内、无害。**A-3（020 加载画像/artifact 须
  `model_validate` 而非 `model_construct`）**：属 020 运行时边界——领域类型仅在**验证式构造**时 load-bearing，
  020 从磁盘反序列化必须走 `model_validate`，否则 Rate/NonNegativeInt/Identifier 约束不生效。

## codex 五轮复审返工（head 已并入）

四轮关闭后，五轮复审再提 4 条（2×P1 + 2×P2）。照旧**先在四轮 head 跑通 `repro_r6.py` 留"修复前"证据、
确认 4 条全部成立（非误报），再按不变量重建、复跑关闭**。也接受 codex 对测试的批评（偏单点、缺组合不变量），
本轮起补 `build_profile→approve→gate` **端到端**负例，并把"合法数值域"作为一类系统性领域约束而非逐个补 if。

| 五轮# | 修复前复现（live, `repro_r6.py`） | 按不变量重建 | 修复后复现 | bypass 负例 |
|---|---|---|---|---|
| 1 (P1) | `field[f1].hallucination_rate=0.0`（全局 0.5）：10 正确+10 伪造同字段，`build_profile` 字段聚合只遍历 golden keys、`per_field` 不记 pred-only，字段 gate 对本字段伪造**全盲** | 字段聚合并入该 field_id 的 pred-only present 键；`eval.py` 对**已知 field_id** 的 pred-only present 记 `per_field.fp`；`support` 仍只数金标观测 | `=0.5`（`f1=0.667`，field_verdict 拒） | `test_q3_1_pred_only_fabrication_shows_in_field_metrics`、端到端 `test_q4_2_fabricating_field_denied_end_to_end` |
| 2 (P1) | `FieldMetrics(value_accuracy=2.0)` 构造成功且 `≥0.98` 恒过阈值；负 `dead_letter_count` 与正 judge 相消，`approval_blockers()==[]` 掩盖真实未解决 | `Rate=Field(ge=0,le=1,allow_inf_nan=False)` 用于全部比率指标/阈值、`NonNegativeInt=Field(ge=0)` 用于 support 与全部计数——**构造期**即拒；`approval_blockers()` **逐项**查 unresolved judge/dead-letter（不再用合计 truthiness） | `ValidationError`（构造期拒） | `test_q4_3_field_metrics_reject_out_of_range_rate`（参数化 2.0/-0.1/1.5）、`test_q2_1_negative_counts_rejected_at_construction`（参数化 7 类计数）、`test_q2_2_negative_count_cannot_mask_unresolved`、`_unresolved_judge_alone_blocks_approval` |
| 3 (P2) | 计划 Task5 要求的 profile-version mismatch / pending_judge 未进 gate：`profile_version="999"` 仍 eligible；merge 在 gate 外用 `not prop.pending_judge` 预检查 | gate 增 `SUPPORTED_PROFILE_VERSION` 常量，`decide` 拒不支持版本（内容哈希只证"这份 v999 被批准"、不证代码理解该格式）；`decide` 增 `pending_judge` 形参并拒，merge 三条自动路径把 pending 判定**收回 gate** | `999` 被拒；pending 被拒 | `test_q4_5_unsupported_profile_version_denied`、`test_q4_2_pending_judge_denied_by_gate` |
| 4 (P2) | `allow_lineage_reset` 是通用"关回归"开关：同 `baseline_id` + reset 即跳过回归给同 lineage 降级 | reset 须 (a) `artifact.baseline_id` 不在任何 prior 中（**确是新 lineage**）、(b) 提供**非空 `lineage_reset_reason`**（记入 `ApprovalRecord`）；同 id+reset 直接拒 | 同 id reset 被拒 | `test_q4_6_lineage_reset_same_baseline_id_rejected`、`_requires_reason`、`_is_explicit_and_auditable` |

### 五轮已知边界（诚实声明）

- **`allow_lineage_reset` 是结构约束 + 审计信号、非授权本身**：五轮明确**不再声称**该 bool 等于人工授权；
  它只保证"确开新 lineage 且留了非空理由并记入 ApprovalRecord"，真正不可伪造的授权输入由 020 提供。
- **领域类型在构造期拒非法值**：`Rate`/`NonNegativeInt` 让越界比率、负计数、NaN/±inf **无法进入**任何画像/
  artifact；配合 `approval_blockers()` 逐项检查，负数不能与正数相消掩盖真实未解决（Q2.2 fail-closed）。
- **端到端负例覆盖字段级伪造**：`test_q4_2_fabricating_field_denied_end_to_end` 走完整
  `build_profile→approve_baseline→with_approval→gate.decide` 链——证据可回验、值正确，仅因字段幻觉被拒，
  证明字段级画像的伪造能一路传导到 gate 拒绝，而非只在 `compare_baselines` 单点断言。

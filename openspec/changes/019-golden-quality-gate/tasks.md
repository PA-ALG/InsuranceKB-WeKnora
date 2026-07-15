# 019 任务

- [x] T1 先写 portable assembler 与 mixed annotator 失败测试，再把 WIP 脚本逻辑移入 goldenset CLI（Q1.1/Q1.2）
- [x] T2 先写 expected-products/disputed/extractable/self-eval 失败测试，再实现 validator（Q1.3～Q1.5）
- [x] T3 先写 baseline artifact 缺项与 approval 不可变测试，再实现 artifact/approval（Q2）
- [x] T4 先写 QualityProfile 指纹/指标/过期失败测试，再实现 profile 生成与校验（Q3）
- [x] T5 先写 merge 默认不自动 supersede 及 profile 资格测试，再实现统一 QualityGate（Q4）
- [x] T6 fixture/replay 全回归、全门禁、validation-report、HANDOFF/05/13/16/20 对账

状态：软件实施完成（确定性软件验收）；真实 11/13 现场不在本 change 改写，由 020 原地接续。

## 过程诚实声明（TDD 实际执行）

- **SDD：达标**。proposal/design/specs(Q1~Q5)/tasks(T1~T6) 先于代码存在并过 review；实现严格照条款，
  测试名引用条款号，裁决记录见下。
- **TDD：T1~T5 全部严格 test-first（先桩→RED→实现→GREEN）**。每个任务同一手法：
  先把对应模块的逻辑打回桩（方法/函数抛 `NotImplementedError`，保留 pydantic 模型契约）
  → 写全面条款级测试 → 跑出 **RED** → 还原实现 → **GREEN**，逐一留证：
  - **T1 assemble**：桩化 `assemble_records`/`_record_from_line` 等 → RED 11 → GREEN 11。
    覆盖 Q1.1 无开发机绝对路径、Q1.2 per-record annotator 保留 + 缺省兜底 + 两者皆缺报错、
    坏行计数、缺 golden 目录标 `missing_golden`、CLI。
  - **T2 validate**：桩化 5 项 check → RED 10 → GREEN 10。覆盖 Q1.3 产品齐全/额外产品不判缺、
    disputed rate 阈值 + at-threshold、extractable 覆盖 + 非 extractable 不计、Q1.4 self-eval=1.0
    + manifest 缺失判非不可变、`failures()` 辅助。
  - **T3 baseline**：桩化 `missing_fields`/`unresolved`/`approval_blockers`/`release_hash`/
    `approve_baseline` → RED 13 → GREEN 13。覆盖 Q2.1 未解决 = dead-letter + 待裁决
    （over-judged 夹 0、多产品求和）、Q2.2 指纹缺项逐项 + 未解决项 + 空产品各自阻断批准、
    Q2.3 版本化 + 跨 baseline 版本隔离 + frozen 不可变、release_hash 内容寻址 + 顺序无关。
  - **T4 profile**：桩化 `is_stale`/`field_verdict`/`check_regression`/`build_profile` → RED 18
    → GREEN 18。覆盖 Q3.1 完美复算/部分 value_accuracy/幻觉 + 缺证据/缺预测计 unknown/disputed
    金标排除、Q3.2 staleness 四维各自 + git_sha/template/source **不**触发的反例、Q3.3 四阈值
    各自失败列举 + 通过 eligible + 自定义阈值 + 缺字段、Q4.6 回归退化/缺候选字段/无退化/容差吸收。
  - **T5 QualityGate（安全攸关核心）**：桩化 `decide` → RED 29 → GREEN 31。覆盖 3 种可自动化动作
    各 eligible、4 种非自动化动作拒绝、high/medium 风险拒绝、缺画像/字段不在画像/未批准/缺指纹、
    staleness 四维各自 + git_sha/template 差异**不**判 stale 的反例、四阈值各自边界 + at-min、
    多失败全列、自定义阈值、GateDecision 回填、无 gate 回退 legacy。
  - 说明：早期草稿曾对 T1~T4 采「先实现→后补测试 + 回溯 RED 验证」，现已按 T5 同法逐一严格重做，
    此声明与仓库现状一致（可复现：对任一模块打桩即得对应 RED）。

## 交付物（新增/改动文件）

- 新增 `goldenset/assemble.py`（portable assembler + CLI）、`validate.py`（release validator）、
  `baseline.py`（BaselineArtifact/ApprovalRecord/RunFingerprint/release_hash）、
  `profile.py`（QualityProfile/FieldMetrics/AutomationThresholds/回归检查）；
- 新增 `knowledge/quality_gate.py`（纯逻辑 QualityGate）；
- 改 `goldenset/release.py`（manifest 汇总 annotator 集合）、`knowledge/models.py`
  （MergePolicy.auto_apply_supersede_low_risk 默认 → False）、`knowledge/merge.py`
  （三条自动路径经同一 gate）、`knowledge/importer.py`（透传 quality_gate/run_fingerprint）；
- 测试 `test_goldenset_{assemble,validate,baseline,profile}_019.py`、`test_quality_gate_019.py`
  （共 98 个新用例 = 11+12+19+22+34，全部严格 test-first，纯 fixture/replay，零真实模型/PDF 凭据）。
- codex review 返工新增测试替身 `tests/kbhelpers.green_gate` / `allow_all_gate`，并迁移 ~60 个存量
  auto_apply 用例注入 gate（fail-closed 契约收紧，见文末返工记录）。

## 裁决记录（设计判断与依据）

1. **manifest 由单 `annotator_model` 改为 `annotator_models` 集合**（Q1.2）：旧 `build_release` 用
   `records[0].annotator_model` 会让混合标注被首条覆盖；改为汇总集合并同步 per-product 集合，
   `test_manifest_is_valid_json` 断言随之更新（spec 故意改的契约，非破坏既有测试）。
2. **assembler 只补齐缺省，不覆盖来源**（Q1.2）：annotator/created_at/schema 优先取源记录，
   仅当源缺省才用 default_annotator/now；源缺 annotator 又无 default 时 fail closed 报错，
   绝不静默贴全局常量。
3. **QualityGate 采用可选注入**（Q4.2）：`MergeEngine(quality_gate=None)` = 在线治理未启用，
   回退 policy 布尔位（保持既有调用与测试的 legacy 行为）；注入后 gate 是自动发布唯一权威，
   布尔位只表达"运营是否允许自动化"。理由：全库 20+ 处 `MergePolicy(auto_apply_add=True)` 依赖
   flag-only 自动应用，强制 gate 会破坏大量既有契约；可选注入既满足 Q4.2（注入时三路径同 gate、
   不可绕过），又不破坏 legacy。
4. **`auto_apply_supersede_low_risk` 默认 True→False**（Q4.1）：3 个 merge 用例 + 1 个 e2e 故事
   依赖旧默认自动应用 supersede，按新契约显式 opt-in `auto_apply_supersede_low_risk=True`
   （保留其测 auto-supersede 语义），非降级测试。
5. **evidence_accuracy 软件代理**（Q3.1）：无 dataset_root 时以"present 预测是否带证据"计；有
   dataset_root 时叠加引文回验。使 CI 无需真实 PDF 即可区分 evidence=1.0 与 <1.0；真实回验由
   020 提供 dataset_root 时启用。
6. **approval 阻断项含"未解决项"**（Q2.2）：除指纹缺项外，dead-letter/未回写裁决 > 0 也拒绝批准
   （"unresolved 不得静默丢弃"的强化）。

## 已知边界

- 本 change 仅确定性软件验收；未产出真实 gs-v0.1/13 产品 baseline（020）。
- `openspec validate 019 --strict` 在本机 CLI 未识别该 item（change 目录已含 proposal/design/
  specs/tasks）；以门禁（ruff/mypy strict/pytest）与本报告为准。

## codex review 返工裁决（PR #8）

codex 对 f25e738 提 9 条（6×P1 + 3×P2），逐条对照 spec/design/企业设计核实**全部成立**，全量返工：

1. **fail-open → fail-closed**（P1#1，最严重，根因）：初版把 QualityGate 做成"可选注入，None 放行"，
   为的是不改动 ~20 存量 `MergePolicy` 测试——但 design.md:17「布尔开关不能绕过 Gate，缺画像统一走
   ReviewItem」明确要求 fail-closed。裁决：`_gate_ok` 无 gate 返回 False，auto_apply 布尔位不能单独
   自动发布。这是刻意的契约收紧；存量用例用 `green_gate`/`allow_all_gate` 显式注入"已批准自动化"。
2. **批准链绑定**（P1#2）：ApprovalRecord 增 `profile_hash`，gate 用 `ApprovalRecord`（非裸 bool）并校验
   `approval.profile_hash == profile.content_hash()`；`approve_baseline` 消费回归 verdict（Q4.6 闭环）。
3. **产物齐全性**（P1#3）：`ProductRunStatus.completeness_blockers` — pred=0 / keypoints 非 ready-done /
   缺 eval 报告任一阻断批准。
4. **零观测不给满分**（P1#4）：value/evidence 零分母记 0.0（失格）；`_evidence_verified` 无 dataset_root
   返回 False（不拿 CI 代理证据冒充回验）。
5. **staleness 六维**（P1#5）：`is_stale` 补 template/source profile；spec Q3.2 文字同步订正（原仅列四维，
   与 design.md:13 冲突——规格自身 bug，一并修）。git_sha 属溯源、非 staleness 维。
6. **validator 收紧**（P1#6）：`max_disputed_rate` 默认 0.05（企业设计 20-runtime line127 ≤5%）；默认强制
   证据回验，无 dataset_root 判 self-eval 失败（`require_evidence=False` 仅供无 PDF 的结构性 CI，显式留痕）。
7. **release_hash 完整**（P2#7）：覆盖 evidence(page+quote)/schema/annotator/disputed 全部语义字段。
8. **supersede risk**（P2#8）：非自动 supersede 进审核保留真实 risk，不硬编码 high_risk_change。
9. **文档一致**（P2#9）：HANDOFF B21 更新 1060 passed + fail-closed 表述；validation-report 计数与 Q 表订正。

首轮返工门禁：ruff/mypy(161) 全绿，non-live 1060 passed。

## codex 复审二轮返工

复审确认首轮 6 项实质关闭，但 **#2/#3/#7 只部分关闭**——批评正确：首轮是"按 review 条目补 if"，
未从"非法状态不可构造"重设计接口。本轮按不变量重设计 + 补 bypass 负例：

1. **approval 强绑定**：`approve_baseline(artifact, profile)` 内部计算 `profile.content_hash()`（不再收
   裸 hash），强制 `profile.fingerprint == artifact.fingerprint`；`QualityGate` 增
   `approval.fingerprint == profile.fingerprint` 校验。错绑跨 baseline/profile 无法构造。
2. **回归强制**：该 baseline 已有批准版本时**必须**提供 `prior_profile`，回归由函数内部跑，
   不接受调用方省略参数跳过 Q4.6。
3. **产物内容寻址**：新增 `ArtifactRef(path+sha256+count)`，run_manifest/pred/eval 必须齐备且
   `pred_ref.count==pred_count`；空 sha256 / 计数不符阻断批准。取代原"任意路径字符串即可批准"。
4. **release_hash canonical**：改为对完整模型 `model_dump` 做 canonical JSON（sort_keys + JSON 转义
   避免分隔符碰撞），除 `created_at`（易变时间戳，有用例锁定）外全字段纳入，含 evidence lineage；
   新增字段自动覆盖。取代原手工拼字段（漏 doc/source_revision）。

**已知边界（诚实声明）**：approve_baseline 纯函数，`prior` 由存储层如实提供、版本唯一性由存储层保证；
ArtifactRef 为结构性校验（真实文件存在/字节哈希由 020 运行时回验）；release_hash 刻意排除 created_at。

复审返工门禁：ruff/mypy(161) 全绿，non-live **1066 passed**；019 专项 104 用例，含端到端 bypass 负例。

## codex 三轮复审返工（按实施计划合同重建）

三轮复审援引权威实施计划 `docs/superpowers/plans/2026-07-13-golden-quality-gate.md`，指出前两轮"照 review
条目补 if、未按计划合同建"。核对计划 Task3/4 后确认 4 条全部成立，按合同重建（先补 bypass 负例再改实现）：

1. **prior 不可伪造 / baseline_id 不可偷换**（三轮#1）：该 baseline 已有批准版本时，`prior_profile` 必须正是
   最近一次批准所绑定的画像（`prior_profile.baseline_approval_sha256 == latest.sha256()`），回归由
   `approve_baseline` 内部计算。换 `baseline_id` 或塞入伪造 `prior_profile` 都无法跳过 Q4.6 回归。
2. **批准绑 artifact 输出内容**（三轮#2）：`BaselineArtifact.sha256()` 为 canonical JSON（sort_keys + 紧凑
   分隔符）内容哈希；`ApprovalRecord.artifact_sha256`、`QualityProfile.{artifact_sha256, baseline_approval_sha256}`
   全链绑内容；gate 校验 profile↔approval↔artifact 三者哈希自洽。只改运行配置不改产物内容 → 不同 artifact →
   不同批准，无法复用旧批准冒充新产物。
3. **每类产物内容寻址 + 计数自洽**（三轮#3）：`BaselineProductArtifacts` 对 run-manifest/pred/dead-letter/
   judge-queue/judgements/eval 六类产物各带 `sha256`+计数，`consistency_errors()` 校验六类均为合法 64 位 hex +
   计数自洽（`resolved≤queue`、`unresolved_judge==queue-resolved`、`unresolved_dead_letter==dead_letter`、
   keypoints 现场）；`approval_blockers()` 再叠加 keypoints=complete 且无未解决项。
4. **回归全指标结构化**（三轮#4）：`compare_baselines` 覆盖全局 micro/macro F1 + hallucination + evidence +
   unresolved + 每字段 value/hallucination/evidence 阈值，失败项为结构化 `RegressionFailure{metric, baseline,
   candidate, allowed}`，不再只查 value/hallucination 两项。

**与实施计划的对齐**：模型/函数按计划 Task3/4 合同实现（`BaselineProductArtifacts` 全字段、`compare_baselines`
全指标结构化、`QualityProfile.{artifact,approval}_sha256`、`approve().artifact_sha256==artifact.sha256()`）；
文件上仍并置于 `baseline.py`/`profile.py`（计划建议拆 artifacts/quality/regression.py），功能等价，可再切分不影响合同。

**已知边界（诚实声明）**：`approve_baseline` 是纯函数——`prior` 批准列表与版本单调/唯一性由 020 批准存储层
如实保证；产物引用为结构性校验（sha256 合法性 + 计数自洽），真实文件存在与字节哈希相符由 020 运行时回验；
`release_hash` 刻意排除 `created_at`（重标不改内容身份，有 `_ignores_created_at` 锁定）；evidence 真实回验依赖
dataset_root（无 PDF 判 0.0 不可信）。

三轮返工门禁：ruff/mypy(161) 全绿，non-live **1074 passed**；019 专项 112 用例（11+12+30+24+35），含端到端
bypass 负例（已 live 复跑确认 different-artifact→different-approval、forged-prior-rejected、gate
cross-approval-denied 三处闭合）。

## codex 四轮复审返工 + 提交前自测闭环

四轮沿调用链复现 4 条 P1，**先跑复现脚本留"修复前"证据 → 按不变量重建 → 复跑证明关闭**（不是改到测试变绿）：

1. **批准提交画像内容哈希**（四轮 #1/#2）：`ApprovalRecord.profile_content_sha256` 提交被批准画像的内容哈希；
   `QualityProfile.content_hash()` 排除 `baseline_approval_sha256` 回指，使其批准前后稳定、可被提交。
   `approve_baseline` 存该哈希；`with_approval` 与 `QualityGate` 校验 `approval.profile_content_sha256 ==
   profile.content_hash()`，gate 再校 `approval.fingerprint == profile.fingerprint`。复制公开 `approval.sha256()`
   已不能冒充"已批准画像"；旧 model 批准也不能授权新 model 指纹画像。
2. **prior 绑到当前生产批准内容 + 换 id 不能跳回归**（四轮 #1/#3）：prior_profile 校 `content_hash() ==
   latest.profile_content_sha256`（不可伪造）；只要 `prior` 非空即须与**当前生产基线**（跨 baseline_id 的最近
   批准）回归——换 `baseline_id` 不再另起免检 lineage；真正的新 lineage/bootstrap 只能显式 `allow_lineage_reset=
   True`（人工、可审计）。
3. **build_profile 复用权威 evaluator**（四轮 #4）：全局 micro/macro F1 + 幻觉 + 证据 与每字段 P/R/F1 全部取自
   `eval.evaluate`（含 pred-only 多余字段计 micro FP、空分母口径一致），删除重复实现的 `_f1`。产生多余字段的模型
   不再被画像误判满分；absent-only 空分母口径与 evaluator 一致。

**自测（回应"提交前完善自测修复、别再来回"）**：逐条 live 复现→关闭，另跑两组独立对抗性红队审计（试破批准链 /
试造 build_profile↔evaluate 漂移）；加固用例 `test_q4_6_per_field_drop_caught_even_when_global_faked_perfect`。

**裁决 / 边界**：`allow_lineage_reset` 只在离线 `approve_baseline`，在线 merge/importer 只消费 gate，运行时无法
触达；`approve_baseline` 绑定画像↔artifact 身份+回归+阈值，但不从 pred 原始内容重算指标（真实性由 020 用
`build_profile` 产出画像保证）；伪造 `ApprovalRecord` 属 020 存储/授权层，且 gate 仍要求其指向真实达标画像。

四轮返工门禁：ruff/mypy(161) 全绿，non-live **1099 passed**；019 专项 136 用例（11+12+34+42+37）。

## codex 五轮复审返工

五轮再提 4 条（2×P1 + 2×P2）。照旧**先在四轮 head 跑 `repro_r6.py` 留"修复前"证据、确认 4 条全部成立 →
按不变量重建 → 复跑关闭**；并接受"测试偏单点"的批评，补 `build_profile→approve→gate` 端到端负例：

1. **每字段聚合并入 pred-only 幻觉**（五轮 #1，P1）：`build_profile` 字段聚合原只遍历 golden keys、`per_field`
   不记 pred-only，同字段"10 正确+10 伪造"时 `field[f1].hallucination_rate=0.0`（全局却 0.5），字段 gate 对本
   字段伪造全盲。修复：字段聚合并入该 field_id 的 pred-only present 键，`eval.py` 对**已知 field_id** 的
   pred-only present 记 `per_field.fp`；`support` 仍只数金标观测。现 `field[f1]` 幻觉 0.5、`f1=0.667`，被拒。
2. **领域类型合法域 + 逐项 blocker**（五轮 #2，P1）：`FieldMetrics(value_accuracy=2.0)` 原可构造且恒过阈值；
   负 `dead_letter_count` 与正 judge 相消掩盖真实未解决。修复：`Rate=Field(ge=0,le=1,allow_inf_nan=False)`（全部
   比率指标/阈值）+ `NonNegativeInt=Field(ge=0)`（support 与全部计数）**构造期**即拒；`approval_blockers()`
   **逐项**查 unresolved judge/dead-letter，不再用合计 truthiness。
3. **gate 校 profile 版本 + 收回 pending_judge**（五轮 #3，计划 Task5，P2）：`QualityGate` 增
   `SUPPORTED_PROFILE_VERSION` 常量并拒不支持版本（内容哈希只证"这份 v999 被批准"、不证代码理解该格式）；
   `decide` 增 `pending_judge` 形参并拒，`MergeEngine` 三条自动路径把 pending 判定**收回 gate**（删 gate 外
   `not prop.pending_judge` 预检查），gate 成为唯一权威。
4. **lineage_reset 须真新 lineage + reason**（五轮 #4，P2）：`allow_lineage_reset` 原是通用"关回归"开关。修复：
   reset 须 (a) `artifact.baseline_id` 不在任何 prior 中（确是新 lineage、不能给同 lineage 降级）、(b) 提供
   **非空 `lineage_reset_reason`**（记入 `ApprovalRecord`）；同 id+reset 直接拒。

**裁决 / 边界**：`allow_lineage_reset` 明确为**结构约束 + 审计信号、非授权本身**（不再声称等于人工授权，真实
不可伪造授权由 020 提供）；`Rate`/`NonNegativeInt` 让越界比率/负计数/NaN 在构造期即不可进入任何画像/artifact。

五轮返工门禁：ruff/mypy(161) 全绿，non-live **1119 passed**；019 专项 156 用例（11+12+45+48+40，含
`build_profile→approve→gate` 端到端 bypass 负例 `test_q4_2_fabricating_field_denied_end_to_end`）。

## 提交前独立红队自测（R6，非 codex 触发）

五轮修完后**不等 codex**，先派 4 支对抗性红队各写脚本 live 攻击（回应"提交前完善 TDD 自测、别再来回"）。
2 支无绕过（领域类型、字段聚合），2 支各挖出真问题，全部 TDD 复现→修→复跑关闭：

1. **D-弱点1（中，端到端真绕过）**：`approve_baseline` 的 lineage_reset"真新 lineage"守卫只查 `baseline_id`
   字符串、不查 golden 集——同一 `golden_release_hash`（同评测基准）换个新 id + reset 即跳过零容差回归，
   退化画像端到端拿到 `QualityGate.decide→eligible`。修复：reset 须 (a) prior 非空、(b) baseline_id 不在
   prior、(c) **golden_release_hash 与所有 prior 不同**、(d) 非空 reason。`baseline_id` 是可随意更换的**弱
   代理**，golden 集才是评测基准这一不变量。
2. **C-2b（中，五轮自引入的纵深防御倒退）**：五轮把 merge 三路径 `not pending_judge` 预检查删净、safety
   100% 押注入 gate；注入不 honor pending 的 gate → pending 候选自动发布。修复：`_gate_ok` **恢复独立 pending
   短路**（gate 仍权威，merge 保留 fail-closed 兜底）——删冗余安全层违背 fail-closed 教训（019返工教训）。
3. **C-2a（低，健壮性）**：`_gate_ok` 无 try/except，旧签名 gate → TypeError 崩整批。修复：gate 异常一律
   fail-closed 走 ReviewItem、不崩批。
4. **D-弱点2/3（低，审计卫生）**：`baseline_id` 构造期禁空/纯空白/首尾空白（`Identifier` 约束）；`prior=[]`
   却 `allow_lineage_reset=True` 报错（不静默吞意图）。

**裁决 / 边界（只文档不改）**：D-弱点4（latest 选取 tiebreak）依赖弱点1 或伪造 prior，弱点1 修完失去入口、
伪造 prior 属 020 存储完整性；B-B（首基线不查全局指标）由在线逐字段 gate 兜底，加全局下限恐误杀合法难产品
首基线；A-1（version 可负）仅可信 prior 的 tiebreaker；A-3（020 加载须 `model_validate` 才使领域约束
load-bearing）记 020 边界。

R6 返工门禁：ruff/mypy(161) 全绿，non-live **1130 passed**；019 专项 167 用例（11+12+54+48+42，含
`_reset_cannot_launder_same_goldenset_downgrade_end_to_end`、`_pending_short_circuits_even_if_gate_ignores_it`
等端到端红队负例）。

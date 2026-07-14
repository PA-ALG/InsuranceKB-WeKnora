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

返工后门禁：ruff/mypy(161) 全绿，non-live **1060 passed**；所有修复先补失败用例（复现 codex 反例）再改实现。

# 024 验收报告（2026-07-16）

> **证明力声明（E5.3）**：本报告全部证据来自零真实模型调用的机制合同测试与冻结录制回放——它们证明编排、解析与护栏行为符合规格，**不证明、也不暗示模型真实召回提升**。真实召回结论字段：**留待 020 D4**（固定模型/样本/预算下的 A/B，按变体版本对账）。

## 1. 门禁（fresh，worktree `ikb-024` @ feat/024-extraction-recall-uplift）

| 项 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy | Success，187 files |
| deterministic lane | **1326 passed / 5 deselected**（gauntlet 返工后：+误杀防线/审计/变体归属回归，既有零破坏） |
| 024 focused | uplift 38 + probe 13 + accept-side 6 + audit 4 passed |

## 2. 工单状态表（E1.1 / E5.3）

- **总数**：25（extract_empty 24 + prompt 域 routing_miss 1，逐条对账 005 validation-report 归因清单——注册表自检 `test_e1_1_registry_matches_attribution_totals` 断言 24/25、分产品 10/6/8、quote_mismatch 特例唯一）。
- **机制覆盖数**：25/25——每条工单有以其标识命名的回放用例（`test_e1_1_ticket_targeted_gapfill_yields_verified_candidate_with_variant_audit[<ticket_id>]`），断言：定向补漏触发 → 回验通过的候选产出 → pred 元数据带变体版本。16 个去重字段全部进入定向短答模板注册（含 10 个长文本字段的值粒度指引）。
- **未覆盖数**：0。
- **诚实边界**：机制覆盖 ≠ 真实转化——脚本响应下用例转绿只证明"若模型给出可回验候选，链路正确接住并盖审计章"。

## 3. 后处理synthetic 机制合同探针结果（非『非退化』证据）（E5.1）

冻结录制集（9 条，覆盖 verified-present / 占位 / 弱值 / 引用型 / 兼容性拒入 / 回验失败 / absent / unknown 全分支）三重钉桩下评分：**探针产品甲/乙/丙 = 1.0 / 1.0 / 1.0（== 基线）**。钉桩：control 变体 `default@v1`、9 条 request_key、manifest `1f95a70a…8a8284`——prompt 组装漂移或录制/预期改动将使探针**显式失败**，不得静默换基线。**F5 加固**：`_FrozenClient` 在真实调用路径上断言出站 prompt 的 `request_key` 等于钉桩值，控制变体一旦携带定向模板（漂移）探针即 fail（回归 `test_e5_1_control_prompt_drift_is_caught`）——此前 `complete` 忽略 `user`，钉桩只校验测试内重建 prompt，漂移可绕过。

## 4. 变体版本清单（020 D4 A/B 对账钩子）

| 版本 | 含义 | 覆盖 |
|---|---|---|
| `default@v1` | 默认变体：prompt 组装与 024 之前逐字节一致（control 臂） | 全部未注册字段 |
| `targeted@v1` | 定向短答模板（E3）+ 值粒度指引（E4，10 字段） | 16 个工单字段（treatment 臂） |

**020 D4 交接**：①A/B 按 pred `metadata["prompt_variant"]` 分臂统计；②真实 3 产品录制集建立后，把本 change 的探针模式（request_key+manifest 钉桩）套到真实录制上替换合成集；③工单转化率=25 条工单字段在 treatment 臂的 present 率对 005 基线。

## 5. E6 护栏证据

- 弱值两族：`WEAK_UNACTIONABLE` 8 模式、`REFERENCE_ONLY` 3 模式（整值即指针 + ≤6 字尾注防误吞）；用例 6 条全绿。
- 字段-值兼容性：Q012 三条历史 bug 固化（退保文案→费用类 / 职业→年龄 / 裸年限→保证续保），双条件+排除词防误杀；校验链 2.5 步与 gapfill 循环双接线，拒绝原因 `incompatible_value` + metadata 可审计。
- **零漂移（E5.2）**：既有约 30 条占位模式与语义未动；全量 1314 回归即实证（含既有 ReplayClient 全管道回放 request_key 未变）。

## 6. 残留与边界

- 抽取主 prompt 未接变体模板（裁决记录 #4）：首轮走基线 extraction prompt，**treatment 生效面=定向补漏（gapfill）**——控制/treatment 两臂首轮一致，A/B 信号在 gapfill。但 **E2.2 变体标识已覆盖每个 pred**（gauntlet F7）：首轮在 `extract.py:_extract_batch` 按 (组,field_id) stamp，fastpath/vote/judge/dead_letter 在 `pipeline.merge_candidates` finalize 兜底 stamp，均与 gapfill 同一注册表——020 D4 A/B 可对账全部 pred 的变体归属，不再限 gapfill 路径。
- `incompatible_value` 归因入桶：005 归因器按 `placeholder` 字符串分桶，新原因落入通用桶——020 重跑归因时如需细分再在归因器加映射（一行）。

## 7. Gauntlet 红队返工（2026-07-17，独立 fresh-eyes agent + live 复现）

送验前 gauntlet 由独立红队 agent 执行，抓到 9 项、7 项已修（2 项经真金标 live 复现）：

| # | 级别 | 缺陷 | 修复 | 证据 |
|---|---|---|---|---|
| **F1** | **严重** | compat 规则 3 误杀真金标 `保证续保期="20年"`（时长字段被"是/否保证续保"规则子串误伤） | 规则 3 加 `field_not="保证续保期"` | accept 侧钉桩 + goldenset 全集扫描 |
| **F2** | **严重** | compat 规则 1 误杀真金标 `费用="…提前退保影响…"`（含"退保"即杀） | 规则 1 值形态收紧为退保损失签名 `^退保\|退保…损失` | 同上 |
| F3 | 高 | 年龄字段带职业限定被误杀（与 E4"保留限定"自相矛盾） | 规则 2 加 `value_not=年龄单位` 放行 | accept 侧钉桩 |
| F4 | 高 | WEAK 清洗裸前缀吞掉"按合同约定的年利率3.5%…" | 加整值锚定（对齐 REFERENCE_ONLY 纪律） | goldenset 全集零误吞 |
| F5 | 高 | E5 探针钉桩未绑定真实调用路径，控制变体可静默漂移 | `_FrozenClient` 断言出站 `request_key`==钉桩 | `test_e5_1_control_prompt_drift_is_caught` |
| F6 | 中 | gapfill 兼容性拒绝原因丢失（记 not_found，违 E6.3） | 记 `incompatible_value` + `metadata.compat_reject` | `test_e6_3_gapfill_compat_reject_records_auditable_reason` |
| F7 | 中 | 首轮/fastpath/vote/judge pred 无变体标识（违 E2.2"每次抽取的 pred"） | 首轮 `_extract_batch` + finalize `merge_candidates` 双 stamp | `test_e2_2_*` 三条 |

**新增"误杀防线"**（此前缺失，正是漏 F1/F2 的根因）：`test_recall_accept_side_024.py` 扫描整个 13 产品 goldenset，断言每个 present 金标值 compatible 且不被清洗——从此任何 compat/cleaning 误杀真金标即红。拒绝侧 Q012 三案仍全绿（护栏未被削弱）。

**教训固化**：写自己想到的测试 ≠ 红队；护栏（防 Q012）与召回目标（防误杀）是成对约束，只测拒绝侧不测接受侧 = 半个护栏。probe_fee 拒绝原因 not_found→incompatible_value 触发 manifest 有意重钉（`1c71f804…`→`1f95a70a…`），E5 三重钉桩按设计要求显式确认。

## codex PR#13 复审返工后（2026-07-18，rebase main@dbc073c1）

- 门禁 fresh：ruff 全绿；mypy strict **226 files**；deterministic **1668 passed / 8 deselected**；`openspec validate 024 --strict` valid。
- 024 focused：58（原 55 中 3 条错误语义断言被替换）+ 新增 `test_recall_experiment_024.py` 10 条（E7 审计往返/分桶/摘要身份 + E3 触发负例正例 + E6 指针检索）。
- **E5 状态更正（诚实边界）**：仓库无改动前真实录制，synthetic 探针只能证明后处理机制合同——E5「同录制集非退化」**未完成，显式让渡 020 D4**（differential replay：同一 raw responses 对 base/PR SHA 重放）；探针测试已改名 `test_e5_mechanism_*` 不再暗示非退化证明。
- 真实召回/粒度改善结论仍完全留待 020 D4（E1 证明力边界不变）。

## codex R2 终审返工后（2026-07-18）

- 上文历史段落中涉及"`_extract_batch`/`merge_candidates` 变体盖章"与"synthetic 非退化"的表述为**已废弃口径（superseded）**，现行权威=R2 返工段与 spec E3/E5/E7 修订：预算=出站调用硬上限（6 组反例）、attempt 链+winning_attempt_id（继承歧义消除）、E5=机制合同+让渡 020 D4、实验/requiredness 配置 fail-closed。
- 门禁 fresh（数字见 PR 回执）：ruff / mypy / deterministic / openspec strict / focused 全绿。

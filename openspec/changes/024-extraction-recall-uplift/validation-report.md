# 024 验收报告（2026-07-16）

> **证明力声明（E5.3）**：本报告全部证据来自零真实模型调用的机制合同测试与冻结录制回放——它们证明编排、解析与护栏行为符合规格，**不证明、也不暗示模型真实召回提升**。真实召回结论字段：**留待 020 D4**（固定模型/样本/预算下的 A/B，按变体版本对账）。

## 1. 门禁（fresh，worktree `ikb-024` @ feat/024-extraction-recall-uplift）

| 项 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy | Success，185 files |
| deterministic lane | **1314 passed / 5 deselected**（基线 1265，新增 49，既有零破坏） |
| 024 focused | `test_recall_uplift_024.py` 38 passed + `test_recall_probe_024.py` 11 passed |

## 2. 工单状态表（E1.1 / E5.3）

- **总数**：25（extract_empty 24 + prompt 域 routing_miss 1，逐条对账 005 validation-report 归因清单——注册表自检 `test_e1_1_registry_matches_attribution_totals` 断言 24/25、分产品 10/6/8、quote_mismatch 特例唯一）。
- **机制覆盖数**：25/25——每条工单有以其标识命名的回放用例（`test_e1_1_ticket_targeted_gapfill_yields_verified_candidate_with_variant_audit[<ticket_id>]`），断言：定向补漏触发 → 回验通过的候选产出 → pred 元数据带变体版本。16 个去重字段全部进入定向短答模板注册（含 10 个长文本字段的值粒度指引）。
- **未覆盖数**：0。
- **诚实边界**：机制覆盖 ≠ 真实转化——脚本响应下用例转绿只证明"若模型给出可回验候选，链路正确接住并盖审计章"。

## 3. 后处理非退化结果（E5.1）

冻结录制集（9 条，覆盖 verified-present / 占位 / 弱值 / 引用型 / 兼容性拒入 / 回验失败 / absent / unknown 全分支）三重钉桩下评分：**探针产品甲/乙/丙 = 1.0 / 1.0 / 1.0（== 基线）**。钉桩：control 变体 `default@v1`、9 条 request_key、manifest `1c71f804…3243f8`——prompt 组装漂移或录制/预期改动将使探针**显式失败**，不得静默换基线。

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

- 抽取主 prompt 未接变体（裁决记录 #4）：E2.2 盖章目前限 gapfill 路径——变体扩展到抽取路径时同步，不影响 020 A/B（treatment 生效面=定向补漏）。
- `incompatible_value` 归因入桶：005 归因器按 `placeholder` 字符串分桶，新原因落入通用桶——020 重跑归因时如需细分再在归因器加映射（一行）。

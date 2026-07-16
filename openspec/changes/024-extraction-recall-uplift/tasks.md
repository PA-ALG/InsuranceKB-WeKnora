# 024 任务（TDD 顺序；测试名引用条款号）

> 轨道 L5（见 docs/insurance-kb/22），即刻可认领，零真实模型调用。二版（2026-07-16）：证明力边界按 PR #11 复审收紧——零调用侧只交付机制/版本化/护栏/非退化框架，真实召回结论归 020 D4。

- [ ] T1 归因工单固化：005 清单逐条 → 机制合同回放用例（E1.1；先全部 RED，本任务不修；用例注明证明力边界）
- [ ] T2 prompt 变体机制：注册表 + 确定性选择 + **版本化**审计标识 + 默认回落零漂移（E2）
- [ ] T3 定向补漏：**schema 驱动触发**（触发器依赖断言不含金标）+ evidence 回验与反幻觉回归（E3）
- [ ] T4 值粒度字段级指引并入变体（E4；prompt 快照断言 + 契约零改动）
- [ ] T5 后处理非退化合同：未变更录制集上 3 基线产品回放评分下界断言进 deterministic 门禁（E5）
- [ ] T6 弱值/兼容性护栏：WEAK_UNACTIONABLE+REFERENCE_ONLY 两族入 cleaning + 字段-值兼容性校验 + Q012/Q026 历史 bug 用例（E6；占位清洗零漂移断言）
- [ ] T7 收尾：validation-report（工单状态表 + 非退化结果 + 变体版本清单 + "真实召回结论留待 020 D4"显式声明，E5）→ HANDOFF 更新 → 020 D4 A/B 交接说明（按变体版本对账）

约束：文件域仅 compiler/；不调真实模型；不动 cleaning 白名单既有语义/尺子/knowledge/；金标只出现在测试评分；送审前过 21 号自测 gauntlet。
状态：**可认领**（从 main 切 `feat/024-extraction-recall-uplift`）。依赖：004/005 已合入。执行者 B（Owner=B，compiler/goldenset 域内自审+另一人 approve）。

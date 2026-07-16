# 024 任务（TDD 顺序；测试名引用条款号）

> 轨道 L5（见 docs/insurance-kb/22），即刻可认领，零真实模型调用。

- [ ] T1 归因工单固化：005 清单逐条 → RED 回放用例（E1.1；先全部红，本任务不修）
- [ ] T2 prompt 变体机制：注册表 + 确定性选择 + pred 元数据审计标识 + 默认回落零漂移（E2.1–E2.3）
- [ ] T3 定向补漏模板：extract_empty 字段第二轮提问，evidence 回验与反幻觉回归断言（E3.1/E3.2）
- [ ] T4 值粒度字段级指引并入变体（E4.1/E4.2）
- [ ] T5 fixture 回归合同：3 基线产品 replay before/after 下界断言进 deterministic 门禁（E5.1）
- [ ] T6 弱值/兼容性护栏：WEAK_UNACTIONABLE+REFERENCE_ONLY 两族入 cleaning + 字段-值兼容性校验 + Q012/Q026 历史 bug RED 用例（E6；占位清洗零漂移断言）
- [ ] T7 收尾：validation-report（工单状态表 + 回放分数表，E5.3）→ HANDOFF 更新 → 020 D4 真实回归交接说明

约束：文件域仅 compiler/；不调真实模型；不动 cleaning 白名单/尺子/knowledge/；送审前过 21 号自测 gauntlet。
状态：**可认领**（从 main 切 `feat/024-extraction-recall-uplift`）。依赖：004/005 已合入。

# 010 任务（TDD 顺序；测试名引用条款号）

> 2026-07-16 基础对齐修订：前置 Space 作用域任务、迁移占号 0007。轨道 L4 首件（见 docs/insurance-kb/22），即刻可认领。

- [ ] T1 Space 作用域接线：导入服务与 CLI 显式 space，fail-closed 与跨 space 不可见用例先行（I6.1）
- [ ] T2 映射规则加载器 + 内置 product_meta 映射（I1.1/I1.2）
- [ ] T3 规范化接线 + 失败入报告（I1.3）
- [ ] T4 未知结构候选映射草案生成（I1.4）
- [ ] T5 幂等键/结构化来源身份 + revision 合并接线（I2.1/I6.2，走 007 引擎；串行导入限制标注 I6.4）
- [ ] T6 批次/ChangeSet/错误隔离/原始快照（I2.2/I2.4）
- [ ] T7 dry-run 默认 + apply 一致性断言（I2.3）
- [ ] T8 产品对齐与一对多拆分（I3）
- [ ] T9 qa_staging 表与 FAQ 直入（I4；Alembic **0007**，I6.3 链序协调）
- [ ] T10 CLI + 13 份 meta 端到端 + 冲突用例（I5）
- [ ] T11 validation-report + HANDOFF 更新

约束：零模型调用；不改 compiler/ 与 goldenset/；复用 knowledge/（007）服务层不绕表；Evidence 不伪造页码锚点（I6.2）。
状态：**可认领**（从 main 切 `feat/010-structured-import`）。依赖：007/016/017 已合入。

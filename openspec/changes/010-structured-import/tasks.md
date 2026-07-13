# 010 任务

- [ ] T1 映射规则加载器 + 内置 product_meta 映射（I1.1/I1.2）
- [ ] T2 规范化接线 + 失败入报告（I1.3）
- [ ] T3 未知结构候选映射草案生成（I1.4）
- [ ] T4 幂等键与 revision 合并接线（I2.1，走 007 引擎）
- [ ] T5 批次/ChangeSet/错误隔离/原始快照（I2.2/I2.4）
- [ ] T6 dry-run 默认 + apply 一致性断言（I2.3）
- [ ] T7 产品对齐与一对多拆分（I3）
- [ ] T8 qa_staging 表与 FAQ 直入（I4，Alembic 增表）
- [ ] T9 CLI + 13 份 meta 端到端 + 冲突用例（I5）
- [ ] T10 validation-report + HANDOFF 更新

约束：零模型调用；不改 compiler/ 与 goldenset/；复用 knowledge/（007）服务层不绕表。
状态：待接手（遗留 B12）。依赖：007 已合入。

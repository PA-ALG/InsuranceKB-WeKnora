# 010 任务（TDD 顺序；测试名引用条款号）

> 二版（2026-07-16，按 PR #11 复审重排）：双通道拆分 + 结构化证据数据模型。轨道 L4 首件，即刻可认领；执行者 C3，**PR 须 Owner-A 复审（claim_evidence DDL + 迁移 0007）**。

- [ ] T1 Space 作用域接线：导入服务与 CLI 显式 space，fail-closed 与跨 space 不可见用例先行（I6）
- [ ] T2 通道一 bootstrap：meta 映射 → 003 注册（幂等、dry-run），**零 Claim/Evidence 断言**（I1）
- [ ] T3 来源登记表：source registry 加载 fail-fast + 未登记来源拒绝用例（I1/I3）
- [ ] T4 映射规则加载器 + 规范化接线 + 未知结构候选草案（I2）
- [ ] T5 迁移 0007：structured_source_records + qa_staging + claim_evidence structured 变体扩展与 CHECK 三态互斥；既有证据零漂移 + downgrade 干净用例（I4；**Owner-A 复审点**；与 021（0006）合入序按注册表规则重接链）
- [ ] T6 通道二导入：幂等键/留存/记录定位/内容哈希 → 007 合并接线，structured Evidence 端到端（I4/I5）
- [ ] T7 批次/ChangeSet/错误隔离 + dry-run 默认与 apply 一致性断言（I5）
- [ ] T8 产品对齐与一对多拆分（沿 003 路由器，fuzzy 一律 unassigned）
- [ ] T9 FAQ → qa_staging（I7）
- [ ] T10 端到端：meta bootstrap + 已登记业务源双 revision 冲突故事 + FAQ（I8）
- [ ] T11 收尾：validation-report（含 Q020 合规声明与 Owner-A 复审记录）→ HANDOFF 更新

约束：零模型调用；不改 compiler/ 与 goldenset/；knowledge/ 只经服务层 + 唯一例外是 T5 的 DDL（显式列出、Owner-A 复审）；Evidence 不伪造页码/chunk 锚点。
状态：**可认领**（从 main 切 `feat/010-structured-import`）。依赖：003/007/016/017 已合入。

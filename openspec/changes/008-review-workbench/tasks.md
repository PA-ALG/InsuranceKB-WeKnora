# 008 任务（TDD 顺序；测试名引用条款号）

> 2026-07-16 条款化并任务化，轨道 L2（见 docs/insurance-kb/22）。T1–T5、T7 即刻可做；**T6 Phase B 等 PR #9（018）合入**。

- [ ] T1 包骨架：FastAPI app 工厂 + HarnessSettings 接线（token/DB）+ 鉴权 401 + space 解析 fail-closed 403（W5.1/W5.2/W6.1）
- [ ] T2 只读查询模块：审核队列 / ChangeSet 列表 / 完整度聚合 三类查询（只读会话；W1.1、W2.1、W3.1 的数据形状用例先行）
- [ ] T3 审核队列页：列表/筛选/详情/approve-reject-defer/批量 approve（仅非 high）；动作幂等与并发冲突（stale 拒绝并刷新）用例（W1.1–W1.4）
- [ ] T4 冲突与变更页：分色明细、双方证据与权威序依据、翻案生成新 ChangeSet、人类可读时间线（W2.1–W2.4，G8）
- [ ] T5 完整度矩阵页：热力矩阵/下钻/导出 CSV+JSONL（W3.1–W3.3）
- [ ] T6 发布与回滚页（W4/W7.1/W7.2）：
  - Phase A（即刻）：快照列表 + 指针 + diff 只读；回滚按钮 feature-flag 关闭；
  - Phase B（PR #9 合入后）：接真实 SnapshotReader 与 018 可恢复回滚，dry-run→二次确认→执行→结果全链用例；
- [ ] T7 Space 全覆盖 + gate 联动：跨 space 不可见矩阵用例（W6.2/W6.3）；019 gate ReviewItem 展示与"无绕过端点"断言（W7.3）
- [ ] T8 收尾：validation-report（含每条款证据）→ HANDOFF 更新 → 14 号 Runbook 增工作台启动段落

约束：零模型调用；不改 compiler/goldenset/adapters；对 knowledge/ 只经服务层（无直接 SQL 写，W5.1 断言）。
状态：**可认领**（轨道 L2；从 main 切 `feat/008-review-workbench`）。依赖：007/016/019 已合入；仅 T6 Phase B 等 018。

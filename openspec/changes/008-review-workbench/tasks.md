# 008 任务（TDD 顺序；测试名引用条款号）

> 二版（2026-07-16，按 PR #11 复审修订）：W4 **整页**推迟至 PR #9（018）合入后；鉴权升级为 token→Space 授权绑定。轨道 L2；T1~T5、T7 即刻可做。执行者 C1，**Owner 复审=A**（workbench/ 属 A 域，17 §1）。

- [ ] T1 包骨架：FastAPI app 工厂 + HarnessSettings 接线 + **token→(principal+Space 集合) 授权绑定**（配置映射；无 token 401；"token A 请求 Space B → 403 且零数据泄露"与"审计 operator=token principal、客户端自报无效"两条 RED 用例先行）（W5/W6）
- [ ] T2 只读查询模块：审核队列 / ChangeSet 列表 / 完整度聚合 三类查询（只读会话；W1/W2/W3 数据形状用例先行）
- [ ] T3 审核队列页：列表/筛选/详情/approve-reject-defer/批量（仅非 high）；幂等与乐观并发用例（W1）
- [ ] T4 冲突与变更页：分色明细、权威序依据、翻案不改历史、变更时间线（W2，G8）
- [ ] T5 完整度矩阵页：热力矩阵/下钻/导出（W3）
- [ ] T6 发布与回滚页（**PR #9 合入后开工**）：SnapshotReader 读取 + 018 可恢复回滚 dry-run→确认→执行全链；合入前仅静态占位导航（W4）
- [ ] T7 Space 全覆盖 + gate 联动：跨 space 不可见矩阵用例（W6）；019 gate ReviewItem 展示与"无绕过端点"路由断言（W7）
- [ ] T8 收尾：validation-report（含每条款证据）→ HANDOFF 更新 → 14 号 Runbook 增工作台启动段落

约束：零模型调用；不改 compiler/goldenset/adapters；对 knowledge/ 只经服务层（无直接 SQL 写，W5 断言）。
状态：**可认领**（从 main 切 `feat/008-review-workbench`）。依赖：007/016/019 已合入；仅 T6 等 018。

# 004 任务

- [ ] T1 公共模块重构：002 的对抗性 JSON 解析器与 quote 回验抽到 `compiler/` 可复用位置（002 测试不破坏）（E3.1/E3.2）
- [ ] T2 06 资产代码化：GROUP_KEYWORDS/7 组/字段桥接 → routing_data.py；占位值正则 → cleaning.py（E2.3/E3.3）
- [ ] T3 章节切分（页码映射）+ 组路由（E2）
- [ ] T4 llm.py 模型接入（litellm 可选 extra + ReplayClient）（提案 §8）
- [ ] T5 分批抽取节点 + 校验链 + 打回流程（E3）
- [ ] T6 补漏 pass + 高风险投票（E4）
- [ ] T7 LangGraph 编排 + checkpoint + 死信 + run manifest（E1）
- [ ] T8 pred 输出 + 13 产品跑分 + validation-report.md（E5）
- [ ] T9 更新 HANDOFF

状态：提案待业务方评审（2026-07-12）。依赖：003 合入；真实弱模型跑分依赖网关凭据（无凭据则 T8 以 ReplayClient 出管道正确性报告，基线分待凭据补跑）。
设计增量：无独立 design.md，遵循 docs/insurance-kb/04；新增依赖 langgraph（08 已选型）。

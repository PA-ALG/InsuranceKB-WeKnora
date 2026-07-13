# 003 任务

- [x] T1 SQLAlchemy/Alembic 初始化 + docker-compose.harness.yml + 首批迁移（P1）
- [x] T2 产品注册服务 + 幂等 + 别名生成（P2）
- [x] T3 文档分类器（确定性特征优先，LLM 兜底）（P3）
- [x] T4 产品路由器 + unassigned 池（P4）
- [x] T5 CLI：register-products / classify + 样本评分报告（P2.1/P4.5）
- [x] T6 多产品拼接测试文档用例（验收第 3 条）
- [ ] T7 更新 HANDOFF

状态：T1~T6 完成（2026-07-12），验收跑分见 validation-report.md（类型 39/39=100%、exact 39/39=100%、LLM 调用 0、注册幂等复跑零新增）。依赖：002 合入（schema 注册表用于险种判定）。
设计增量：无独立 design.md；表结构以 03 §7 为权威，偏差需先修订 03。

红绿循环遗留裁决（2026-07-12）：`test_product_aliases.py::test_short_strips_type_suffix` 判定**测试正确、改实现**。
依据：该测试要求 short 别名保留中缀括号组（"平安盛世金越（尊享版26）终身寿险（分红型）" → "平安盛世金越（尊享版26）"），
只剥类型后缀及其尾部限定括号；原实现剥掉全部括号会把（尊享版26）/（至尊版26）/创享等不同产品折叠成同一别名
"平安盛世金越"——按 P4.2 同名多产品即歧义、永远不能自动归属，等于让别名路由对这批产品失效，违背 P2.3 别名服务于
路由的意图（数据集中确有此三组同前缀产品）。修复：`aliases._strip_type_suffix` 改为只剥【尾部】括号组再试后缀。

T6 补充：路由器新增章节级入口 `routing.route_sections`（Section 带 section_ref），拼接文档各章节独立路由，
无确定性命中的章节各自进 unassigned（fuzzy/歧义候选附带，不自动归属）；`persist_unassigned` 落 unassigned_pool 表（P4.4）。

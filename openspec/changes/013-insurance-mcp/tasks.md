# 013 任务（TDD 顺序；测试名引用条款号）

> 2026-07-16 条款化并任务化，轨道 L3（见 docs/insurance-kb/22）。**实现基线 = PR #9（018）合入后的 main**——读路径依赖 SnapshotReader（M4），在此之前只做规格评审，不开工。

- [ ] T1 包骨架：官方 `mcp` SDK server 工厂（stdio）+ 连接 token 鉴权 + space 绑定 fail-closed（M2.2/M4.2）
- [ ] T2 `resolve_product`：exact→alias→candidates 三级、绝不单选猜测、as_of_date 生效区间过滤（M1.1；只读复用 003 别名索引）
- [ ] T3 `get_product_facts`：经 018 SnapshotReader 读 published 快照事实，三态/confidence/证据摘要/claim_id 信封（M1.2/M4.1/M4.3）
- [ ] T4 `get_claim_evidence`：全证据链；非 published 一律 not_found 不泄露存在性（M1.3）
- [ ] T5 `compare_products`：产品×字段矩阵，缺值显式 unknown+注释（M1.4）
- [ ] T6 横切：响应信封（as_of_date/schema_version/disclaimer/trace_id）、not_found reason 枚举、只读事务断言（M2.1/M2.3/M2.5）
- [ ] T7 SSE 传输 + SDK 测试客户端端到端故事（等待期 as_of/停售/多义/draft 不可见）（M2.4/M3.1/M3.2）
- [ ] T8 收尾：validation-report → HANDOFF 更新；真实 WeKnora Agent 挂载联调登记到 L6/B10（M3.3）

约束：全程零写库、零模型调用；WeKnora 细节不入本包（只读 harness 自有 DB）；不改 knowledge/ 与 adapters/。
状态：**规格就绪**；实现待 PR #9 合入后认领（从 main 切 `feat/013-insurance-mcp`）。

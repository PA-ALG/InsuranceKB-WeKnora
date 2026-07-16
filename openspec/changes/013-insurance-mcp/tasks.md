# 013 任务（TDD 顺序；测试名引用条款号）

> 二版（2026-07-16，按 PR #11 复审修订）：传输改 **HTTP Streamable 主路径**（WeKnora 禁用 stdio）。轨道 L3；**实现基线 = PR #9（018）合入后的 main**（读路径依赖 SnapshotReader，M3），在此之前只做规格评审不开工。执行者 C2（Owner=C）。

- [ ] T1 包骨架：官方 `mcp` SDK（版本锁定）server 工厂（**HTTP Streamable**，loopback）+ 连接 token 鉴权 + space 绑定 fail-closed（M3/M4）
- [ ] T2 `resolve_product`：exact→alias→candidates、as_of_date 生效区间（M1；只读复用 003 别名索引）
- [ ] T3 `get_product_facts`：经 018 SnapshotReader 读快照事实（M1/M3；夹具=018 published snapshot fixture）
- [ ] T4 `get_claim_evidence`：全证据链；非 published 不泄露存在性（M1）
- [ ] T5 `compare_products`：矩阵 + 显式 unknown（M1）
- [ ] T6 横切：响应信封/not_found 枚举/只读事务断言（M2）
- [ ] T7 传输与集成：Streamable HTTP 往返合同测试 + SSE 兼容层 +"stdio 仅本地单测"断言（M4）
- [ ] T8 端到端故事（等待期 as_of/停售/多义/draft 不可见）+ 收尾：validation-report → HANDOFF；真实 WeKnora Agent 挂载登记 L6/B10（M5）

约束：全程零写库、零模型调用；WeKnora API 细节不入本包（只读 harness 自有 DB；挂载配置属部署事项）；不改 knowledge/ 与 adapters/。
状态：**规格就绪**；实现待 PR #9 合入后认领（从 main 切 `feat/013-insurance-mcp`）。

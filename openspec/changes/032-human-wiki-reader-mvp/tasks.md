> [!WARNING]
> **SUPERSEDED / HISTORY-ONLY（D0，2026-07-26）**：本文件仅保留历史证据，不再是可执行路线，不得继续实现、重放或复用其中的运行时与迁移安排。当前权威设计见 `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`。

# 032 任务（Space/auth 风险 A；只读 service/UI 风险 C）

- [ ] T1 冻结目录/产品页 DTO 与 `ApprovedSnapshotReader` port，写 HR1/HR2 RED
- [ ] T2 实现 `human_reader` service：产品解析、事实分组、Evidence/typed gap 映射；零 mutable Claim 查询
- [ ] T3 写 HR3 RED：401、跨 Space 常量 403、未知/跨 Space 产品不可区分；复用既有 token→Space 授权模型
- [ ] T4 实现只读 FastAPI/Jinja 页面；写路由表零写、免责声明、结构化 Evidence 与内部预览测试
- [ ] T5 与 013 建 shared serving contract test，证明同 snapshot/hash/canonical facts；不修改 MCP 内部实现
- [ ] T6 focused 套件 + 一次真实 TestClient smoke；validation report 诚实记录 WeKnora production UI/P-1 为 NOT RUN

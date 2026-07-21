# 032 任务（风险 C；独立只读消费面）

- [ ] T1 冻结目录/产品页 DTO 与 `ApprovedSnapshotReader` port，写 HR1/HR2 RED
- [ ] T2 实现 `human_reader` service：产品解析、事实分组、Evidence/typed gap 映射；零 mutable Claim 查询
- [ ] T3 写 HR3 RED：401、跨 Space 常量 403、未知/跨 Space 产品不可区分；复用既有 token→Space 授权模型
- [ ] T4 实现只读 FastAPI/Jinja 页面；写路由表零写、免责声明、结构化 Evidence 与内部预览测试
- [ ] T5 与 013 建 shared serving contract test，证明同 snapshot/hash/canonical facts；不修改 MCP 内部实现
- [ ] T6 focused 套件 + 一次真实 TestClient smoke；validation report 诚实记录 WeKnora production UI/P-1 为 NOT RUN

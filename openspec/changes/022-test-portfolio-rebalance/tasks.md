# 022 任务

- [x] T1 P0：live scope 生命周期回归与 helper 修复
- [x] T2 P0：PostgreSQL integration marker/CI service job 与 WeKnora manual workflow
- [x] T3 P1：bridge contract/live 拆分并保持 12+1 收集语义
- [x] T4 P2：pipeline 按 checkpoint/runtime/CLI 拆分并提取 support
- [x] T5 P2：revision 按 notify/import 拆分并提取 support
- [x] T6 P3：coverage-context overlap audit、测试与开发规范
- [x] T7 全量门禁、独立规格/质量复审、validation/HANDOFF/PR 对账

状态：P0～P3 软件实现、本地全量门禁、独立审查及 PostgreSQL 16 GitHub Actions 集成验证均完成，见 PR #5 与 `validation-report.md`。真实 WeKnora live 是否通过只取决于受控环境中的 workflow 运行证据；当前保持 `NOT RUN`，软件实现和 PostgreSQL CI 不能替代该状态。

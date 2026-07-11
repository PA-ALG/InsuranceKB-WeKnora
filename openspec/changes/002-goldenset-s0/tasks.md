# 002 任务

- [ ] T1 schema 注册表加载器 + 版本号（G1）
- [ ] T2 PDF→带页码文本（本地解析优先，pypdf/pdfplumber；扫描件占位报错即可，本批无扫描件）
- [ ] T3 标注 Agent：分字段组 prompt、三态输出、evidence 结构（G2.1~G2.3）
- [ ] T4 引文回验 + meta 比对 + disputed 机制（G2.2/G2.4）
- [ ] T5 断点续跑缓存（G2.5）
- [ ] T6 金标 release 目录与 manifest（G3）
- [ ] T7 eval runner + 指标 + 报告（G4）
- [ ] T8 用 13 产品跑出 gs-v0.1，产出 manifest 与 disputed 清单
- [ ] T9 更新 HANDOFF、05 文档如有口径修正

状态：提案待评审（2026-07-11）。依赖：001 合入。
设计增量：无独立 design.md，实现完全遵循 docs/insurance-kb/05；PDF 解析选型若超出 08 清单需先修订 08。

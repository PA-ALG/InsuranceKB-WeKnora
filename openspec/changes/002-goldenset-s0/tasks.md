# 002 任务

- [x] T1 schema 注册表加载器 + 版本号（G1）
- [x] T2 PDF→带页码文本（本地解析优先，pypdf/pdfplumber；扫描件占位报错即可，本批无扫描件）
- [x] T3 标注 Agent：分字段组 prompt、三态输出、evidence 结构（G2.1~G2.3）
- [x] T4 引文回验 + meta 比对 + disputed 机制（G2.2/G2.4）
- [x] T5 断点续跑缓存（G2.5）
- [x] T6 金标 release 目录与 manifest（G3）
- [x] T7 eval runner + 指标 + 报告（G4）
- [ ] T8 用 13 产品跑出 gs-v0.1，产出 manifest 与 disputed 清单
- [ ] T9 更新 HANDOFF、05 文档如有口径修正

状态：T1~T7 开发完成（2026-07-11）。验证：ruff ✅ · mypy strict ✅ · pytest 62 passed（含 002 新增 39 个用例）。
T8（用 13 产品跑真实金标 gs-v0.1）与 T9 由主会话执行。
实现备注：eval 的 evidence 准确率经 --dataset-root 对原 PDF 回验（金标目录不另存页文本缓存）；分红型跨险种扩展并入 whole-life/term-life/annuity/endowment/supplementary-pension 五个险种；基线中文字段无英文名时 field_id 为 zh_<hash> 稳定占位，正式英文名补齐走 schema 升版。
设计增量：无独立 design.md，实现完全遵循 docs/insurance-kb/05；PDF 解析选型若超出 08 清单需先修订 08。

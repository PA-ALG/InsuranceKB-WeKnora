# 007 任务

- [x] T1 SDD：specs/mainchain.md（从 proposal 四段推导验收条款）+ 本任务拆解
- [x] T2 知识域 ORM（knowledge/tables.py）+ Alembic 0002 迁移（K1）
- [x] T3 pred JSONL → Claim 导入器 + 记录级/批级幂等（K2）
- [x] T4 增量合并引擎：五种 ChangeItem + 03 §6.2 裁决序 + claude-session 裁决队列占位 + 翻案（K3）
- [x] T5 审核门禁：ReviewItem 稳定 ID + approve/reject/defer + 低风险 enrich 自动通过策略（K4）
- [x] T6 页面编译 + WeKnora 发布器 + ReleaseSnapshot/回滚（K5，respx 全 mock）
- [x] T7 端到端两批材料故事测试（K6）
- [x] T8 门禁全绿（K7）+ HANDOFF 更新

状态：T1~T8 完成（2026-07-12）。测试 34 个（tests/test_knowledge_*.py，spec K1~K6 一一对应）；
门禁 `ruff check .` / `mypy src tests`（strict）/ `pytest -m "not live" -q` 全绿（192 passed），
既有测试零破坏；不改 compiler/、goldenset/ 既有文件；pyproject 零新增依赖。
live 契约用例 `test_k5_5_live_publish_and_rollback_roundtrip`（-m live）留遗留清单，待 WeKnora
测试实例（docker compose）可用后执行。

设计增量：无独立 design.md；数据模型/裁决序以 docs/insurance-kb/03 为唯一权威，
本 change 已先行修订 03（pending_judge、schema_version 串、source_kind 幂等键、
rendered_pages 物化、④ 裁决 claude-session 队列化），实现与文档一致。

红绿循环裁决记录（2026-07-12）：高风险字段的 **add** 也不自动应用（03 §2.5 "add 低风险自动应用"
的对偶推论）——三个高风险测试首批需先 approve 才能形成 published 基线，判定实现正确、改测试。

# 008 · 审核工作台最小版（workbench MVP）

> 状态：提案（2026-07-12）。**实现由其他模型接手**（遗留清单 B 类）——本提案即交接物，含足够的实现指引。
> 设计权威：docs/insurance-kb/03（ReviewItem/ChangeSet/权威序）、08（选型：FastAPI + Jinja2 + HTMX）、master plan P0-5/P1-1。

## 为什么做

007 交付了审核门禁的数据与状态机（ReviewItem、ChangeSet、conflicts、快照），但操作只有 CLI。专家审核、冲突处理、缺口查看需要一个**对人友好的最小界面**——这也是"对人像真实 wiki 一样友好"目标里"确认/审核"的那一半（阅读那一半在 WeKnora Wiki 界面）。

## 做什么（四个页面，MVP 只读+四个动作）

1. **审核队列页**：待审 ReviewItem 列表（按产品/风险等级/类型筛选），单条视图=字段+候选值+证据对照（原文引文+页码，可跳 PDF 页）+ 裁决历史；动作仅四个：approve / reject / defer / 批量 approve（低风险）。动作走 007 的 review 服务，全部留痕；
2. **冲突与变更页**：ChangeSet 列表 → change_items 明细（add/enrich/supersede/conflict/retract 分色），conflict 展示双方证据与自动裁决依据（权威序留痕），支持翻案（=发起新 ChangeSet，走审核）；
3. **完整度矩阵页**：产品 × schema 字段的填充率热力矩阵（present/absent/unknown/冲突/待审 分色），点格子下钻到 Claim 与证据——这就是缺口清单（01 §2#4 的落地）；数据源：claims 表聚合 + eval 报告；
4. **发布与回滚页**：release_snapshots 列表、当前指针、diff 摘要；回滚按钮（二次确认 + dry-run 预览，遵循 12 #5 规范）。

## 技术要求

- FastAPI + Jinja2 + HTMX（08 已选型），落点 `harness/src/insurance_harness/workbench/`（001 已占位）；只读 harness DB + 调用 007 的服务层函数，**不得绕过服务层直写表**；
- 鉴权 MVP：单一共享 token（企业 SSO 对接列后续）；审计：每个动作记 operator 字段；
- 测试：服务层动作用例复用 007 的夹具；页面用 FastAPI TestClient 断言关键元素；门禁同既有标准；
- 零模型调用。

## 不做什么

- 不做 schema 编辑器（P1-3 后续）、不做 QA 管理（P1-2）、不做金标复核界面（可复用本框架后续加）；不改 WeKnora 前端。

## 验收

用 007 端到端故事的数据库夹具起服务：审核队列可见高风险冲突项 → approve 后 ChangeSet 状态流转正确且页面反映；完整度矩阵与 claims 聚合一致；回滚 dry-run 显示 diff、apply 后指针回切。门禁全绿。

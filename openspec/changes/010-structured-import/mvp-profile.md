# 010 MVP Thin Profile（不代表完整 010 完成）

> 适用范围：2026-07-21 批准的 23-entry 受控输入 MVP。完整 I1～I9 与 T5～T12 继续保留在企业 M2；本页只冻结本轮可独立验收的子集。

## Schema profile 与 behavior profile

本 MVP 只收窄运行时 behavior，不得缩减已经固定给迁移 `0007` 的数据库合同。若本轮创建 `0007`，它 SHALL 一次安装 I4/I7/I9 的完整前向兼容 DDL（包括结构化 SourceRevision 绑定、M:N batch association、ChangeSet mapping/fingerprint 约束、qa_staging、v2 read model 与所有 downgrade guards）。存在暂未启用的表/列/约束不代表相应 M2 服务行为已完成；禁止先应用 partial `0007`、以后原地改写。

## 本轮必须交付

1. 复用已完成的 T1～T4：Space、产品主数据 bootstrap、来源登记、已确认 mapping/effective version；
2. 只接受一个批准、版本化的 known-schema JSON profile，不做未知 schema 推断、CSV/API 通用连接器或 mapping 草案审批 UI；
3. 创建完整前向兼容 `0007` schema；已知 schema adapter 把每条记录绑定到可重构的公共 `SourceRevision`，Evidence 通过 `structured_record_id` 指向该冻结 revision，保留 `source_system / external_record_id / source_revision / record_locator / record_hash / mapping_version`，禁止伪 page/chunk；
4. 结构化事实断言经 `ProposedClaim → MergeEngine → ChangeSet/Review → ReleaseSnapshot`，不得直写 published Claim；
5. 记录级幂等键与内容 hash collision fail closed；同一 SourceRevision 重放零知识/业务 mutation（若复用 append-only lifecycle audit，可追加明确 idempotent decision，不得产生新 record/Evidence/ChangeSet/Claim）；
6. 发布快照冻结 structured provenance，Reader 发布后零回查源记录；
7. 原始 FAQ `question/answer` 只进入 staging/留存，不参与 current facts；只有输入中显式存在且通过批准 mapping 的 `fact_assertions[]` 才能形成 Claim 候选。最终 snapshot 对这些 fact assertions 可追溯到 FAQ structured record；这不等于 012 QA 已交付。
8. 为 028 单一 manifest dispatcher 提供 additive exact-entry API：产品注册只接收明确 `product_meta` path+sha256，完整 preflight 后精确注册且不扫描 root/sibling/PDF；registered structured import 只接收明确 record ref+sha256、source authority/schema/profile 与 mapping manifest/effective version，完整 preflight 后调用本页同一治理服务。两条通道都返回 canonical receipt/count/hash，零 `CompilationJob`/模型调用；任何 extra/skipped/hash drift 在首写前 fail closed。

## 本轮明确后置

- 未知 schema 自动映射、CSV/API、mapping 变化受控重算全矩阵；
- generalized mapping-change reprocessing、多批次运行时编排和十万条压力测试；`structured_import_batch_records`、I9 constraints 与 `qa_staging` schema 仍必须随 `0007` 创建；
- qa_items/FAQ 发布与完整 QA 服务；
- FAQ 语义去重、派生 QA、问答检索和 FAQ 页面；
- 完整 structured import CLI/运营工作台。

## 状态口径

MVP 通过时分别报告：`0007 schema contract=PASS`、`010 known-schema thin behavior=PASS`、`010 full I1～I9/T6～T12=PARTIAL`。不得因 schema 已存在就勾选未实现的 M2 行为。

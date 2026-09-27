# WeKnora 0.8.2 与 Harness 插件适配实施计划

> 使用 superpowers:executing-plans 逐项执行；已有设计/执行授权，不再重开选择流程。

**Goal:** 保留G3.5真实成果并将平台升级到固定v0.8.2，形成可保留领域插件接缝。
**Architecture:** 原生平台负责来源/发现算法/唯一Release；Harness负责领域准入/审核授权。沿已有REST及lifecycle接缝适配，不添加平行编排。
**Tech Stack:** Go、Python Harness、Vue、现有PostgreSQL迁移和组件构建入口。

详细Owner/范围/要求与checkbox队列以 OpenSpec 130 为唯一执行记录。

- [ ] 模型迁移：读取新runtime.Resolve/Connection与旧model配置，验证model ID、remote_model_name、凭据及自定义headers不漂移。既有dispatch/no-retry测试先移植到新api.Endpoint边界，旧文件删除；运行go test ./internal/models/... ./internal/types。
- [ ] 数据迁移：核实versioned与enterprise双ledger、上游076—110及破坏性SQL，先脚本/合同RED再改入口；实际恢复在既有测试环境验证，不碰生产数据。
- [ ] 来源兼容：保留knowledge_revision_source、g3_platform_source_snapshot、citation_revision合同，运行相关service/repository/router测试，已有快照不重解析。
- [ ] 上游合并：使用no-commit固定合并，逐冲突保留产品不变量并采用新原生接口，自动合并路径也按受影响合同检查。
- [ ] 插件边界：复用product_ingestion平台client、原生操作与release接缝，确认同一Harness在旧/新合同fixture通过，Schema改动不需Go构建。
- [ ] 前端/构建：保留业务挂载点、读取/来源UI；type-check、相关tests/build；集中构建受影响组件，禁止逐症状部署。
- [ ] 冻结树独审及必要修复；交付前精确记录源码、制品、配置、迁移/恢复方案。真实窗口仅沿已授权范围，未授权外发集中确认。
- [ ] 原生来源→发现→准入→审核/唯一发布→检索/原文点击；报告费用/重用/未知结果与G4接续条件。

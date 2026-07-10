# 保险知识图谱企业部署指南

> **维护者**：项目团队
> **最后更新**：2026-07-06
> **对应版本**：v0.5.0+

---

## 一、项目定制化开发概览

本项目基于开源 [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) 进行了保险领域深度定制化开发，从通用桌面知识库演变为保险行业专业知识图谱系统。

### 1.1 与开源版本的关系

| 维度 | 开源 llm_wiki | 本项目定制 |
|------|--------------|----------|
| 架构继承 | 三层架构（Sources → Wiki → Schema）、Two-step CoT ingest | ✅ 保留并增强 |
| 知识图谱 | sigma.js + 4-signal relevance | ✅ 自研 relation-index + 保险领域知识图谱 |
| 部署形态 | Tauri 桌面应用 | 🔄 改为 Web 服务（Rust 后端 + 前端 SPA） |
| 向量检索 | LanceDB 可选 | ✅ 修复为 1152 维完整维度 + 完整协议 |

### 1.2 定制化功能矩阵

#### 保险领域深度改造

| 改造项 | 实现文件 | 功能说明 |
|--------|----------|---------|
| 知识域体系 | `knowledge-schema.ts` | 8 大保险知识域：`product`（服务权益）、`product_catalog`（险种产品库）、`method`、`cases`、`customer`、`compliance`、`content`、`activity`、`general` |
| 强类型 Schema Registry | `insurance-schema-registry.ts` | 定义保险实体：`service_plan`、`service_benefit`、`product_overview`、`product_comparison`、`rate_table` 等 |
| DomainSkill 插件架构 | `knowledge-domain-skill.ts` | 跨险种可插拔扩展架构，已实现 `HealthServiceSkill` |

#### 抽取架构重写

| 功能 | 实现文件 | 说明 |
|------|----------|------|
| Section-Scan 架构 | `product-catalog-extractor.ts` | OCR全文 → Section拆分 → Group-round LLM抽取 → 注入原文 → Phase 5精炼 |
| 四级 PDF 提取 Pipeline | `backend/src/handlers/fs.rs` | 内部OCR → pdf-extract → pdftotext → 图片marker fallback（含乱码检测） |
| 模块化产品抽取 | `product-catalog-modules.ts` | 按险种白名单提取，支持不同险种的字段差异 |
| 批量导入服务端编排 | `backend/src/handlers/ingest.rs` | `POST /api/ingest/batch/*` 接口，Node worker 复用前端抽取逻辑 |

#### 知识治理与更新闭环

| 功能 | 实现文件 | 说明 |
|------|----------|------|
| 知识冲突检测 | `conflict-detector.ts`、`diff-engine.ts` | 检测字段级冲突，支持新旧值对比 |
| Review 系统 | `review-view.tsx`、`review-persistence.ts` | 人工审核队列，支持"采用新值/保留旧值" |
| 知识演化追踪 | `evolution-panel.tsx` | 读取已解决 review 记录，展示知识变更历史 |
| 来源追踪与清理 | `product-catalog-sync.ts` | 字段页支持 `value_sources` + `sources[]`，删除时按来源清理独占字段 |

#### 部署架构变更

| 变更项 | 说明 |
|--------|------|
| 从 Tauri 桌面到 Web 服务 | Rust 后端 `backend/src/main.rs`（8081端口）+ 前端 SPA |
| Docker 20 交付 | `deployment/releases/llm-wiki-linux-amd64-docker20/` 已包含完整部署脚本 |
| 向量检索修复 | 从 384 维硬编码改为动态 1152 维，前后端协议对齐 |

---

## 二、企业生产环境部署亟需优化

### 2.1 P0 优先级（必须在生产部署前完成）

#### 多租户与权限体系

| 问题 | 风险 | 建议方案 |
|------|------|---------|
| 当前项目按路径全局共享，无用户隔离 | 数据泄露、误操作 | 新增多租户 schema：`tenant_id` + `project_id` 二级隔离 |
| 无鉴权体系 | 未授权访问 | 接入 OAuth2 / SSO，API 网关鉴权，`backend/src/main.rs` 加 auth layer |
| 无 RBAC 权限控制 | 权限滥用 | 定义角色：`viewer`、`editor`、`owner`、`admin`，权限粒度到项目/操作 |

#### 并发控制与数据一致性

| 问题 | 风险 | 建议方案 |
|------|------|---------|
| 多用户同时写入同一项目可能冲突 | 数据损坏 | `project-mutex.ts` 已提供基础互斥锁，需扩展为分布式锁（Redis/etcd） |
| 批量导入缺少幂等性 | 重复处理 | 增强 `idempotency_key` 机制，保证重复请求安全 |
| 索引更新与读取无隔离 | 查询不稳定 | 引入读写分离，增量更新使用双缓冲切换 |

#### 可观测性与生产级日志

| 问题 | 风险 | 建议方案 |
|------|------|---------|
| 当前缺少结构化日志 | 问题排查困难 | 引入 tracing / slog，日志输出 JSON 格式，含 trace_id、tenant_id、project_id |
| 缺少监控指标 | 无法感知系统健康度 | 暴露 Prometheus metrics：ingest QPS、rag latency、error rate、索引大小 |
| 缺少告警机制 | 故障无法及时发现 | 关键指标告警：rag latency > 5s、error rate > 5%、磁盘空间 > 80% |

### 2.2 P1 优先级（建议在第一阶段迭代完成）

#### 索引性能与规模化

| 问题 | 风险 | 建议方案 |
|------|------|---------|
| 当前 token 检索在 Rust 端仍可能扫描全部 md（过渡方案） | 查询延迟随数据量增长 | 尽快迁移到 SQLite FTS5 或 Elasticsearch |
| 图索引在项目打开时重建 | 启动慢、体验差 | 持久化图索引到 SQLite，增量更新而非全量重建 |
| LanceDB 在大项目上的性能未知 | 扩展性风险 | 压力测试 >100k chunks，必要时迁移到 Qdrant / Milvus |

#### HTTPS 与安全加固

- **反向代理**：部署时强制 HTTPS（nginx / traefik）
- **路径安全**：已在 `ingest.ts` 做路径安全检查，需确保所有 Rust handler 都有 project path guard
- **敏感信息**：API keys、embedding endpoints 不应进入前端，统一由后端管理

#### 备份与恢复

| 需求 | 建议方案 |
|------|---------|
| 数据定期备份 | 自动备份 wiki 目录 + LanceDB + review 数据到对象存储 |
| 灾难恢复演练 | 定期执行恢复演练，RPO/RTO 指标定义 |
| 版本历史 | 重要知识页支持版本历史，可回滚 |

### 2.3 P2 优先级（中长期规划）

#### 水平扩展与高可用

- **无状态化**：Rust 后端可多实例部署，共享存储（NAS/对象存储）
- **读写分离**：查询走只读副本，ingest/update 走主实例
- **降级开关**：embedding / LLM / 向量检索支持独立降级，保证核心功能可用

---

## 三、实施路线图建议

### 3.1 第一阶段（生产可用）

目标：满足最小企业级生产要求

| 任务 | 预计工时 | 依赖 |
|------|---------|------|
| 多租户 schema 设计与实现 | 2w | - |
| API 鉴权层（OAuth2/SSO） | 1w | 多租户 schema |
| 基础 RBAC 权限控制 | 1w | 鉴权层 |
| 结构化日志 + Prometheus metrics | 1w | - |
| 关键告警规则配置 | 0.5w | metrics |
| SQLite FTS5 token 索引 | 2w | - |

**总计**：7.5w

### 3.2 第二阶段（体验优化）

| 任务 | 预计工时 | 依赖 |
|------|---------|------|
| 图索引持久化与增量更新 | 1w | - |
| HTTPS 反向代理配置 | 0.5w | - |
| 自动备份与恢复 | 1w | - |
| 分布式锁替代 project-mutex | 1w | 多租户 |

**总计**：3.5w

### 3.3 第三阶段（规模化）

| 任务 | 预计工时 | 依赖 |
|------|---------|------|
| 无状态化改造 + 多实例部署 | 2w | 一、二阶段 |
| 读写分离 | 1w | 无状态化 |
| 降级开关体系 | 1w | - |
| LanceDB → Qdrant/Milvus（如需要） | 2w | 压力测试验证 |

**总计**：6w

---

## 四、当前 Docker 部署现状

项目已提供 `deployment/releases/llm-wiki-linux-amd64-docker20/` 交付物，包含：

- ✅ Docker 镜像构建
- ✅ docker-compose.yml 部署模板
- ✅ Poppler PDF 工具链
- ✅ 内部 OCR 集成
- ⚠️ 缺少多租户/鉴权（本指南 P0）
- ⚠️ 缺少结构化日志/监控（本指南 P0）

**当前部署验证**：
- 容器 smoke test 通过
- 首页 200、`/api/health` 正常
- 运行时 LLM/Vision/Embedding 配置可读取

---

## 五、关键架构约束

### 5.1 数据路径

```
WIKI_DATA_PATH/
  ├── tenant-xxx/          # 多租户后新增
  │   ├── project-aaa/
  │   │   ├── wiki/
  │   │   ├── raw/
  │   │   ├── .llm-wiki/
  │   │   └── .lancedb/
  │   └── project-bbb/
  └── tenant-yyy/
```

### 5.2 API 安全

- 所有 Rust handlers 必须通过统一 project path guard
- 禁止前端直接读取 LLM API keys、embedding endpoints
- `isSafeIngestPath()` 已提供路径注入防护，复用此机制

### 5.3 索引更新策略

- ingest 后自动刷新索引
- 增量更新优先，全量重建降级为后台任务
- 索引版本与项目 dataVersion 绑定

---

## 六、总结

当前项目已从通用知识库演变为**保险领域专业知识图谱系统**，核心优势是强类型 schema 驱动的高准确率抽取。

但从桌面应用到企业生产部署，仍需补全以下企业级能力：

**P0（必须完成）**：多租户、鉴权、可观测性、并发控制

**P1（建议完成）**：索引性能、HTTPS、备份

**P2（中长期）**：水平扩展、高可用

建议按 P0 → P1 → P2 顺序实施。

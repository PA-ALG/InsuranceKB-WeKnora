> [!WARNING]
> **SUPERSEDED / HISTORY-ONLY（D0，2026-07-26）**：本文件仅保留历史证据，不再是可执行路线，不得继续实现、重放或复用其中的运行时与迁移安排。当前权威设计见 `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`。

# 032 Human Wiki Reader MVP 验收规格

## ADDED Requirements

### Requirement: HR1 独立只读产品 Wiki

Human Wiki Reader SHALL 是独立于 008 审核工作台的只读消费面，提供产品目录与产品页；页面 SHALL 展示产品/版本身份、当前批准 `snapshot_id`、`manifest_hash`、按 schema 分组的事实和 Evidence 摘要。它不得提供任何审核、发布、回滚或知识写端点。

#### Scenario: 路由表零写操作

- **WHEN** 枚举 Human Wiki Reader 的全部 HTTP 路由
- **THEN** 只有只读 GET/HEAD 路由，不存在审核、发布、回滚或任意业务写端点

### Requirement: HR2 只读批准快照

所有业务事实 SHALL 只由 029 `ApprovedSnapshotReader` 返回；Human Wiki Reader 不得直读 mutable Claim、ReviewItem 或原始 Source 表补正文。当前 snapshot 无有效完整 manifest approval 时 SHALL 返回类型化 unavailable，不显示候选知识。

#### Scenario: 候选 Claim 不可见

- **WHEN** 当前数据库存在尚未进入批准 snapshot 的新 Claim 候选
- **THEN** 产品页继续显示批准 snapshot 的冻结事实，且候选值不可见

### Requirement: HR3 Space 与身份 fail closed

每个请求 SHALL 由服务端 token 绑定 principal 与允许的 KnowledgeSpace；未鉴权返回 401，越 Space 返回常量 403，未知产品/跨 Space 产品均返回不可区分的 not-found。响应不得泄露其他 Space 的产品、snapshot 或 manifest 存在性。

#### Scenario: 跨 Space 不泄露

- **WHEN** Space A 的 token 请求只存在于 Space B 的产品页
- **THEN** 返回与不存在产品相同的 not-found，响应不含 B 的任何标识

### Requirement: HR4 Evidence、缺口与免责声明

每个展示事实 SHALL 带来源类型、可核验 Evidence 摘要与稳定 claim/fact 标识；结构化 Evidence 不得伪造页码/chunk。缺失或无适用版本 SHALL 展示 typed gap 与“未收录不等于不存在”；页面 SHALL 展示 purpose 配置的免责声明。

#### Scenario: 结构化来源不伪造文档定位

- **WHEN** 产品事实来自 source_kind=structured
- **THEN** 页面展示 source system、external record/revision/locator/hash，而不显示伪页码或伪 chunk

### Requirement: HR5 与 Agent 同快照合同

对同一 Space、产品、日期和字段过滤，032 与 013 SHALL 通过同一个 serving service 得到相同 `snapshot_id`、`manifest_hash` 和 canonical fact 集；呈现格式可以不同，但不得各自回查或重算事实。

#### Scenario: 人与 Agent 的 canonical facts 一致

- **WHEN** 032 产品页与 013 `get_product_facts` 查询同一请求
- **THEN** 两边的 snapshot、manifest 和 canonical fact identity/value 集完全一致

### Requirement: HR6 P-1 前内部预览边界

032 SHALL 明确标识为批准快照的 Harness 内部阅读面；P-1 不存在时不得调用 WeKnora 普通用户可见 Wiki 写接口，也不得宣称生产 Wiki UI 已发布。

#### Scenario: Reader 请求零 WeKnora 写入

- **WHEN** 读取目录或产品页
- **THEN** WeKnora writer fake 的调用次数为零，响应带内部预览标识

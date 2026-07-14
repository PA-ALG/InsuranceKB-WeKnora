# 016 规格（验收条件）——KnowledgeSpace 与强制作用域

## S1 KnowledgeSpace 模型

- S1.1 新增 `knowledge_spaces`：id、tenant_id、raw_kb_id、wiki_kb_id、name、binding_status；unbound 时三个绑定字段必须全部 NULL，bound 时必须全部非空；bound 行的 `(tenant_id, raw_kb_id)` 与 `(tenant_id, wiki_kb_id)` 唯一；
- S1.2 新增不可变值对象 `KnowledgeScope(space_id, tenant_id, raw_kb_id, wiki_kb_id)`；只有从数据库加载的 bound Space 可以构造，服务不得从全局设置补省略的 scope；unbound 数据只能由 migration/admin API 按 space_id 操作；
- S1.3 `binding_status=unbound` 的 Space 只允许离线迁移/检查，不允许 WeKnora 读取、Wiki 发布与在线 Snapshot 读取。

## S2 数据隔离

- S2.1 InsuranceProduct、ProductDocument、UnassignedItem、Claim、ChangeSet、ReviewItem、ReleaseSnapshot、CurrentRelease 直接持有 `space_id`；
- S2.2 ProductAlias/ProductVersion/Evidence/Revision/ChangeItem/Conflict/SnapshotClaim 通过父外键继承空间，跨空间父子关联在服务层和数据库约束可表达处均拒绝；
- S2.3 所有仓储/服务入口显式接收 scope，查询条件必须含 `space_id`；通过裸 ID 访问另一空间对象返回 not found/ScopeViolation，不泄漏对象是否存在；
- S2.4 产品编码、ChangeSet 幂等键、review_key、release label 和 current pointer 均改为空间内唯一；
- S2.5 tenant A/B 可创建相同业务键，列表、合并、审核、发布和回滚结果互不影响。

## S3 迁移

- S3.1 0001/0002 现有库升级到新 migration 后数据不丢失，历史行归入唯一 `legacy-default` Space；
- S3.2 legacy Space 默认为 unbound 且三个绑定字段为 NULL；CLI `scope bind` 要求 tenant/raw/wiki 三项显式输入，在单事务中校验唯一、写三项并切为 bound，任一步失败保持原 unbound；
- S3.3 新装空库不自动创建可用于生产的默认 Space；
- S3.4 downgrade 只支持“数据库中仅有 legacy-default 一个 Space，且 scoped 业务键折叠后满足 0002 全局唯一约束”的状态；否则迁移在执行 DDL 前给出冲突清单并拒绝，绝不丢数据。满足前置条件时可恢复 0002 结构。

## S4 API 与安全

- S4.1 WeKnora adapter 调用前校验 scope 已绑定；
- S4.2 WeKnora knowledge 响应的 tenant/KB 与 scope 不一致时抛 `ScopeViolation` 并不返回内容；
- S4.3 日志与 run manifest 包含 space_id、tenant_id、raw_kb_id，但不记录 token/API key。

## S5 工程门禁

- S5.1 migration、ORM、注册/路由、merge、review、publisher 的双空间测试覆盖相同业务键与越权访问；
- S5.2 既有单空间测试通过显式测试 scope 迁移，不保留生产代码中的隐式默认；
- S5.3 Ruff、mypy、非 live pytest 全绿。

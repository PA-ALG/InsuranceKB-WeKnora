# 016 增量设计

权威设计：`docs/insurance-kb/20-enterprise-runtime-foundation.md` §3。

## 数据模型

`KnowledgeSpace` 放在 `db/models.py`，作为产品域与知识域共同依赖的基础模型。unbound 行的 tenant/raw/wiki 三列均为 NULL，bound 行三列均非空，以 CHECK + bound 值唯一约束保证。`KnowledgeScope` 放在新的 `db/scope.py`，是冻结的 Pydantic 值对象；加载时必须从数据库中的 bound Space 构造，不能只信任调用方拼接的 tenant/KB。

聚合根直接持有 `space_id`，主要查询以 `(space_id, id)` 或 `(space_id, business_key)` 进行。子对象仍使用现有父外键；服务取得父对象后核对其 `space_id`，避免为了本 change 给所有子表重复加列。

## 迁移

0003 分三个可回滚阶段完成：

1. 创建 `knowledge_spaces`，给受影响表加 nullable `space_id`；
2. 若存在历史数据，创建固定 ID 的 `legacy-default` unbound Space 并回填；空库不创建；
3. 重建唯一约束、设 `space_id NOT NULL`，将 `current_release` 改为以 space_id 唯一。

SQLite migration 测试覆盖 upgrade/downgrade；空库可以无损回退，多 Space、非 legacy Space 或全局键冲突则在 DDL 前拒绝，不尝试有损折叠。生产启动检查发现 unbound Space 时，产品注册、路由、live bridge、publish 等所有普通业务入口均 fail closed，但管理员仍可执行 list/show/bind。

## 服务改造顺序

先改产品注册/路由，再改 knowledge importer/merge/review，最后改 publisher。每一步用双 Space 测试保持可运行。共享 helper `require_scoped_row()` 统一实现“另一 Space 的 ID 视为不存在”，不在各模块散落不同异常语义。

## 取舍

- 首版不引入 PostgreSQL RLS，避免同时改变部署角色模型；应用层强制 scope + scoped unique/FK 是本 change 的验收边界；
- 不使用默认 tenant/KB 配置兼容旧调用。测试 fixture 显式创建 scope，确保新接口无法被遗漏。

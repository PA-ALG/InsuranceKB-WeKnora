# 016 · 企业 KnowledgeSpace 与强制作用域

## 为什么做

WeKnora 已提供 tenant/KB ACL，但 Harness 的产品、Claim、ChangeSet、审核项和发布指针仍是全局数据模型。若直接接入企业多租户，同编码产品、同 release label 或同 review key 会冲突，查询也可能跨租户返回数据。

## 做什么

1. 新增 `KnowledgeSpace`，显式绑定 WeKnora tenant、KB-RAW 与 KB-WIKI；
2. 所有 Harness 聚合根增加 `space_id`，服务入口统一接收 `KnowledgeScope`；
3. 全局唯一约束改为空间内唯一，CurrentRelease 改为每空间一条；
4. 提供历史单租户数据的两阶段迁移与显式 bind 流程；
5. 加入跨空间越权测试，默认 fail closed。

## 不做什么

- 不实现企业 SSO UI；身份仍由 WeKnora token/API key 提供；
- 不实现批量 worker 与 advisory lock（014）；
- 不接 WeKnora 文档编译，留给 017。

## 影响面与文件域

- 组件：产品域、知识域、数据库迁移、WeKnora adapter 调用前置校验；
- 硬边界：保险逻辑进 Go/Vue = 0；WeKnora API 细节仍只在 `adapters/weknora/`；
- Schema/Golden：不改变寿险字段 schema 和 Golden 口径；只改变运行数据的隔离键；
- 主要文件域：`harness/src/insurance_harness/db/`、`product/`、`knowledge/`、`config.py`、对应 tests 与 migration；
- 与其他 change：016 实施期间 017/018 不得并行修改上述目录；019 仅可先做 `goldenset/` 内不依赖 merge 的部分。

## 验收故事

创建 tenant A/B 两个 Space，各自注册相同 `product_code`、相同 release label；二者均成功且互不可见。使用 A 的 scope 查询或发布 B 的对象时被拒绝。历史数据迁移到 unbound Space 后不能执行 live 发布，显式绑定后恢复。

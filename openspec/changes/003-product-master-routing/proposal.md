# 003 · 产品主数据与文档分类路由（S1，master plan P0-1）

## 为什么做

"一份文件涉及多个产品、实体对齐不准"是业务方排第一的技术难题（01 §2#1）。解法的地基是**产品主数据**（稳定 ID + 别名 + 版本）和**确定性优先的对齐**：备案文号/planCode/标准名精确匹配 → 别名匹配 → 才轮到向量/LLM 候选。这也是抽取管道（004+）一切事实归属的前提。本 change 同时引入 Harness 自有 PostgreSQL（03 §7 的第一批表）。

## 做什么

1. **Harness DB 基础**：SQLAlchemy + Alembic 初始化；docker-compose 开发库；首批迁移：`insurance_products`、`product_aliases`、`product_versions`、`product_documents`（03 §7 草案的产品域子集，含 up/down）；
2. **产品主数据服务**：从 `product_meta.json` 批量注册产品（planCode=稳定业务键、versionNo、备案文号、销售状态/渠道、生效日期）；别名管理（产品简称/别称/曾用名）；
3. **文档分类器**：输入解析后文本 → 文档类型（条款/产品说明书/费率表/FAQ/宣传材料，确定性特征优先：备案文号页眉、"费率表"表头、条款章节结构；LLM 只兜底）+ 险种判定（加载 002 的 schema 注册表选 profile）；
4. **产品路由器**：文档/章节 → `product_candidates[]`（多产品文档允许一对多）；置信分级：exact（备案文号/planCode 命中）/ alias / fuzzy（LLM 候选）；fuzzy 与同分候选**不自动归属**，进 `unassigned` 候选池（表 + 导出清单）；
5. CLI：`register-products`（吃 dataset/shouxian_product）与 `classify`（对样本 39 个 PDF 跑分类+路由，输出报告）。

## 不做什么

- 不做字段抽取（004）；不做 ChangeSet/审核（005+）；不做 WeKnora 写入；不做人工确认 UI（unassigned 只出清单）。

## 验收

- 13 产品注册成功且幂等（重跑不重复建）；
- 样本 39 个 PDF：文档类型分类准确率 100%（类型特征极强）；产品路由 exact 命中率 ≥ 90%（文件都在产品目录内，有 meta 对照可自动评分）；
- 构造一份拼接的多产品测试文档：各章节路由到正确产品，混淆章节进 unassigned 而非错挂。

## 影响面

- 新增依赖：sqlalchemy、alembic、psycopg；docker-compose.harness.yml（独立文件，不动上游 compose）；
- 硬边界不受影响。依赖：002（schema 注册表）。

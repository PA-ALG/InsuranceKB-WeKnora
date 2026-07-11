# 003 规格（验收条件）

## P1 DB 基础

- P1.1 `alembic upgrade head` 在空库建出 insurance_products / product_aliases / product_versions / product_documents；`downgrade base` 干净回退；
- P1.2 表结构与 03-knowledge-model.md §7 一致（业务键：products.plan_code 唯一；aliases(product_id, alias) 唯一；versions(product_id, version_no) 唯一）；
- P1.3 docker-compose.harness.yml 一条命令起 dev Postgres；连接串走 HarnessSettings。

## P2 产品注册

- P2.1 `register-products <dir>` 扫描产品目录（product_meta.json/.txt 均兼容），注册产品+版本+文档登记；幂等：重跑零新增、变化字段（如销售状态）更新并记 updated_at；
- P2.2 meta 缺失/损坏的目录跳过并入报告，不中断批次；
- P2.3 产品名、条款名自动生成初始别名（全名/去括号名/简称规则），可追加人工别名。

## P3 文档分类

- P3.1 分类器输出 DocumentType(条款/产品说明书/费率表/FAQ/宣传材料/未知) + 险种 + 置信度 + 判定依据（命中的确定性特征或 LLM 理由）；
- P3.2 确定性特征命中时不调用 LLM；39 个样本 PDF 全部零 LLM 调用完成分类且正确（类型可由文件名+内容特征双验证）；
- P3.3 未知类型不猜测，标 unknown 待人工。

## P4 产品路由

- P4.1 路由器输入（文本, 页码范围）→ [ProductCandidate(product_id, confidence: exact|alias|fuzzy, 依据)]；
- P4.2 exact：备案文号或 planCode 或产品全名精确命中；alias：别名表命中；fuzzy：仅 LLM/相似度候选——**fuzzy 一律进 unassigned 池，不得自动归属**；
- P4.3 同一文档多章节可路由到不同产品（一对多）；
- P4.4 unassigned 池表 + 导出 JSONL（含候选与依据，供未来审核）；
- P4.5 样本自动评分：39 个 PDF 的 exact 命中率 ≥ 90%（以所在产品目录为真值）。

## P5 工程

- P5.1 全部规则逻辑（特征、别名生成、归一化）单元测试；DB 层用 pytest 夹具（临时库或 sqlite 兼容层——若用 sqlite 需声明差异边界）；
- P5.2 ruff/mypy/pytest 全绿，CI 覆盖；LLM 兜底路径用 ReplayClient 夹具测试。

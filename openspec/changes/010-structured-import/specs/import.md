# 010 规格（验收条款，每条对应 pytest 用例）

> **2026-07-16 基础对齐修订**：本规格原写于 016/017 落地之前。新增 I6（Space 作用域与结构化来源身份）。原条款 ID 不变。

## I1 映射器

- I1.1 映射规则为 YAML（source_field → field_id + 变换器名），加载 fail-fast：未知 field_id / 未知变换器 / 重复映射即报错并定位；
- I1.2 内置 product_meta 映射：planCode→险种代码、versionNo→条款版本标识、reportPreparedFileCode→regulatory_filing_no、planSalesStatus→销售状态、startDate→开始使用时间、planSalesChannel→销售渠道（以 dataset 13 份实测全通过）；
- I1.3 值规范化复用 goldenset/normalize + compiler/cleaning：日期多格式→ISO、金额中文单位→数值、枚举同义映射；规范化失败的记录进 staging 报告而非静默丢弃；
- I1.4 未知 JSON 结构：字段名相似度（编辑距离/别名表）+ 值类型推断生成候选映射草案（YAML，带 per-field 置信），落 `mapping-drafts/` 待人工确认；**草案未确认不得用于正式导入**。

## I2 幂等与批次

- I2.1 幂等键 `source_system + external_record_id + source_revision`：同键重导零新增（返回 unchanged 计数）；revision 变化 → 走 007 合并（enrich/supersede/conflict）而非重复建 Claim；
- I2.2 每批次生成一个 ChangeSet；批内记录级失败隔离（单条坏记录不中断批次，入错误清单）；
- I2.3 **dry-run 默认**：输出 记录数/产品匹配率/未匹配清单/缺字段/预计 add-enrich-supersede-conflict 计数，不落库；`--apply` 才执行且报告与 dry-run 预测一致（同一输入差异=0）；
- I2.4 原始记录快照留存（审计），data_quality=structured_direct，权威等级按来源配置（官网同步/系统数据）。

## I3 产品对齐

- I3.1 记录级产品对齐复用 003 路由器（planCode exact 优先）；对不上的记录进 unassigned 池，**不自动挂靠**；
- I3.2 一条记录含多产品字段（如对比表）→ 拆分为多产品 Claim（一对多）。

## I4 FAQ 通道

- I4.1 FAQ 输入（问题/答案/关联产品）落 qa_staging 表（012 前的暂存），字段：问题、答案、product_id、来源、external_record_id；幂等同 I2.1；
- I4.2 qa_staging 不参与检索与发布（012 接手后消费）。

## I5 端到端

- I5.1 13 份 product_meta 直入：匹配 100%、重导零新增；
- I5.2 冲突用例：构造 planSalesStatus 变更的新 revision → supersede/conflict 按权威序产生并留痕；
- I5.3 CLI：`python -m insurance_harness.knowledge.import_cli structured <file|dir> [--mapping X] [--apply]`；
- I5.4 零模型调用；门禁全绿（既有测试不破坏）。

## I6 Space 作用域与结构化来源身份（016/017 对齐）

- I6.1 导入一律在显式 KnowledgeSpace 内执行（016 fail-closed）；批次、ChangeSet、qa_staging 记录均带 space；跨 space 业务键互不可见；
- I6.2 结构化来源身份：`source_kind=structured`，来源身份即 I2.1 幂等键（source_system + external_record_id + source_revision）；Evidence 定位 = 记录定位（jsonpath/行号）+ 内容哈希，**不伪造页码/chunk 锚点**；不经 WeKnora bridge，Evidence lineage 按 017 结构落 structured 变体，不得复用 WeKnora revision 字段语义；
- I6.3 Alembic 迁移占号 **0007**（openspec/changes/README.md 注册表已预分配）；若合入时 021（0006）尚未合入，与其负责人协调 down_revision 链序；
- I6.4 021 落地前，同一 source_system + external_record_id 的 revision 更替仅允许**串行导入**（对齐 HANDOFF ⓪-0a 边界）；CLI 帮助文本标注此限制。

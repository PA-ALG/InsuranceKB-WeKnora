# 010 · 结构化知识直入通道（JSON/FAQ → Claim/QA）

> 状态：**已条款化，可认领**（2026-07-16 基础对齐修订：新增 I6 Space 作用域与结构化来源身份；迁移占号 0007；轨道 L4 首件，见 docs/insurance-kb/22）。
> 依赖：007/016/017 已合入 main；不依赖 018（不触发布读路径）。设计权威：master plan P0-2、02 §6 落点映射、13 §2 G4、20（企业运行约束）。业务方需求②原文："已有 JSON 产品知识库/FAQ，要跳过文档解析流程直接融入 wiki，快速补全知识页面（含知识融合与冲突处理）"。

## 为什么做

业务方存量最大、最干净的知识是结构化产品库与 FAQ；直入通道是见效最快的补全路径，且其产物走 007 合并引擎即可自动获得冲突处理与审核。

## 做什么

1. **输入**：JSON/JSONL/CSV/Excel 的产品记录与 FAQ；`product_meta.json` 形态优先支持（已有 13 份样例）；
2. **映射器**：字段映射规则（源字段 → schema field_id，YAML 可配）；内置映射：产品主数据（planCode/versionNo/备案文号…→ 003 产品注册）、产品字段（→ Claim，data_quality=structured_direct，权威等级=官网同步/系统数据）、FAQ（→ QA 候选，012 前先落 qa_staging 表）；
3. **未知 schema 处理**：对未见过的 JSON 结构自动生成候选映射草案（字段名相似度+值类型推断，确定性；LLM 建议可选）→ 人工确认后入映射库复用；
4. **幂等与批次**：`source_system + external_record_id + source_revision` 幂等键（master plan §1.3 指标）；每批次 = 一个 ChangeSet，dry-run 预检（记录数/产品匹配率/缺字段/预计新增更新冲突）默认开启，`--apply` 才生效（12 #5）；
5. **规范化**：日期/金额/年龄段/百分比/枚举统一归一（复用 goldenset/normalize + cleaning）。

## 验收

13 份 product_meta 直入：产品匹配 100%、重复导入零新增；构造一份与已发布 Claim 冲突的 JSON（如销售状态变更）→ 走权威序产生 supersede/conflict 且留痕；dry-run 报告字段齐全。零模型调用。门禁全绿。

## 不做什么

datasource 自动同步（WeKnora 已有入口，对接后续）、FAQ 语义去重（012）。

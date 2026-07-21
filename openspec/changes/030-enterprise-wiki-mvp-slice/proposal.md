# 030 · Enterprise LLM Wiki Real MVP Slice

> 状态：MVP I0/I1，规格待独立复核。它是跨包验收 change，不拥有其他功能域实现。

## 为什么做

项目已有大量组件和测试，但缺少真实多文档纵向闭环。030 固定一个不依赖 13 产品 canonical 020 的小型、真实、可重复 MVP slice，用它证明 LLM Wiki 的产品价值并暴露集成缺口。

## 固定输入

仓内 5 产品 ×（3 PDF + product_meta）=20 份真实来源：

1. 平安e生保（尊享版）医疗保险；
2. 平安e生保（悦享版）医疗保险；
3. 平安盛世金越（尊享版26）终身寿险；
4. 平安盛世金越（尊享版26）终身寿险（分红型）；
5. 平安盛世金越养老年金保险（分红型）。

另建 3 份受控来源：混合产品文档、同产品后续修订/冲突、FAQ JSON。全部记录 provenance/hash。

## 做什么

- 固定 source manifest、rights/provenance、schema/template/model plan 与独立 admission；
- 零模型 contract fixtures 与真实弱模型 run 分离；
- E2E 验证分类/归属、模板、抽取/回验、融合/冲突、人审、manifest/hash 批准、Reader/MCP 同快照、更新、Alert、回滚；
- 出具质量与效率报告。

## 不做

不修改 020 canonical artifacts，不替 S/K/M 修功能，不完成 P-1、13 产品 baseline 或千份并发。

## 文件域

新 `dataset/mvp-*`、030 tests/runbook/artifacts/validation report。功能问题退回原 Owner。

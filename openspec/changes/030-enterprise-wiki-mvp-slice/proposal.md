# 030 · Enterprise LLM Wiki Real MVP Slice

> 状态：MVP I0a/I0b/I1，规格与实施计划已独立复核。它是跨包验收 change；I0b 只拥有窄 run-admission core/profile，I1 不拥有其他功能域实现。

## 为什么做

项目已有大量组件和测试，但缺少真实多文档纵向闭环。030 固定一个不依赖 13 产品 canonical 020 的小型、真实、可重复 MVP slice，用它证明 LLM Wiki 的产品价值并暴露集成缺口。

## 固定输入

仓内 5 产品 ×（3 PDF + product_meta）=20 份冻结输入；其中 PDF 进入编译来源主链，`product_meta` 只走产品注册通道并产生零 Claim/Evidence：

1. 平安e生保（尊享版）医疗保险；
2. 平安e生保（悦享版）医疗保险；
3. 平安盛世金越（尊享版26）终身寿险；
4. 平安盛世金越（尊享版26）终身寿险（分红型）；
5. 平安盛世金越养老年金保险（分红型）。

另建 3 份受控来源：混合产品文档、同产品后续修订/冲突、FAQ JSON。全部记录 provenance/hash。

## 做什么

- 固定 23-entry manifest、rights/provenance、registration/source eligibility、Golden Slice、routing policy、schema/template lock、structured-dispatch lock、model plan/deployment roles、resource caps、clean integration SHA 与独立 admission；
- 在 027 合入后提供最小 parameterized run-admission core + 代码固定的 030 MVP profile：root-protected approver policy 绑定 key fingerprint/真人/role/domain/purpose/schema/Space，实现 027 `AdmissionVerifier` 并签发 opaque `VerifiedAdmission` 供 028 preflight 消费；其 `AdmissionBinding` 仅为只读审计 view；MVP 不开放任意 profile/schema DSL，不修改/借用 020 硬编码 evaluator；
- 签名 envelope、最终 strict request 与 live bundle 全部存放在 Git 外的内容寻址控制目录，绑定 clean integration SHA；仓内只留 unsigned template 与 sanitized digest/index/report，消除批准工件自改 SHA 的循环；
- 零模型 contract fixtures 与真实弱模型 run 分离；
- E2E 验证分类/归属、模板、抽取/回验、融合/冲突、人审、manifest/hash 批准、Reader/MCP 同快照、更新、Alert、回滚；
- 出具质量与效率报告。

## 不做

不修改 020 canonical artifacts，不替 S/K/M 修功能，不完成 P-1、13 产品 baseline 或千份并发。

## 文件域

新 `dataset/mvp-*`、最小 `harness/src/insurance_harness/run_admission/{models,evaluator,trust_policy,cli}.py` 与 `profiles/mvp.py`、030 tests/runbook/unsigned templates/validation report。live control/artifacts 不进 Git；除该 admission core/profile 外的功能问题退回原 Owner。

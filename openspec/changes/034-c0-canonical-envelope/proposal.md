# 034 · C0 Canonical Envelope

> 状态：Wave 1 实施中（总控窗口，2026-07-26）。授权：23 号控制板 §8
> D-2026-07-26-5（主线开发执行模式）；依赖：D0 已合入（PR #34）。
> 权威设计源：
> `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
> §8.4（Canonical serialization 与 digest 合同）与 §16 C0 行。

## 为什么做

033 把所有跨语言、跨进程、长期保存的 identity/digest 收敛到唯一的
`CanonicalEnvelopeV1`。P2a、P5a1、P5a2、P6b（Candidate digest）、Release、
Schema、AutomationScope、EvidenceFragment 和 WeKnora managed-page contract
全部复用这一份规范。若无 C0，各 PR 会各自发明编码规则（历史上
`template_packages` 已有一套自有 domain separator），跨语言（未来 Go 端
W1/P11）与跨版本的 hash 将不可复现。C0 是 CAP0、P2a 的直接前置
（033 §16 DAG）。

## 本 Change 做什么

- 冻结语言中立规范 `CanonicalEnvelopeV1`（新文档
  `docs/insurance-kb/25-canonical-envelope-v1.md`）：JCS/RFC 8785 序列化、
  UTF-8/NFC/LF 文本约束、tagged scalar（date/datetime/decimal）、五个显式
  sentinel（NULL/UNKNOWN/ANY/±∞）、set 排序去重、map 键 UTF-16 码元排序、
  domain-separated SHA-256 hash 框架；
- 交付 expected bytes/hash vectors（`canonical_vectors_v1.json`）：合法用例
  的 exact canonical UTF-8 字节与 SHA-256，以及非法用例的确定性拒绝原因；
  向量的 canonical 字符串为手工按规范编写、hash 由冻结字符串独立计算，
  不由实现生成，保证实现与向量互相独立验证；
- 交付 Python reference codec：新包
  `harness/src/insurance_harness/canonical/`（values/encoder/hashing/errors +
  打包向量），零 harness 内部依赖，纯函数、无 I/O、无 DB。

## 不做什么（非目标）

- 不改 Go/WeKnora fork：Go adapter 只在条件 W1 或 P11 首次消费时实现并跑
  同一 vectors（033 §8.4）；
- 不建领域表、不动 Candidate/Release/Schema 实现、无 Alembic 迁移；
- 不迁移 `template_packages` 的自有 hash：其与 C0 的对账按 24 号处置清单
  由 P6a 合同裁决；
- 不提供"宽松模式"：任何非法输入（float、非 NFC、裸控制符、naive
  datetime、超范围 int、`$` 前缀键）一律 fail closed，不静默归一化可疑输入。

## 影响面

- 新增：`insurance_harness/canonical` 包、向量资源、25 号规范文档、
  本 change、README 台账 034/035 占号；
- 无既有生产代码修改；无迁移；deterministic lane 新增两个测试文件；
- 后续消费者：CAP0（合同 hash）、P2a、P5a1、P5a2、P6b、P8、W1/P11（Go）。

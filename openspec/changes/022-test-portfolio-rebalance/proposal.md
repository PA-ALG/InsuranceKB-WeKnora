# 022 · 测试组合再平衡

## 背景

016/017 已形成 916 个确定性 non-live 测试和 5 个真实基础设施测试，但当前 PR CI 明确排除全部 live；同时 `test_source_bridge_live_017.py` 混放 12 个确定性契约与 1 个 live E2E，两个 source 测试文件超过 1500/2000 行。测试数量证明了大量局部行为，却没有形成 PostgreSQL 并发与 WeKnora 真实回链的自动执行节奏。

## 目标

1. 将 deterministic、PostgreSQL integration、WeKnora live 三类证据拆成显式门禁；
2. 修复 live scope 在测试开始前失去 Engine attestation 的 fixture 生命周期；
3. 拆分混合命名与超大测试文件，保持行为、断言和收集数量；
4. 用 coverage-context 重叠报告辅助判断重复测试，不按 LOC 或异常文案机械删测试；
5. 将完成状态区分为 software complete、integration verified、live verified。

## 非目标

- 不减少 scope/product/knowledge/publisher/client 各 public boundary 的零查询、零写、零 I/O 证明；
- 不在本 change 实现 021 的不同 revision ordering；
- 不把真实 WeKnora 服务强塞进每个 PR；
- 不用覆盖率百分比或测试数量作为单一合并门槛。

## 方案选择

- **A 最小修补**：只修 fixture 和文件名。速度快，但没有 PostgreSQL CI 与客观重叠审计，不能覆盖 P0-P3。
- **B 结构化再平衡（采用）**：三类门禁、按职责拆文件、coverage-context 报告，不删行为。改动以测试/CI/文档为主，风险可控。
- **C 激进减量**：跨模块合并 scope 测试并引入全量 mutation CI。维护成本和误删风险过高，本轮不采用。

## 完成定义

- deterministic 与 PostgreSQL integration 在 PR CI 分 job 运行且均不得依赖外部密钥；PostgreSQL job 使用独立的 `HARNESS_TEST_POSTGRES_URL`，并用 JUnit 证明 selected tests 大于零且 skipped 为零；
- WeKnora live 有显式手工 workflow、冻结的七变量映射和环境 preflight；缺变量或 pytest 内部 skip 时 workflow 失败而不是产生伪成功；
- source bridge 的 12 个 contract 与 1 个 live E2E 分文件；
- 原两个超大测试文件按职责拆分，所有新测试文件不超过 1000 行，原测试收集总数保持不变；
- coverage-context overlap 工具具备确定性单元测试，只报告候选，不自动删除或阻断；
- 全量 deterministic、PostgreSQL integration、Ruff、mypy、diff check 全绿；真实 WeKnora 未配置时必须继续标记 NOT RUN。

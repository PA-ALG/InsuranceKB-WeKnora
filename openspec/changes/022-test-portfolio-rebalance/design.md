# 022 增量设计

## 1. 测试门禁

Pytest marker 分为：

- 无 marker：deterministic unit/contract，PR 主 job 运行；
- `integration_postgres`：只依赖 GitHub Actions PostgreSQL 16 service，PR 独立 job 运行；
- `live`：依赖受控 WeKnora、bound Harness Space 与真实 knowledge，手工 `workflow_dispatch` 运行。

主 job 使用 `-m "not live and not integration_postgres"`。PostgreSQL job 通过本 job 的 service credential 显式提供非 secret 的 `HARNESS_TEST_POSTGRES_URL` 并运行 `-m integration_postgres`。WeKnora workflow 绑定 `harness-live` environment，并冻结以下映射：

- GitHub secret → `HARNESS_LIVE_API_KEY`、`HARNESS_LIVE_DB_URL`；
- GitHub environment variable → `HARNESS_LIVE_BASE_URL`、`HARNESS_LIVE_SPACE_ID`、`HARNESS_LIVE_KNOWLEDGE_ID`、`HARNESS_LIVE_PARSER_FINGERPRINT`、`HARNESS_LIVE_KB_ID`。

preflight 逐项检查七个变量，只输出缺失变量名，绝不输出值；缺失时在 pytest 前失败。PostgreSQL lane 同样在 pytest 前检查 `HARNESS_TEST_POSTGRES_URL` 与 service health。PostgreSQL lane 必须保存 JUnit，并要求 selected/executed tests 大于零、skipped 为零；WeKnora lane 每次被调用时适用同一 JUnit 约束，未调用则状态保持 `NOT RUN`。全 skip 不能形成绿色证据。三个 collection 表达式必须互斥，合并后的完整 node 集合等于无 `-m` 的全量 collection；PostgreSQL 并发 node 只属于 integration，四个 WeKnora node 只属于 live。

## 2. live scope 生命周期

`KnowledgeScope` 的数据库 attestation 仅保存 Engine 弱引用。测试 helper 必须使用 context manager/yield fixture，让 Engine 与 Session 覆盖完整测试生命周期；teardown 后才关闭并 dispose。确定性回归用 SQLite 证明 context 内 capability 有效、退出后失效。

## 3. 文件边界

- bridge：共享编排 helper 进入 `tests/support/source_bridge.py`；确定性契约进入 `test_source_bridge_contract_017.py`；唯一真实 E2E 留在 `test_source_bridge_live_017.py`。
- pipeline：共享 fake/builder 进入 `tests/support/source_pipeline.py`；checkpoint、runtime/artifact、CLI/resource lifecycle 分文件。
- revision：共享 identity/claim/evidence builder 进入 `tests/support/source_revision.py`；notification/race 与 importer/tombstone/aggregate 分文件。

拆分只移动测试与提取 setup，不改变生产行为。文件移动必然改变完整 pytest node ID，因此拆分前后比较按字典序排序的规范化身份多重集 `(test function name, parameter id)`、marker 集合、收集总数和 focused 结果；四项均保持一致，before/after 清单进入 validation evidence。禁止从一个 test module import 另一个 test module。

## 4. 重叠审计

引入 `pytest-cov` 的 per-test context。采集使用 `pytest --cov=insurance_harness --cov-context=test`，再用 `coverage json --show-contexts` 导出；输入只保留 `harness/src/insurance_harness/**/*.py` 生产包，排除 tests、migrations、生成物与第三方代码。audit 忽略空/default context，并移除 pytest context 的 phase 后缀后再规范化 test identity。`scripts/test_portfolio_audit.py` 将每个 test context 映射到执行过的 `(source_file, line)` 集合，输出 Jaccard `>=` 阈值且达到最小共同执行行数的 overlap 候选，并以等于阈值的用例锁定边界。CLI 固定输出有效 context 数、production line 数、候选数和阈值；解析失败、没有有效 context 或没有 production line 时非零退出，发现 overlap 候选本身仍为零退出。

报告只用于人工复审：同一 production line overlap 不代表相同副作用语义。只有输入、public boundary、失败阶段和副作用断言均同构时才可合并。scope 核心 capability 测试与各 consumer 的接线/零副作用测试默认视为不同证明层。每个 change 的 validation report 必须维护 `Risk ID | Primary layer | Test node/pattern | Distinct failure surface | Execution lane` 表，由规格审查核对。

## 5. 状态语言

- `software complete`：deterministic 门禁通过；
- `integration verified`：PostgreSQL 16 service 的 GitHub Actions job 通过，JUnit 证明 tests 大于零且 skipped 为零，并保留 run URL、commit SHA 与时间；本地结果只能用于调试；
- `live verified`：指定 WeKnora environment 中的 live workflow 通过，JUnit 证明 tests 大于零且 skipped 为零，并保留 run URL、commit SHA 与时间。

任何 NOT RUN/skip 不得升级状态。

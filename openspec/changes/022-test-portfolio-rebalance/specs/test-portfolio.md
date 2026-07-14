# 022 规格（验收条件）——测试组合再平衡

## P0 真实门禁可执行

- P0.1 live scope helper 在使用期间保持数据库 Engine attestation，有确定性回归证明进入/退出生命周期；
- P0.2 PostgreSQL 并发 recompile 使用 `integration_postgres` marker、独立的 `HARNESS_TEST_POSTGRES_URL`，并在 PR CI 的 PostgreSQL 16 service job 中真实运行；preflight 检查变量与 service health，JUnit 必须证明 tests 大于零且 skipped 为零；
- P0.3 WeKnora live workflow 使用受控 environment；preflight 检查 `HARNESS_LIVE_BASE_URL/API_KEY/DB_URL/SPACE_ID/KNOWLEDGE_ID/PARSER_FINGERPRINT/KB_ID`，只输出缺失变量名、不输出值，缺失变量使 workflow 在 pytest 前失败；JUnit 必须证明 tests 大于零且 skipped 为零；
- P0.4 deterministic、integration、live 三个 collection 互斥且并集等于全量 collection；PostgreSQL 并发 node 只属于 integration，真实 WeKnora node 只属于 live，并保存 collect-only 清单作为验收证据。

## P1 命名与选择准确

- P1.1 bridge 的 12 个 deterministic contract 与 1 个 live E2E 分文件；
- P1.2 `_live_` 文件中只有真实端点用例可被 pytest 收集，真实用例保留 `live` marker；
- P1.3 拆分前后的 13 个 bridge 规范化身份多重集 `(test function name, parameter id)`、marker、数量和行为保持一致；before/after 清单进入 validation evidence。

## P2 大文件按职责拆分

- P2.1 source pipeline 的 checkpoint、runtime/artifact、CLI/resource lifecycle 分文件；
- P2.2 source revision 的 notification/race 与 importer/tombstone/aggregate 分文件；
- P2.3 共用 builder 位于 `tests/support/`，不得通过 test-module 互相 import；
- P2.4 原 pipeline 88、revision 51 个 collected tests 全部保留；以排序后的规范化身份多重集 `(test function name, parameter id)` 比较拆分前后，marker 与 focused 行为不变，before/after 清单进入 validation evidence，拆分后的单个测试文件不超过 1000 行。

## P3 客观重叠审计

- P3.1 coverage-context audit 使用 `pytest --cov=insurance_harness --cov-context=test` 与 `coverage json --show-contexts`，只消费 `harness/src/insurance_harness/**/*.py` 生产代码上下文；tests、migrations、生成物和第三方代码不得进入集合；空/default context 被忽略，pytest phase 后缀被规范化；
- P3.2 阈值、最小共同执行行数可配置，输出稳定排序；Jaccard 等于阈值时必须包含，低于阈值时不得包含；
- P3.3 audit 固定输出有效 context 数、production line 数、候选数和阈值；解析失败、零有效 context 或零 production line 非零退出；overlap 候选本身只报告，不自动删除测试或使 CI 失败；
- P3.4 每个 change 的 validation report 使用固定表 `Risk ID | Primary layer | Test node/pattern | Distinct failure surface | Execution lane` 记录新增测试；规格审查必须核对，完成状态不得只引用 passed 数量。

## P4 工程门禁

- P4.1 deterministic、PostgreSQL integration focused、Ruff、mypy、diff check 全绿；PostgreSQL lane 必须有 tests 大于零且 skipped 为零的 JUnit 证据；仅当声明 `live verified` 时，WeKnora lane 必须提供同样的 JUnit 证据；
- P4.2 无真实 WeKnora 环境时只可报告 NOT RUN，不得伪造 live 成功；
- P4.3 HANDOFF、Runbook、OpenSpec validation 对三类状态与运行证据保持一致；`integration verified` 只能引用成功的 PostgreSQL 16 Actions job URL/commit SHA/时间，本地结果不得替代；`live verified` 同样必须引用受控 workflow URL/commit SHA/时间。

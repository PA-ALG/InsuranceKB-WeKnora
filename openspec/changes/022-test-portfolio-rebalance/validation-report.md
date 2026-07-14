# 022 验收报告：测试组合再平衡

> 日期：2026-07-14。状态以可复现证据为准；本报告不会用本地结果替代基础设施 workflow。

## 1. 状态结论

| 状态 | 结论 | 证据 |
|---|---|---|
| `software complete` | PASS | deterministic `933/938 collected`、exit 0；Ruff PASS；mypy 151 files PASS |
| `integration verified` | PASS | [run 29312423361](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29312423361) / [job 87018894440](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29312423361/job/87018894440)，commit `ed46df78fb975c5ef7963e49dd1e208dba31fdaa`，2026-07-14T06:47:23Z～06:47:54Z |
| `live verified` | NOT RUN | 未触发受控 `harness-live` workflow；无 WeKnora JUnit/run URL |

PostgreSQL 证据来自 GitHub 托管 PostgreSQL 16.14 service：`1 passed, 937 deselected`，JUnit guard 输出 `tests=1 skipped=0`；[JUnit artifact](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29312423361/artifacts/8302579856) SHA-256 为 `d75bdd1eb3666e4a1ca5ed33b12cdca3cd967565c8c2b5d5bd08ea3a1af2d47a`。只有受控 WeKnora workflow 满足同一非零、零 skip 条件后才能更新第三行。

## 2. 风险—证明层—执行 lane

| Risk ID | Primary layer | Test node/pattern | Distinct failure surface | Execution lane |
|---|---|---|---|---|
| R-LIVE-SCOPE | fixture capability | `test_p0_1_live_scope_context_keeps_attestation_until_exit` | Session/Engine 在 live 用例开始前被释放 | deterministic |
| R-PG-RACE | real database concurrency | `test_t7_live_postgresql_concurrent_notifications_create_one_recompile` | PostgreSQL unique/race/transaction 行为与 SQLite 不同 | `integration_postgres` |
| R-CI-FAKE-GREEN | evidence gate | `test_ci_lanes_022.py` + `check_junit.py` | marker 漏标、全 skip、零收集仍绿色 | deterministic + workflow guard |
| R-WEKNORA-CONTRACT | external endpoint | 四个 `live` nodes | 真实 REST、download/chunks、publisher 与 evidence backlink | `live` |
| R-BRIDGE-MIX | test selection | `test_source_bridge_contract_017.py` / `test_source_bridge_live_017.py` | deterministic contract 被 `_live_` 文件名掩盖 | deterministic / `live` |
| R-PIPELINE-SPLIT | checkpoint/runtime/CLI boundaries | `test_source_pipeline_{checkpoint,runtime,cli}_017.py` | 拆分漏断言、resource cleanup、artifact atomicity | deterministic |
| R-REVISION-SPLIT | notification/import boundaries | `test_source_revision_{notify,import}_017.py` | stale/race 与 tombstone/import 语义被搬运遗漏 | deterministic |
| R-OVERLAP-INPUT | governance tooling | `test_test_portfolio_audit_022.py` | 非生产路径、空 context、阈值边界污染报告 | deterministic |

## 3. RED → GREEN 证据

| 项目 | RED | GREEN |
|---|---|---|
| live scope 生命周期 | helper 不存在，collection exit 2 | focused 1 passed；相关 63 passed / 2 live skipped |
| CI lanes / JUnit | 初始契约 8 failed；仅 live workflow 变更不触发 CI 的回归 1 failed；secret 作用域/负 skipped 回归 2 failed；immutable action/逐 suite 计数回归 3 failed | `test_ci_lanes_022.py`: 10 passed；integration 1、live 4 精确归属 |
| coverage audit | script 不存在，collection exit 2；真实 `--cov-context=test` 参数未安装 exit 4 | synthetic + real artifact smoke 5 passed |
| production path traversal | `src/insurance_harness/../external.py` 被错误接受，1 failed | traversal 被拒绝，audit 5 passed |
| P2 quality follow-up | helper 漏检 judge/dead-letter；enter 前 cancellation 残留 PDF，3 failed | focused 3 passed；pipeline 全量 88 passed |

## 4. Collection 与拆分清单

### 4.1 三条 lane

| Collection | 数量 | 精确约束 |
|---|---:|---|
| full | 938 | 三 lane 并集 |
| deterministic | 933 | `not live and not integration_postgres` |
| PostgreSQL | 1 | 仅真实并发 recompile node |
| WeKnora live | 4 | adapter 2 + publisher 1 + bridge E2E 1 |

三集合两两互斥；`test_ci_lanes_022.py` 在 pytest 内重新 collect 并核对并集。

### 4.2 bridge before / after manifest

拆分前 13 项全部位于 `test_source_bridge_live_017.py`；拆分后前 12 项位于 `test_source_bridge_contract_017.py`，最后 1 项仍位于 live 文件：

1. `test_live_prerequisite_gate_names_every_missing_variable_contract`
2. `test_live_prerequisite_gate_rejects_sqlite_and_redacts_secret_contract`
3. `test_anchor_selection_is_page_backed_and_uniquely_chunk_linked_contract`
4. `test_anchor_selection_rejects_source_without_chunks_contract`
5. `test_anchor_selection_rejects_source_without_unique_chunk_contract`
6. `test_manifest_to_import_context_preserves_bridge_identity_contract`
7. `test_manifest_context_rejects_duplicate_and_non_bijective_docs_contract`
8. `test_manifest_context_rejects_self_consistent_forged_identity_contract`
9. `test_live_import_product_seed_flushes_parent_before_version_contract`
10. `test_sources_public_package_imports_before_compiler_contract`
11. `test_injected_failure_cleans_live_resources_and_temp_paths_contract`
12. `test_scripted_model_is_deterministic_and_credential_free_contract`
13. `test_live_source_bridge_compiler_import_evidence_backlink` (`live`)

规范化 identity 多重集、marker 与 12+1 数量 before/after 一致；focused deterministic 12 passed，live 本地 1 skipped，未伪报成功。

### 4.3 pipeline / revision before / after manifest

| Suite | Before | After | Count |
|---|---|---|---:|
| pipeline | `test_source_pipeline_017.py` | checkpoint 19 + runtime 42 + CLI 27 | 88 |
| revision | `test_source_revision_017.py` | notify 22 + import 29 | 51 |

完整排序清单已随 change 保存为 [p2-before.json](evidence/p2-before.json) 与 [p2-after.json](evidence/p2-after.json)；仓库内原始 SHA-256 分别为 `380b8c228c6f08656afb1d1502da23cbf144806d60384624629c9f81330ed16d`、`61db5cceeda344278573a4f099783e3a2f0390c5605f130c113a1a05a2209cfb`。以下精确 canonicalization（`jq -c` 输出包含末尾换行）得到的 before/after SHA-256 均为 `aab5228275be80c12e1694d049ad56fbd3951f3dc468cf15fb8b03c61b95af52`：

```bash
jq -c '[.[] | del(.path)] | sort_by(.function, .parameter_id, .markers)' \
  openspec/changes/022-test-portfolio-rebalance/evidence/p2-before.json > /tmp/p2-before-normalized.json
jq -c '[.[] | del(.path)] | sort_by(.function, .parameter_id, .markers)' \
  openspec/changes/022-test-portfolio-rebalance/evidence/p2-after.json > /tmp/p2-after-normalized.json
shasum -a 256 /tmp/p2-before-normalized.json /tmp/p2-after-normalized.json
```

marker 多重集保持：`parametrize=66`、`asyncio+parametrize=28`、`none=25`、`asyncio=20`。最大拆分文件 739 行；没有 test-module 相互 import。

## 5. 门禁与 overlap audit

- deterministic：`933/938 tests collected (5 deselected)`；全量运行 exit 0；
- Ruff：`All checks passed!`；
- mypy：`Success: no issues found in 151 source files`；
- focused scope coverage：5 个 scope/consumer 文件，`208 passed`；
- real coverage-context audit（threshold 0.8、minimum shared 5）：`context_count=193`、`production_line_count=1946`、`candidate_count=999`、exit 0。

999 个候选说明 parametrized 分支与共享 setup 有高执行行重叠，不说明其失败面相同。本 change 未据此删除 scope/product/knowledge/publisher/client 的隔离断言；候选只作为后续逐条复审清单。

## 6. 独立审查

| 范围 | Spec review | Quality review | 处理结果 |
|---|---|---|---|
| OpenSpec / plan | Approved（两轮） | — | zero-skip、非空 context、文件所有权已固化 |
| P0 live lifecycle | Approved | Approved | 无 finding |
| P0 CI lanes | Approved | Approved after two fixes | secret 作用域/action pin、逐 suite JUnit finding 已按 TDD 修复 |
| P1 bridge | Approved | Approved | 无 finding |
| P2 split | Approved | Approved after fix | 两项 quality finding 已按 TDD 修复并复审 Approved |
| P3 audit | Approved after traversal fix | Approved | 无剩余 finding |
| 整包差异 | Approved | Approved after live cleanup fix | AST/全量门禁复核无剩余代码 finding |

## 7. 外部证据边界

- PostgreSQL：`integration verified`，GitHub Actions run/job、commit、时间、JUnit 计数与 artifact 摘要见 §1；deterministic job 同一 run 亦成功。
- WeKnora：本机没有七变量受控环境；在手工 workflow 成功前保持 `NOT RUN`。

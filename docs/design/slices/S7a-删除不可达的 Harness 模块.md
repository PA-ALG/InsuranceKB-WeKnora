# S7a · 删除不可达的 Harness 模块

> 状态：总控派工（2026-10-17） ｜ 作者：Claude Code ｜ 依据：蓝图 §8（G3–G6、G11）、§10.1、§11（S7 平台收敛与清理）
> 分支：`slice/s7a` ｜ 工作目录：`.worktrees/s7a` ｜ 实现方：Claude ｜ 审核方：Codex（净删除约 6 万行、跨多个旧目录）
> 真实调用：无

## 1. 目标与最小机制

蓝图 §10.1 把 `knowledge/`、`adapters/`、`runtime/`、`product/`、`workbench/`、`flywheel/`、`capacity/`、`mcp/`、
`s0q_047.py` 等定为 RETIRE（0% 可达），`knowledge_compiler/`、`goldenset/`、`live_env/` 中也有大量不可达的旧资产。S7 拆成
多片，S7a 只做 Harness：**删除从真实入口静态不可达的模块**，连同只为它们存在的测试、脚本与 CI 步骤，守卫基线随之下降。

最小机制是一条新守卫：计算可达闭包，不可达模块必须出现在显式保留清单里，清单只减不增。仍可达的旧链路
（`product_ingestion.pipeline` 拉起的 G3、`compiler/`、`knowledge/`、`adapters/`、`sources/`）由 S5 退役；仍超过 500 行的
文件在 S7 末尾统一拆分，本片不拆。

## 2. 可达的定义

模块可达 ⇔ 在下列根的静态 import 闭包中。闭包跟随全部 import（模块级与函数内、绝对与相对），以及字符串里的模块路径
（`"insurance_harness.x.y"`，覆盖 `import_module`/`__import__`）；导入模块同时加载其父包。

1. `harness/pyproject.toml` 的 `[project.scripts]`（`wiki-api`、`wiki-worker` → `service_shell.cli`）；
2. Alembic 加载的模块：`harness/migrations/env.py` 与 `versions/*.py`；
3. `deploy/product-ingestion/configure.py` 的 import；
4. 现行命令行：`contracts.export`、`compilers.schema_fields.publish`、`db.scope_cli`，以及 `eval/` 下的命令（属于第 5 条）；
5. 蓝图 §4.2 目标目录（`common.HARNESS_TARGET_DIRS`）中的全部模块。

不是根的旧命令行：`goldenset.admission_cli`、`flywheel.cli`、`product.cli`、`compiler.cli`、`run_admission.cli`、
`structured_import.cli`、`s0q_047`、`harness/scripts/*`。

## 3. 删除范围（按 `main@76efdc825` 计算：403 个模块中 107 个不可达，删除 87 个，约 5.6 万行）

| 目录 | 删除的模块 |
|---|---|
| `knowledge_compiler/` | 37 个：ec01/formal_candidate/revision_set（815）、c5_preview、marker/relation_receipt/section_anchor/terms_section 等 `*_596_1` 家族、candidate_batches/manifest/handoff、review_dossier、fair_*、weak_strong_ceiling、golden18_human_gate、schema_first_selector、g3_source_index、service_schema_catalog_830_g3、medical_schema_pack_596_1 |
| `goldenset/` | 17 个：admission*（8）、run_020、execution_artifacts_020、schema67_*（5）、golden_v2_review_intake_596_1、golden18_xlsx_import_bridge_596_1 |
| `flywheel/` | 10 个（保留 `__init__`、`tables`：Alembic 需要） |
| `runtime/`、`capacity/`、`workbench/`、`mcp/`、`s0q_047.py` | 整包删除（含 workbench 模板与静态资源） |
| `live_env/` | `github_backend`、`github_live` |
| 其他 | `product.cli`、`product.routing`、`product_ingestion.routing`、`compiler.cli`、`run_admission.cli` |

仍可达因而保留的（不在本片）：`goldenset/` 的 GoldenRecord、比较器、指标等（S2 已迁入 `eval/`，旧件随 S5）、
`live_env/config`、`flywheel/tables`、`knowledge/tables` 与 `release_guard_ddl_018`（Alembic）、`template_packages/`（待核实）。

## 4. 保留清单（不可达但保留，守卫 `KEEP_UNREACHABLE`）

| 模块 | 理由 | 退出 |
|---|---|---|
| `knowledge_compiler.incremental_changes`、`source_authority`、`retractions` | 蓝图 REWIRE → `changes/`，增量唯一语义 Owner | S8 |
| `structured_import/`（7 个模块） | 蓝图 REWIRE → `ingest/` 结构化导入 | 第二期前 |
| `product.register`、`aliases`、`meta` | `structured_import.service` 的依赖 | 随结构化导入 |
| `live_env.compose`、`local_gate`、`local_provisioning`、`model_probe`、`provision`、`space`，`adapters.weknora.admin_client` | 可信 local-live 镜像工作流与摘要固定的插件契约（`deploy/upstream/weknora-plugin-contract.yaml` 的 `compatibility.harness_retry_scope`，摘要写死在 `harness/scripts/prepare_weknora_adoption.py`）运行 `tests/test_local_live_cli_023.py`，它经 `harness/scripts/local_live.py` 加载这些模块；改契约属于本地 live 供应链变更，不在本片 | local-live 镜像链路退役（I1） |

## 5. 测试、脚本、CI 与配置

- **测试**：整文件删除只测被删模块的测试（含 `wbhelpers.py`、`run_admission_execution_contract_020.py` 等辅助文件）。
  混合文件只删依赖被删模块的用例，保留对仍存在模块的覆盖：
  - `test_production_entrypoints_027.py`：删 `compiler.cli`/`product.cli` 的入口与构造器用例（含按 openspec 027 清单证明
    `compiler/cli.py` 的用例）；
  - `test_mvp_admission_030.py`：删 `run_admission.cli` 用例；去掉一处只为观察 `compiler.cli` 传输的 monkeypatch；
  - `test_compiler_pipeline.py`、`test_recall_config_024.py`：删 CLI 用例；
  - `test_scope_product_016.py`：删 `product.routing`/`product.cli` 用例，保留 `register_products` 的 scope 用例；
  - `test_schema_wiki_candidate_evidence_authority_121.py`：删针对 `schema_wiki_release_596_1` 的一条；
  - `test_596_1_semantic_input_binding_069.py`：删与 `weak_strong_ceiling` 镜像计划的交叉比对；
  - `product_ingestion/test_routing.py`、`test_fixture_candidate_human_batch_059.py`：只留被其他测试共用的夹具；
  - `test_ci_lanes_022.py`（PostgreSQL 节点清单）、`test_scaffold.py`（子包清单）、`conftest.py`（815 回放的收集开关）同步。
- **脚本**：删 `github_live.py`、`run_s0q_047.py`、`wheel_smoke_workbench.py`、`build_596_1_relation_receipt_096.py`、
  `freeze_schema67_reviewed_golden_successor_596_1.py`；`baseline_004.py` 依赖 `compiler.cli` 的两个函数，与依赖它的
  `eval_005.py`、`validate_006.py` 一起删除（三者只为 openspec 004–006 生成已冻结的报告，评测已由 `eval/` 取代）。
- **CI**：`harness-ci.yml` 的 `wheel-smoke` 去掉工作台冒烟一步，保留"构建 wheel 并装进空 venv"。
- **配置**：`config.py` 删除 `workbench_*` 四项（`extra="ignore"`，旧环境变量被忽略）；`harness/README.md`、
  `scripts/install.sh` 去掉已删包与 `product.cli` 的说明。
- **依赖不在本片调整**：`jinja2`、`python-multipart` 删除后不再被引用，但改依赖要同步 `uv.lock` 与
  `deploy/product-ingestion/requirements.lock`，另开小片。

## 6. 验收（受保护，RED 单独提交）

`tests/architecture/test_harness_reachability.py`（只用标准库 `ast`，不导入 Harness 包）：

- 入口模块（pyproject 脚本、`CLI_ROOTS`）必须存在，改名即失败；
- 不可达模块 ⊆ `KEEP_UNREACHABLE`，否则列出模块名失败；
- `KEEP_UNREACHABLE` 中已删除或已变为可达的条目失败（清单只减）；
- 自测：相对 import、函数内 import、字符串模块路径都能被解析。

RED 时第二条失败（87 个模块）。

## 7. 门禁与改动范围

- 门禁：`harness/` 下 `uv run pytest -q -m "not live and not integration_postgres"`（相对 main 不新增失败）、
  `uv run ruff check .`、`uv run mypy src tests`、`uv run python -m insurance_harness.contracts.export --check`；仓库根
  `pytest -q tests/architecture`；`git diff --check`。
- 基线：删除后在仓库根运行 `python tests/architecture/record_baseline.py`（不带 `--init`），G3/G4/G5/G6/G11 只降不升，单独提交。
- 允许：`harness/src/insurance_harness/` 下第 3 节列出的模块与 `config.py`、`harness/tests/`、`harness/scripts/`、
  `harness/README.md`、`.github/workflows/harness-ci.yml`、`scripts/install.sh`、`tests/architecture/baseline.json`（脚本生成）。
- 不改：Alembic 迁移与表定义、`contracts/`、`deploy/`、`docs/insurance-kb/evidence`（另片移出）、Go 与前端。

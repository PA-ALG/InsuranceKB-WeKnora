# S7d-1 · 退役 G3 产品导入链（Harness 侧）

> 状态：Claude 2026-10-22 提出；用户同日同意删除，并要求先打包备份（"可以删，但是你看下把它打个包，放在哪里，有个地方可以找回来"）｜ 作者：Claude Code
> 依据：蓝图 §10（`product_ingestion`、`knowledge_compiler`、`compiler` 等 RETIRE）、§11 S7；S7a 可达性守卫
> 实现方：Claude ｜ 审核方：Codex（净删除远超 200 行，改动守卫清单与服务外壳）｜ 真实模型调用：0
> 备份：标签 `archive/pre-s7-legacy-20261022`（`main@53ec54b1e`），以及本机 `archives/legacy-830-g3-20261022/`
> 后续：S7d-2 退役 Go 侧（G3 平台路由、产品导入桥、830 领域代码）与前端产品导入面板

## 1. 目标与现状

**G3 产品导入**是 830 时期"上传产品 → 自动编译 → 发布"的独立服务：`wiki-api`、`wiki-worker` 开启 `product_ingestion` 时提供。

- 部署只有 `deploy/product-ingestion/`，本机环境没有部署它；
- 企业知识的编译发布（`compilers/`、`bundle/`、`changes/`）不使用它。

它让约 9.5 万行旧代码保持"可达"，路径有两条：

1. `service_shell/cli.py` 在开启时导入 `product_ingestion`；
2. 守卫根 `deploy/product-ingestion/configure.py` 导入它，它再依赖 `knowledge_compiler`、`compiler`、`goldenset`、`model_policy`、`run_admission`、`sources`、`template_packages`。

另有 3 处已保留的旧工具也会牵住这条链，都是保留清单里的模块，随各自链路退役：

| 保留模块 | 牵住的路径 |
|---|---|
| 本地 live 探针 `live_env.model_probe` | → `compiler.llm` → `model_policy` → … |
| 结构化导入 → `product.register` → `product.classify` | → `goldenset` → `compiler.llm` |
| `config.py`（`HarnessSettings`） | → `model_policy`（生产模型策略校验，只属于这条旧链） |

## 2. 设计

1. **切断三处牵连**，行为不变或只删旧链专属行为：
   - **A**：`live_env.model_probe` 的抽取探针改用本文件已有的 `_post` 与 `_completion`。请求不变：`max_tokens` 4096，system 加 user 两条消息。遇到 `finish_reason=length` 重试一次，与原客户端相同。
   - **B**：`product.classify` 在本模块内定义 `ModelClient` 协议（`async complete(system, user) -> str`）与 `PageText`（`page_no`、`text`），不再导入 `goldenset`。
   - **H**：`config.HarnessSettings` 删除 `require_frozen_production_model_policy` 校验及其 `model_policy` 导入。该校验只服务于旧链的生产模型策略，现行链路不用 `model_profile=production`。
2. **服务外壳去掉产品导入**：
   - `service_shell/cli.py`：删除两处 `product_ingestion` 分支与 `TYPE_CHECKING` 导入；`build_worker_loop` 只返回 `WorkerLoop`；
   - `service_shell/config.py`：删除 `product_ingestion_*` 设置、对应校验与任务类型策略；
   - `service_shell/principal.py`：删除 `product_ingestion` 服务身份及其两项能力。

   `wiki-api` 和 `wiki-worker` 保留（蓝图 KEEP），只剩探针、任务指标与空的处理器注册表。
3. **删除 `deploy/product-ingestion/`**，并从守卫根中移除其 `configure.py`。
4. **删除切断后不可达的全部模块**：共 177 个，约 9.5 万行。
   - 包括 `product_ingestion` 中除 `__init__`、`tables`、`artifact_tables` 以外的 62 个模块；三个保留模块由 Alembic 载入，`__init__` 只留说明；
   - 以及整包删除 `knowledge_compiler`、`compiler`、`goldenset`、`model_policy`、`run_admission`、`sources`、`template_packages`，含包内的 README、prompts 等资源，它们只被已删代码与已删测试引用。
5. **保留清单增加 21 项**。这 21 个模块原先经产品导入链可达，切断后只被已保留的本地 live 与结构化导入使用，与使用者一同保留、一同退役：
   - `adapters.weknora.*`、`live_env`、`live_env.config`；
   - `canonical.*`、`product`、`product.classify`、`product.version_resolver`、`schemas.*`；
   - `config`。

   这是原有保留理由的延伸，不是新的豁免。清单从此按使用者的退役只减不增。
6. **测试**：
   - 删除只测试已删模块的测试与辅助文件，约 200 个，其中包括 `tests/product_ingestion/` 里除 `test_schema_metadata.py` 以外的全部，以及两个旧脚本 `capture_596_1_pdfplumber_artifacts_061.py`、`freeze_s0q_full_golden_049.py`；
   - 保留测试中两处随退役调整：
     - `test_product_classify.py` 改用脚本化客户端，不再用 `goldenset` 的回放客户端，断言不变并多核对一次调用参数；
     - `test_service_shell_principal_039.py` 的服务身份清单去掉 `product_ingestion`；
   - 若 `test_ci_lanes_022.py` 冻结的 PostgreSQL 节点含被删测试，同步移除。

## 3. 上游补丁

无。被删文件的 G3、G4、G11 等基线由脚本下调。

## 4. 验收（RED，Claude 编写，受保护）

- **`tests/architecture/test_harness_reachability.py`**：
  - 守卫根去掉 `deploy/product-ingestion/configure.py`；
  - 保留清单加入 §2 第 5 条的 21 项。旧代码下这些项仍可达，会报"清单过期"，因此 RED 失败。
- **新增 `tests/architecture/test_product_ingestion_retired.py`**：
  - `deploy/product-ingestion` 不存在；
  - `service_shell` 各模块不以任何方式引用 `product_ingestion`，包括 import、`TYPE_CHECKING` 与模块路径字符串；
  - `product_ingestion` 包内只剩 `__init__.py`、`tables.py`、`artifact_tables.py`；
  - 7 个整包已删除：`compiler`、`goldenset`、`model_policy`、`run_admission`、`knowledge_compiler`、`sources`、`template_packages`；
  - 三处牵连已切断：`live_env/model_probe.py` 不导入 `insurance_harness.compiler`，`product/classify.py` 不导入 `insurance_harness.goldenset`，`config.py` 不导入 `model_policy`。

## 5. 改动范围

- `harness/src/insurance_harness/`：
  - `service_shell/{cli,config,principal}.py`；
  - `live_env/model_probe.py`、`product/classify.py`、`config.py`；
  - `product_ingestion/`（只留三个文件）；
  - 删除上述 7 个包。
- `deploy/product-ingestion/`（删除）。
- `harness/tests/`、`harness/scripts/`（删除旧测试与脚本；上述两处测试调整）。
- `tests/architecture/baseline.json`（脚本下调）。

## 6. 上线与验证

无运行时变化：本机没有部署产品导入服务，企业链路不经过被删模块。Go 侧产品导入桥在未配置时返回 `NOT_CONFIGURED`，随 S7d-2 删除。Harness 全量测试以 CI 为准。

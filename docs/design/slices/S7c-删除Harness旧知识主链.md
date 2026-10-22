# S7c · 删除 Harness 旧知识主链（`knowledge/` 的 007 主链与 3 个已标记模块）

> 状态：Claude 2026-10-22 提出（规划由 Claude 负责，用户同日授权）｜ 作者：Claude Code
> 依据：蓝图 §10（`knowledge/` → RETIRE，保留 Alembic 必需部分）、§11 S7；S7a（#193）的可达性守卫
> 实现方：Claude ｜ 审核方：Codex（净删除远超 200 行，并改动受保护的守卫清单）｜ 真实模型调用：0

## 1. 目标与现状

**`knowledge/`**：change 007 时期的 Harness 知识主链，已被 S3–S8 的 `compilers/`、`bundle/`、`changes/` 与 WeKnora 发布权威取代。主链包括 Claim 落库、增量合并、审核、页面编译与发布。

- 包内 21 个模块里，只有 `tables.py` 和 `release_guard_ddl_018.py` 仍被 Alembic 使用：
  - `harness/migrations/env.py` 注册知识域表；
  - `versions/0005` 引入 DDL。
- 其余 18 个模块约 9,047 行，现在仍"可达"，只因为 `knowledge/__init__.py` 把它们全部再导出，而 Alembic 导入 `tables` 时会先加载包。
- 模拟清空再导出后，这 18 个模块全部不可达，没有任何入口或目标目录依赖它们：authority、fallback、importer、merge、models、pages、projection、publisher、quality_gate、reader、reconcile、release_plan、review、snapshots、source_aggregates、source_keys、source_lifecycle、source_revision。

**`knowledge_compiler.{incremental_changes, source_authority, retractions}`**：约 810 行。在可达性守卫的保留清单里，标注为"S7 删除：已被 S8a 的 changes/ 取代"。只有 `test_incremental_changes_058.py` 使用它们。

## 2. 设计

1. **清空再导出**：`knowledge/__init__.py` 只留文档字符串，说明包内只剩 Alembic 需要的表与 DDL。`from insurance_harness.knowledge import tables` 照常可用。
2. **删除 18 个模块**及包内 `README.md`，即 007 主链说明。
3. **删除 3 个 `knowledge_compiler` 模块**，并从守卫保留清单中移除对应 3 项。保留清单只减不增。
4. **删除只测试被删模块的测试文件**：
   - `test_incremental_changes_058.py`；
   - `test_knowledge_{e2e,importer,merge,pages,publisher,review}.py`；
   - `test_publish_state_machine_018.py`、`test_quality_gate_019.py`、`test_reconcile_018.py`、`test_release_plan_018.py`；
   - `test_release_publisher_postgres_018.py`、`test_release_snapshot_live_018.py`；
   - `test_review_workbench_008.py`、`test_workbench_concurrency_008.py`；
   - `test_scope_knowledge_016.py`、`test_scope_publisher_016.py`；
   - `test_snapshot_{facts,fallback,pages,reader}_018.py`；
   - `test_source_bridge_live_017.py`、`test_source_ordering_021.py`；
   - `test_source_lifecycle_{021,delete_021,import_021,postgres_021}.py`；
   - `test_source_retract_017.py`、`test_source_revision_{import,notify,postgres}_017.py`。

   `test_source_lifecycle_migration_021.py` 只用 `tables`，保留。

   还要删除只服务于上述测试的辅助文件，它们导入被删模块：
   - `tests/kbhelpers.py`、`tests/wbhelpers.py`；
   - `tests/support/{legacy_publisher_007,release_018,source_revision,source_bridge}.py`；
   - 以及只测试 `source_bridge` 辅助函数的 `test_source_bridge_contract_017.py`，它对应的 live 测试已在上表删除。

   > 2026-10-22 修正（Claude 实现时发现）：原清单只按直接导入列出测试，漏了导入被删模块的辅助文件及其唯一使用者，补列于此。
5. **其余配置**：若 `harness/pyproject.toml` 的 mypy、ruff 或覆盖率配置点名了被删模块或测试，一并删除这些条目。

不做：`db/`、`adapters/`、`product/` 等其余 RETIRE 目录，以及 `product_ingestion` 链，留给 S7d。

## 3. 上游补丁

无（只动 Harness 与守卫清单）。被删文件的 G3、G4、G11 基线由脚本下调。

## 4. 验收（RED，Claude 编写，受保护）

- **`tests/architecture/test_harness_reachability.py`**：保留清单删去 3 个 `knowledge_compiler` 项。被删的模块仍存在时，"每个模块可达或在保留清单"这一项失败。
- **新增 `tests/architecture/test_legacy_knowledge_removed.py`**：
  - `knowledge/__init__.py` 没有任何 import；
  - `knowledge/` 下只剩 `__init__.py`、`tables.py`、`release_guard_ddl_018.py`；
  - Alembic 的两处引用仍能解析到保留模块：`env.py` 导入 `tables`，`0005` 导入 DDL。

## 5. 改动范围

- `harness/src/insurance_harness/knowledge/`（清空 `__init__`，删 18 个模块与 README）；
- `harness/src/insurance_harness/knowledge_compiler/{incremental_changes,source_authority,retractions}.py`（删除）；
- `harness/tests/`（删除 §2 列出的 32 个测试文件与 6 个辅助文件）；
- `harness/pyproject.toml`（只删指向被删内容的条目，如有）；
- `tests/architecture/baseline.json`（脚本下调）。

## 6. 上线与验证

无运行时变化：被删模块从任何入口都不可达。Harness 全量测试以 CI 的 deterministic 作业为准，本地跑受影响模块与守卫。

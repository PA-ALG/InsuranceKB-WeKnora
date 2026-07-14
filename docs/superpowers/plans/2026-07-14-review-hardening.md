# Review Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 客观收口六项复审意见，修复 rollback flush 写序、零 Evidence 同 revision、Directory provenance/discovery、KB identity 类型与开发门禁漂移，同时保持 018/021 和 eval/live 边界。

**Architecture:** 每个行为缺口由 `openspec/changes/022-review-hardening/specs/review-hardening/spec.md` 的独立 RH 条款约束。生产变更限制在 publisher、source revision、PredRecord/pipeline/importer、Directory source 与 WeKnora scope adapter；测试治理只修正 CLAUDE.md lane，不删除 016 隔离证明。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Pydantic v2、pytest/pytest-asyncio/respx、Ruff、mypy strict、OpenSpec。

## 全局执行硬门

- 工作目录固定为 `/Users/houjing/Documents/LLM_wiki/.worktrees/insurancekb-enterprise-foundation`；pytest/Ruff/mypy 命令的 `workdir` 固定为其 `harness/` 子目录。
- 严格 TDD：行为变更先运行精确 node 并看到正确原因 RED，再写最小 production code；既有不变量只作明确标注的 baseline characterization，不人为破坏代码制造 RED。
- 每个任务串行使用 fresh implementer。实现者自检后，先由独立 spec reviewer 对照完整任务和 RH 条款审查；finding 由同 implementer 修复并交同 reviewer 重审至批准；随后才启动独立 quality reviewer，finding 同样修复、重跑并重审至批准。
- 任何 task 未完成两阶段批准，不进入下一 task；整包同样先 spec、后 quality。
- 依 `CLAUDE.md`，AI 在本计划会话中无条件不 commit/push；只保留可供人类复核的 working-tree diff。commit/push 与最终 SHA 的外部 CI 仅由人类完成，随后可另开续验。

---

### Task 1: RH1 rollback savepoint 写序

**Files:**
- Modify: `harness/src/insurance_harness/knowledge/publisher.py`
- Test: `harness/tests/test_scope_publisher_016.py`

- [ ] **RED 1：DB flush failure 必须零 Wiki I/O。** 在基线 snapshot/pointer 建好后注册 `before_flush`，只在 `session.new` 出现 `source_kind="rollback"` 的 ChangeSet 时抛 `RuntimeError("injected rollback flush failure")`；`finally` 移除 hook。新增 `test_rh1_1_rollback_flush_failure_performs_zero_wiki_mutations`，异常后提交 outer transaction，断言新增 HTTP 调用数为 0、pointer/audit 与基线一致。
- [ ] 从 `harness/` 运行：`uv run pytest tests/test_scope_publisher_016.py::test_rh1_1_rollback_flush_failure_performs_zero_wiki_mutations -q`。预期 RED：当前 Wiki update 已发生后才触发 injected flush failure。
- [ ] **GREEN 1 最小中间实现：** 先进入 `session.begin_nested()`，再创建/add ChangeSet、调用 `_move_pointer()`、显式 `session.flush()`，最后进入 Wiki loop。此时 RH1.1 应 GREEN；暂不声称 RH1.2。
- [ ] 重跑 RH1.1 精确 node，预期 PASS。
- [ ] **RED 2：Wiki failure 必须回滚 savepoint。** 新增 `test_rh1_2_rollback_wiki_failure_rolls_back_savepoint_after_outer_commit`；Wiki mock 抛错，捕获后执行 `session.commit()`，重新查询 pointer 与 rollback ChangeSet。对 GREEN 1 的中间实现预期 RED：pointer/audit 可被 outer commit。
- [ ] **GREEN 2：** 让 DB mutation/flush 与 Wiki loop 处于同一个 `with session.begin_nested():`；Wiki 异常退出时 savepoint 自动 rollback。不得在进入 savepoint 前 add/修改 rollback 对象，因为 `begin_nested()` 会先 flush pending state。
- [ ] 运行：`uv run pytest tests/test_scope_publisher_016.py::test_rh1_1_rollback_flush_failure_performs_zero_wiki_mutations tests/test_scope_publisher_016.py::test_rh1_2_rollback_wiki_failure_rolls_back_savepoint_after_outer_commit tests/test_scope_publisher_016.py::test_s2_3_rollback_wiki_failure_does_not_move_pointer_or_add_trace -q`。预期 3 passed。
- [ ] 完成实现者自检 → spec review/re-review → quality review/re-review。

### Task 2: RH2 零 Evidence 同 revision

**Files:**
- Modify: `harness/src/insurance_harness/knowledge/source_revision.py`
- Test: `harness/tests/test_source_revision_notify_017.py`

- [ ] **RED：** 新增参数化 `test_rh2_1_applied_unknown_only_revision_is_same_revision_without_evidence`，必须通过真实 `import_pred_records` 建立 `tri_state="unknown"`、`evidence=[]`、合法 `SourceImportContext`、一个 unknown placeholder、零 ClaimEvidence；覆盖 applied `document` 和“先建空 pending recompile、再被 importer 复用为 applied”的 `recompile`。通知同 identity，期望 same/no new ChangeSet。
- [ ] 运行：`uv run pytest tests/test_source_revision_notify_017.py::test_rh2_1_applied_unknown_only_revision_is_same_revision_without_evidence -q`。预期两个参数 case 分别以 `source change set is ambiguous` / `source change set cannot be replayed` RED。
- [ ] **GREEN：** 仅在 active revisions 为空时查询同 identity aggregate；唯一 scoped、parent/child aggregate 完整合法且 status=`applied` 的 `document|recompile` 返回 same no-op；pending 只允许零 item `recompile` 继续既有 reuse；其余状态、多个 rows、非法 children 全部 fail closed。不得只验证 parent/count，必须复用完整 aggregate validator。
- [ ] 重跑 RH2.1，预期全部 PASS。
- [ ] **Characterization：** 新增 `test_rh2_2_zero_evidence_new_revision_creates_then_reuses_one_recompile`：A 为零 Evidence applied，B 只改变同 knowledge/raw-KB 的 revision；连续 notify B 两次，断言 first created、second reused、两次 `stale_count=0`、唯一 pending B。该合同是既有语义，记录 baseline GREEN；其作用是防止新 applied 分类误把 B 当 A。
- [ ] **Fail-closed regression：** 新增参数化 `test_rh2_2_zero_evidence_malformed_or_conflicting_aggregate_fails_closed_without_mutation`，覆盖 malformed parent/child、document+recompile 多行冲突、非法 status/非空 pending；异常后提交 outer transaction并比较 ChangeSet/ChangeItem/ClaimEvidence/stale 基线。允许当前部分 case baseline GREEN，但新增分类不得使其退化。
- [ ] 运行：`uv run pytest tests/test_source_revision_notify_017.py tests/test_source_revision_import_017.py -q`。预期全绿。
- [ ] 完成实现者自检 → spec review/re-review → quality review/re-review。

### Task 3: RH3 Directory provenance 与 discovery

**Files:**
- Modify: `harness/src/insurance_harness/compiler/models.py`
- Modify: `harness/src/insurance_harness/compiler/pipeline.py`
- Modify: `harness/src/insurance_harness/knowledge/importer.py`
- Modify: `harness/src/insurance_harness/sources/directory.py`
- Test: `harness/tests/test_source_pipeline_runtime_017.py`
- Test: `harness/tests/test_source_models_017.py`
- Test: `harness/tests/test_knowledge_importer.py`

- [ ] **RED provenance：** 新增 `test_rh3_1_directory_unknown_without_evidence_is_rejected_before_database_writes`，Directory unknown record 使用 `source_mode="directory_replay"`、`evidence=[]`，分别调用 legacy/source-aware importer；断言 ScopeViolation 且 ChangeSet/ChangeItem/Claim/ClaimEvidence 零新增。当前 PredRecord 不保存 mode、legacy path 接受该行，预期 RED。
- [ ] **RED pipeline tagging：** 新增参数化 `test_rh3_1_pipeline_emits_explicit_weknora_and_directory_source_modes`，直接覆盖 `_to_pred` 的 scoped manifest→`weknora`、unscoped manifest→`directory_replay`，并断言旧 JSON 缺字段时 `PredRecord` 解析为 `legacy`。运行 `uv run pytest tests/test_source_pipeline_runtime_017.py::test_rh3_1_pipeline_emits_explicit_weknora_and_directory_source_modes -q`，预期因字段不存在/默认错误 RED。
- [ ] **GREEN provenance：** `PredRecord` 增加 `Literal["legacy", "weknora", "directory_replay"]` 字段，旧 JSON 缺省 `legacy`；pipeline `_to_pred` 根据 scoped manifest 写 `weknora`，unscoped Directory 写 `directory_replay`；`import_pred_records` 在任何 scope query/mutation 前拒绝任一 `directory_replay` record。不得拒绝旧 `legacy` fixture或已批准 source-aware input。
- [ ] 运行：`uv run pytest tests/test_knowledge_importer.py::test_rh3_1_directory_unknown_without_evidence_is_rejected_before_database_writes tests/test_source_pipeline_runtime_017.py::test_rh3_1_pipeline_emits_explicit_weknora_and_directory_source_modes -q`，预期全部 PASS。
- [ ] **RED discovery：** 新增 `test_rh3_2_directory_discovers_mixed_case_pdf_suffixes_in_stable_order`，直接目录含 `a.pdf` 与 `B.PDF`，断言两份均物化且排序稳定。运行精确 node，预期当前只发现 `a.pdf` 的 RED。
- [ ] **RED typed failure：** 新增 `test_rh3_3_mixed_case_pdf_failure_is_typed_and_yields_no_partial_documents`，`a.pdf` 正常、`B.PDF` 在 page loader 失败；断言未 yield、typed stage/key/source_id 稳定。当前忽略 `B.PDF`，预期 RED。
- [ ] **GREEN discovery：** 用 `root.iterdir()` + `path.suffix.lower() == ".pdf"` 枚举直接候选并稳定排序；不要用 `Path.is_file()` 预过滤，因为它会跟随 symlink 且会把 FIFO `.pdf` 从既有 typed INTEGRITY failure 变成静默忽略。保留 loop 内 symlink/direct-file/snapshot 校验。
- [ ] 运行：`uv run pytest tests/test_source_models_017.py::test_rh3_2_directory_discovers_mixed_case_pdf_suffixes_in_stable_order tests/test_source_models_017.py::test_rh3_3_mixed_case_pdf_failure_is_typed_and_yields_no_partial_documents -q`，预期 2 passed。
- [ ] 运行 focused：`uv run pytest tests/test_source_models_017.py tests/test_source_pipeline_runtime_017.py tests/test_knowledge_importer.py -q`，预期全绿。
- [ ] 完成实现者自检 → spec review/re-review → quality review/re-review。

### Task 4: RH4 字段感知 KB identity

**Files:**
- Modify: `harness/src/insurance_harness/adapters/weknora/scope.py`
- Test: `harness/tests/test_client_scope_016.py`

- [ ] **RED：** 新增 metadata/chunk 两个 `rh4_2` case：scope tenant/raw KB 均为 `"5"`，响应 tenant `5` 合法但 `knowledge_base_id=5` 必须拒绝；同时保留 numeric tenant 与 `test_numeric_metadata_identity_normalizes_to_safe_download_path` 回归。当前 numeric KB 会跨型匹配，预期 RED。
- [ ] 运行：`uv run pytest tests/test_client_scope_016.py -k 'rh4_2' -q`，预期 numeric KB cases FAIL。
- [ ] **GREEN：** 新增 strict-string KB matcher，只替换 metadata/chunk `knowledge_base_id` 两处比较；tenant/knowledge 继续使用现有安全 numeric matcher。
- [ ] 运行：`uv run pytest tests/test_client_scope_016.py tests/test_weknora_source_contract_017.py -q`，预期全绿。
- [ ] 完成实现者自检 → spec review/re-review → quality review/re-review。

### Task 5: RH5/RH6 测试治理

**Files:**
- Modify: `CLAUDE.md`
- Test: `harness/tests/test_ci_lanes_022.py`

- [ ] **RED：** 新增 `test_rh6_1_claude_default_gate_selects_only_deterministic_lane`：精确且唯一要求 `pytest -m "not live and not integration_postgres" -q`，拒绝旧 `pytest -m "not live" -q`，并要求文档说明 PostgreSQL/live 独立 lane。当前 CLAUDE.md 仍为旧命令，预期 RED。
- [ ] 运行：`uv run pytest tests/test_ci_lanes_022.py::test_rh6_1_claude_default_gate_selects_only_deterministic_lane -q`，预期 FAIL 于旧 marker expression。
- [ ] **GREEN：** 更新 CLAUDE.md 默认门禁与独立 lane 说明；重跑精确 node，预期 PASS。
- [ ] 冻结 RH5：运行 `uv run pytest --collect-only -q tests/test_source_bridge_contract_017.py`，预期 12 tests collected；运行 `uv run pytest --collect-only -q tests/test_source_bridge_live_017.py`，预期 1 test collected；运行 `uv run pytest tests/test_ci_lanes_022.py -q`，预期 lane 精确合同全绿。不得改 bridge node ID/marker。
- [ ] 冻结 RH6：记录 016 scope 相关 suite before/after node manifest 或至少 `git diff --name-status` 删除检测，确认没有删除 capability/consumer tests。
- [ ] 完成实现者自检 → spec review/re-review → quality review/re-review。

### Task 6: 整体验证与交接

**Files:**
- Create: `openspec/changes/022-review-hardening/validation-report.md`
- Modify: `openspec/changes/022-review-hardening/tasks.md`
- Modify: `HANDOFF.md`

- [ ] 从仓库根运行 `openspec validate 022-review-hardening --strict`，预期 `Change '022-review-hardening' is valid`；telemetry 网络告警不改变 validator exit status。
- [ ] 从 `harness/` 运行 `uv run ruff check .`，预期 `All checks passed!`。
- [ ] 从 `harness/` 运行 `uv run mypy src tests`，预期 strict 零 issue。
- [ ] 从 `harness/` 运行 `uv run pytest -m "not live and not integration_postgres" -q`，预期 exit 0、零 failed。
- [ ] 创建 validation report，逐条记录正确原因的 RED、GREEN、focused/full 命令及审查结论。
- [ ] 更新 tasks/HANDOFF，明确 RH1 仅为函数内 savepoint hardening，outer transaction/进程终止/多页补偿仍属 018；RH2 不实现 ordering/processed_at/SourceHead/CAS，仍属 021；Directory 保持 eval-only；live 是 existing-knowledge 不是 upload。
- [ ] 外部状态：旧 PostgreSQL CI 证据不得覆盖未提交 working tree。人类提交/推送并获得最终 SHA 的 PostgreSQL 16 job 前，新的 integration 状态记 `PENDING HUMAN PUSH/CI`；WeKnora 无受控证据继续 `NOT RUN`。
- [ ] 完成整包 spec review/re-review，批准后再做整包 quality review/re-review；Critical/Important 为零才可交付人类复核。
- [ ] 运行 `git diff --check` 与 `git status --short`，报告真实 working-tree 状态；不由 AI commit/push。

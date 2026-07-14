# 022-review-hardening 验证报告

> 日期：2026-07-14。本文记录可复现的本地证据与实现 commit `e316487f` 的 GitHub CI；不借用更早 commit 的外部结果。

## 1. 当前状态

| 层级 | 状态 | 证据/下一步 |
|---|---|---|
| OpenSpec strict | PASS | `Change '022-review-hardening' is valid`，exit 0；PostHog telemetry DNS warning 非阻断 |
| 本地 deterministic 软件门禁 | PASS | Ruff、mypy strict、deterministic pytest 均 exit 0 |
| task-level 独立审查 | PASS | RH1～RH6 的 spec review 与 quality review 均在返修复审后 `Approved` |
| 整包独立审查 | PASS | 整包 spec review `Approved`；quality review 的唯一 Important 已按 TDD 修复并复审 `Approved` |
| GitHub deterministic | PASS | commit `e316487f` 的 required check 成功 |
| PostgreSQL 16 integration | PASS | commit `e316487f` 的 PostgreSQL 16 job 与 zero-skip JUnit guard 成功 |
| WeKnora live | `NOT RUN` | 没有受控 `harness-live` run URL、最终 commit、时间与零 skip JUnit 证据 |

整包软件实现、独立双审、提交推送与 PR #5 更新已完成；本报告不声称 WeKnora live 已运行。

## 2. 客观复审裁决

| 原意见 | 裁决 | 本 change 的实际处理 |
|---|---|---|
| ① rollback 外部写早于 DB flush | 成立 | RH1 在函数内 savepoint 中先落本地 mutation/flush，再执行 Wiki I/O；Wiki 失败回滚 savepoint |
| ② 空 Evidence recompile | 部分成立 | 新 revision 本来可 stage recompile；真实缺口是 applied、零 Evidence 的同 revision 被误判，RH2 只修该状态识别 |
| ③ Directory 回放导入黑洞 | 部分成立 | eval-only 拒绝是设计边界；RH3 增加显式 provenance 并闭合 unknown/JSONL 绕过，同时修复 `.PDF` 漏发现 |
| ④ int/string identity | 部分成立 | numeric tenant 与已批准的 numeric knowledge ID 继续兼容；只将 `knowledge_base_id` 收紧为严格字符串 |
| ⑤ live 文件拆名 | 当前 HEAD 不成立 | 已是 12 个 deterministic contract + 1 个真实 live node，本 change 不重复改名/迁移 node ID |
| ⑥ scope 测试再平衡 | 观察成立，删测结论不成立 | 不按 overlap 自动删隔离证明；RH6 修正本地 deterministic lane 合同与命令解析回归 |

## 3. RED → GREEN 与条款证据

### RH1 · rollback savepoint 写序

- RH1.1 RED：注入 rollback `flush` failure 时，失败前已经发生 **2 次 Wiki HTTP**，证明外部 mutation 早于本地持久化检查。
- RH1.1 GREEN：rollback ChangeSet、pointer move 与 `flush` 进入 nested transaction，并位于第一次 Wiki I/O 之前；flush failure 时 Wiki 请求为零。
- RH1.2 RED：只交换写序的中间实现中，Wiki 失败后 caller 提交 outer transaction，会把 pointer/audit 持久化。
- RH1.2 GREEN：DB mutation/flush 与 Wiki loop 置于同一 savepoint；Wiki 异常退出会回滚本地 pointer/audit。
- focused：`uv run pytest tests/test_scope_publisher_016.py tests/test_knowledge_publisher.py -q` → **43 passed, 1 skipped**，exit 0。
- 独立审查：task spec review `Approved`；task quality review `Approved`，无剩余 finding。

边界：这只是函数内 savepoint hardening。函数返回后的 outer transaction commit/rollback、进程终止、跨多页外部补偿与 reconciliation 仍归 018；不得称为 PostgreSQL/WeKnora 原子提交。

### RH2 · 零 Evidence 同 revision

- RH2.1 RED：通过真实 importer 建立 unknown-only、零 ClaimEvidence aggregate 后，同 identity 的 `document` 报 `source change set is ambiguous`，`recompile` 报 `source change set cannot be replayed`。
- RH2.1 GREEN：仅在 active revisions 为空时，对同 identity 的唯一 aggregate 做完整 scope/parent/child/status/action/decision 校验；合法 applied `document|recompile` 返回 same-revision no-op。
- RH2.2 characterization：新 identity 创建并复用唯一 pending recompile、`stale_count=0` 是既有 baseline GREEN；该用例用于防止新分支把 B 误判为 A，没有人为制造 RED。
- RH2.2 fail-closed quality RED：`invalid action` 与 `applied + needs_review` 两种畸形 aggregate 均出现 `DID NOT RAISE`；补齐完整 aggregate 校验后恢复无泄漏拒绝与零 mutation。
- 整包 quality RED：持久化 `ChangeItem.proposed=[]` 时，共享 validator 在 `merge.py:290` 泄漏 `AttributeError: 'list' object has no attribute 'get'`（focused **1 failed, 7 deselected**），违反 malformed child 的无泄漏合同。
- 整包 quality GREEN：在 RH2 helper 的 validator 边界保留既有 `ScopeViolation`，只将数据形状导致的 `AttributeError/TypeError/ValueError` 归一化为 `ScopeViolation("source change set cannot be replayed")`；不吞 SQLAlchemy/I/O/系统异常。精确 node **1 passed, 7 deselected**，完整 fail-closed 参数集 **8 passed**。
- focused：`uv run pytest tests/test_source_revision_notify_017.py tests/test_source_revision_import_017.py -q` → **62 passed**，exit 0。
- 独立审查：task spec review `Approved`；task quality review 经首轮返修后 `Approved`；整包 quality 的 non-object JSON finding 修复后复审 `Approved`。

边界：RH2 不比较 revision hash 先后，不新增 `processed_at` ordering、SourceHead、per-source lock 或 CAS；不同 revision 并发/乱序仍归 021/B23。

### RH3 · Directory provenance 与 discovery

- RH3.1 provenance RED：初始 **4 failed**，两条 importer 路径未拒绝 Directory unknown record，且 `PredRecord` 没有 `source_mode`。
- RH3.1 GREEN：新 pipeline 逐行写 `weknora|directory_replay`，旧 JSON 缺字段时默认 `legacy`；records/JSONL、legacy/source-aware 四条入口均在数据库 mutation 前拒绝 `directory_replay`。
- quality re-review RED：records 两例已通过，但 JSONL 两例仍失败，且每例已经执行 **1 条 KnowledgeSpace SELECT**；JSONL 改为先 parse/reject 后 attestation query，闭合“零数据库访问/写入”的精确失败面。
- RH3.2/RH3.3 RED：初始 **2 failed**，大写 `.PDF` 被忽略，损坏的 `B.PDF` 也未产生 typed all-or-nothing failure。
- RH3.2/RH3.3 GREEN：直接目录以 `suffix.lower()=='.pdf'` 稳定排序发现大小写后缀；任一物化失败仍返回稳定 stage/key 的 `SourceMaterializationError`，不 yield 部分 batch。
- focused：`uv run pytest tests/test_source_models_017.py tests/test_source_pipeline_runtime_017.py tests/test_knowledge_importer.py -q` → **136 passed**，exit 0。
- 独立审查：task spec review `Approved`；task quality review 经 JSONL preflight 返修后 `Approved`。

边界：Directory replay 仍是 Golden/评估输入，不能导入生产知识库、不能伪造 `knowledge_id/raw_kb_id`；本 change 不新增递归目录扫描。

### RH4 · 字段感知 KB identity

- RH4.2 RED：metadata/chunk 两个 numeric `knowledge_base_id=5` case 均 `DID NOT RAISE ScopeViolation`。
- RH4.2 GREEN：只在 metadata/chunk 的 `knowledge_base_id` 使用严格字符串 matcher；tenant 与 knowledge identity 保留既有安全 numeric 兼容。
- RH4.1 regression：numeric tenant 与 numeric knowledge identity 合同继续通过。
- focused：`uv run pytest tests/test_client_scope_016.py tests/test_weknora_source_contract_017.py -q` → **110 passed**，exit 0。
- 独立审查：task spec review `Approved`；task quality review `Approved`，无剩余 finding。

### RH5/RH6 · 测试治理

- RH5 characterization：当前基线已为 GREEN，不制造行为 RED；collection 冻结为 contract **12 tests**、live **1 test**。该 live node 是 existing-knowledge E2E，不是 upload 创建覆盖。
- RH6.1 RED：CLAUDE.md 仍使用 argv marker `not live`，会在本地选择 PostgreSQL integration；质量复审另以 **3 个 RED** 锁定换行合并与替代 pytest prefix 漏检。
- RH6.1 GREEN：默认命令精确为 `not live and not integration_postgres`；lane parser 合同覆盖等价调用与 Markdown 换行。
- RH6.2：`git diff --diff-filter=D -- harness/tests` 无输出；没有按行数、node 数或 overlap 删除 capability/consumer 测试。
- focused：`uv run pytest tests/test_ci_lanes_022.py -q` → **15 passed**，exit 0。
- 独立审查：task spec review `Approved`；task quality review 经 parser 返修后 `Approved`。

follow-up（不在本 change 文件边界）：`harness/README.md:29` 仍展示旧的 `pytest -m "not live" -q`。后续文档清理应改为 deterministic marker expression；历史 OpenSpec/validation 中的旧命令是当时证据，不应机械改写。

### RH7 · TDD 与分层状态

- 行为测试名包含 `rh1_1/rh1_2`、`rh2_1/rh2_2`、`rh3_1/rh3_2/rh3_3`、`rh4_2`、`rh6_1`，可回溯对应条款。
- RH2 新 identity、RH4 numeric compatibility、RH5 collection 被明确记录为 characterization/regression baseline GREEN，没有伪造 RED。
- 本地 deterministic 通过不替代 PostgreSQL CI，更不替代 WeKnora live；外部状态见 §6。

## 4. 最终本地门禁（fresh evidence）

所有命令均在当前未提交 working tree 上于 2026-07-14 重新运行：

```text
# repository root
openspec validate 022-review-hardening --strict
Change '022-review-hardening' is valid
exit 0

# harness/
uv run ruff check .
All checks passed!
exit 0

uv run mypy src tests
Success: no issues found in 151 source files
exit 0

uv run pytest -m "not live and not integration_postgres" -q
961 passed, 5 deselected, 209 warnings in 78.16s
exit 0
```

OpenSpec 命令随后尝试 flush PostHog telemetry 时出现 `ENOTFOUND edge.openspec.dev`；validator 自身先返回 valid 且进程 exit 0，因此该网络告警只记录为非阻断 telemetry 失败。

## 5. 独立审查状态

| 范围 | Spec review | Quality review | 结论 |
|---|---|---|---|
| OpenSpec / implementation plan | `Approved` | — | strict validator PASS |
| RH1 | `Approved` | `Approved` | 无剩余 finding |
| RH2 | `Approved` | `Approved after fixes` | action/decision fail-closed finding 已修复复审 |
| RH3 | `Approved` | `Approved after fixes` | JSONL preflight finding 已修复复审 |
| RH4 | `Approved` | `Approved` | 无剩余 finding |
| RH5/RH6 | `Approved` | `Approved after fixes` | parser findings 已修复复审 |
| 整包 022-review-hardening | `Approved` | `Approved after fix` | 唯一 Important：non-object persisted JSON 泄漏 `AttributeError`；已按 TDD 修复并复审，无剩余 Critical/Important/Minor |

## 6. 外部证据与仓库状态

- 实现 commit：`e316487f391b944d08b010b7d4cf538e7430ed0b`，已推送至 `codex/016-enterprise-foundation` 并更新 [PR #5](https://github.com/PA-ALG/InsuranceKB-WeKnora/pull/5)。
- GitHub deterministic：[PASS](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29326117805/job/87062728898)，run 对应 head `e316487f`。
- PostgreSQL 16 integration：[PASS](https://github.com/PA-ALG/InsuranceKB-WeKnora/actions/runs/29326117805/job/87062729019)，zero-skip JUnit guard 同步通过。
- WeKnora：`NOT RUN`。existing-knowledge live E2E 未受控运行，且当前 adapter 不提供 uploader，所以不能表述成 upload 覆盖。
- 本次 commit/push/PR 更新由用户在会话中明确授权；没有 force-push。
- 提交前仓库检查：`git diff --check` exit 0；`git diff --diff-filter=D -- harness/tests` exit 0 且无输出，确认未删除测试。实现提交后 working tree clean。
- 上述检查、整包双审、本地门禁与实现 commit 外部 CI 均满足后，T7 已勾选；PR 后续文档类提交仍须保持 required checks 全绿。

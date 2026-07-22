# 029 ReleaseManifest + Human Approval MVP 验证报告

> 日期：2026-07-22。本文区分 029 本域软件证据、真实 PostgreSQL/最终整包门禁和跨域集成证据；`PENDING`、`NOT RUN`、skip 或 sanitized fixture 均不得表述为生产验收成功。

## 1. 当前结论与证明力边界

029 推进 Enterprise LLM Wiki 的发布权威主链：完整 serving 制品被一个 canonical `ReleaseManifest` 绑定，具名真人的 exact-hash approval 与显式 expected-current CAS 分离，Human/Agent 共享 `ApprovedSnapshotReader` 合同，逻辑回滚不重新调用模型，P-1 前普通用户 WeKnora Wiki 发布保持 fail closed。

| 范围 | 当前状态 | 证据边界 |
|---|---|---|
| RA1～RA6 本域实现 | PASS | 各阶段 Spec/Quality 双审均已 `Approved` |
| RA7 本域实现 | LOCAL PASS | stable-root-FD、atomic final install 与最后 inode/byte closure 已独立 Spec/Quality `APPROVED FOR DRAFT`；post-rebase focused 含全部 `103` 条 CLI tests |
| 029 fresh focused | PASS WITH EXPECTED PG SKIP | rebase 后最新 HEAD：`233 passed, 1 skipped in 26.76s`；该 skip 是未注入 URL 的 integration marker，不作为 PG 证据 |
| Ruff / mypy / diff | PASS | Ruff clean；mypy `318` source files clean；文档提交后的 OpenSpec/diff 结果见 §10 |
| 真实 PostgreSQL 16 | PASS | rebase 后最新代码 HEAD isolated container：`4 passed, 40 deselected in 3.03s`；JUnit guard `tests=4 skipped=0` |
| RA7 跨域集成 | BLOCKED EXTERNALLY | 028 producer/public contract、ClaimEvidence lineage 与 production trusted composition 尚未提供；029 缺合同路径 fail closed |
| 整包独立 Spec/Quality review | APPROVED FOR DRAFT | Quality findings 经逐轮 RED→GREEN remediation；最终增量 Spec/Quality 均无 Critical/Important |
| final full deterministic / PR | DRAFT ONLY | 已 rebase 到 `origin/main=5fe3c396`；七个 external contract blocker 未关闭，full deterministic 按计划未运行 |
| 生产 WeKnora UI | NOT RUN / BLOCKED | P-1 capability 不存在，返回 typed `P1CapabilityMissing` |
| 真实 model/provider/Node/TS | 0 calls | 029 治理路径不导入、不调用这些执行面 |

本报告没有修改 `HANDOFF.md`、控制板、registry、028、ClaimEvidence、MCP/workbench、030/032 或任何源码/测试；这些共享域由对应 Owner 串行更新。

## 2. RA1 canonical manifest 证据

### 2.1 四类 serving artifact

以下是 `tests/test_release_manifest_029.py::_manifest` 的 sanitized fixture，经当前 canonical 实现重新计算；它只证明算法与固定测试向量，不是生产 release 记录。

| Artifact group | Count | SHA-256 |
|---|---:|---|
| facts（含完整 frozen Evidence） | 2 | `209842c9e0b18efc19d153bb73ed735e226f91a430a264e1c1938a901d437e35` |
| rendered pages | 2 | `25bdf20453a69494e15f35770e828e8ad797e2b54abe12709188adb36b0eebbb` |
| directory entries | 2 | `f9ba4ee6ad524da6a3cc44b497f47bab4a8ad634425e08fbf6ad49120122abd6` |
| relationships | 2 | `1b667c538d621dd542019a707062d6dca03f0f4233d5ef953b8ed9167049d695` |

同一 fixture 的外层 `manifest_sha256`：

```text
077d2dea3d2fbb84104e74e3410b6f145c8c7ca38f1ac62ce16b8c626fd60a8f
```

示例同时绑定 `schema_version`、`space_id`、`snapshot_id`、`read_model_version`、canonical-sorted `template_hashes` 与 `model_plan_hash`。四组 item tuple、各自 count/digest 和上述 identity 全部进入外层 payload。空组显式表示为 `[]`、`count=0` 和 canonical `[]` hash，不允许省略。

哈希算法固定为：

```python
sha256(
    json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()
```

### 2.2 Mutation matrix

| 变更/伪造 | 分组 digest | 外层 hash | 验证结果 |
|---|---|---|---|
| fact 或 Evidence insert/delete/mutate | 改变 | 改变 | 旧 manifest/approval fail closed |
| rendered page insert/delete/content mutate | 改变 | 改变 | fail closed |
| directory entry insert/delete/mutate | 改变 | 改变 | fail closed |
| relationship insert/delete/mutate | 改变 | 改变 | fail closed |
| 任一 group count 伪造 | 与 canonical items 不一致 | 不可信 | `ReleaseManifestIntegrityError` |
| 任一 group SHA-256 伪造 | 与 canonical items 不一致 | 不可信 | `ReleaseManifestIntegrityError` |
| outer `manifest_sha256` 伪造 | 分组可不变 | 不匹配 | `ReleaseManifestIntegrityError` |
| artifact 输入顺序/JSON key 顺序变化 | 不变 | 不变 | canonical 等价 |
| Evidence 同一时刻的不同时区表示 | 不变 | 不变 | 统一规范为 UTC |
| naive Evidence datetime、NaN/Inf、mutable/非 JSON 值 | — | — | schema/build fail closed |
| snapshot 后 mutable Claim/Evidence 改动 | frozen manifest 不变 | 不变 | builder/reader 不回查 mutable Claim 补正文 |

## 3. RA2/RA3/RA5 persistence、approval、CAS 与 rollback

### 3.1 Authorization matrix

| 请求 | 结果 | CurrentRelease |
|---|---|---|
| 具名 `human`/`principal`，Space、`release_approver`、manifest hash、authorization receipt 全部 exact | append one approval；exact retry 幂等 | 不变 |
| `model` 或 `service` actor | typed authorization rejection | 不变 |
| 未授权 principal 或 authorizer unavailable/denied | typed rejection | 不变 |
| wrong Space / role / actor / manifest hash / receipt | typed exact-attestation rejection | 不变 |
| 缺失、空白或非 canonical actor/receipt/reason | validation/approval rejection | 不变 |
| 同一 manifest 的不同 attestation | 一个 winner；另一个 typed `ReleaseApprovalError` | 不变 |
| approval 后 frozen projection drift | manifest rebuild mismatch + safe alert path | 不变 |

`ReleaseApproval` 记录 `space_id + snapshot_id + manifest_hash + actor + actor_type + role + authorization_receipt + reason + approved_at`，并由 migration guard 保持 append-only。Approval service 只 flush，不替 caller commit/rollback，也不移动 current pointer。

### 3.2 CAS 与 rollback matrix

| 操作 | 前置 | 结果 |
|---|---|---|
| 首次 promote | exact approval、重算 manifest 相同、显式 `expected_current_snapshot_id=null` | CAS 成功并 append activation audit |
| 后续 promote | exact approval/hash 且 expected current 与 DB current exact | CAS 成功 |
| stale expected current / wrong Space / missing approval | 任一不匹配 | typed failure；pointer 不变 |
| approval 后 artifact tamper | 重算 hash 不同 | typed failure + append safe alert；pointer 不变 |
| concurrent promote | 相同 expected current | 设计目标为一个成功、loser typed stale-CAS |
| rollback | 目标仍有 exact approval，且曾有 exact activation audit，expected current exact | 复用同一 CAS 内核切换 |
| rollback 到未批准、hash substitution 或从未激活 candidate | 前置不成立 | typed failure；pointer 不变 |

Rollback 路径的静态边界禁止 `runtime/model/provider/publisher`，测试 provider fake 为零调用；旧 snapshot 不重新生成事实。

### 3.3 PostgreSQL 硬门禁

Migration graph 的 fresh 只读检查为 `uv run alembic heads` → `0013 (head)`。随后在 isolated PostgreSQL 16 container 上执行真实 lane：

```text
HARNESS_TEST_POSTGRES_URL=<sanitized-isolated-postgresql-16-url> \
uv run pytest -q -m integration_postgres \
  tests/test_release_manifest_migration_029.py \
  tests/test_release_approval_029.py \
  --junitxml=reports/postgres-029.xml

4 passed, 40 deselected in 3.03s

uv run python scripts/check_junit.py reports/postgres-029.xml
tests=4 skipped=0
```

| PostgreSQL 行为 | 实测结果 | 当前 |
|---|---|---|
| manifest UPDATE / DELETE | DB trigger 以 SQLSTATE `23514` 实际拒绝；nested savepoint 后 Session 可用 | PASS |
| approval UPDATE / DELETE | DB trigger 以 SQLSTATE `23514` 实际拒绝；nested savepoint 后 Session 可用 | PASS |
| activation audit / release alert UPDATE / DELETE | DB trigger 实际拒绝；row counts 保持不变 | PASS |
| exact composite FK / cross-Space splice | `fk_release_approvals_exact_manifest` 以 SQLSTATE `23503` 实际拒绝 | PASS |
| `role=release_approver` CHECK | `ck_release_approvals_role` 以 SQLSTATE `23514` 实际拒绝非法 role | PASS |
| non-empty downgrade preflight | 在首个 DDL 前 fail closed；version、tables、triggers、rows 均不变 | PASS |
| exact manifest race | 两个真实 backend 在 precheck 后竞争并收敛同一 manifest，caller Session 均可用 | PASS |
| same approval attestation race | 两个真实 backend 收敛同一 approval | PASS |
| different approval attestation race | 一 winner、一 typed `ReleaseApprovalError`；loser Session 可继续 scoped query/flush | PASS |
| concurrent CurrentRelease CAS | 一 winner、一 typed `stale_current_release`；两个 Session 均可用 | PASS |

该 lane 早期暴露两个 029 test-only 问题：并发 helper 派生的 child ID 超过数据库 `VARCHAR(36)`，以及 loser Session 可用性断言误用了全局 manifest count、没有按竞争 Space 精确计数。rebase 后最终门禁又暴露 production `_insert_if_absent` 只指定一个 conflict arbiter，无法稳定吸收同一 row 同时命中 snapshot/hash 两个唯一约束；真实 RED 为 raw `UniqueViolation`。实现改为 targetless `ON CONFLICT DO NOTHING`，再由 scoped exact winner read 区分幂等或 typed conflict；原失败与整条 PG lane 重跑通过。此证据来自真实 PostgreSQL trigger、constraint、`RETURNING`、savepoint 与并发 backend，SQLite 没有替代任何 PG 语义。

## 4. RA4 唯一 ApprovedSnapshotReader 合同

唯一公开读取方法为：

```python
def read_current(
    self,
    scope: KnowledgeScope,
    *,
    product_id: str | None = None,
    product_version_id: str | None = None,
    predicates: tuple[str, ...] | None = None,
    effective_on: date | None = None,
    claim_id: str | None = None,
) -> ApprovedSnapshotResult | ServingFailure: ...
```

权威链固定为 `CurrentRelease → published/frozen ReleaseSnapshot → exact ReleaseManifestRecord → recomputed ReleaseManifest → exact ReleaseApproval`。读取只消费 manifest 中冻结事实；不查询 mutable Claim。

成功 DTO：

- `ApprovedSnapshotResult(snapshot_id, manifest_hash, approval_principal, approved_at, read_model_version, facts)`；
- `CanonicalServingFact` 包含 claim/revision、product/version、predicate/name/group、三态 value、effective interval、confidence、schema version 和稳定排序 Evidence；
- document Evidence 保留 knowledge/source revision、quote、authority、page/chunk 与 lineage；
- structured Evidence 是为 010 预留的严格 discriminated branch，包含 source system/record/revision/locator/hash/mapping version，不伪造 page/chunk。

失败 DTO 为不含 facts 的 `ServingFailure(code, snapshot_id?, manifest_hash?)`。固定 code：`no_release`、`unsupported_read_model`、`approval_missing`、`manifest_missing`、`manifest_mismatch`、`product_not_found`、`predicate_not_found`、`effective_date_miss`、`claim_not_found`、`scope_mismatch`。跨 Space 失败不泄露 foreign identity；coverage gap 不用空 facts 冒充成功；批准快照中的 `unknown` 仍是成功 fact。

Facts 排序键为 `(product_id, product_version_id, predicate, effective_from|date.min, effective_to|date.max, claim_id, revision_no)`；Evidence 以 kind + 稳定 source identity + evidence id 排序。Human/Agent 应导入同一 DTO/方法并回显同一 `snapshot_id + manifest_hash`；013/032 consumer wiring 不在 029 文件域内。

## 5. RA6 staging 与 P-1 边界

- `build_staging_candidate_manifest` 只允许 frozen、`building` 状态 candidate；不创建 approval、不移动 `CurrentRelease`，未批准 candidate 对 `ApprovedSnapshotReader` 不可见。
- legacy 007/018 publisher 与 release plan 已从 production `src` 删除，只保留在 `tests/support` 作为 staging/test-only characterization；production package 不再导出其 writer/executor/client surface。
- test-only writer 的所有 module/class/private I/O entrypoint 都必须先验证不可伪造、exact `(space_id, wiki_kb_id)` staging capability；无 capability、伪造 capability、wrong scope/wiki 在 DB/Wiki 副作用前失败。
- production 唯一边界 `request_production_wiki_publish(ProductionWikiPublishRequest)` 没有 client/executor surface，固定返回 `P1CapabilityMissing(status="blocked", code="p1_capability_missing")`，并保持现有 approved reader/pointer 不变。
- `P-1 / production WeKnora Wiki UI = NOT RUN / typed BLOCKED`。029 不改变 018 state machine，也不声称普通用户 Wiki UI 已上线。

## 6. RA7 人控治理 CLI

五个固定命令：

```text
python -m insurance_harness.knowledge.release_cli apply-review-decisions --request <human-yaml> --compilation-manifest <json> --output <json>
python -m insurance_harness.knowledge.release_cli build-candidate --run-request <yaml> --review-receipt <json> --output-dir <new-dir>
python -m insurance_harness.knowledge.release_cli approve-manifest --request <human-yaml> --manifest <json> --output <json>
python -m insurance_harness.knowledge.release_cli promote-approved --request <human-yaml> --manifest <json> --approval-receipt <json> --output <json>
python -m insurance_harness.knowledge.release_cli seal-run-artifacts --directory <dir> --compilation-manifest <json> --release-proof <json> --serving-proof <json>
```

模块只导入既有 review/release/serving services；architecture tests 禁止 compiler runtime/stage、model/model_policy、provider、MCP/workbench、subprocess/Node/TS 路径。没有 trusted application `GovernanceContext` 时，直接 `python -m` 固定 stderr `{"code":"trusted_context_required","status":"blocked"}`、exit `2`、零写入；artifact/request 文件本身不能创建 authority。

### 6.1 Sanitized human review request

```yaml
input_origin: human-authored
space_id: space-1
compilation_manifest_hash: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
decisions:
  - review_id: review-1
    expected_version: "2026-07-22T00:00:00+00:00"
    action: approve
    principal: alice@example.com
    actor_type: human
    authorization_receipt: iam:reviewer:alice:42
    reason: inspected exact ChangeSet and evidence
    request_id: review-request-1
```

对 strict parsed JSON payload 使用 §2.1 canonical 算法，示例 `request_hash` 为：

```text
c6a72c6c7005453419cf857aaba61d604cb2fd89ece3db6efda85ecee8bbdb60
```

每个 blocking ReviewItem 必须出现一次，并绑定 exact version、explicit `approve|reject`、具名 principal、auth receipt、reason 与 request ID；不存在默认 decision、`defer→approve`、模型/服务账号或批量自动批准。

### 6.2 Sanitized release approval request

```yaml
input_origin: human-authored
space_id: space-1
manifest_hash: eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
snapshot_id: snapshot-1
expected_current_snapshot_id: null
principal: release.owner@example.com
actor_type: human
authorization_receipt: iam:release-approver:owner:42
reason: inspected complete release manifest
```

同一算法计算的示例 `request_hash`：

```text
64e61fed26274b0c337f88684413f3e6f2605eea7131b8b75eb0691d9385656e
```

`expected_current_snapshot_id` 必须显式存在，值可为 `null`；缺字段与显式 `null` 不等价。CLI 不发现并代填 manifest hash、snapshot、principal、receipt 或 expected current。

## 7. Compilation-to-final-seal proof

当前 029 本域验证链：

1. `apply-review-decisions` 重新核对 compilation manifest hash、Space、完整 blocking ReviewItem/ChangeSet/ChangeItem inventory、stale version 与 external authorizer；只按真人明确 action 调用既有 review service。
2. `build-candidate` 重验每个 compiler file 的 safe relative path、hash、size、item count，重验 review receipt/DB event/ChangeItem exact inventory，并核对 base snapshot/hash、target revisions/facts hash 与 accepted ChangeItem lineage；candidate 是 fresh DB-only projection，`CurrentRelease` 不变。
3. `approve-manifest` 重验完整 ReleaseManifest 与 explicit expected current，只 append exact approval/receipt，不 promote。
4. `promote-approved` 重放相同 human request、manifest、approval receipt 与 DB exact row，只调用一次 RA3 CAS；成功后写 exact release proof。
5. `seal-run-artifacts` 重验完整 human/review/candidate/approval/release/serving chain、DB current/audit/approval，以及两次实际 `ApprovedSnapshotReader` 返回的 Human/MCP exact DTO。它在 directory lock 下以 no-follow 方式打开并持有单一 run-root FD；递归扫描与 stable read 全部相对该 FD。最终 JSON 先写入不可预测 private temp inode 并 `fsync`，再以 descriptor-relative hard-link exclusive install 到 `artifact-manifest.json`，因此 partial bytes 永不可见；final 安装后不做存在 TOCTOU 的按名删除。post-scan/root verify 之后最后重验安装 inode 与 exact bytes，路径/内容漂移 typed fail closed。

本域 tests 已覆盖 compiler artifact drift、request/receipt semantic substitution、stale/concurrent DB state、self-declared serving proof、reader ordering/evidence/principal/time/version drift、seal 前后文件 TOCTOU、whole-directory rename、same-directory replacement sentinel、private partial write、late extra file、post-child typed error 与 post-scan final replacement。

跨域真实 compilation-to-final-seal run 仍为 `BLOCKED EXTERNALLY`，不能把 029 synthetic/fake producer fixture 表述为 028 integration PASS。

## 8. External integration blockers（029 不跨域修）

1. 028 producer/public compilation contract 尚未提供 `compiled_at`。
2. 028 contract 尚未提供 paired `base_snapshot_id` / `base_manifest_hash`。
3. 028 contract 尚未提供 exact `change_items` inventory；每项至少需要 `change_set_id`、`change_item_id`、`claim_id`、`action`、`decision`。
4. 028 contract 尚未提供 exact `target_claim_revisions`。
5. 028 contract 尚未提供 canonical `target_facts_hash`。
6. `ClaimEvidence` 没有 `change_item_id`；Evidence-only 合法变更目前无法证明 exact lineage，因此必须 fail closed。
7. production `ReleaseAuthorizer` 与 028/029 trusted composition root 不存在；直接 shell CLI 只能 typed blocked、exit 2、零写。

在这些 producer/lineage/authority 合同落地前，029 不复制 028 producer，不修改 ClaimEvidence，也不以猜测/default/数据库发现代替 sealed input。尤其 Evidence-only same-revision delta 必须拒绝，不能静默视为合法 candidate。

## 9. Review 状态

| 范围 | Spec review | Quality review | 结论 |
|---|---|---|---|
| RA1 manifest | Approved | Approved | 本域关闭 |
| RA2 persistence/approval | Approved | Approved | 本域关闭；PG 最终环境门禁另列 |
| RA3 promote / RA5 rollback | Approved | Approved | 本域关闭；PG CAS 最终环境门禁另列 |
| RA4 serving reader | Approved | Approved | 本域关闭 |
| RA6 staging/P-1 boundary | Approved | Approved | 本域关闭 |
| RA7 governance CLI | APPROVED FOR DRAFT | APPROVED FOR DRAFT | stable-root-FD、inode-safe failure handling、atomic complete-final install 与 last exact closure 已逐轮复审关闭 |
| Whole change RA1～RA7 | APPROVED FOR DRAFT | APPROVED FOR DRAFT | 最终无 Critical/Important；七个跨域 blocker 不因本域通过而关闭 |

最终 reviewer 已逐项检查 tenant isolation、mutable-read absence、append-only approval、无自动真人 decision、governance-only imports、final-seal ordering、migration/down-grade guards 与真实并发结果。

## 10. 验证账本与退出条件

### 10.1 已有 fresh 本域证据

| 门禁 | 结果 |
|---|---|
| RA7 CLI focused | standalone remediation run `103 passed in 15.48s`；随后全部纳入 post-rebase focused |
| 029/root focused | post-rebase `233 passed, 1 skipped in 26.76s`；PG URL 缺失产生 integration skip，不计作 PG PASS |
| PostgreSQL 16 integration | post-rebase 最新代码 HEAD：`4 passed, 40 deselected in 3.03s`；JUnit guard `tests=4 skipped=0` |
| Alembic graph | `0013 (head)`，单 head |
| Ruff | PASS |
| mypy | `Success: no issues found in 318 source files` |
| `git diff --check` | PASS |
| OpenSpec strict（Task 8 文档后） | `Change '029-release-manifest-approval-mvp' is valid`，exit 0 |

### 10.2 尚未完成

- independent Spec/Quality review：`APPROVED FOR DRAFT`；所有已报告 Critical/Important 均已 RED→GREEN 并由原 reviewer 复核关闭。
- 已 fetch/rebase `origin/main=5fe3c396`；focused/static 与最新代码 HEAD 的真实 PG lane 均已重跑，PG JUnit `skipped=0`。
- PR-ready full deterministic：NOT RUN BY DESIGN；七个 external integration blocker 尚未关闭，且当前只允许 Draft。
- diff/cross-domain/secret audit：PASS；唯一数据库 URL pattern 命中为 migration 测试固定 fixture `user:password@localhost`，不是凭据。最终代码 head 为 `c8c2f58b`；push/Draft PR URL 待创建后回填。

退出规则：真实 PG、增量独立双审、rebase 后 focused/static 均已关闭；七个 external integration blocker 仍使本分支最多创建 Draft。不得自行 merge。

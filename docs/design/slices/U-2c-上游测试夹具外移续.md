# U-2c · 上游测试夹具外移（续）：parent_child 与 knowledge_replace

> 状态：Claude 2026-10-31 提出 ｜ 作者：Claude Code ｜ Issue #451（U-1 阶段 c）｜ 前一片：U-2b（#490）
> 依据：蓝图 §8 G10（上游补丁只减不增）、G11（上游包内不新增生产 Go 文件，测试文件允许）；U-2b Spec §2.2
> “可还原但需先改我方测试夹具”两项。真实模型调用 0；不部署；不改生产代码。

## 1. 目标

把 U-2b 留下的两个上游测试文件恢复为固定上游 v0.9.0（`f17ee8a8d`）原字节，G10 153 → 151：

| 文件 | 我方改动（现状） | 处理 |
|---|---|---|
| `internal/application/service/knowledge_process_parent_child_test.go` | 共用桩加字段（`existing`、`deleted`、`batchErr`、`afterBatch`）与方法（`ListAllChunksByKnowledgeID`、`DeleteChunks`、`CreateChunksAtRevision`、`DeleteByChunkIDList`，`BatchIndex` 可失败/回调）；上游测试外包一层 `require.NoError` | 见 §2.1 |
| `internal/application/service/knowledge_replace_test.go` | 夹具整体移到我方 `knowledge_replace_fixture_test.go` 并加字段（`allocated*`、`sourceSnapshots`、`files`）与方法；文件尾部两个我方测试 | 见 §2.2 |

## 2. 做法

共同原则（沿用 U-2b）：上游测试文件逐字节还原；我方代码只出现在同包的我方测试文件里；断言原样搬运；生产代码不改。
**U-2b R1 教训**：包装类型嵌入上游桩时，凡上游桩有方法在内部调用被覆写的方法，包装类型也必须覆写那个方法（内层接收者
不会分派到外层）。本片每个包装类型的注释写明“嵌入桩没有方法调用被覆写的方法”，并在 §4 用变异核对断言的故障敏感性。

### 2.1 parent_child

- 我方生产代码在每次 `processChunks` 里按精确 ID 清理（W1）、按解析修订写分块、可能按分块 ID 删向量，所以共用桩需要这几个
  方法。它们放在我方新文件 `knowledge_process_parent_child_revision_test.go`，声明在上游桩类型上，**不保存状态**
  （上游桩无法加字段）：`ListAllChunksByKnowledgeID` 返回空、`DeleteChunks` / `DeleteByChunkIDList` 无操作、
  `CreateChunksAtRevision` 与上游 `CreateChunks` 一样记录 `created`。
- 需要观察清理结果的我方测试改用同文件里的记录型包装：`recordingChunkService`（记录 `DeleteChunks` 的 ID）、
  `recordingRetrieveEngine`（记录 `DeleteByChunkIDList`，`BatchIndex` 先调上游桩记录 `indexed`，再回调 `afterBatch`、
  返回 `batchErr`）。使用方：我方 `knowledge_attempt_cleanup_upgrade_test.go`（只改夹具构造与参数类型，断言不变）。
- 已登记保留的上游补丁文件 `knowledge_process_index_retry_test.go`（U-2b §2.2“行为改变”类）原本经嵌入读取共用桩的
  `deleted` 字段；本片在它的两个桩类型上各加一个 `deleted` 字段（仅 2 行），记录方法放在上面的我方文件里。该文件仍是补丁
  文件，计数不变。
- 我方加在上游测试外的 `require.NoError` 成为同文件新测试 `TestProcessChunksIndexesEveryTextChildSucceeds`，准备步骤与上游
  测试相同（U-2b 对追加断言的同一处理）。

**lint**：还原后上游原句 `svc.processChunks(...)` 不检查返回值，`golangci-lint --new-from-merge-base` 会在本 PR 报 1 个
`errcheck`（该行与上游字节相同；合并后不再是“新问题”）。`.golangci.yml` 与 `go-lint.yml` 都是未改的上游文件，加排除会新增
补丁文件，抵消本次还原。处理需 Owner 裁定：(a) 作为文档化例外接受（先例：#460 对上游原样行的 36 个 lint 问题）；或
(b) 本文件不还原（回退本片中单独的 parent_child 提交并同步 RED 清单）。同类的 `opensearch/repository_test.go`（U-2b 因
`lll` 保留）在 (a) 下也可还原，不在本片范围。

### 2.2 knowledge_replace

- 删除我方 `knowledge_replace_fixture_test.go`；还原后的上游文件重新提供夹具。新我方文件 `knowledge_replace_revision_test.go`：
  - 在上游桩类型上声明我方生产路径需要的方法：`replaceFileRepo.AllocateParseAttempt`（只更新单行，与原夹具同义）、
    `CommitDirectRevision` / `FinalizeSubtaskRevision`（入队阶段不应调用，返回错误，与原夹具同义）、`replaceFileStore.GetFile`。
  - `GetFile` 的取舍：上游夹具的 `apply` 不认识 `file_sha256` 列，行里没有 SHA 时重解析会读回文件计算 SHA；上游存储不保存
    替换文件的字节。`GetFile` 只服务夹具的两个路径：原文件返回上游常量 `replaceFileOldContent`；已保存的替换文件读回空内容；
    已删除或从未保存的路径返回错误。上游替换测试从不断言重解析算出的 SHA；断言修订绑定的我方测试用保存字节的包装存储。
  - 记录型包装：`revisionReplaceRepo`（记录 `AllocateParseAttempt` 的入参与每次已生效的来源写入；写入失败语义沿用上游桩的
    “指定次失败 / 提交后报错”，生效时补写 `file_sha256`）、`byteKeepingReplaceStore`（保存字节，`SaveFile`/`DeleteFile` 委托
    上游桩以保留计数、事件与删除记录）、`revisionReplaceHarness`（上游 harness 加两个包装并接入 service）。
  - 原文件尾部的两个我方测试原样搬入，只把 `newReplaceFileHarness(t)` 换成 `newRevisionReplaceHarness(t)`。
- 共用该夹具的上游原样文件（`knowledge_reparse_dequeue_test.go`、`knowledge_datasource_replace_test.go`）不改。

### 2.3 其余 24 个保留文件复核

逐个核对与 v0.9.0 的差异：KBPOLICY 9、`kgRepo` 3、行为改变 5、SQL 夹具缺列 1、本机假 IP 的 SSRF 5 的理由均未因
#490/#493 改变（差异中无修订来源相关内容；#493 只迁移生产服务）。`opensearch` 的 `lll` 见 §2.1 lint 段。本片不新增还原。

## 3. 改动范围

- 还原：上述两个上游测试文件；
- 我方测试：新增 `knowledge_process_parent_child_revision_test.go`、`knowledge_replace_revision_test.go`；删除
  `knowledge_replace_fixture_test.go`；改 `knowledge_attempt_cleanup_upgrade_test.go`（夹具构造）；
- 已登记补丁文件 `knowledge_process_index_retry_test.go`：两个字段；
- `tests/architecture/`：RED、基线（`record_baseline.py` 只降）；`docs/design/upstream-patches.md` 追加退出行。

## 4. 验收

- RED `tests/architecture/test_u2c_upstream_tests_restored.py`：两个文件与 `f17ee8a8d` 逐字节相同；我方夹具文件已删除、
  搬运的我方测试仍在；G10 ≤ 153 − 2。
- 门禁：`go build ./...`；`go vet` / `go test ./internal/application/service/`（失败集合与 main 相同：本机假 IP DNS 与沙箱
  9 个）；`golangci-lint --new-from-rev=origin/main`（预期仅 §2.1 的 1 个 errcheck）；`pytest -q tests/architecture`；
  `git diff --check`。
- 故障敏感性（仓库外 `go test -overlay` 变异，不提交）：对搬运或改夹具的测试里的“不得写入 / 不得调用”断言，注入违反该断言
  的生产改动，修复后的夹具必须让测试失败；对依赖包装类型记录的断言，再用“记录方法被绕过”的坏包装证明断言会因此变成空过。

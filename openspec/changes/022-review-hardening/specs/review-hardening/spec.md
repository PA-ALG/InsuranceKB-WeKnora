# 022-review-hardening 验收规格

## ADDED Requirements

### Requirement: RH1.1 回滚 DB flush 必须早于 Wiki mutation

`rollback_to_snapshot` SHALL 在第一次 Wiki mutation 前，于可回滚 savepoint 内创建 scoped rollback ChangeSet、移动 current pointer 并完成 flush。

#### Scenario: 本地 flush 失败时零外部写

- **WHEN** rollback ChangeSet/pointer 的 flush 失败
- **THEN** Wiki 请求数为零
- **AND** 原 current pointer 与 rollback audit 保持不变

### Requirement: RH1.2 Wiki failure 必须回滚本地 savepoint

RH1.1 的 DB 阶段成功后，任一 Wiki mutation 失败 SHALL 回滚该 savepoint。

#### Scenario: Wiki 失败后 caller 提交 outer transaction

- **WHEN** Wiki upsert 抛错且调用方捕获异常后提交 outer transaction
- **THEN** 数据库不得留下新 rollback ChangeSet
- **AND** current pointer 仍指向回滚前 snapshot

### Requirement: RH1.3 局部 hardening 不得冒充跨系统原子性

本 change SHALL 只保证函数内 flush/Wiki failure 的双向零半成品；函数返回后的 outer commit/rollback、进程终止和多页外部补偿 SHALL 继续归 018。

#### Scenario: 报告能力边界

- **WHEN** validation/HANDOFF 描述 RH1 的完成状态
- **THEN** 必须明确 outer transaction 与 reconciliation residual
- **AND** 不得宣称已提供 PostgreSQL/WeKnora 原子提交

### Requirement: RH2.1 零 Evidence 的 applied revision 必须同 revision 幂等

当 active ClaimEvidence 集为空，但同 scope/knowledge/revision 存在唯一、aggregate 合法且 applied 的 `document` 或 `recompile` ChangeSet 时，再次通知该 identity SHALL 返回 same-revision no-op。

#### Scenario: unknown-only applied revision 被重复通知

- **WHEN** source-aware import 已成功 applied 且只产生 unknown placeholder、零 ClaimEvidence
- **AND** 随后通知相同 SourceImportIdentity
- **THEN** `same_revision` 为 true、`change_set_id` 为空
- **AND** 不创建新 ChangeSet，也不抛 ambiguous/cannot-replay

### Requirement: RH2.2 零 Evidence 的新 identity 仍必须 stage recompile

当 active Evidence 为空且 incoming identity 没有 applied aggregate 时，通知 SHALL 创建或复用唯一 pending recompile，并允许 `stale_count=0`；malformed/multiple/conflicting aggregate SHALL fail closed 且零 mutation。

#### Scenario: 零 Evidence 来源收到不同 revision identity

- **WHEN** 已处理 identity A 没有 ClaimEvidence
- **AND** 调用方在 017 串行前提下通知 identity B
- **THEN** 系统创建或复用 B 的唯一 pending recompile
- **AND** `stale_count` 可以为零

#### Scenario: 零 Evidence 的 applied aggregate 畸形

- **WHEN** 同 identity 的 applied document/recompile 含 malformed、multiple、跨 scope 或不合法 child aggregate
- **THEN** 通知抛出无泄漏的 ScopeViolation
- **AND** stale timestamp 与 ChangeSet 均无新增，Session 仍可继续提交既有合法工作

### Requirement: RH2.3 不得在本 change 推断 revision 顺序

RH2 SHALL NOT 比较不同 revision 的先后、接收缓存/延迟 metadata，或实现 processed_at/SourceHead/CAS；这些能力 SHALL 继续归 021/B23。

#### Scenario: 规格与实现保持排除项

- **WHEN** 开发或复审 RH2
- **THEN** 不新增 revision hash 排序、processed_at ordering 或跨 revision lock/CAS

### Requirement: RH3.1 Directory replay 产物必须保持 eval-only

新 pipeline 产出的每条 PredRecord SHALL 带显式 `source_mode=weknora|directory_replay`，旧 artifact 缺省为 `legacy` 以保持兼容。生产 source-aware importer 与显式 legacy importer SHALL 在零数据库写入前拒绝 `directory_replay`，包括 unknown/零 Evidence 行，且 SHALL NOT 以文件名或 replay identity 伪造生产 lineage。

#### Scenario: Directory pred 尝试导入

- **WHEN** Directory replay bundle 含 present 或 unknown/零 Evidence record
- **THEN** source-aware 与 legacy import 路径均抛出明确 ScopeViolation
- **AND** ChangeSet、ChangeItem、Claim 与 ClaimEvidence 均无新增

### Requirement: RH3.2 Directory PDF discovery 必须大小写无关且稳定

Directory source SHALL 发现直接产品目录下所有 regular、扩展名大小写无关的 `.pdf` 文件并按稳定文件名排序物化。

#### Scenario: 同目录含小写与大写 PDF 后缀

- **WHEN** 直接目录同时包含 `a.pdf` 与 `B.PDF`
- **THEN** 两个文件均进入 SourceDocument/manifest 输入
- **AND** 结果按确定性文件名顺序排列

### Requirement: RH3.3 Directory 单文件失败仍必须全批失败

单文件物化失败 SHALL 使整批以 typed stage/key 失败且不得产生部分 SourceDocument；本 change SHALL NOT 新增递归目录扫描。

#### Scenario: 大小写 PDF 中一份损坏

- **WHEN** 任一已发现 PDF 无法 hash/parse/materialize
- **THEN** 抛出带稳定 stage/key 的 SourceMaterializationError
- **AND** 不向 compiler 返回部分 documents

### Requirement: RH4.1 合法 numeric tenant 与 knowledge identity 必须兼容

`tenant_id` SHALL 保留非负整数与规范十进制 scope string 的等价；017 已批准的安全 numeric knowledge ID 兼容 SHALL 继续有效。

#### Scenario: canonical numeric identities

- **WHEN** scope tenant 为 `"5"` 且响应 tenant 为整数 `5`
- **OR** 请求 knowledge ID 为 `"123"` 且响应 knowledge ID 为整数 `123`
- **THEN** 其余 scope 字段匹配时请求通过 identity guard

### Requirement: RH4.2 knowledge_base_id 必须是严格字符串

Metadata 与 chunk 的 `knowledge_base_id` SHALL 是严格 JSON string 并与 `scope.raw_kb_id` 精确相等；numeric/bool/float/missing/mismatch SHALL 在返回内容或 download 前统一 fail closed 为 `ScopeViolation("scope mismatch")`。

#### Scenario: numeric KB ID 不得跨型匹配 string scope

- **WHEN** scope raw KB 为 `"5"`，响应 `knowledge_base_id` 为整数 `5`
- **THEN** metadata 与 chunk 路径均拒绝响应
- **AND** 错误不泄漏原 payload

### Requirement: RH5.1 Bridge contract/live node 现状必须保持

`test_source_bridge_contract_017.py` SHALL 保持 12 个 deterministic contract，`test_source_bridge_live_017.py` SHALL 保持 1 个真实 live E2E；本 change SHALL NOT 为已完成评论重复改名或改变 node ID/marker。

#### Scenario: 三 lane collection

- **WHEN** CI contract 分别 collect deterministic 与 live marker
- **THEN** 12 个 bridge contract 只属于 deterministic lane
- **AND** 1 个 bridge E2E 只属于 live lane

### Requirement: RH5.2 Existing-knowledge live 不得描述成 upload 覆盖

Existing-knowledge live E2E SHALL NOT 描述成 upload 创建覆盖，未运行 SHALL 保持 `NOT RUN`。

#### Scenario: 无受控 WeKnora run evidence

- **WHEN** 没有 protected harness-live run URL、commit、时间和零 skip JUnit
- **THEN** validation/HANDOFF 的 `live verified` 状态仍为 `NOT RUN`

### Requirement: RH6.1 默认本地门禁必须只选择 deterministic lane

CLAUDE.md 的默认本地 pytest 门禁 SHALL 精确选择 `not live and not integration_postgres`；PostgreSQL 与 WeKnora SHALL 分别使用独立 CI/manual lane。

#### Scenario: 本机没有 PostgreSQL URL

- **WHEN** 开发者按 CLAUDE.md 运行默认 pytest 门禁且未设置 `HARNESS_TEST_POSTGRES_URL`
- **THEN** integration_postgres node 不被选择
- **AND** deterministic suite 可以独立完成

### Requirement: RH6.2 Scope 测试不得按 overlap 自动删除

016 scope 测试 SHALL NOT 按行数、节点数或 coverage overlap 自动删除；只有输入类别、public boundary、失败阶段和副作用断言均同构且一项是严格断言子集时，才可在冻结 before/after manifest 后合并。本 change SHALL NOT 删除 capability/consumer 分层证明。

#### Scenario: overlap audit 产生候选

- **WHEN** coverage-context audit 报告候选对
- **THEN** 候选只进入人工复审
- **AND** 不自动删除、合并或降级跨 Space/零副作用证明

### Requirement: RH7.1 测试必须引用条款并保存 RED→GREEN

所有驱动行为变更的测试名 SHALL 包含对应 `rhN_M` 条款号，并保存可复现 RED→GREEN 证据；用于证明既有语义未被新分支破坏的 characterization/regression SHALL 明确标注基线已为 GREEN，不得人为破坏实现制造 RED。

#### Scenario: 行为任务交付审查

- **WHEN** RH1、RH2、RH3、RH4 或 RH6 行为变更任务申请完成
- **THEN** reviewer 可从测试名定位条款号
- **AND** validation report 包含正确原因的 RED 与修复后的 GREEN

### Requirement: RH7.2 最终门禁与外部状态必须分层

Ruff、mypy strict、deterministic pytest SHALL 全绿；PostgreSQL SHALL 由独立 GitHub Actions job 以 tests>0、skipped=0 验证；真实 WeKnora 没有受控 run evidence 时 SHALL 保持 `NOT RUN`。

#### Scenario: 软件完成但没有新 live run

- **WHEN** 本地 deterministic 门禁和 PostgreSQL CI 通过但未触发 protected WeKnora workflow
- **THEN** 可报告 software complete/integration verified
- **AND** 不得报告 live verified

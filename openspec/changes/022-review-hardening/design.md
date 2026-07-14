# 022-review-hardening 设计

## 1. 复审裁决

| 意见 | 裁决 | 本 change 处理 |
|---|---|---|
| ① rollback 外部写先于 DB flush | 成立，但完整跨系统原子性仍属 018 | 采用局部 savepoint：DB mutation+flush 在 Wiki I/O 前；Wiki 失败回滚 savepoint；最终 outer commit failure 明确为 residual |
| ② 空 Evidence recompile | 部分成立 | 新 revision 本来能创建 recompile；修复 applied 同 revision 因零 Evidence 被判 ambiguous |
| ③ Directory 回放导入黑洞 | 部分成立 | 不可导入是有意 eval-only；保留拒绝并补明确合同；修复直接目录中 `.PDF` 大小写静默遗漏 |
| ④ int/string identity | 部分成立 | `tenant_id` 是上游 uint64，numeric knowledge ID 也是 017 已批准兼容；仅 KB ID 改为严格字符串 |
| ⑤ live 文件拆名 | 当前 HEAD 不成立 | 022 已拆成 12 contract + 1 live；不重复改 node ID |
| ⑥ 016 测试再平衡 | 维护性观察成立，删测结论不成立 | 保留 245 个风险 case；修复 CLAUDE.md lane 漂移并由合同测试锁定 |

## 2. RH1 回滚写序

三种候选方案：

1. 只交换 `_upsert_page()` 与 `session.flush()`：能让注入的 flush failure 早于 I/O，但 Wiki failure 会留下可提交 DB mutation，不可接受；
2. 在 nested transaction 内先创建 rollback ChangeSet、移动 pointer 并 flush，再执行 Wiki upsert；任一 Wiki failure 使 savepoint rollback；
3. 实现 018 的 durable PublishPlan/Attempt saga：语义最完整，但会重复并扩大已排期 change。

本 change 采用方案 2。它修复评论给出的确定性失败面，并保留现有“Wiki 失败后 caller 即使 commit 也没有新 pointer/audit”合同。它不声称解决函数返回后的 outer commit/rollback 与外部 Wiki 的一致性；该 residual 必须继续在 018 通过 durable plan、attempt 和 reconciliation 解决。

## 3. RH2 零 Evidence revision 身份

Evidence 是事实证据，不是 source processing head。unknown-only source-aware import 可以合法产生 applied `document`/`recompile` ChangeSet 而没有 ClaimEvidence。当前 notify 只从 active Evidence 推断 revision，导致同 identity 的 applied ChangeSet 被 `_existing_recompile()` 误判为 ambiguous/cannot-replay。

修复只在 active revision 集为空时读取并验证同 identity 的 applied source ChangeSet：

- 唯一、scoped、aggregate 合法且 status=`applied` 的 `document`/`recompile` 表示该 revision 已处理，通知为 same-revision no-op；
- pending 空 `recompile` 仍走既有 reuse；
- malformed、multiple、pending document、带非法 children 的 aggregate 继续 fail closed；
- 没有同 identity aggregate 的 incoming revision 仍创建唯一 pending recompile，允许 `stale_count=0`。

这只闭合同 revision；不比较 SHA-256 revision 的新旧，不触碰 021 的 ordering。

## 4. RH3 Directory replay

Directory source 缺少数据库 attested `KnowledgeScope` 和 WeKnora identity，因此它的 revision/page audit 只能用于 Golden/评估。仅靠 Evidence audit 不能覆盖 unknown/零 Evidence 行：这些行当前没有 audit，显式 legacy importer 可能把它们当历史数据接收。为闭合整包语义，`PredRecord` 增加向后兼容的 `source_mode`（旧文件缺省为 `legacy`），pipeline 对新产物逐行写 `weknora` 或 `directory_replay`；生产 importer 和 legacy importer 都必须在 SQL 前拒绝 `directory_replay`。不能通过文件名或 replay identity 伪造生产 lineage。

真正的 discovery 缺口是 `glob("*.pdf")` 对扩展名大小写敏感。直接目录中的 regular `.pdf`/`.PDF` 必须按稳定文件名排序全部物化；子目录递归仍不属于本 change。损坏/无法解析文件继续以 typed `SourceMaterializationError` 使本批全失败。

审计另发现 source-aware unknown 的 `doc="-"` 与多 source 零 winner terminal partition 问题；它们不属于 Directory import 边界，记录为后续 importer/lifecycle change，不在本轮顺手扩张。

## 5. RH4 字段感知 identity

上游 canonical wire shape 为：tenant ID 是整数，knowledge/chunk/KB ID 是字符串；017 另外批准 numeric knowledge ID 的安全路径兼容。因此保留通用 matcher 给 tenant 与 knowledge identity，新增 strict string matcher 专供 metadata/chunk 的 `knowledge_base_id`。畸形 numeric/bool/float KB ID 必须统一变为不泄漏 payload 的 `ScopeViolation("scope mismatch")`。

## 6. RH5/RH6 测试治理

RH5 仅记录当前精确 collection：bridge contract 文件 12 nodes，live 文件 1 node；不改名。

RH6 不删除 scope capability 与 consumer 接线的分层证明，也不以 999 个 overlap candidates 作为冗余结论。新合同测试要求 CLAUDE.md 的默认本地 pytest 命令精确选择 `not live and not integration_postgres`；PostgreSQL 继续由独立 service job 的非零、零 skip JUnit 证明，WeKnora live 继续由受控手工 workflow 证明。

## 7. 验证与边界

- 行为任务逐个 RED→GREEN，测试名包含 `rh1_1`、`rh2_1`、`rh3_2`、`rh4_1`、`rh6_1`；
- 每任务先规格审查、再质量审查；
- 最终运行 Ruff、mypy strict、`pytest -m "not live and not integration_postgres" -q`；
- `pytest -m "not live"` 在无 PostgreSQL URL 时失败是 022 防伪绿的正确行为，不再作为本地 deterministic 门禁；
- 任何 live skip/NOT RUN 不升级为 `live verified`。

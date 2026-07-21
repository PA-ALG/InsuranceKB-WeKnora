# 020 阶段验证报告：T1 run-admission

> 状态：**T1 软件闭环已在 021 合入后的基线上验证；真实数据运行 BLOCKED。** 本报告不是 D2～D5 的最终运行报告，T2～T7 与 T8 最终对账均未完成。

## 1. 当前准入结论

- 权威工件：`run-admission.json`；人读镜像：`run-admission.md`。
- 状态：`BLOCKED`。
- evaluated revision：`2169c5821021dfc9513d3cc760dea4fc4e519112`。
- source plan 当前固定 designated merge：019=`4d9c84e25bd53f3564631b8f8dc0b1f85e21e55f`、021=`cfefcc9b3a7d6af0503f3b76cf8ac5a1b6d44b35`；identity contract=`45dd7c9d5d784435969a744ef72e76b4bd9ab9d0d4bac6e59ea2899c241fe69`。
- checker：`020.1`；runtime capability：`budget-ledger-v3-canary-v1`。
- provider probe：annotator、weak_extractor、judge 均为 `not_attempted`。
- 模型调用：0；token：0；费用：0。
- 模型指纹：未冻结，作为 `model_identity_pending` 阻塞；production Bailian 只接受 provider 保证可调用且不可变、并与实际 POST `model_id` 相同的 `immutable_deployment_id`，revision-only 与 `gmt_modified` observation 不得授权可变 alias。

本次 PR #24 hardening 按两阶段提交生成证据：先将代码与 source plan 提交为 `2169c582`，再由 repository CLI 在该 clean code SHA 上重新生成 JSON/Markdown；CLI 按预期 exit 2（typed `BLOCKED`）。canonical 工件已不含 `dirty_consumed_file`、`dependency_revision_mismatch`、`dependency_not_ancestor`、`identity_contract_mismatch` 或 `execution_surface_unpinned`。

当前阻塞类别如下；完整逐产品/逐输入证据以 canonical JSON 为准：

1. 预算：`budget_contract_missing`、`budget_not_admitted`。
2. 审批：`approval_missing`。
3. 输入/provenance：11 个产品为 `missing_historical_provenance`；`平安福满分（2026）养老年金保险` 另有 `missing_path` 与 `unconsumed_product_file`。
4. 模型 identity/probe：三个角色均为 `model_identity_pending`，因此未发起 probe。

上述结果证明 fail-closed 路径生效，不代表这些前置条件已经满足。production policy 不再接受 019/021 feature head；它先要求 plan exact pin 上述两个 merge SHA，再检查 merge 是 evaluated revision 祖先。clean-SHA canonical 工件已通过该组软件身份检查；其余阻塞解除前，020 仍不得进入真实 annotation/baseline。

## 2. 软件验证证据

2026-07-21 在合并 021 后的当前工作树执行：

| 门禁 | 结果 |
|---|---|
| 020 focused suite | `700 passed` |
| 全量 non-live / non-PostgreSQL | `2607 passed, 30 deselected`，221.91 秒 |
| Ruff | PASS，`All checks passed!` |
| mypy strict | PASS，285 source files |
| OpenSpec strict | PASS |
| `git diff --check` | PASS |
| 复核 | 独立高风险/预算复核 + 主线程完整 identity/mutation-boundary 复核；无遗留 P0/P1/P2 |

本轮关闭的关键安全/一致性路径：

- annotation schema/product/shared inputs 使用内容寻址快照；提交前从 exact snapshot/PDF bytes 重渲染并做语义等值校验。
- PDF snapshot 拒绝 hardlink 替换；checkpoint 拒绝多链接、WAL/SHM，并从 descriptor exact bytes 在内存 deserialize 校验。
- baseline final validation 到 settlement 持有同一 run lock，阻止 TOCTOU 竞争写。
- settle/resume 后 fresh 重算 candidate authorization；目标产品不在授权集时返回类型化 `BLOCKED`。
- durable budget ledger 覆盖 reservation、attempt owner-CAS、跨 run replay、部分结算、release/claim 竞争及发送边界崩溃恢复。
- 未认证的 provider `no_usage` authority 已从 production/test API 删除；历史或篡改的 `no_usage` 只能按 uncertain/full-reserve 恢复。若未来需要零费用 reconciliation，必须另立 OpenSpec，完整交付 trust root、签名 schema、受控 loader 与 provider evidence lineage。
- 同 run budget revision 只允许单调提高 account ceiling；产品、exact request、request pool 及其 limits/rates 的任何增删改均拒绝。

### PR #24 identity hardening 增量证据

- Bailian 初始 RED：4 个 expected failure，分别证明 matching revision-only probe 被错误接受，以及 revision-only、mismatched immutable ID、`model_construct` 三种 runtime role 均会到达 inference seam。补充的 forged invalid probe mode RED 进一步证明它会到达 client factory。
- dependency 初始 RED：2 个 expected failure，证明 test policy 尚不能指定 exact revisions，production inspector 也只拥有 key set/ancestry 而没有 designated revision mapping。
- focused GREEN：完整 020 suite `700 passed`；预算/identity 的独立聚焦复核 `55 passed`；最终 Bailian HTTP mutation-boundary policy matrix `8 passed`。
- repository CLI：clean code SHA regeneration exit `2`/`BLOCKED`；provider probes 仍全部 `not_attempted`，零模型调用。

## 3. 数据覆盖与裁决完成度

| 项目 | 本阶段结果 |
|---|---|
| 新增人工/模型标注产品 | 0；NOT RUN |
| 剩余 2 产品 annotation | NOT RUN（T2） |
| gs-v0.1 dry-run/release | NOT RUN（T3） |
| 13 产品 baseline | NOT RUN（T4） |
| judge queue / dead letter | NOT RUN（T5） |
| long-field keypoints / before-after | NOT RUN（T6） |
| approved baseline / QualityProfile | NOT RUN（T7） |
| adjudication completion | 0；尚无本轮待裁决结果集 |
| 13 产品指标/unresolved 清单 | 尚未生成；不得填充估算值 |

## 4. 已知边界与下一步

- 019/021 designated merge pin 已进入 source plan，clean-SHA artifact 已按两阶段流程生成。下一步补齐 11 个产品的历史 provenance，并修复 `平安福满分（2026）养老年金保险` 的缺失/未消费输入。
- 只有当 Bailian 能提供 provider-guaranteed invocable immutable deployment ID 时，才可将其逐角色冻结为与实际 `model_id` 相同的 identity；否则 admission 保持 typed `BLOCKED`。之后再取得 provenance/budget 签名审批，创建并准入 durable budget account，只运行准入 probe。
- 重新生成 canonical admission；只有结果为 READY 才可按 T2→T7 执行，任何不明确状态继续 BLOCKED/暂停。
- PostgreSQL integration 与 WeKnora live 本阶段未运行；它们不是 T1 零模型准入软件的完成证据，也不得由 non-live 测试冒充。
- 受当前执行沙箱的共享 uv cache 权限与审批额度限制，CLAUDE.md 中等价的 `uv run` 命令未执行；本报告使用工作树锁定的 `.venv` 运行同一 Ruff、mypy 与 pytest 目标并保留真实退出结果。不得把这一说明改写为 exact `uv run` 已通过。
- 两轮复核仅留下 P3 future hardening：为 session lock 自身补 `st_nlink == 1`，以及审视非 checkpoint baseline 工件是否统一 single-link。当前私有 run directory/同 UID 威胁边界下不阻塞 T1，但后续应单独 TDD，不能静默扩大本 change。

## 5. D5/T8 状态

D5 要求的实际成本、运行时间、模型指纹、13 产品指标、unresolved 与 B1/B2/B3/B4/B6/B7/002 对账，必须在 T2～T7 完成后引用同一 artifact/approval identity 统一收尾。当前仅完成 T1 阶段报告，因此 T8 保持未勾选。

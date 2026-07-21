# 020 阶段验证报告：T1 run-admission

> 状态：**T1 软件闭环已在 021 合入后的基线上验证；真实数据运行 BLOCKED。** 本报告不是 D2～D5 的最终运行报告，T2～T7 与 T8 最终对账均未完成。

## 1. 当前准入结论

- 权威工件：`run-admission.json`；人读镜像：`run-admission.md`。
- 状态：`BLOCKED`。
- evaluated revision：`62ce831c54490517d16cfe53e55b7d8476c80bbe`。
- checker：`020.1`；runtime capability：`budget-ledger-v3-canary-v1`。
- provider probe：annotator、weak_extractor、judge 均为 `not_attempted`。
- 模型调用：0；token：0；费用：0。
- 模型指纹：未冻结，作为 `model_identity_pending` 阻塞；不得以可变 model alias 代替不可变 deployment/revision identity。

当前阻塞类别如下；完整逐产品/逐输入证据以 canonical JSON 为准：

1. 预算：`budget_contract_missing`、`budget_not_admitted`。
2. 审批：`approval_missing`。
3. 输入/provenance：11 个产品为 `missing_historical_provenance`；`平安福满分（2026）养老年金保险` 另有 `missing_path` 与 `unconsumed_product_file`。
4. 模型 identity/probe：三个角色均为 `model_identity_pending`，因此未发起 probe。

上述结果证明 fail-closed 路径生效，不代表这些前置条件已经满足。021 已以 PR #23 合入，所需 revision `f557fc94` 已固定且为 evaluated revision 的祖先；`dependency_set_mismatch`、`identity_contract_mismatch`、`execution_surface_unpinned`、`digest_mismatch`、`dirty_consumed_file`、`untracked_consumed_file` 均已消失。其余阻塞解除前，020 仍不得进入真实 annotation/baseline。

## 2. 软件验证证据

2026-07-21 在合并 021 后的当前工作树执行：

| 门禁 | 结果 |
|---|---|
| 020 focused suite | `674 passed` |
| 全量 non-live / non-PostgreSQL | `2581 passed, 30 deselected`，287.25 秒 |
| Ruff | PASS，`All checks passed!` |
| mypy strict | PASS，285 source files |
| OpenSpec strict | PASS |
| `git diff --check` | PASS |
| 独立最终复核 | 两轮 APPROVE；无 P0/P1/P2 |

本轮关闭的关键安全/一致性路径：

- annotation schema/product/shared inputs 使用内容寻址快照；提交前从 exact snapshot/PDF bytes 重渲染并做语义等值校验。
- PDF snapshot 拒绝 hardlink 替换；checkpoint 拒绝多链接、WAL/SHM，并从 descriptor exact bytes 在内存 deserialize 校验。
- baseline final validation 到 settlement 持有同一 run lock，阻止 TOCTOU 竞争写。
- settle/resume 后 fresh 重算 candidate authorization；目标产品不在授权集时返回类型化 `BLOCKED`。
- durable budget ledger 覆盖 reservation、attempt owner-CAS、跨 run replay、部分结算、release/claim 竞争及发送边界崩溃恢复。

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

- 021 依赖与 execution-surface identity 已固定并通过；下一步补齐 11 个产品的历史 provenance，并修复 `平安福满分（2026）养老年金保险` 的缺失/未消费输入。
- 冻结三模型不可变 identity，取得 provenance/budget 签名审批，创建并准入 durable budget account；随后只运行准入 probe。
- 重新生成 canonical admission；只有结果为 READY 才可按 T2→T7 执行，任何不明确状态继续 BLOCKED/暂停。
- PostgreSQL integration 与 WeKnora live 本阶段未运行；它们不是 T1 零模型准入软件的完成证据，也不得由 non-live 测试冒充。
- 受当前执行沙箱的共享 uv cache 权限与审批额度限制，CLAUDE.md 中等价的 `uv run` 命令未执行；本报告使用工作树锁定的 `.venv` 运行同一 Ruff、mypy 与 pytest 目标并保留真实退出结果。不得把这一说明改写为 exact `uv run` 已通过。
- 两轮复核仅留下 P3 future hardening：为 session lock 自身补 `st_nlink == 1`，以及审视非 checkpoint baseline 工件是否统一 single-link。当前私有 run directory/同 UID 威胁边界下不阻塞 T1，但后续应单独 TDD，不能静默扩大本 change。

## 5. D5/T8 状态

D5 要求的实际成本、运行时间、模型指纹、13 产品指标、unresolved 与 B1/B2/B3/B4/B6/B7/002 对账，必须在 T2～T7 完成后引用同一 artifact/approval identity 统一收尾。当前仅完成 T1 阶段报告，因此 T8 保持未勾选。

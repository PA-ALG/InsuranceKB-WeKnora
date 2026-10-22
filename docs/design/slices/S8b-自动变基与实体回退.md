# S8b · 自动变基与实体回退：Head 前进但没碰到同一批成员时直接上线；按实体回退到旧版本

> 状态：Claude 2026-10-22 提出（蓝图 S8 第二片，用户已批准"增量更新优先"）｜ 作者：Claude Code
> 依据：蓝图 §6.2"并发"、§6.5"实体级回退"，§11 S8 完成标准"回退 A 保留 B"
> 实现方：Claude（2026-10-22 起 Codex 额度有限，Claude 实现）｜ 审核方：Codex ｜ 真实模型调用：0

## 1. 问题（代码核对，`main@2e335177a`）

- **没有自动变基**：`release.Service.Activate` 用 `checkBase` 要求 Candidate 的 base 恰好等于当前 Head，否则一律返回 `NEEDS_REBASE`。两款产品各自准备增量发布时，后激活的那个即使与先上线的内容毫不相干，也必须重新比对、重新提交。
- **没有实体回退**：蓝图要求"以该实体旧成员作为 delta 生成新 Release，保留其他实体的后续修订"，即 S8 完成标准里的"回退 A 保留 B"。今天企业路径上没有回退入口；上游 `WikiReleaseService.Revert` 是整版回退，而且没有路由。

## 2. 设计

### 2.1 平台：按成员判断能否自动变基（Go，`internal/enterprise/release`）

Candidate 的 base 与当前 Head 不同时，按以下步骤处理：

1. 先按现有逻辑判断是不是"已提交过的重试激活"（`replay`），是就返回已提交的 Release。
2. 读取 base Release 的成员：base 为空表示"还没有 Release"，成员为空；base 指向找不到的 Release 时返回 `NEEDS_REBASE`。
3. **本 Candidate 触及的 slug** = 其成员 slug ∪ removals。逐个比较它在 base 与当前 Head 中的状态：digest 相同，或两边都没有，才算"未变"。
4. 全部未变时，把 delta 应用到**当前 Head** 的成员上（与现在的 `materialize` 相同），并以当前 Head 作为期望值写入（仍然经过 CAS）。新 Release 的 `BaseReleaseID` 是当前 Head。
5. 只要有一个触及的 slug 在 base 之后被改过、新增或删除，就返回 `NEEDS_REBASE`，不写入；`Detail` 写明冲突的 slug 数量，不写内容。

base 与 Head 相同但 `base_epoch` 不一致时，仍按现在的规则返回 `NEEDS_REBASE`：base 引用自相矛盾，不变基。

只比较成员 digest，与险种和字段无关，符合硬边界 4。概念等成员依赖的 claim 是否过期，仍由 Harness 报告（S8a `stale_concepts`），平台不判断。

### 2.2 Harness：实体回退命令（`insurance_harness.changes.revert`）

```text
python -m insurance_harness.changes.revert --space S --entity E --to-release R \
       --reason "<原因>" [--activate] [--dry-run]
```

- **实体的成员**：`kind == "entity"` 且 `payload.entity_id == E`，或 `kind == "claim"` 且 `payload.subject_ref == E`。

  本切片不回退 wiki 页面与概念，它们各有发布流程；报告中列出 Active 里引用了该实体、可能需要随之更新的概念 slug。
- **组装 Candidate**（`revert_bundle(active, target, entity_id, compiler_identity)`）：
  - `members`：目标 Release R 中该实体、且与 Active 中 digest 不同（或 Active 中没有）的成员，原样复制 payload、evidence_refs 与 access_scope；
  - `removals`：Active 中该实体、R 中没有的成员；
  - `origin = revert`，base 为读取时的 Active；
  - 没有任何差异时返回 None，命令不提交，退出码 0，报告"无需回退"。
- **决定**：回退一律是人工决定（`--reason` 必填），不走机器审核路由；`--activate` 时人工批准并激活。
- **报告**：报告是 JSON，只写 slug、计数与标识，不写正文。
- **前提**：R 未退役。R 已退役、其来源可能已解除固定时，平台会按现有规则拒绝；命令把错误代码原样报告。

## 3. 上游补丁

无。`internal/enterprise/` 与 Harness 都是项目自有代码。

## 4. 验收（RED，Claude 编写，受保护）

**`internal/enterprise/release/rebase_acceptance_test.go`**：

1. **不相干的前进**：
   - base=first，另一个 Candidate 改了 `x` 并已上线（Head=second）；本 Candidate 改 `b`、删 `a`。
   - 激活成功：新 Release 的 base 是 second；同时含有 second 的 `x` 与本 Candidate 的 `b`，`a` 已删除；共写入两次。
2. **Head 改过本 Candidate 要改的 slug**：返回 `NEEDS_REBASE`，不写入。
3. **Head 改过本 Candidate 要删的 slug**：返回 `NEEDS_REBASE`。
4. **Head 新增了本 Candidate 要新增的同名 slug**：返回 `NEEDS_REBASE`。
5. **base 是找不到的 Release**：返回 `NEEDS_REBASE`。
6. **base 为空**（首次发布时准备的 Candidate），Head 已有与之不相干的成员：自动变基成功。

同时修订 `publish_acceptance_test.go::TestAStaleBaseNeedsRebaseAndWritesNothing`：

- 原来的"base 为空"用例按新规则变为第 6 条，移到新文件；
- 保留"另一个 base"（找不到的 Release）仍为 `NEEDS_REBASE`；
- `TestABaseEpochThatNoLongerMatchesNeedsRebase` 不变。

**`harness/tests/changes/test_revert_acceptance.py`**：

7. R1 有 A/f1=v1、A/f2=v1、B/f1=v1、实体 A；R2（Active）有 A/f1=v2、A/f2=v1（未变）、A/f3、B/f1=v2、实体 A。

   回退 A 到 R1 的结果：
   - `members` 只有 A/f1（R1 的 payload 与 digest）；
   - `removals` 只有 A/f3；
   - B 与 A/f2、实体 A 都不出现；
   - `origin = revert`，base 为 R2。
8. 目标与 Active 对该实体完全相同时，返回 None。

实现方另补：

- 命令的人工决定、`--dry-run`、报告与错误代码；
- Go 的重试激活在变基场景下仍返回同一 Release。

## 5. 改动范围

- `internal/enterprise/release/`（`publish.go` 及测试）；
- `harness/src/insurance_harness/changes/revert.py`（及必要的入口）；
- 实现方测试；
- 守卫的 CLI 入口列表加入 `insurance_harness.changes.revert`，由 Claude 在 RED 提交中修改。

## 6. 上线与验证

Go 部分随下一次 App 构建上线（需用户批准）。上线后用演示 Space 做一次真实回退：

- 选一款产品回退到较早的 Release，再回退到当前；
- 核对其他产品的成员 digest 不变；
- 不调用模型。

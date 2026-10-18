# RV3 · pack 准入试点：重疾险按 0.9 门槛先放开

> 状态：用户已确认（2026-10-18："批准，先按你建议来吧"，即"先只放开一个 pack 试点 + 把 RV4 抽检做实"，不先补 Golden） ｜ 作者：Claude Code
> 依据：蓝图 §6.3、硬边界 8；RV1、RV2c（#204）
> 分支：`slice/rv3` ｜ 工作目录：`.worktrees/rv3` ｜ 实现方：Claude ｜ 审核方：Claude 自审（只改审核策略的配置取值，见 §4）

## 1. 依据（RV2c，#204）

- 156 条被审核的 Claim，对 150、错 6，整体精确率 96.2%。每个 pack 只有 1 款产品，门槛的 Wilson 95% 下界在 0.79–0.90，统计上不能证明达到 95%。
- 只有重疾险（1828）上，打分器把错误压到了门槛以下：
  - 门槛 0.9 时达标 24 条、对 23 条，精确率 95.8%；
  - 门槛 1.0 时 21/21 全对；
  - 3 条错误的分数分别为 0.95、0.85、0.25。
- 意外险那条无中生有得分在 0.9 以上；两全险与终身寿险没有错误，门槛只是"见过的最低分"。这几个 pack 都不放开。

## 2. 决定

- `catalog/review_policy.json` 升为 version `2`：只准入 `schemapack_critical_illness_insurance`，`default` 门槛 0.9，没有字段级覆盖。
- 其余 pack 不准入，仍一律进人工队列。
- 准入仍按整款判定（RV1）：一款产品只要有一条非 unknown 的 Claim 低于门槛或没有分数，整款就进人工队列。
- **试点约束**：
  - RV4（发布后分层抽检）落地之前，每一次 MACHINE 发布都由人工对该版本逐条复核，结果记在发布 Issue 中；
  - 要扩大到其他 pack，或调整这个门槛，必须满足其中一项：该 pack 有第 2 款产品的 Golden，或 RV4 累计的抽检数据。每次调整都升审核策略版本。

## 3. 不在本片

RV4 抽检机制、人工队列页面（RV5）、其他 pack 的准入。

## 4. 验收与改动范围

- **受保护验收**（RED 单独提交）：`harness/tests/catalog/test_review_policy_pilot.py`：
  - 随包策略版本为 `2`；
  - 只准入重疾险，`threshold(<重疾险>, 任一字段) == 0.9`，其他 pack 返回 `None`；
  - `policy_ref == "review-policy@2"`。
- **RV1 验收修正**（单独提交）：`test_review_policy.py::test_the_shipped_policy_admits_no_pack_yet` 断言的是"随包策略不准入任何 pack，直到 RV3"。RV3 起这一前提不再成立，该用例改为只核对 `policy_ref` 与版本的对应关系；其余用例不变。
- **改动范围**：只改 `harness/src/insurance_harness/catalog/review_policy.json`。
- **归档理由**：只改配置取值，没有代码、合同或评分口径变化，由 Claude 自审合并。
- **门禁**：Harness `pytest`（catalog、review、publish 相关）、`ruff`、`mypy`；架构守卫；CI 全绿。

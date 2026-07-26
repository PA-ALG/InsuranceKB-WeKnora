# 036 · Validation Report

> 2026-07-27，Wave 1 实施 agent。worktree `ikb-cap0`，分支
> `feat/036-cap0-capacity-contract`，基线 `main = dedbbafb`（含 C0 PR #36、
> P1 PR #38）。未 commit/push，树留给总控评审。

## 交付物（12 逻辑文件）

- `harness/src/insurance_harness/capacity/`：`models / loader / evaluator /
  questionnaire / __init__`，生产代码合计 **500 行**（预算 ≤500）；零迁移、
  无 DB/网络，唯一 I/O 是读 profile 文件与写问卷。
- `harness/tests/test_capacity_contract_036.py`：70 用例（含参数化展开，
  覆盖 CAP0.1–CAP0.10 全部 Scenario）。
- `docs/insurance-kb/cap0-launch-questionnaire.md`：八项 + 存量回填中文
  问卷（generator 生成，防漂移测试锁定；2026-07-27 口头申报两项已预填）。
- OpenSpec 036 proposal / specs/capacity-contract/spec.md / tasks.md +
  本报告；README 台账 036 行状态更新。

## 2026-07-27 业务方口头申报（总控中途指令）已落实

- 申报口径：约 3000 份文档（区间 1000–5000，PDF/PPT 混合）+ 约 30 万
  文本片段（区间 10–50 万），`source_kind=declared`（非实测）；
- `StockBackfillWorkloadV1` 增加 `total_text_fragments` 字段（五字段），
  测试 fixture 的 launch 档与 `source_ref` 携带该申报及区间；
- 问卷第九节把两项申报作为预填（区间见节内注），业务方只需确认/修正；
- 模型保持规模无关：只校验非负/一致性，数量级上限仅 C0 安全整数域
  （2^53−1，identity 编码域约束，非产品上限）。

## TDD 证据

- RED：`uv run pytest tests/test_capacity_contract_036.py -q` 在包创建前
  收集即错——`ModuleNotFoundError: No module named
  'insurance_harness.capacity'`（1 error during collection）；
- GREEN：实现包 + 生成问卷后同命令 **70 passed**（首次全绿）。

## 门禁

| 门禁 | 结果 |
|---|---|
| focused（`tests/test_capacity_contract_036.py`） | **70 passed** |
| `uv run ruff check`（包 + 测试） | PASS（All checks passed!） |
| `uv run mypy`（strict，6 files：包 5 + 测试） | PASS（no issues） |
| `openspec validate 036-cap0-capacity-contract --strict` | PASS，exit 0 |
| 全量 deterministic | NOT RUN（按任务指令只跑 focused；无既有代码修改） |
| PostgreSQL / WeKnora live lane | NOT RUN（不适用：无 DB/网络面） |
| CI | NOT RUN（待 PR） |

## 执行中裁决的口径（供评审复核）

1. **作用域**：部署级 Profile（`deployment_id`）+ 每证据档可选
   `space_overrides`（全字段可选=继承、全空拒绝、key 受 pattern 约束、
   参与 hash）；理由见 proposal「作用域裁决」。
2. **档位×来源矩阵**：launch 受理 declared|measured（D-1 第 1/2 条）；
   `stress_breakpoint` 只受理 measured（申报式 breakpoint = 无工作负载
   假设）；`contracted_forecast` 不强制 measured（承诺区间无法实测）。
3. **contracted_forecast 只降级 launch 不降级 design**：D-1 明示 P2a/P2b
   放行前置仅为 declared launch 档；033 §5.1 只在 P15 且发布画像声明承诺
   时阻断验证 forecast。
4. **回填可行性规则**：`document_count>0` 时要求 吞吐×窗口 ≥ 文档数——
   算术上不可能完成的申报计划视同无工作负载假设，fail closed（超出任务
   最小校验清单的新增规则，评审可否决）。
5. **float 全域拒绝**：与 C0.3 对齐，int/str/Decimal 受理、binary float
   在任何数值字段 typed 拒绝，YAML 未加引号小数会得到改写指引。
6. **stock_backfill 裁决出处**：2026-07-27 执行裁决由总控窗口下达，23 号
   控制板 §8 尚无对应编号行，proposal 已注明补录随本 PR 评审进行。

# 036 · Tasks

## Contract Card

1. **单一职责**：冻结 versioned CapacityProfile（八项 §5.1 输入 + 三档
   证据 + `stock_backfill`）与 launch/contracted_forecast/stress_breakpoint
   阻断语义，交付八项业务问卷。**非目标**：压测平台、分片、第二数据库、
   拍脑袋倍数/默认数值、领域表/迁移、P4b/P6b/P9a/P15 执行接线、WeKnora
   改动。
2. **读写权威/事务/幂等**：纯模型 + 纯函数库；唯一 I/O 是读 profile 文件
   与写问卷文件；无 DB、无网络；幂等性即确定性（同内容同 hash，经 C0
   `canonical_hash(object_type="capacity-profile")`）。
3. **状态机**：无持久状态机；evaluator 输出封闭三态
   `SUFFICIENT_FOR_DESIGN | SUFFICIENT_FOR_LAUNCH |
   INSUFFICIENT_CAPACITY_EVIDENCE`（D-2026-07-26-1 门禁语义）。
4. **威胁矩阵**：
   - 无工作负载假设混入 → 全字段必填无默认、库不带示例 Profile 常量、
     申报式 stress_breakpoint 拒绝、不可行回填计划拒绝；
   - 档位混用（declared 冒充实测解锁 P15）→ 封闭 `source_kind` + evaluator
     只在 `measured` 给 `SUFFICIENT_FOR_LAUNCH`；
   - 画像错配（拿画像 A 证据放行画像 B）→ `applicable_release_profile`
     必填 + 不匹配即 INSUFFICIENT/阻断；
   - identity 漂移 → float 全域拒绝、int 限 2^53−1、Decimal 定点规范化
     继承 C0、YAML/JSON 同 hash 测试钉死；
   - 静默改历史 → frozen 模型 + 内容寻址，改内容必换 version/hash；
   - 问卷与合同漂移 → 槽位标注合同字段路径 + 仓库问卷与 generator 逐
     字节防漂移测试。
5. **验收测试清单**：见 spec CAP0.1–CAP0.10 全部 Scenario；focused +
   Ruff + mypy strict + OpenSpec strict；PG/live lane 不适用（NOT RUN，
   无 DB/网络面）。
6. **路径预算**：≤12 个逻辑文件（包 5 + 测试 1 + 问卷文档 1 + OpenSpec
   proposal/spec/tasks 3 + validation-report 1 + README 台账 1），生产
   代码 ≤ 500 行，无迁移。

## Tasks

- [x] T1（RED）：写 `harness/tests/test_capacity_contract_036.py`——模型
  fail-closed 矩阵（八项缺失、未知字段、负数/float/超界、p95/burst/
  inline 跨字段、naive datetime、空 source_ref、launch 缺 stock_backfill、
  不可行回填、申报式 breakpoint、空 override、非法 space key、冻结拒绝
  赋值）、内容寻址（同内容同 hash、变更换 hash、Decimal 规范化、与 C0
  `canonical_hash` 显式对账）、evaluator 三态矩阵（declared 只解锁设计、
  measured 解锁上线、承诺画像缺 forecast 只阻断上线、画像错配、breakpoint
  不阻断）、loader（YAML/JSON 同 hash、扩展名/缺文件/解析错/float 拒绝）、
  问卷（八项 + stock_backfill 全出现、写出一致、仓库零漂移）；此时包不
  存在，收集即 RED。
- [x] T2（GREEN）：实现 `harness/src/insurance_harness/capacity/`
  （models / loader / evaluator / questionnaire + `__init__`），生成
  `docs/insurance-kb/cap0-launch-questionnaire.md`，使 T1 全绿。
- [x] T3：README 台账 036 行状态更新；proposal 记录作用域裁决
  （部署级 + 档内可选 per-Space override）与 2026-07-27 stock_backfill
  裁决出处。
- [x] T4：门禁：focused 单文件、`ruff check`、`mypy`（strict，capacity 包
  + 测试）、`openspec validate 036-cap0-capacity-contract --strict`；
  validation-report 记录 RED→GREEN 证据与 NOT RUN 项。

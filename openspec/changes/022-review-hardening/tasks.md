# 022-review-hardening 任务

- [x] T0 六项评论只读取证、根因分析与边界裁决
- [x] T1 规格/设计与实现计划独立复审（spec 三轮内 Approved；plan 三轮内 Approved；strict validator PASS）
- [x] T2 RH1：rollback savepoint 写序两轮 RED→GREEN；spec/quality 均 Approved
- [x] T3 RH2：零 Evidence 同 revision 幂等 RED→GREEN + 双审
- [x] T4 RH3：Directory eval-only 合同与大小写 PDF discovery RED→GREEN + 双审
- [x] T5 RH4：字段感知 KB identity RED→GREEN + 双审
- [x] T6 RH5/RH6：冻结 live 现状、修正 CLAUDE deterministic lane 合同 + 双审
- [x] T7 全量门禁、整包复审、validation/HANDOFF/外部 PR 状态对账（未提交 working tree；外部 CI 待人类 push）

## 裁决记录

- ①选择 nested savepoint 的局部 hardening，不在本 change 重复 018 saga；outer commit/rollback residual 仍归 018。
- ②不是“新 revision 被空 Evidence 阻止”，而是 applied 同 revision 在零 Evidence 时被误判；只修同 revision 状态识别。
- ③Directory replay 保持 eval-only；不伪造生产 identity。只修直接目录大小写 PDF 的无痕遗漏；source-aware unknown `doc="-"` 与多 source 零 winner terminal partition 另行排期。
- ④只收紧 `knowledge_base_id`；numeric tenant 与 numeric knowledge ID 是不同合同，继续兼容。
- ⑤已由 `022-test-portfolio-rebalance` 完成，不重复改 node ID。
- ⑥不以 overlap 数量删测试；本轮修复 CLAUDE.md 与三 lane 的真实漂移。
- processed_at、不同 revision 并发/乱序明确不在本 change。

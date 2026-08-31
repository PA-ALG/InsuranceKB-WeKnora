# 126 · Implementation Tasks

## M0 · Authority, frozen inputs and RED

- [x] 裁决 `B0=PASS`、写入 `G1_ONLY` 状态，并保持 G2+ 锁定。
- [x] 占用唯一 OpenSpec 126，冻结 G1-R1..G1-R9、Owner matrix 与 STOP 条件。
- [x] 冻结 base/entity/release/SchemaPack/ordered67/B0 Evidence digest；D0、Docker SKIP。
- [ ] 由独立只读 reviewer 复核 M0 exact head/tree；未通过前不写功能代码。

## Requirement-first RED ledger

| Requirement | 旧实现上必须先出现的最小 RED | 预期失败原因 |
|---|---|---|
| G1-R1 | Harness/route stability test 查实体稳定 route/page ID | 旧 payload 没有独立 canonical page route/ID |
| G1-R2 | 编译真实 815 authority 并断言 76 个唯一页面 | 旧 Release 只有 75 members 且无 free_wiki |
| G1-R3 | 逐页断言 67/67 三态和 unknown typed reason | 旧字段是 member，但没有实体作用域 FieldAssertion 合同 |
| G1-R4 | known field 同源 Claim/Evidence 与 exact locator 回归 | 旧聚合链未冻结 G1 PageManifest 的 Claim/Evidence refs |
| G1-R5 | 断言短标题与 namespace/page ID 同时存在 | 旧 payload 只有 field_id，短标题在前端静态表 |
| G1-R6 | 76-member manifest/preparation 原子性测试 | 旧合同只接受 75-member Schema Release |
| G1-R7 | current/pinned entity route 无 fallback 测试 | 旧 API 没有实体页面图 route contract |
| G1-R8 | 架构/contract test 拒绝第二 authority 与可编辑事实副本 | 旧合同未对 G1 graph 显式冻结该边界 |
| G1-R9 | 公共 renderer 的 2-section 测试 | 旧医疗实现/展示把 7-section 绑定在产品代码中 |

每项 RED 必须在实现前保存命令、退出码和期望失败断言；依赖、环境或接口未调用错误无效。

## M1 · Thin real Candidate Preview

- [ ] 按 G1-R1/R2/R3/R5/R9 先写并运行 Harness RED，再实现最小 entity page compiler。
- [ ] 共享 payload contract/hash 冻结后，按 G1-R6/R7 先写 Go RED，再扩展现有 Release read。
- [ ] 按 G1-R1/R5 先写前端 RED，再增加实体 overview/section/field/free-wiki route/navigation。
- [ ] 使用真实 815 Candidate/Claim/Evidence Preview 证明 1 overview、1 section、3 field、空
  free_wiki、短标题、完整 namespace 与至少 1 个 exact source click。
- [ ] 提交 M1 最薄纵切；若 48 小时无真实 Preview，STOP。

## M2 · Complete 76-page graph

- [ ] 关闭 76/76 唯一 ID、67/67 三态、unknown typed reason、全部稳定 route。
- [ ] 关闭 Section→FieldAssertion、known 同源 Evidence、标题/分类不改变 identity。
- [ ] 关闭公共 renderer 的非 7 节点单测；不得注册其余 10 类产品 Profile。
- [ ] 提交 M2 完整页面图并更新 Requirement 矩阵。

## M3 · Atomic isolated Release

- [ ] 冻结 integration head 与 image change-impact；总控仅构建受影响镜像一次（D2）。
- [ ] 复用 D2 exact digest，在隔离环境形成一个 `NOT_FOR_PRODUCTION` Release（D3）。
- [ ] 验证 activation 前旧 Active 完整可读，activation 后 current/pinned 只读 exact 新 Release。
- [ ] 验证 76 页同 release、无混版，以及三个 known field exact source click/fail closed。
- [ ] 证明生产 `8081`、生产 Active、Provider/model calls 均未变化。

## Closeout

- [ ] 完成 `docs/insurance-kb/evidence/830-g1/` 全部清单与复现步骤。
- [ ] 独立 reviewer 只读复核 exact head/tree/runtime/release/evidence pack，unresolved=0。
- [ ] focused tests、适用 CI、git diff/status、worktree clean 全部有新证据。
- [ ] 最终只报告 `G1=PASS|FAIL|STOPPED`；G2 readiness 只读，不启动 G2。

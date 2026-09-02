# 126 · Implementation Tasks

## M0 · Authority, frozen inputs and RED

- [x] 裁决 `B0=PASS`、写入 `G1_ONLY` 状态，并保持 G2+ 锁定。
- [x] 占用唯一 OpenSpec 126，冻结 G1-R1..G1-R9、Owner matrix 与 STOP 条件。
- [x] 冻结 base/entity/release/SchemaPack/ordered67/B0 Evidence digest；D0、Docker SKIP。
- [x] 由独立只读 reviewer 复核 M0 exact head/tree；未通过前不写功能代码。

初次只读复核在 `0f1cbe1840774aca6e1a3eb74bbc65687d97680b` /
`447dcbde22641136effc6d612134caeb7348fc4f` 报告 3 个 BLOCKER。总控在
`bc93bbef19e24877f0a8816dc49395bc662d703f` / `71601455e486fe7b21b358032939b0799cafbc8f`
完成唯一纠偏；同一只读 Review 随后报告 PASS、`UNRESOLVED_COUNT=0`，Win1 才启动。

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

- [x] 按 G1-R1/R2/R3/R5/R9 先写并运行 Harness RED，再实现最小 entity page compiler。
- [x] 共享 payload contract/hash 冻结后，按 G1-R6/R7 先写 Go RED，再扩展现有 Release read。
- [x] 按 G1-R1/R5 先写前端 RED，再增加实体 overview/section/field/free-wiki route/navigation。
- [x] 使用真实 815 Candidate/Claim/Evidence Preview 证明 1 overview、1 section、3 field、空
  free_wiki、短标题、完整 namespace 与至少 1 个 exact source click。
- [x] 提交 M1 最薄纵切；若 48 小时无真实 Preview，STOP。

M1 接线现冻结为同一 lifecycle 的四个原子边界：

1. 同一 `POST .../schema/preparations` 接受严格互斥的 G1 manifest request；服务端从已
   验证 manifest 派生 76 snapshots、`Content=""`，并使用 embedded canonical
   `manifest_sha256`；review policy/batch identity 只能从重放后的 815 source Release
   派生。
2. 增加不依赖 Head 的 human-admin preparation scope bootstrap 和 Draft/Ready entity
   overview/section/field/free-wiki reads；前端稳定路由使用严格单值 `preparation_id`。
3. 增加 preparation-scoped G1 citation authority：服务器从完整 G1 citation 回放并核对
   旧 815 C5 citation/join/source custody 后才签发既有 opaque token；前端不得自行截断
   citation 后越过该核对。
4. 此阶段只形成真实 Candidate Preview；不激活、不创建 successor Release、不修改
   production `8081`。historical release scope bootstrap 与 successor source bridge 保留
   为 R7/M3 后续，不得混入本次 M1 完成声明。

独立 Review 对 `dc5d4ef34845f59f75cfaa843f4342616754ac63` / tree
`854b187db15f69e1da9aff90b2b8979fefedbbe1` 的纠偏复核：11-path diff 无新增 finding；
显式 pin、UNKNOWN typed reason、空 Content read custody 与 TS bbox 子项关闭。仍保留
writer lifecycle、Candidate preparation read、真实 source click、Head-independent
historical pin 四个结构 blocker；本轮 M1 只关闭前三者中的 M1 范围，不提前宣称 M3。

Harness 合同冻结于 `8fa27956c6368502f21d52245d2cea905f0e2ce1` /
`82e490ef47da775aed0d8176c7f31a27f6d537e9`。独立只读 Review
`01a05917-a8e7-7b00-bf36-82bef310c2a5` 报告 PASS、`UNRESOLVED_COUNT=0`；这只关闭
R1-R5/R8/R9 的离线合同层，不改变 R6/R7/live UI/source-click 的 NOT RUN 状态。

M1 真实 Preview 已在 `740d9b7c55f047e30c59c087dc29b943e3849726` /
`bb29b5d6cf9533f69bd14728736e916513f3119c` 的隔离 D1 runtime 形成。Draft
`g1-m1-740d9b7c-preview` 使用真实 815 source release/epoch，UI 实测 overview、
`application-and-contract`、present/absent_explicitly/unknown 三个 FieldAssertion 与空
free_wiki；`insured_eligibility` 的 source click 命中原 PDF 第 2 页 exact bbox。Preview
读窗口前后 scope counts 与 Head 完全相同，production `8081` 身份不变。M1 只关闭
Candidate Preview，不把 Draft 冒充 Review/Release/Active，也不提前关闭 M3 current/pinned。

## M2 · Complete 76-page graph

- [x] 关闭 76/76 唯一 ID、67/67 三态、unknown typed reason、全部稳定 route。
- [x] 关闭 Section→FieldAssertion、known 同源 Evidence、标题/分类不改变 identity。
- [x] 关闭公共 renderer 的非 7 节点单测；不得注册其余 10 类产品 Profile。
- [x] 提交 M2 完整页面图并更新 Requirement 矩阵。

M2 candidate `d1b8d8e9e1213a28d4b762f0767120b121b218c1` 的内容树已通过页面图复核，但其
commit message 提前把 NEXT 指向 M3，独立 Review 报告唯一 BLOCKER。总控仅重写未推送 tip；
纠正 head `edc74ac7fb82dcb8e443020bab151a116f57ef32` 保持 tree
`4ada9652d998f3b2effcaea29552aaee840f2ebd` 不变，并与树内 NEXT 同为 M2。可见只读 Review
`01a05c5d-0483-7641-9bec-948442015a0d` 随后报告 `REVIEW=PASS`、
`UNRESOLVED_COUNT=0`。M2 关闭后才允许推进 M3；G2 继续锁定。

## M3 · Atomic isolated Release

- [ ] 冻结 integration head 与 image change-impact；总控仅构建受影响镜像一次（D2）。
- [ ] 复用 D2 exact digest，在隔离环境形成一个 `NOT_FOR_PRODUCTION` Release（D3）。
- [ ] 验证 activation 前旧 Active 完整可读，activation 后 current/pinned 只读 exact 新 Release。
- [ ] 验证 76 页同 release、无混版，以及三个 known field exact source click/fail closed。
- [ ] 证明生产 `8081`、生产 Active、Provider/model calls 均未变化。

M3 D2 的首个观察结论已被后续只读取证纠正。integration
`06b101665921844cabf666574514c2b71ebd4b12` / tree
`e14c5057f87427670f8a0382b357b6970ecd74f8` 保持冻结，B0 映射仍只影响 app/frontend。
唯一 app build 的 SSH 客户端观察链退出 `130` 后，原 BuildKit job 继续运行并在
`2026-09-02T02:45:38.736896529+08:00` 形成 exact tag，镜像为
`sha256:f913037cfe74a7bbd7e8a819a56ccb92fea32ae3da4b6511d460a04f3b920327`；其
commit/tree/source-subset/lock labels 全部匹配冻结输入，因此计为原第一次 build 的
`PASS_LATE`，不得重建 app。原 STOP 回执保持不可变；superseding 纠正回执为
`docs/insurance-kb/evidence/830-g1/m3/d2-app-build-reconciliation.json`。

根因是 raw `limactl` 在默认 `~/.lima` 查询，未使用 Colima 的
`$HOME/.colima/_lima`，从而把 SSH/host-port-forwarding 异常误判为实例丢失。正确实例持续
`Running`，Docker/VM 无重启、无 OOM、无磁盘满；原 production app/frontend 容器在 guest
内保持 exact identity、healthy/HTTP 200。宿主 `8080/8081` 转发仍待在不替换、不重启生产
容器的前提下恢复。frontend dist 已 PASS，但 frontend image 的唯一 D2 build 尚未开始；
当前继续 G1 M3，不启动 Release/Head、Provider/model 或 G2。

## Closeout

- [ ] 完成 `docs/insurance-kb/evidence/830-g1/` 全部清单与复现步骤。
- [ ] 独立 reviewer 只读复核 exact head/tree/runtime/release/evidence pack，unresolved=0。
- [ ] focused tests、适用 CI、git diff/status、worktree clean 全部有新证据。
- [ ] 最终只报告 `G1=PASS|FAIL|STOPPED`；G2 readiness 只读，不启动 G2。

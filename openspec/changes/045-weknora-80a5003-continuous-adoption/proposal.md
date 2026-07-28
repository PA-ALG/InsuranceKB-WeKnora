# 045 · WeKnora `80a5003` Mainline Snapshot Continuous Adoption

## 状态

`SPEC-ONLY / IMPLEMENTATION NOT STARTED`

本 change 冻结把 WeKnora 从
`v0.6.3@5eefa70e6fc8f9ec27958779f91ece6cf685598c` 无损升级到官方
post-v0.7.1 mainline snapshot
`80a5003cc99a427098afe184eee6601916d3d156`
（tree `18fcf68e7a008ce69929e32233f0b6914040c223`）的最小合同，并把同一
机制固化为后续固定官方 identity 的持续升级入口。

## 用户价值

用户可以使用该 snapshot 新增的 Wiki 单页历史、Diff、人工编辑与 Revert，
并持续获得已批准官方 identity 的能力与修复；同时保险 Harness 保持插件化，
现有数据库、W1 revision manifest 和可验证来源不因官方升级丢失或被静默
覆盖。

## 为什么现在做

当前仓库已合入 W1，但 trusted local-live runtime 仍从旧官方 commit 构建且
不含 W1。目标 snapshot 继承的官方 chain 与项目 W1 分别使用不同语义的
`000066`，并新增官方 `000075_wiki_page_revisions`。若只改版本号、覆盖
migration 或重建数据库，会造成错误迁移历史、W1 schema 丢失或不可恢复的
数据风险。仅升级到 v0.7.1 又不包含用户要求的 page revision 功能。

## 本 Change 冻结什么

1. exact 官方 commit/tree/checksum、release ancestor 与持续升级协议；
2. 官方 migration 与企业 migration 的 source/state ledger 分离；
3. `pre_66 / upstream_66_plus / legacy_w1_66 / fresh_target` 四来源无损收敛；
4. unknown/dirty/partial state fail-closed 且零写；
5. W1 与现有 redaction patch 的 machine-readable 重放；
6. migration 编号、schema object 与 patch surface 三层碰撞 CI；
7. trusted image/provenance/SBOM/digest 与备份 clone 演练；
8. Code 与 Artifact 两阶段交付，禁止用未构建 runtime 冒充采用完成。
9. Wiki 单页 history/diff/manual edit/revert/optimistic-locking 的 bounded
   upstream feature 验收。

本 change 显式修改 038 `W1.6 patch budget 与上游兼容义务`：W1 的领域合同
与 patch identity 不变，但 migration 从官方 chain 迁入 enterprise chain，
并为 classifier/bridge/readiness/collision gate 增加受控 adoption surface。
这是解决已发生的 upstream `000066` 冲突所必需的合同迁移，不是第五 patch。

## 明确不做

- 不实现或解除 P2d/P3 ACL、P11/P13/P14；
- 不增加未登记 WeKnora patch 或保险领域 Go 逻辑；
- 不清空/重建现有数据库，不自动 force migration version；
- 不认证 W1-on-SQLite、provider/live full 或生产正式切流；
- 不跟随 mutable upstream main，只采用固定且获批的 upstream identity
  （stable tag 或 exact snapshot commit/tree）；
- 不把官方新 API key/activity audit/source download 能力直接声明为现有
  Harness 安全合同的替代物。

## 交付边界

- Spec PR：design/proposal/spec/tasks/registry，零代码/迁移/runtime；
- Code PR：`80a5003` sync、W1 replay、migration 分轨/bridge、collision CI，
  以及不含 runtime digest 的 source-lock v2 与 main-only multi-image trusted
  workflow；
- Artifact PR：从已合入 main 的 trusted workflow 执行 build、四状态备份
  clone 演练、digest/image-lock/cutover。

实现阶段属于高风险 migration/supply-chain Mission，最多两轮 corrective；
任何数据状态无法证明或出现未登记第三 patch 时立即停止。

# 046 · Tasks

## 046 文档交付

- [x] C1 核验 exact base、80a5003 ancestry 与 adopted target manifest。
- [x] C2 读取当前 Wiki revision、route、ACL、migration 与 thin-upgrade 证据。
- [x] C3 输出 capability gap，严格区分单页能力与整版 Release。
- [x] C4 冻结 S0-R Mission Card 的 exact paths、表/索引、migration、read
  surface、升级责任与命令预算。
- [x] C5 冻结唯一 R0/R1、双 Candidate、四故障点、并发 read 与 ACL shrink
  fixture。
- [x] C6 冻结暂定 PublishAuthorizationV0 canonical bytes、校验顺序与失败零写。
- [x] C7 独立 Spec/Delivery review。
- [x] C8 用户批准按 Mission Card 启动并执行 S0-R。

## 后续 S0-R（本 Change 不执行）

- [ ] R1 从开始时最新 origin/main 建 clean 独立 worktree。
- [ ] R2 只在 Mission Card exact patch/migration budget 内 RED→GREEN。
- [ ] R3 在专用 Space/凭据执行唯一 fixture 与允许的 targeted commands。
- [ ] R4 两工作日内输出 `RELEASE_PATH_FEASIBLE` 或
  `RELEASE_PATH_NOT_FEASIBLE`，附 actual patch/migration/upgrade responsibility。
- [ ] R5 若 PASS，另开生产 OpenSpec 与 043 Amendment；若 FAIL，停止载体路线。

## 永久非目标

- [ ] 不在 046 实现生产 Kernel、P2d、S0-Q、source_reader、MCP、UI 或部署。
- [ ] 不新增 official migration，不修改 upstream migration identity。
- [ ] 不以单页 Demo、历史代码或 Harness receipt 冒充 serving Active Head。

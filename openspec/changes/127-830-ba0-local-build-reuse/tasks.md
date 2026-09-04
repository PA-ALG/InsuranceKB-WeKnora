# 127 · Implementation Tasks

## Task 1 · OpenSpec 与 BA0_ONLY 状态

- [x] 在 change 不存在时运行 strict validate，保存 missing-change RED 与退出码。
- [x] 冻结 BA0-REQ-01..06 和唯一 Owner、origin-main 与 implementation 两组 base/tree、
  worktree/branch、build budget 与 effects 边界。
- [x] 原子同步五个当前状态面并登记 OpenSpec 127；G1 保持 PASS，G2 保持锁定。
- [x] 运行规格存在性、Requirement ID、strict validate 与 `git diff --check`。

## Task 2 · 完整 RED 与 YELLOW 范围门

- [ ] 为 BA0-REQ-01..06 写完整 focused Python/Go RED，并确认均因缺实现而失败。
- [ ] 由只读 reviewer 核对写域、真实 build 预算、无新增服务/表/平台和 D3 standalone 拓扑；
  `YELLOW=PASS` 前不写生产实现。

## Implementation 与 D1

- [ ] 冻结 versioned 外部依赖事实、app input manifest 与 canonical identity。
- [ ] 稳定 build-source 元数据，令两个 Go `RUN` 共享持久 module/build cache。
- [ ] 接通唯一公共入口的 lookup-before-build，并加入 standalone exact-image artifact smoke。
- [ ] focused tests、受影响 package、OpenSpec 和 diff 检查全部 GREEN 后冻结 D2 build source。

## D2 / D3 / Closeout

- [ ] 在真实 app build 总预算 1 内执行首次请求；exact hit 为 0，miss 最多为 1。
- [ ] 第二次相同 identity 请求返回同一 image identity 且 Docker build invocation 为 0。
- [ ] D3 artifact smoke 使用 exact image，build/pull、网络、端口、依赖和业务 effects 均为 0。
- [ ] 独立复核通过后关闭 BA0，清零授权并返回用户；不得自动启动 G2。

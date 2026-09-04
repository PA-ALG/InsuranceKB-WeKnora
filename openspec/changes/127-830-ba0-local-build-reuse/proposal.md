# 127 · 830 BA0 本地构建复用

## Why

G1 已终态 `PASS`，但其 app 镜像构建暴露出相同制品重复构建、Go 编译缓存不能稳定复用、
构建元数据随墙钟漂移，以及 D3 路径可能隐式触发 build 的工程风险。用户已授权在 G2
之前以一次性 BA0 工程门关闭这些风险；BA0 不是产品 Goal。

## What Changes

- 以 versioned manifest 和外部依赖事实计算完整、可重算的 app artifact identity；
- 在固定 `colima-g1-build` context 中 lookup-before-build：exact hit 不构建，miss 最多构建一次，
  冲突或漂移失败关闭；
- 使用冻结 build-source 的稳定二进制元数据，并让两个 Go `RUN` 共享持久 module/build cache；
- 以 versioned lock 固定 base、Debian、Python 构建工具、DuckDB 等影响输出的外部事实；
- 以 standalone exact-image Compose 执行只读 `CONTAINER_ARTIFACT_SMOKE`，build/pull 均为 0；
- 将 BA0 全程真实 app build 预算固定为 1，所有产品、Provider、生产与 G2 effects 固定为 0，
  越界立即 STOP 并返回用户。

## Current identity

```text
CURRENT_AUTHORIZATION=BA0_ONLY
CURRENT_PRODUCT_GOAL=NONE
BA0_STATUS=WIP
G1_STATUS=PASS
G2_STATUS=LOCKED_PENDING_BA0_PASS_AND_EXPLICIT_USER_AUTHORIZATION
ORIGIN_MAIN_BASE=0e7a26568a2164f9501e409f38fee0d4a62539cb
ORIGIN_MAIN_TREE=b96aa35fd2fe86283757deb258920c489de4b4b6
IMPLEMENTATION_BASE=874e50d44aec5941faae045e761280aa69aee1a3
IMPLEMENTATION_BASE_TREE=2ec76af38258a0220d5dc117a9b789890345e7d7
WORKTREE=/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-ba0-implementation
BRANCH=codex/830-ba0-implementation
OWNER=830-BA0总控
REAL_APP_BUILD_BUDGET=1
REAL_APP_BUILDS_USED=0
```

## Boundaries

本 change 不实现 G2，不调用 Provider/model，不接触业务数据库、生产 `8081` 或生产 Active，
不建设 CI/remote cache、基础镜像产品线、第二平台或第二构建 authority，也不把性能分钟数
设为 BA0 PASS 的硬 SLA。缓存只影响性能，不能成为制品正确性 authority。

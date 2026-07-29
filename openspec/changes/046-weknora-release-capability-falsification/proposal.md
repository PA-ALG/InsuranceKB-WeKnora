# 046 · WeKnora Release capability falsification

## 状态

`SPEC + MISSION CARD ONLY / S0-R IMPLEMENTATION NOT STARTED`

## 为什么做

WeKnora 已采用 `80a5003`，具备单页 history/diff/manual edit/revert，但当前
生产 Go/SQL/API 没有整版 manifest、Active Head/CAS、pinned/release-aware read
或 release-managed write guard。必须先用两工作日、有界 patch 的实验判断
WeKnora 是否适合作为唯一 serving Active Release carrier，不能直接建设生产
Kernel，也不能把单页能力当成整版能力。

## 本 Change 做什么

- 记录当前 fork 的 capability gap，逐项标记
  `PRESENT|PATCHABLE|ABSENT|UNKNOWN`；
- 冻结 S0-R 的 exact fixture、暂定 PublishAuthorization、校验顺序、失败零写、
  read/ACL 场景与 patch/migration/命令预算；
- 将 S0-R 终态限制为 `RELEASE_PATH_FEASIBLE` 或
  `RELEASE_PATH_NOT_FEASIBLE`。

## 不做什么

- 不实现 Release Kernel 或 S0-R；
- 不修改 Go/Python/Vue、migration、workflow、principal、Artifact 或部署；
- 不运行 full/provider/live/PostgreSQL；
- 不修改 043，不解除 `source_reader` block；
- 不承诺 UNKNOWN 可补，也不冻结生产 Release schema/API。

## 依赖与后续

046 依赖 Sole Serving Active Release Authority ADR、Authority Amendment 2、
OpenSpec 033 D0.13 与已采用的 045 source。046 Spec Approved 后，仍须用户逐项
批准 Mission Card 才能开始 S0-R。S0-R PASS 只允许后续形成独立生产
OpenSpec/043 Amendment；FAIL 则重新评估单一载体，不能恢复双 Head。

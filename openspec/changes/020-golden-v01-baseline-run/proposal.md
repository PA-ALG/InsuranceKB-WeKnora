# 020 · gs-v0.1 与 13 产品基线真实运行

## 为什么做

002 T8 尚有 2 产品，HANDOFF B2/B3/B6/B7 尚未完成。它们是高 token、依赖真实模型和凭据的数据运行，不应与 019 的确定性软件验收混在一起，但必须以 SDD 方式保留准入、断点、产物和验收合同。

## 做什么

1. 原地接续现有 11/13 WIP，仅标注两个缺失产品；
2. 使用 019 工具发布并验证 gs-v0.1；
3. 运行 13 产品弱模型 baseline，处理 judge queue、dead letter；
4. 完成 long-field keypoints 与 before/after 回归；
5. 生成 approved baseline/QualityProfile 并更新 002、HANDOFF 与路线图。

## 运行准入

开始真实调用前必须在 `run-admission.md` 固定：annotator/weak/judge 的精确 provider+model ID、prompt/schema/golden 指纹、凭据可用性检查结果、预计 token/费用上限、断点目录、超预算停止条件和业务方确认。凭据只从环境读取且不得写入仓库。

## 依赖

硬依赖 002 的 WIP 现场，以及 004 抽取管道、005 评测口径、006 template fast path 和 019 的 release/profile/gate 工具。

## 不做什么

- 不修改评测口径或在线 Gate 逻辑；发现工具问题回到 019 以 TDD 修复；
- 不重标现有 11 产品；
- 不因模型/网络不可用伪造运行成功。

## 影响面与文件域

- 数据：`dataset/goldenset/wip-gs-v0.1/`、新 immutable release、baseline run artifacts；
- 文档：002 tasks/T8 handover、020 admission/validation、HANDOFF/05/13/16；
- 代码原则上不改；若必须修工具，暂停运行并走 019 change。

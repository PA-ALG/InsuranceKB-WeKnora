# 067 · 061 Public Single-Arm Golden Score

## 状态

`STABLE CANDIDATE / EXTERNAL REVIEW PENDING / PROVIDER NOT RUN`

061 的公开 scorer 只服务固定的 pdfplumber/DeepSeek 与 MinerU/DeepSeek 解析消融。
066 需要在同一已准入 MinerU artifact 上评分 GPT-5.6-sol ceiling，但不得复制 061
的 Golden parser、metrics 或 admission。本 change 只把现有确定性能力收敛成一个
窄公开单臂 seam；它不运行模型，也不授予任一模型生产资格。

## 单一职责

- 公开 `score_admitted_frozen_arm(...) -> AdmittedFrozenArmScoreV1`；
- Golden 前重放 exact 三 artifact admission，并验证 frozen output 与全部非模型
  authority；
- 只接受 MinerU candidate parser role，允许任意完整、被 receipt 绑定但不获
  authority 的 semantic model identity；
- 复用同文件现有 exact 049 Golden parser、Schema60、metrics 与 absolute gates；
- 返回 metrics、无 Golden 答案的 exact60 correctness flags、gate reasons 与 C0
  receipt。

## 非目标

- 不修改 provider、runner、066、Golden、Schema、parser 或生产模型策略；
- 不调用模型、provider、live、DB、PostgreSQL 或 WeKnora；
- 不建立模型 registry、榜单、通用 evaluator、自动路由或 fallback；
- 不输出 Golden expected value，不生成 Release、审核或最终 MVP GO。

## 路径预算

严格七路径：OpenSpec README、067 proposal/tasks/validation/spec 四件、既有
`vertical_falsification.py`、一个新 focused test。需要第八路径即停机。

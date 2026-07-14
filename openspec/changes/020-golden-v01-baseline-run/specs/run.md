# 020 规格（验收条件）——Golden 与 Baseline 真实运行

## D1 运行准入

- D1.1 `run-admission.md` 固定精确模型 ID、schema/prompt/template/golden 指纹、预算/停止条件、断点目录和业务确认；
- D1.2 启动前只检查凭据存在与端点连通性，不输出凭据；任一缺失则状态 blocked，零模型调用；
- D1.3 总消耗达到批准上限时安全停止并保留可恢复现场，扩大预算需新确认记录。

## D2 gs-v0.1

- D2.1 不改现有 11 产品，只完成爱满分两全和附加意外伤害两个缺失产品；每条记录含真实 annotator_model；
- D2.2 quote 逐字回验，present/absent 必须有 evidence；每产品 disputed rate≤0.05；
- D2.3 使用 019 validator 发布 13/13 immutable gs-v0.1，所有 extractable 字段有三态；self-eval 全 1.0；
- D2.4 勾选 002 T8/T9，WIP 原始输出保留。

## D3 全量基线与裁决

- D3.1 13 产品均有完整 run manifest/pred/dead-letter/judge artifacts/eval；
- D3.2 judge queue 全部 resolved 或逐条登记 pending 原因；dead letter 重跑后仍失败的保留最终原因；
- D3.3 judge 回写后重新出分，不以回写前分数作为批准基线。

## D4 Keypoints 与回归

- D4.1 全部 present 且归一化值≥30字的字段有 keypoints 或明确 pending 工单；
- D4.2 完成 005 路由修复与 006 template fast path 的 before/after 对比；
- D4.3 使用 019 生成 baseline artifact、approval 与 QualityProfile；未满足自动资格的字段不得人工改指标。

## D5 收尾

- D5.1 validation-report 记录实际 token/费用、运行时间、模型指纹、13 产品指标和 unresolved 清单；
- D5.2 更新 HANDOFF B1/B2/B3/B4/B6/B7、002 tasks、05/13/16；
- D5.3 数据 release 不含绝对路径、凭据或未脱敏客户数据。

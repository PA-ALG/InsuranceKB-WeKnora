# 020 任务

- [ ] T1 完成 run-admission，确认模型/凭据/预算/断点与停止条件（D1）
- [ ] T2 生成两个产品分页工件并完成实际标注、quote 回验与 disputed 修正（D2.1/D2.2）
- [ ] T3 dry-run、发布 gs-v0.1、自评满分、收尾 002 T8/T9（D2.3/D2.4）
- [ ] T4 断点运行 13 产品 baseline，复跑 dead letter（D3.1）
- [ ] T5 完成 judge queue 回写与重新出分（D3.2/D3.3）
- [ ] T6 完成长字段 keypoints 与 before/after 回归（D4.1/D4.2）
- [ ] T7 生成 approved baseline/QualityProfile（D4.3）
- [ ] T8 validation-report、HANDOFF/002/05/13/16/20 对账（D5）

状态：待运行准入；未完成 admission 前不得触发真实模型调用。

- [ ] D4b（024 R2 让渡承接）differential replay：以同一批不可变 raw responses 对 base SHA 与 candidate SHA 重放评分，建立"后处理改动非退化"真实证据（024 E5 的非退化半条在此完成；synthetic 机制探针不作数）

# 012 任务（TDD 顺序；测试名引用条款号）

> 三版（2026-07-18，codex PR #12 复审收口）：T1 升级为断言级绑定模型；T6 升级为冻结投影扩展。**前置：010 域段完成（消费 qa_staging）+ 021 合入**。执行者 C3；QA 新模块 Owner=C，**qa 表/绑定/冻结投影/发布接线全部属 knowledge 域接线点，Owner-A 复审**。

- [ ] T1 迁移 0009：`qa_items`（身份）+ `qa_revisions`(不可变) + `qa_assertions` + `qa_assertion_claim_bindings`（复合 FK 闭 Space）——含"跨 Space 绑定被数据库拒绝（双方言）""revision 追加不覆盖"迁移/约束测试（Q1）
- [ ] T2 发布硬门禁：每 assertion ≥1 published 绑定（部分覆盖拒发）+ **冻结事务内锁定重验（TOCTOU：并发 supersede/retract → 发布失败或重试）** + 五类 fail-closed 进 ReviewItem（Q1）
- [ ] T3 权威 QA 通道：qa_staging 消费 + 确定性值匹配 → assertion 级绑定 + qa_unbound 工单分流（Q2）
- [ ] T4 派生 QA 生成器：模板 YAML + 只从 published 生成 + 幂等（Q3）
- [ ] T5 同步义务：supersede→derived 追加新 revision 重编/authoritative 复核；retract→下架（均 ChangeSet 留痕、零原地覆盖）（Q3）+ 相似问指纹合并 + alias 问句表（Q4）
- [ ] T6 冻结投影扩展：SnapshotQA + QA 区块进 rendered pages + read_model_version 升级（reader 先行 rollout gate）+ 回滚指针切换一致 + **mutable 表不可访问仍可读** + 冻结后写入被拒（双方言）（Q5）
- [ ] T7 端到端全链故事（含 V1→V2→改 mutable→回滚 V1 精确复原）（Q6）
- [ ] T8 收尾：validation-report → HANDOFF 更新

约束：零模型调用；不改 compiler/goldenset/adapters；迁移仅 0009（链序按注册表规则）；read_model_version 升级按注册表合入序取号（010 v2 之后）。
状态：**已条款化，规格复审收口中（PR #12）——收口前不可认领**。依赖：007/016/018 已合入 + 010 域段（qa_staging，候 021）。

# 010 任务（TDD 顺序；测试名引用条款号）

> 三版（2026-07-16，按 PR #11 二轮复审重排）：structured 证据须闭合**全消费链**（models/merge/pages/序列化），不是只改表。分两段开工：**T1~T4 即刻**（通道一/登记/映射，不触 knowledge 域）；**T5~T9 基于 PR #9 合入后的 main**（knowledge 域接线，Owner-A 复审），且须**先于 021 开工合入**（或与 021 负责人显式协调）。执行者 C3。

- [ ] T1 Space 作用域接线：导入服务与 CLI 显式 space，fail-closed 与跨 space 不可见用例先行（I6）
- [ ] T2 通道一 bootstrap：meta 映射 → 003 注册（幂等、dry-run），**零 Claim/Evidence 断言**（I1）
- [ ] T3 来源登记表：source registry 加载 fail-fast + 未登记来源拒绝用例（I1/I3）
- [ ] T4 映射规则加载器 + 规范化接线 + 未知结构候选草案（I2）
- [ ] T5 迁移 0007 + 领域模型（**knowledge 域起点，基于 PR #9 后 main**）：structured_source_records + claim_evidence 的 source_kind/structured_record_id + CHECK 按 kind 分支；`ProposedEvidence` kind 分支校验；**既有 weknora/legacy 用例零漂移回归 + downgrade 干净**（I4）
- [ ] T6 merge 接线：`_evidence_rows` 持久化新字段、enrich 追加与 aggregate 去重保留 structured 身份（I4）
- [ ] T7 pages/序列化接线：`_evidence_view` structured 验证分支（hash 一致→verified、缺失→显式 unverified、零伪引用）+ 快照冻结 Evidence JSON 与 013 证据链合同含新字段（I4）
- [ ] T8 通道二导入：幂等（同键同 hash no-op）+ **同键异 hash 碰撞 fail-closed** + revision 更替走 007 合并（I5）
- [ ] T9 批次/ChangeSet/错误隔离 + dry-run 默认与 apply 一致性断言（I5）
- [ ] T10 产品对齐与一对多拆分 + FAQ → qa_staging（I7）
- [ ] T11 端到端：meta bootstrap + 双 revision 冲突 + 碰撞用例 + **发布链回溯（source_verified=true、locator+hash 可回溯、零伪引用）**（I8）
- [ ] T12 收尾：validation-report（Q020 合规声明 + knowledge 域改动清单 + Owner-A 复审记录）→ HANDOFF 更新

约束：零模型调用；不改 compiler/ 与 goldenset/；**knowledge 域改动显式清单 = tables.py/models.py/merge.py/pages.py/证据序列化 + 迁移 0007**（全部 Owner-A 复审，17 §1）；Evidence 不伪造页码/chunk 锚点。
状态：**可认领**（T1~T4 即刻；T5 起等 PR #9 合入，从新 main 继续）。依赖：003/007/016/017 已合入；T5~T9 前置 018。

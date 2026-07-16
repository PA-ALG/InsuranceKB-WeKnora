# 010 任务（TDD 顺序；测试名引用条款号）

> 四版（2026-07-16，按 PR #11 三轮复审重排）：**不插入关键路径**——T1~T4 即刻并行；**T5 起基于 021 合入后的 main**（018→021→020 不变）。structured 证据须闭合全消费链**含冻结合同**（FrozenEvidence 变体/发布时去引用/读侧零回查）。执行者 C3，knowledge 域全量 **Owner-A 复审**。

- [ ] T1 Space 作用域接线：导入服务与 CLI 显式 space，fail-closed 与跨 space 不可见用例先行（I6）
- [ ] T2 通道一 bootstrap：meta 映射 → 003 注册（幂等、dry-run），**零 Claim/Evidence 断言**（I1）
- [ ] T3 来源登记表：source registry 加载 fail-fast + 未登记来源拒绝用例（I1/I3）
- [ ] T4 映射规则加载器 + 规范化接线 + 未知结构候选草案 + **mapping_version（映射内容哈希）单一权威**（I2/I4）
- [ ] T5 迁移 0007 + 领域模型（**knowledge 域起点，基于 021 合入后 main**）：structured_source_records（insert-only+DB 拒 UPDATE）+ claim_evidence 的 source_kind/structured_record_id/mapping_version + CHECK 按 kind 分支；`ProposedEvidence` kind 分支校验；**既有 weknora/legacy 校验/裁决行为不变回归 + downgrade 干净**（I4）
- [ ] T6 merge 接线：`_evidence_rows` 持久化新字段、enrich/aggregate 去重键含 structured 身份+mapping_version、**space 一致性 fail-closed**（I4）
- [ ] T7 发布/冻结接线：`pages._evidence_view` structured 验证分支（canonical hash 重算比对；缺失/篡改 ⇒ 拒发）+ **`FrozenEvidence` 按 kind 分支变体与发布时去引用冻结** + SnapshotReader/013 证据链只读冻结值（**冻结后零回查可变表用例**：模拟源表不可访问仍可读）（I4）
- [ ] T8 通道二导入：双轴幂等（同键同 hash 同 mapping_version→no-op）+ **同键异 hash 碰撞 fail-closed** + **映射修正受控重算** + per-source 串行化（对齐 021 lock/CAS 模式，含并发用例）（I5/I6）
- [ ] T9 批次/ChangeSet/错误隔离 + dry-run 默认与 apply 一致性断言（I5）
- [ ] T10 产品对齐与一对多拆分 + FAQ → qa_staging（I7）
- [ ] T11 端到端：meta bootstrap + 双 revision 冲突 + 碰撞/映射重算用例 + **发布链回溯（冻结 provenance 全套、零回查、零伪引用）**（I8）
- [ ] T12 收尾：validation-report（Q020 合规声明 + knowledge 域改动清单 + Owner-A 复审记录 + 冻结合同证据）→ HANDOFF 更新

约束：零模型调用；不改 compiler/ 与 goldenset/；**knowledge 域改动显式清单 = tables.py/models.py/merge.py/pages.py/snapshots.py（含 reader 消费合同）+ 迁移 0007**（全部 Owner-A 复审，17 §1）；Evidence 不伪造页码/chunk 锚点；源记录表 insert-only。
状态：**可认领**（T1~T4 即刻；T5 起等 018 与 021 合入，从新 main 继续）。依赖：003/007/016/017 已合入；T5~T8 前置 018+021。

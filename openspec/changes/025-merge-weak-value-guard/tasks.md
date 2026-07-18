# 025 合并前置弱值门槛 · 任务

> 二版（2026-07-18，codex PR #17 复审收口）。依赖：007 主链 + 018（PR #9 已合入）；**实现排在 021 之后（021 规格已提出、尚未实现——G8 锁序依赖其 per-source lock 语义）**。文件域：`knowledge/merge.py` + `knowledge/tables.py` + `knowledge/models.py` + 只读查询 API + 迁移 0011（含迁移测试）+ docs 03 §8（已先行修订）。测试名引用条款号（G1~G9）。零真实模型调用。

## 任务（红绿；每条护栏必配 accept 侧/负测——024 gauntlet 教训：只测拒绝侧=半个护栏）

- [ ] T1 **SpecificityRelation 偏序比较器**（G2）：schema/value-type/predicate 级、版本化（comparator_version）、附 rule_id；自由文本默认 incomparable；白名单关系（存在性=量化投影/枚举父子/严格子集投影）才可判 strictly_weaker。**按值类型建 accept/reject 对偶矩阵**：每类白名单规则配"可证明弱化→判弱"正测 + "更短但更强/相反口径/规则变化（80周岁 vs 终身、保证续保 vs 不保证、90天 vs 30天）→ incomparable"负测；等价改写→equivalent。InformationFeatures/score 独立实现，断言其**不出现在任何抑制判定路径**。
- [ ] T2 **抑制资格前提 + 门槛接线**（G1/G3/G4）：merge 在 K2 冲突/supersede 判定前做 E1~E5 校验。**拒绝侧**：全前提成立 + strictly_weaker → 不开 conflict/不生 ReviewItem/不落 Claim。**accept 侧 RED 矩阵（codex 四类反例逐条入测）**：①同权威更新 effective_from → 不抑制（回 007 ②裁决）；②高风险（等待期）→ 不抑制进强审；③present→absent_explicitly → 不抑制开 conflict；④pending_judge → 不抑制；另：缺基线/区间缺失或不可比/比较器抛错 → fail-open。
- [ ] T3 **suppressed_observations 表 + 迁移 0011**（G5）：append-only 事件表、Space 复合 FK 闭合、唯一约束 `(space_id, change_set_id, proposal_fingerprint, existing_claim_id, existing_revision_no, comparator_version)` exact-once；候选完整快照+Evidence/来源身份+基线 revision+双方权威/生效区间+特征向量/两分/comparator_version/rule_id/actor/fingerprint 全字段落库；服务层无 update/delete + 生产角色无 UPDATE/DELETE（迁移内 GRANT 断言）；malformed/跨 Space/model_copy 绕构造 fail-closed 三件套；双方言（sqlite 单测/pg 集成）。**无审计的丢弃测试断言为违规**。
- [ ] T4 **observation 生命周期**（G7）：基线 supersede/retract/stale → active 观察重建 proposal 重新进入 007/025 全流程；观察自身来源删除（021 retract）→ invalidation 事件、不复活。端到端：强基线来源删除 → 弱观察重新裁决落 Claim；观察来源先删 → invalidated 且基线后续 retract 不复活。
- [ ] T5 **事务/锁/幂等**（G8）：claim-key advisory/row lock（锁序 source→claim-key）；锁内复核基线 revision（CAS）；observation/事件与 drop 决定同一事务；审计写失败注入 → 整体回滚 fail-open。**PostgreSQL 双会话四场景**：suppress-vs-supersede、suppress-vs-retract、重复批/事务重试 exact-once、审计写失败——结果等价某串行序；缺 pg 环境显式 skip 并记录（021 L5.6 纪律）。
- [ ] T6 **008 消费合同**（G6/G9）：进 007 候选的 information_score+comparator_version 写入 decision_basis；只读抑制计数/明细 API（Space 强制、分页、无写端点）；**负测钉死**：不存在"信息量更高即 auto-supersede"路径 + 排序读持久化分数（升级比较器不改历史排序依据）。
- [ ] T7 **收尾**：validation-report（条款→测试名 + accept/reject 矩阵 + 双会话结果/或 NOT RUN + 抑制事件样例）→ 核对 docs 03 §8 行与实际 DDL 一致 → HANDOFF 更新 → 008 W1.1 抑制计数展示交接说明。

## 裁决记录（设计判断及依据）

1. **抑制是裁决不是过滤**（二版重构核心，codex PR #17 复审确立）：一版自称"中性前置过滤、007 语义一字不改"，但 drop 判定了"旧值胜、候选不进裁决链"——绕过了 K3.2 ② 生效时间、高风险强审、三态冲突语义。二版以 E1~E5 资格前提保证"候选在更高优先级维度不可能胜出"才谈弱化。**教训（对齐 019/012 系列）：规格自洽≠对照真实底座；G1 一版只拿本 change 内概念（score/authority）自洽，没对照 K3.2 逐级短路字面与 docs 03 高风险清单。**
2. **标量分数≠语义证明**（G2）：一版用 informationScore 全序判"严格更弱"，但全序表达不了 incomparable——G3 承诺"不可比不抑制"在机制上不可实现（任意两分数必可比）。二版拆成偏序 SpecificityRelation（白名单可证明关系）与 score（仅排序）。"同输入确定"只证可重复，不证判定正确。
3. **抑制不等于丢弃观察**（G5/G7）：一版只留两值两分摘要，强基线来源删除后弱观察不可恢复（Evidence 从未落库、引用计数不含它）——K3.4 下开 conflict 至少留 candidate Claim，一版反而比现状更易丢知识。二版 SuppressedObservation 保存完整快照+Evidence 身份，基线失效即重评；观察自身来源删除即 invalidation 不复活。
4. **审计与丢弃必须原子**（G8）：先 drop 后写审计=审计失败时出现规格明令禁止的无审计丢值；021 per-source lock 锁不住跨来源同 claim-key 并发（L3.1 字面即 per-source）——需 claim-key 锁 + 锁内复核（与 012 冻结事务 TOCTOU 重验同一教训）。唯一约束 exact-once 防重试重复计数。
5. **与权威序正交**（G4，一版保留）：更高权威的更粗略值是合法修订；信息量永不凌驾权威。
6. **绝不静默**（G5，一版保留并强化）：任何抑制留 append-only 审计（服务层+DB 权限双层强制，对齐 docs 03 §8 不可变表约定）。
7. **迁移 0011**：suppressed_observations 独立表（append-only），不复用 change_sets/conflicts（语义不同：抑制=未开冲突的前置裁决记录）；docs 03 §8 已先行登记（tables.py"文档先改"合同）；README 已占号。
8. **008 口径闭合**（G9）：未抑制候选的 score 落 decision_basis（K3.3 既有 jsonb，零表变更）而非新表；读侧读持久化值防比较器版本漂移——codex 指出的"排序字段来源未定"由此闭合。

约束：文件域见页首；不改 007 权威/裁决语义（除 G1 资格内枚举）；不碰 compiler/goldenset/adapters；比较器不参考金标；送审前过 21 号自测 gauntlet（含 accept 侧红队：构造"更优值被误抑制"负例四类——新日期/高风险/absent_explicitly/并发基线变化）。
状态：**提案+规格二版定稿（codex PR #17 复审收口），可认领**；**实现候 021**（规格已提出、尚未实现；018 已随 PR #9 合入 2026-07-17）。

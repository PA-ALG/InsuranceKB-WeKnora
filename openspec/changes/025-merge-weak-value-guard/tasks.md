# 025 合并前置弱值门槛 · 任务

> [!CAUTION]
> **以下任务冻结，当前不可认领。** 只有 MVP 后重新排入完整 010/merge hardening、027 已完成且新的 delta 获批后才可重排；旧依赖段和示例不构成开工授权。

> 三版（2026-07-18，codex PR #17 两轮复审收口）。依赖：007 主链 + 018（PR #9 已合入）；**实现排在 021 之后（021 规格已提出、尚未实现——G7 重评复核/G8 锁序依赖其 SourceHead/per-source lock 语义）**。文件域：`knowledge/merge.py` + `knowledge/models.py`（ProposedClaim.effective_to）+ `knowledge/importer.py` + `knowledge/tables.py`（双表）+ 触发器 DDL + 只读查询 API + 迁移 0011（含迁移测试）+ docs 03 §8（已先行修订）。测试名引用条款号（G1~G9）。零真实模型调用。

## 任务（红绿；每条护栏必配 accept 侧/负测——024 gauntlet 教训：只测拒绝侧=半个护栏）

- [ ] T1 **SpecificityRelation 偏序比较器**（G2）：schema/value-type/predicate 级、版本化（comparator_version）、附 rule_id；自由文本默认 incomparable；白名单关系（存在性=量化投影/枚举父子/严格子集投影）才可判 strictly_weaker。**按值类型建 accept/reject 对偶矩阵**：每类白名单规则配"可证明弱化→判弱"正测 + "更短但更强/相反口径/规则变化（80周岁 vs 终身、保证续保 vs 不保证、90天 vs 30天）→ incomparable"负测；等价改写→equivalent。InformationFeatures/score 独立实现，断言其**不出现在任何抑制判定路径**。
- [ ] T2 **抑制资格前提 + 门槛接线 + effective_to 贯通**（G1/G3/G4）：`ProposedClaim` 增 `effective_to` 并贯通 `_prop_dump`/canonical proposal/importer 输入/`_create_claim`/revision 审计（`test_g1_effective_to_round_trip_before_suppression`——往返未全链通过前 E4 不可判定即不抑制）；merge 在 K2 冲突/supersede 判定前做 E1~E5 校验。**拒绝侧**：全前提成立 + strictly_weaker → 不开 conflict/不生 ReviewItem/不落 Claim。**accept 侧 RED 矩阵（codex 反例逐条入测）**：①同权威更新 effective_from → 不抑制（回 007 ②裁决）；②**低权威但不同/更新有效期 → 不抑制**（E4 全权威适用，进 conflict 记录）；③高风险（等待期）→ 不抑制进强审；④present→absent_explicitly → 不抑制开 conflict；⑤pending_judge → 不抑制；另：缺基线/区间单侧有值或值不等/比较器抛错 → fail-open。
- [ ] T3 **root+events 双表 + 迁移 0011**（G5）：`suppressed_observations`（root 不可变快照，唯一约束 `(space_id, change_set_id, proposal_fingerprint, existing_claim_id, existing_revision_no, comparator_version)` exact-once；候选完整快照+Evidence/来源身份+基线 revision+双方权威/生效区间+特征向量/两分/comparator_version/rule_id/actor/fingerprint 全字段）+ `suppressed_observation_events`（event_type/causation_id/reason/occurred_at/ordering/event_fingerprint，唯一约束 `(space_id, observation_id, event_type, causation_id)`；root 与首条 suppressed 事件同事务）；Space 复合 FK 闭合；**双方言触发器禁两表 UPDATE/DELETE**（018 release_guard 模式；直接 SQL UPDATE/DELETE 在 sqlite 与 pg 均断言失败），pg 另 REVOKE 纵深；状态折叠纯函数——乱序/重复事件恒同态、invalidated/source_superseded 终态；malformed/跨 Space/model_copy 绕构造 fail-closed 三件套。**无审计的丢弃测试断言为违规**。
- [ ] T4 **observation 生命周期 + 来源 revision 状态机**（G7）：基线 supersede/retract/stale → active 观察重评；重评在 021 per-source lock 内复核 SourceHead.state=active + latest_revision 匹配 + Evidence 非 stale，任一不满足追加失效事件不重建 proposal；`test_g7_newer_source_revision_invalidates_old_observation`（B-r1 被抑制 → B 推进 r2 致 r1 stale 未删 → A baseline retract → 断言 r1 永不复活、仅 r2 新观察参与）；观察来源先删 → invalidated 且基线后续 retract 不复活；新 revision 观察独立入流程不借旧身份。
- [ ] T5 **事务/锁/幂等（三类失败语义）**（G8）：claim-key advisory/row lock（锁序 source→claim-key）；锁内复核基线 revision（CAS）；observation/事件与 drop 决定同一事务。失败注入分类断言：①比较器异常（写入前）→ 单候选 fail-open、事务继续、其余候选不受影响；②持久化失败 → 整 merge unit-of-work abort，断言 Claim/ChangeSet/observation **零部分提交**、下一次健康事务重试该候选被正常处理；③唯一键冲突 → exact duplicate 幂等成功 / same-key-different-payload fail-closed，分别验证。**PostgreSQL 双会话四场景**：suppress-vs-supersede、suppress-vs-retract、重复批/事务重试 exact-once、持久化失败——结果等价某串行序；缺 pg 环境显式 skip 并记录（021 L5.6 纪律）。
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

（以下为二轮复审收口，2026-07-18）

9. **E4 扩至全权威 + effective_to 贯通**（codex P0-1）：一版 E4 只限"同权威"，低权威不同时间切片候选仍可能被吞；且 `ProposedClaim` 现实中无 `effective_to`，"区间相等"在输入链上不可证明——规格凭空使用了不存在的字段（**教训：规格里引用的每个字段都要对照真实模型字面，与 011 的 effective_end→effective_to 同款**）。三版取 codex 方案 1：字段贯通全链 + E4 适用全部权威。
10. **【裁决点，明示供复审质疑】E4 的"逐端相等"把双方同为 null 的端视为相等**：codex 字面建议"任一端缺失一律 fail-open"。我方裁决为 null==null 视为该端相等，理由：①未注日期是主流场景（条款抽取多数不带 effective 区间），若双 null 也 fail-open，025 对 Q026 动机场景（无日期粗略重抽值淹没审核队列）完全失效；②K3.2 ② 字面仅在"同级且**双方有** effective_from"时生效，双 null 不构成对它的绕过；③双 null 的候选未主张任何时间边界，不存在"不同时间切片"；④单侧有值仍严格 fail-open。若 codex 认为双 null 仍有未覆盖风险，请指出具体反例。
11. **来源 revision 状态机**（codex P0-2）：一版 G7 只在"删除"时失效观察；021 L3.3 的 stale（新 revision 推进 head、旧 Evidence 标 stale 未删）会让 r1 旧观察在基线失效后复活。三版：不再是当前 active head revision 即终态失效；重评前在 per-source lock 内三重复核（active/latest_revision/Evidence 非 stale）。**教训：生命周期条款必须对照相邻状态机（021）的全部状态枚举，不能只处理自己想到的转移。**
12. **事件 schema 与双方言不可变**（codex P1-3）：'一张表+折叠'没有 event_type/causation/ordering 就无法表达"同一 observation 的后续事件"；GRANT 在 sqlite 无意义——018 已有双方言触发器先例，护栏强度要对齐仓内既有最强实践而非最省事写法。三版 root+events 双表 + 触发器。
13. **三类失败语义**（codex P1-4）：一版"整事务回滚**或** fail-open 回 007"在事务语义上不成立（INSERT 失败后事务已 failed，无法继续 007；整体回滚也带走本批其他副作用）。三版分三类：计算异常写入前 fail-open / 持久化失败整 unit-of-work abort 零部分提交可重试 / 唯一键冲突按 payload 同异分幂等与 fail-closed。**教训：写"失败处理"条款时要按数据库事务真实语义走一遍状态，不能并列两个互斥出路。**

约束：文件域见页首；不改 007 权威/裁决语义（除 G1 资格内枚举）；不碰 compiler/goldenset/adapters；比较器不参考金标；送审前过 21 号自测 gauntlet（含 accept 侧红队：构造"更优值被误抑制"负例四类——新日期/高风险/absent_explicitly/并发基线变化）。
状态：**提案+规格三版定稿（codex PR #17 两轮复审收口），可认领**；**实现候 021**（规格已提出、尚未实现；018 已随 PR #9 合入 2026-07-17）。

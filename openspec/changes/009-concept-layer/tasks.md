# 009 任务（TDD 顺序；测试名引用条款号）

> 三版（2026-07-18，codex PR #12 复审收口）：T1 升级为五表+定义版本化；T2 对齐 predicate+持久排除；T4 目标图门禁；T5 Space-scoped purpose；T6 冻结投影扩展。轨道 L4 第二件（010 域段之后）。执行者 C3；概念新包 Owner=C，**概念表/冻结投影/发布接线属 knowledge 域，Owner-A 复审**。

- [ ] T1 迁移 0008 + 概念注册五表：`concepts`(UUID + (space_id,canonical_key) 唯一) / `concept_revisions`(不可变定义修订) / `concept_aliases`((space_id,alias) 唯一) / `claim_concepts`(复合 FK) / `concept_match_exclusions`——含"同名概念双 Space 各自成立""跨 Space 边被数据库拒绝（双方言）""定义修订可审计"用例 + 词表幂等导入 + LLM 候选不自动转正（C1）
- [ ] T2 概念-Claim 确定性关联：基于 `predicate`+规范化值命中 + 规则版本入边审计 + relink 全量/增量一致 + 拉黑持久生效（重启后重算不复现）（C2）
- [ ] T3 概念主页编译：定义区（取 current concept_revision）/跨产品差异表/义项索引 + **混源防护断言**（定义区无产品值、差异表逐行单源）（C3）
- [ ] T4 wikilink 互链 + 断链硬门禁**验目标快照全图**（含"引用同次发布将删除页面拒发"用例）（C4）
- [ ] T5 Purpose：Space-scoped 加载 fail-fast + 唯一注入点 + manifest 冻结 (space_id,purpose_version,digest) + 跨 Space 隔离用例（C5；涉及 compiler/prompts 组装函数重构——**不得破坏 004/006 既有 prompt 快照测试，先读再改**）
- [ ] T6 冻结投影扩展：concept_revision/绑定/页面 provenance 冻结 + read_model_version 升级（reader 先行 rollout gate）+ 回滚指针一致 + **mutable 表不可访问仍可回放** + 冻结后写入被拒（双方言）（C6）
- [ ] T7 端到端：3 产品×2 概念夹具全故事 + supersede 重编 + V1→V2→改 mutable→回滚 V1 精确复原（C6）
- [ ] T8 收尾：validation-report → HANDOFF 更新

约束：零模型调用；不改 compiler 抽取主体（仅 prompts 组装函数的 purpose 注入点）与 goldenset/adapters；迁移仅 0008（链序按注册表规则）；read_model_version 按注册表合入序取号。
状态：**已条款化，规格复审完成（PR #12 已合入，2026-07-18），按 L4 依赖顺序可认领**。依赖：007/016/018 已合入 + 010 域段（候 021）。

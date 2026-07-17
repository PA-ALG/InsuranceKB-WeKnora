# 015 反馈飞轮 · 验证报告

范围：spec `flywheel.md` 的 **unblocked 段**——F1 信号提取（T1）、F2 对齐+聚合（T2 除 ReviewItem 落地）、F3 报表+CLI 编排（T3 除 011 合流）。gated 段（ReviewItem 投影 / 009 概念词表 / 011 报告合流）显式标注、未虚报。

## 1. 门禁（deterministic lane）

```
uv run ruff check .        → All checks passed
uv run mypy src tests      → Success: 197 source files
uv run pytest -m "not live and not integration_postgres" -q
                           → 1317 passed, 5 deselected（零破坏；本变更净增 52 用例）
```

live / integration_postgres：本变更不触碰 WeKnora REST 或 PostgreSQL 专有路径，记 **NOT RUN**（无关）。零真实模型调用（F4.2）——全部识别器/对齐/编排为确定性纯规则，无网络无模型。

## 2. 条款 → 测试 溯源

| 条款 | 断言 | 测试 |
|------|------|------|
| F1.1 增量游标 | 游标后才处理、(ts,trace_id) 决胜、单调不回退、重跑不重处理 | `test_f1_1_new_traces_filters_by_cursor` / `_tiebreak_by_trace_id` / `_next_cursor_is_max` / `_rerun_processes_nothing_new` |
| F1.1 客户端 | 解析+过滤+入库即脱敏；`trust_env=False` | `test_f1_1_client_parses_filters_and_redacts` / `_default_client_trust_env_false` |
| F1.2 无引用 | 实质回答零引用→命中；有引用/拒答→不命中 | `test_f1_2_no_citation_substantive_answer_without_refs` / `_not_flagged_when_refs_present` / `_refusal_is_not_no_citation` |
| F1.2 低置信/拒答 | 拒答话术 或 score<阈值→命中；正常→否 | `test_f1_2_low_confidence_by_refusal_phrase` / `_by_score_threshold` / `_normal_answer_no_low_confidence` |
| F1.2 负反馈 | annotation 或 score≤上界→命中 | `test_f1_2_negative_feedback_by_annotation` / `_by_score` |
| F1.2 空知识 | 对齐+无 claim→命中；有 claim/无 lookup/无实体→否 | `test_f1_2_empty_knowledge_when_aligned_but_no_claim` / `_no_empty_knowledge_when_claim_exists` / `_no_empty_knowledge_without_lookup_or_entity` |
| F1.2 可启停 | 关某识别器→其信号被抑制 | `test_f1_2_disabled_recognizer_suppressed` |
| F1.3 脱敏 | 手机/证件遮蔽、业务数字保留 | `test_f1_3_redact_masks_phone` / `_masks_id_card` / `_preserves_non_pii_numbers` |
| **F2.1 对齐（对齐侧）** | 全名 exact→对齐、唯一别名→对齐、注入词表→回填 field、最长优先 | `test_f2_1_exact_name_aligns_to_product` / `_unique_alias_aligns_to_product` / `_field_name_attached_when_vocab_provided` / `_field_name_longest_match_wins` |
| **F2.1 对齐（拒绝侧 fail-safe）** | 两产品歧义→None、无产品→None（观察队列不开单） | `test_f2_1_two_products_is_ambiguous_returns_none` / `_no_product_mention_returns_none` |
| **F2.1 对齐（红队修正）** | 混合 exact+alias 跨层歧义→None、字段名产品名子串不误挂、剔除后真实字段仍命中 | `test_f2_1_mixed_exact_and_alias_two_products_returns_none` / `_field_not_attached_from_product_name_substring` / `_genuine_field_survives_product_name_scrub` / `_field_survives_when_mentioned_outside_product_name` |
| F2.2 聚合 | 稳定 ID、粒度区分、首触开单、同缺口累计不重复、异实体异缺口、样例≤5 计数不封顶 | `test_f2_2_stable_gap_key_deterministic` / `_distinguishes_granularity` / `_first_trigger_opens_gap` / `_same_gap_accumulates_not_duplicates` / `_distinct_entities_are_distinct_gaps` / `_samples_capped_at_five_but_count_unbounded` |
| F2.3 reopen | resolved 再触发→reopened；open 再触发→保持 | `test_f2_3_resolved_gap_reopens_on_retrigger` / `_open_gap_stays_open_on_retrigger` |
| F3.1 报表 | 分状态计数、TopN 降序、相对快照新增、产品分布 | `test_f3_1_report_counts_by_status` / `_top_unanswered_ordered_by_hit_count` / `_new_count_relative_to_previous_snapshot` / `_by_product_distribution` |
| **F3.3 编排** | 对齐信号入缺口、游标增量、claim_lookup 驱动空知识、忽略陈旧对齐键、自陈空知识覆盖面 | `test_f3_3_pull_aligns_signals_into_gaps` / `_respects_incoming_cursor` / `_empty_knowledge_via_claim_lookup` / `_ignores_stale_client_aligned_entity` / `_declares_empty_knowledge_coverage` |
| **F3.3 CLI** | dry-run 出报表、诚实披露空知识未评估、`--open-tickets` 受阻非零退出、dry-run 不写游标 | `test_f3_3_cli_dry_run_prints_report` / `_report_declares_empty_knowledge_not_evaluated` / `_open_tickets_is_gated_nonzero` / `_dry_run_does_not_write_cursor` |

共 **52 用例**（F1 21 · F2 18 · F3 13）。RED 均落行为断言（AssertionError，非 ImportError/mypy）：对齐/编排先以 wrong-value 骨架（`align_question` 恒 None、`run_pull` 恒空报表）建红墙再实现；提交前红队新增 7 用例亦先复现缺陷（RED）再修复。

## 3. 设计判断（详见 tasks.md 裁决记录 1–8）

- **F2.1 fail-safe（护栏成对）**：复用 003 `route_document`——candidates 仅含 exact/alias（确定性可归属），fuzzy/歧义别名进 unassigned。对齐取最强置信层（exact>alias）唯一产品，多产品/无命中→None。既测对齐侧也测 4 个拒绝分支（doc-21：只测拒绝侧或只测对齐侧都是半个护栏）。**tier-priority 的取舍**：短别名子串误命中他产品时，exact 层唯一产品仍正确对齐（比"任意 2 产品即 None"更少误伤合法单主体问题）；残余风险（exact+他产品别名同现的对比型问题）归到 exact 主体，罕见且低危，属有意识取舍。
- **F3.3 dry-run 不推进游标**：预览不改状态；游标只在真正开单（durable action）后前移。`--open-tickets` 受阻期非零退出（rc=2）+ stderr 诚实告警"未开任何单、未推进游标"，绝不静默假装成功（fail-honest，呼应 019 教训）。
- **编排 I/O 解耦**：`run_pull` 纯函数（游标+对齐+聚合+报表）与文件/DB/Langfuse I/O 解耦，纯单测 3 例；CLI 仅测渲染/退出码 glue 3 例。

## 4. 诚实边界（gated，未虚报）

| 项 | 状态 | 依赖 |
|----|------|------|
| ReviewItem(type=knowledge_gap) 落地投影（F2.2 单据） | **聚合逻辑已测，DB 投影未落** | `ensure_review_item` 的 subject 校验期望 merge 域 change_item 语义，knowledge_gap 无此形态 → 需与 knowledge 域协调新 subject（不单方改 knowledge/）。候 PR#9。CLI `--open-tickets` 已埋位、受阻非零退出。 |
| F2.1 概念级对齐（009 词表） | product/field 级已实现；concept_id 恒 None | 候 009 概念词表（PR#12） |
| CLI 路径的 empty_knowledge 信号 | **CLI 未接 claim_lookup → 该信号 CLI 路径不评估**（其余 3 类评估）；**报表自陈 `empty_knowledge_active=False` 并显式披露**（红队#3 修正），不静默少报；`run_pull`/`detect_signals` 逻辑已测（DI） | 需接 knowledge claim 后端（候 PR#9） |
| F3.1 时序指标（缺口→闭环平均周期） | 未建模 | 需 KnowledgeGap 加 first_seen/resolved_at 时间字段 |
| F3.2 与 011 健康度报告合流 | 未做 | 候 PR#12 |

## 5. 自测 gauntlet（doc-21，独立 fresh-eyes 红队 live 复现）

对 align/pull/cli 新面派发独立红队（非本作者视角），要求每条发现附 runnable 复现与实测输出。查实并修 **4 个缺陷 + 1 悬疑**，均先复现（RED）再修：

| # | 严重度 | 缺陷 | 修复 | 回归 |
|---|--------|------|------|------|
| 1 | MAJOR（值粒度上线即 CRITICAL） | 字段名是产品名子串（"养老"∈"…养老年金…"）→ 对该产品**任意**问题误挂 field，割裂产品级缺口为伪字段缺口 | 匹配字段前先剔除已命中产品名/别名整段 span（`_scrub_product_surface`）；只删整段，正文独立字段词仍保留 | `test_f2_1_field_not_attached_from_product_name_substring` +2 守卫 |
| 2 | MAJOR（对称性漏洞） | 对齐取"最强置信层再判唯一"→"A 全名(exact)+B 别名(alias)"绕过歧义误挂 A，与"两全名→None"不对称 | 改为**全部 actionable 唯一产品才对齐**（跨层），≥2 产品→None（见裁决 7） | `test_f2_1_mixed_exact_and_alias_two_products_returns_none` |
| 3 | MAJOR（诚实缺口） | empty_knowledge 在 CLI 路径静默不评估（CLI 未接 claim_lookup），报表不披露→少报 1/4 信号且不自知 | 报表自陈 `empty_knowledge_active`；CLI 显式打印"空知识未评估（未接 claim 源，其余 3 类已评估）" | `test_f3_3_pull_declares_empty_knowledge_coverage` / `test_f3_3_cli_report_declares_empty_knowledge_not_evaluated` |
| 4 | MINOR | 同长字段名以插入序任意决胜 | 改字典序确定性决胜 | 已并入对齐用例 |
| 悬疑 | — | 入站 trace 自带 `aligned_entity` 未对齐时保留 → 客户端伪造键借道触发 empty_knowledge | `run_pull` 对 `aligned_entity` 取权威：未对齐即清空 | `test_f3_3_pull_ignores_stale_client_aligned_entity` |

**红队 probed-and-cleared（实测未能攻破，存档已实际行使的护栏）**：产品级两侧护栏（无法伪造缺席产品误接、无法误拒清晰单产品）、同层多产品歧义正确→None、字段挂到 None 产品不可能（field 仅在唯一产品后计算）、空字段词表键跳过、游标 `new_count`/单调不回退、dry-run 与 gated `--open-tickets` **均不写游标**、`signal_types`/`top_unanswered`/`by_product` 确定性、无模型/网络调用。

**教训固化**：初版对齐我自认 fail-safe 且已写"护栏成对"裁决，独立红队仍 live 复现出**跨层不对称**与**产品名子串误挂**两个我没想到的洞——再次印证 doc-21：自测价值在独立 fresh-eyes + live 复现"我没想到的失败模式"，而非只测自己想到的失败路径；"半个护栏（字段侧只测了对齐、没测子串误配）比没有更危险"。

## 6. 未做（诚实，非本轮范围）

- gated 段见 §4；ReviewItem(knowledge_gap) 投影、009 概念对齐、011 报告合流、空知识 CLI 后端接线均候依赖。
- Langfuse 直连 live 拉取（F1.1 客户端已就位、`trust_env=False`）未在真实 Langfuse 上跑，记 `NOT RUN`（离线 JSONL 源已端到端验证编排）。

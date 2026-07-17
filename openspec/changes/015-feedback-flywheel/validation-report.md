# 015 反馈飞轮 · 验证报告

> 二版（2026-07-17）：codex PR #18 复审收口后重写。一版曾含与终版实现矛盾的旧设计描述
>（§3"取最强置信层"）与过度声明（"Trace 从不承载原始 PII"/"F1.1 完成"），已按实际修正——
> 漂移经过在 tasks.md 裁决 10–14 留痕。

范围：spec `flywheel/spec.md`（正式 delta）的 unblocked 段——F1.1a 离线源+游标、F1.2 信号、F1.3 脱敏（构造边界）、F2.1 对齐+观察队列、F2.2/2.3 聚合、F3.1 报表、F3.3 CLI。gated 段（F1.1b Langfuse 直连 / F2.4 ReviewItem 投影 / F3.2 011 合流 / 009 概念词表）显式标注、未虚报。

## 1. 门禁（deterministic lane，复审收口后 fresh）

```
uv run ruff check .        → All checks passed
uv run mypy src tests      → Success: 196 source files
uv run pytest -m "not live and not integration_postgres" -q
                           → 1334 passed, 5 deselected（零破坏）
openspec validate 015-feedback-flywheel --strict → valid（正式 delta）
```

live / integration_postgres：本变更不触碰 WeKnora REST 或 PostgreSQL 专有路径，记 **NOT RUN**（无关）。零真实模型调用（F4）——全部识别器/对齐/编排为确定性纯规则，无网络无模型。

## 2. 条款 → 测试 溯源（复审收口新增/修订加粗）

| 条款 | 断言 | 测试 |
|------|------|------|
| F1.1a 游标 | 游标后才处理、(ts,trace_id) 决胜、单调不回退、重跑不重处理 | `test_f1_1_new_traces_filters_by_cursor` / `_tiebreak_by_trace_id` / `_next_cursor_is_max` / `_rerun_processes_nothing_new` |
| **F1.1a 时序/去重** | 混合时区按 UTC 实际时刻序、批内同 trace_id 去重保最新、垃圾时间戳构造期拒 | `test_f1_1a_mixed_timezone_ordered_by_utc_instant` / `_same_trace_id_deduped_in_batch` / `_garbage_timestamp_rejected_at_construction` |
| F1.2 四类识别 | 各类命中/不命中/拒答不误报编造/可启停 | `test_f1_2_*`（11 例） |
| F1.3 脱敏 | 手机/证件遮蔽、业务数字保留 | `test_f1_3_redact_*`（3 例） |
| **F1.3 构造边界** | 直接构造与 JSONL 两入口均已脱敏 | `test_f1_3_trace_question_redacted_at_construction` |
| F2.1 对齐（两侧+红队） | exact/别名对齐、词表回填、跨层歧义→None、子串不误挂等 | `test_f2_1_*`（10 例，见 §5） |
| **F2.1 观察队列** | 未对齐信号保留 trace_id/脱敏问题/信号/原因明细 | `test_f2_1_pull_observations_carry_consumable_details` |
| F2.2 聚合 | 稳定 ID、累计不重复开单、异实体异缺口 | `test_f2_2_*` |
| **F2.2 最近样例/去重计数** | 最近 ≤5 滚动替换（非冻结最早）、同 trace_id 不重复计数、first/last_seen | `test_f2_2_samples_are_most_recent_five` / `_duplicate_trace_id_not_double_counted` / `_first_and_last_seen_tracked` |
| F2.3 reopen | resolved 再触发→reopened；**保 first_seen 清 resolved_at** | `test_f2_3_resolved_gap_reopens_on_retrigger` / `_open_gap_stays_open_on_retrigger` / **`_reopen_preserves_first_seen_clears_resolved_at`** |
| F3.1 报表 | 分状态计数、TopN 降序、相对快照新增、产品分布 | `test_f3_1_*` |
| **F3.1 TopN 问题/闭环周期** | TopN 携带脱敏问题样例；闭环周期可复算、无闭环显式 None | `test_f3_1_top_unanswered_carries_redacted_question` / `_avg_closure_days_from_resolved_gaps` / `_avg_closure_none_when_no_resolved` |
| F3.3 编排 | 对齐入缺口、游标增量、空知识 DI、忽略陈旧对齐键、自陈覆盖面 | `test_f3_3_pull_*` |
| **F3.3 编排（复审新增）** | 识别器关闭不虚报已评估、同批重复只计一次 | `test_f3_3_pull_empty_knowledge_inactive_when_disabled` / `_duplicate_trace_counted_once` |
| F3.3 CLI | dry-run 报表、披露空知识未评估、`--open-tickets` 受阻、不写游标 | `test_f3_3_cli_*`（既有 4 例） |
| **F3.3 CLI（复审新增）** | 缺配置 fail-closed 无 SQLite 回退、dry-run 零建库零迁移、受阻参数前置一切 I/O、space 常量响应不泄标识、`--apply` 游标+缺口状态跨周期闭环、观察队列仅 `--apply` 导出 | `test_f3_3_cli_missing_db_config_fail_closed` / `_dry_run_creates_no_db_file_no_schema` / `_open_tickets_gate_precedes_all_io` / `_missing_space_fail_closed_constant_response` / `_apply_persists_cursor_and_gaps_for_next_cycle` / `_observations_exported_only_on_apply` |

共 **69 用例**（复审收口：RED 22 → GREEN，含 codex 4 条 live 复现反例逐条转 RED）。已删除 2 个**虚构合同**测试（旧 Langfuse 客户端假设根 trace 顶层携带 Q/A，与 WeKnora 生产者实际产出不符——见裁决 10）。

## 3. 设计判断（详见 tasks.md 裁决记录 1–14）

- **F2.1 fail-safe（终版=跨层唯一，红队定案）**：candidates 仅含 exact/alias；**全部 actionable 命中唯一产品才对齐，≥2 个不同产品→None**。初版"取最强置信层（exact>alias）再判唯一"被红队复现出对称性漏洞（"A 全名+B 别名"误挂 A）后推翻——本报告一版曾残留旧描述，与裁决 7 矛盾，已修正（裁决 14）。
- **F1.3 脱敏=构造边界**：`Trace.question` before-validator，全入口一致；不依赖 adapter 调用约定（初版仅 adapter 内脱敏被 codex 反例攻破，裁决 5 修订）。
- **F3.3 dry-run=零副作用**：不写游标/状态/文件、不迁移 schema、DB 只读、缺配置 fail-closed；`--apply` 才持久化（游标+缺口状态文件+观察队列导出，跨周期状态经文件闭环）。
- **durable DB 三表随 F2.4 投影同批落地**（与 codex 提议的分歧点，裁决 13）：文件态满足现行 spec 持久化/可消费语义；DB 化与 subject 形态/事务边界是同一次域设计，不提前占号建表。

## 4. 诚实边界（gated，未虚报）

| 项 | 状态 | 依赖 |
|----|------|------|
| F1.1b Langfuse 直连 | **未做**（虚构合同旧客户端已删除） | WeKnora 生产者合同组装（observation+named scores+分页/退避）+ citation 合同 SDD 裁决（owner 级）+ sanitized fixture |
| F2.4 ReviewItem(knowledge_gap) 投影 + durable DB 存储 | 聚合逻辑已测；投影/DB 未落 | **PR#9 已合入（2026-07-17）**；剩余依赖=knowledge_gap subject 形态与域主协调（不单方改 knowledge/） |
| F2.1 概念级对齐（009 词表） | product/field 级已实现；concept_id 恒 None | 候 009 概念词表（PR#12） |
| CLI 路径 empty_knowledge 信号 | CLI 未接 claim_lookup → 不评估且**报表自陈**；逻辑已测（DI） | 需接 knowledge claim 后端 |
| F3.2 与 011 健康度报告合流 | 未做 | 候 PR#12 |

## 5. 自测 gauntlet 与外部复审（doc-21）

**第一轮（提交前红队，2026-07-16）**：独立 fresh-eyes 红队 live 复现修 4+1（产品名子串误挂、跨层歧义绕过、空知识覆盖面静默、同长字段任意决胜、陈旧 aligned_entity 借道）——详表见 git 历史一版报告，测试全部保留。

**第二轮（codex PR#18 外部复审，2026-07-17）**：5 阻断+3 High，独立复核后核心全部属实：

| # | 缺陷（live 复现） | 修复 |
|---|------|------|
| B1 | 旧 Langfuse 客户端消费**虚构合同**（WeKnora 根 trace 无 Q/A→真实数据产垃圾信号） | 删除客户端+虚构测试；直连转 gated F1.1b（合同前置） |
| B2 | 裸字符串时序/批内不去重/样例冻结最早 5/无游标写入路径 | UTC 语义时序+构造期校验；批内+聚合双去重；最近 5 滚动；`--apply` 持久化 |
| B3 | dry-run 建库+迁移；缺配置静默回退 SQLite；受阻参数晚校验 | 零副作用 dry-run；fail-closed；gate 前置一切 I/O |
| B4 | 观察队列只有计数；CLI 无跨周期状态；TopN 输出内部 key；无闭环周期 | 队列明细+导出；gaps-file 闭环；TopN 带脱敏问题；first_seen/resolved_at 周期 |
| B5 | JSONL 入口 PII 直通（"从不承载原始 PII"声明不成立） | 脱敏上移构造边界（before-validator） |
| H1 | openspec strict FAIL（无正式 delta） | 转正式 delta spec，strict 通过 |
| H2 | 识别器关闭仍报 `empty_knowledge_active=True` | `config.empty_knowledge and claim_lookup is not None` |
| H3 | 文档漂移（旧设计描述残留/候 PR#9 过时/完成度过度声明） | 本报告重写；tasks 状态重标；裁决 10–14 留痕 |

**教训固化（两轮叠加）**：第一轮红队修完自认收口，外部复审仍再抓 8 项真伤——其中"虚构合同"与"声明与实现漂移"是我红队没有的视角（红队测的是我写的代码内部一致性，codex 对照的是**外部真实生产者与规格文本**）。固化：自测 gauntlet 须含"对照真实上游合同/规格字面"一步，不能只测代码自洽。

## 6. 未做（诚实，非本轮范围）

- gated 段见 §4：F1.1b 直连、F2.4 投影+DB 三表、009 概念对齐、011 合流、空知识 CLI 后端接线。
- Langfuse live 拉取无从谈起（直连未做），记 `NOT RUN`；离线 JSONL 源已端到端验证（含 `--apply` 跨周期闭环）。

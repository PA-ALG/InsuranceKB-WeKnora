# 任务

按 specs 逐条落 pytest（测试名引用条款号 F1~F4），TDD 实现至门禁全绿；validation-report + HANDOFF 更新收尾。零真实模型调用；新包 `harness/src/insurance_harness/flywheel/`。

## 依赖门控（诚实标注——不预支未合入的域；2026-07-17 复审后修订）

- **T1（F1 信号提取）＝部分 gated**：识别器/脱敏/游标自包含；空知识信号用注入式 claim_lookup（DI），不硬依赖 knowledge。**F1.1b Langfuse 直连 gated**：WeKnora 生产者根 trace 无 Q/A（在 chat.completion 子 observation），直连须先落组装合同 + citation 合同 SDD 裁决（spec F1.1b）。
- **T2（F2 对齐开单）＝部分 gated**：003 产品路由器**可用**；009 概念词表候 PR #12；`ReviewItem(type=knowledge_gap)` 投影（F2.4）——**PR #9 已合入（2026-07-17），剩余依赖是 knowledge_gap subject 形态与域主协调**（`_require_scoped_review_subject` 期望 change_item 语义，不单方改 knowledge/）。
- **T3（F3 报表 CLI）＝部分 gated**：报表/CLI 自包含；011 报告合流候 PR #12。

## 任务

- [~] **T1 · F1 信号提取器**（离线段完成；直连 gated）
  - [x] F1.2 四类识别器（可配置启停）+ "拒答不误报为编造"判别；F1.3 证件→手机→保单号顺序脱敏（业务数字保留）——**脱敏为 Trace 构造边界**（before-validator，全入口一致；复审收口）；F1.1a 增量游标（UTC 语义时序 + 批内去重 + (ts,trace_id) 决胜/幂等/单调；持久化经 CLI `--apply` 写游标文件）。
  - [ ] F1.1b Langfuse 直连（gated）：按 WeKnora 生产者合同组装根 trace+observations+named scores、完整分页/退避、citation 合同裁决——**合同 fixture 验证前不提供直连**（虚构合同的旧客户端已删除）。
- [~] **T2 · F2 对齐与开单**（对齐+聚合核心完成；ReviewItem 落地段 gated）
  - [x] F2.2/F2.3 **缺口聚合核心**（`gaps.py`，纯逻辑 unblocked）：稳定 ID、hit_count 累计（同 trace_id 不重复计数）、**最近**样例≤5（滚动替换）+ 平行脱敏问题样例、first_seen/last_seen/resolved_at（reopen 保 first_seen 清 resolved_at）、幂等不重复开单、resolve→reopened。
  - [x] F2.1 产品级对齐（复用 003 路由器）（`align.py`，unblocked）：question 当单页文档路由；candidates 只含 exact/alias（可归属），fuzzy/歧义进 unassigned；全部 actionable 唯一产品→对齐，≥2 产品/无命中→None（观察队列不开单，fail-safe）；字段级先剔除产品名表面串再注入词表匹配；概念级候 009。**10 用例（护栏成对：对齐侧+拒绝侧+2 红队用例）**。
  - [x] F2.1 **观察队列可消费**（复审收口）：未对齐信号保留 trace_id/脱敏问题/信号类型/原因（no_actionable_match|multi_product_ambiguity）明细，`--apply --observations-out` 可导出 JSONL 供人工归属——不再只留计数丢明细。
  - [ ] F2.4 ReviewItem(type=knowledge_gap) 投影：`ensure_review_item` 收自由 type_ 但 `_require_scoped_review_subject` 期望 change_item 语义；knowledge_gap 无 change_item → **需 knowledge 域协调新 subject 形态**（边界，不单方改 knowledge/）。**PR#9 已合入（2026-07-17），此项剩余依赖=subject 设计协调**。CLI `--open-tickets` 已埋位，受阻期非零退出不假装开单；durable DB 缺口存储随本投影同批落地（见裁决 13）。
- [~] **T3 · F3 报表与 CLI**（报表+CLI 编排完成；011 合流 pending）
  - [x] F3.1 **报表核心**（`report.py`，unblocked）：分状态计数 + TopN 答不上（**输出脱敏问题样例**，非仅内部 key）+ 新增 + **闭环平均周期**（first_seen/resolved_at，可复算；无已闭环缺口显式 None 不虚报）+ 产品分布。
  - [x] F3.3 CLI `flywheel pull`（`pull.py` 纯编排 + `cli.py` I/O）：编排 F1(游标+信号)→F2(对齐+聚合)→F3(报表)；默认 dry-run **零副作用**（不写游标/状态/文件、不迁移 schema、DB 只读）；缺 DB 配置 **fail-closed**（无 SQLite 回退）；`--open-tickets` 在一切 I/O 前受阻退出；`--apply` 持久化游标+缺口状态文件（跨周期累计/reopened：上轮输出=下轮输入）+ 观察队列导出；space 校验 fail-closed 常量响应不泄标识。
  - [ ] F3.2 与 011 健康度报告合流：候 PR#12。
- [ ] **T4 · 收尾**：validation-report（条款→测试名 + 依赖门控清单）+ HANDOFF B17。

## 裁决记录（设计判断及依据）

1. **RED 落行为断言（doc-21）**：所有识别器/聚合用 wrong-value 骨架（非 NotImplementedError），红墙 13+5 条全是 AssertionError，非 ImportError/mypy。
2. **F1 不硬依赖 knowledge**：空知识信号用注入式 `claim_lookup`（DI），F1 完全自包含可测；对齐在 F2 回填 `aligned_entity`。
3. **游标 (timestamp, trace_id) 二元决胜**：同 timestamp 多 trace 时以 trace_id 稳定决胜，避免漏/重处理；游标单调不回退。
4. **缺口聚合与 ReviewItem 投影解耦**：聚合（稳定 ID/计数/样例/reopen）是纯 flywheel 逻辑，unblocked 且可测；ReviewItem 落地是**独立的 knowledge 域投影**——`ensure_review_item` 虽收自由 type_，但 subject 校验期望 merge 域 change_item，knowledge_gap 无此语义，故不单方改 knowledge/，留待与域主协调新 subject 形态（硬边界：对 knowledge/ 只经服务层且不擅改契约）。
5. **脱敏是构造边界（2026-07-17 复审修订）**：初版只在 Langfuse 适配器 `_to_trace` 调 `redact_pii`——codex 反例证实 JSONL 入口直通原始手机号，"Trace 从不承载原始 PII"当时不成立。修订：`Trace.question` 加 before-validator，脱敏在**模型构造边界**（任何入口一致，不依赖 adapter 调用约定）；业务数字（位数少）不被长数字串规则误遮。
6. **报表诚实边界**：时序类指标（缺口→闭环平均周期）需 first_seen/resolved_at 时间字段，本版未建模，validation-report 显式标注不虚报。
7. **F2.1 对齐 fail-safe（护栏成对，经提交前红队修正）**：复用 003 `route_document`——candidates 只含 exact/alias，fuzzy/歧义别名进 unassigned。对齐规则（**终版**）：**全部 actionable 命中唯一产品才对齐，≥2 个不同产品→None**，无 candidates→None。初版按"取最强置信层（exact>alias）再判唯一"，红队 live 复现出其对称性漏洞——"A 全名(exact)+B 别名(alias)"会绕过歧义误挂 A，而"两个全名→None"，同一语义因表面形式不同而结果不对称；因产品别名是产品专属（非通用词）我先前顾虑的误拒风险可忽略，故改为跨层唯一，更对称更 fail-safe。字段级：先**剔除已命中的产品名/别名表面串**再用注入词表匹配（否则字段名是产品名子串时——如"养老"∈"…养老年金…"——会对该产品任意问题误挂字段，红队#1 复现）；剔除只删整段 span，正文里独立出现的字段词仍保留可命中。同长字段以字典序确定性决胜。测试覆盖对齐侧+拒绝侧（含跨层歧义、产品名子串两个红队用例）。概念级候 009 → concept_id 恒 None。
8. **F3.3 dry-run 不推进游标 + `--open-tickets` 受阻不假装**：dry-run 是预览，预览不改状态——故默认路径**不写游标文件**（下轮可复现同报表），游标只在真正开单（durable action）后才前移。`--open-tickets` 投影候 PR#9+域协调，受阻期**非零退出（rc=2）+ stderr 诚实告警"未开任何单、未推进游标"**，绝不静默假装成功（fail-honest，呼应 019 教训）。编排核心 `run_pull` 与 I/O 解耦以便纯单测，CLI 仅测渲染/退出码 glue。`run_pull` 对 `aligned_entity` 取权威：对齐→gap_key，未对齐→清空（忽略入站陈旧键，防客户端伪造键借道触发 empty_knowledge）。
9. **提交前 gauntlet（doc-21，独立 fresh-eyes 红队 live 复现）**：对 align/pull/cli 新面派红队探两侧护栏/跨层歧义/游标/CLI 健壮性并 live 复现。查实并修 4+1：**#1** 字段名是产品名子串→误挂字段（MAJOR，值粒度上线即 CRITICAL）→表面串剔除；**#2** 混合 exact+alias 绕过歧义（MAJOR 对称性漏洞）→跨层唯一（见裁决 7）；**#3** 空知识信号 CLI 路径静默不评估（MAJOR 诚实缺口）→报表自陈 `empty_knowledge_active` + CLI 显式披露"未接 claim 源，其余 3 类已评估"；**#4** 同长字段任意决胜（MINOR）→字典序；**悬疑**（入站陈旧 aligned_entity 借道触发空知识）→run_pull 取权威清空。红队 probed-and-cleared 存档：产品级两侧护栏、同层多产品歧义、字段挂空产品不可能、游标单调不回退、dry-run/gated 均不写游标、确定性零模型。**+7 用例（共 52），全量 1317 passed 零破坏**。教训：初版对齐逻辑我自认 fail-safe 并写了"护栏成对"裁决，红队仍复现出跨层不对称与子串误挂两个我没想到的洞——印证"自测要独立 fresh-eyes + live 复现，而非只测自己想到的失败模式"。

### codex PR #18 复审收口（2026-07-17，执行者=Claude 架构会话，worktree `ikb-015`）

codex 出 **Request changes**（5 阻断 + 3 High）。第一性原理独立复核：核心全部属实（4 条反例 live 复现、Go 生产者合同/文档漂移静态核实），按其建议顺序 spec→RED→GREEN 返工。**RED 22 → GREEN 69**；全量 deterministic **1334 passed**（零破坏）。

10. **Langfuse 直连降级为 gated（阻断1 裁决）**：核实 `internal/tracing/langfuse/middleware.go`——根 trace 无 Input、`Finish` 只写 `{"status": code}`，问答在 `chat.completion(.stream)` 子 observation。旧 `langfuse_client.py` 归一化的是**虚构合同**（真实数据下 question=''、answer="{'status':200}"、产垃圾 no_citation）→ **整体删除**（含其 2 个虚构合同测试），取 codex 给的 de-scope 路径。直连回归条件已写入 spec F1.1b（observation 组装 + named scores + 完整分页/退避 + citation 合同 SDD 裁决 + sanitized fixture）；citation 合同涉及"是否给 WeKnora 平台级 trace 增加脱敏 citation 摘要"（Go 侧改动）——owner 级裁决，不在本 PR 单方定。
11. **时序语义与去重（阻断2 裁决）**：游标比较改 timezone-aware UTC（无时区视为 UTC；垃圾时间戳 Trace 构造期即拒）；同批同 trace_id 去重保最新；聚合器 (gap_key, trace_id) 实例内守卫不重复计数（跨轮由游标保证）；样例改**最近 ≤5** 滚动（spec F2.2 字面语义）。**迟到数据 lookback/429 退避**属直连 live 关切，随 F1.1b 落地。
12. **CLI 收紧（阻断3 裁决）**：dry-run 零副作用（去自动 migrate——迁移属部署流程；sqlite 目标不存在即 fail-closed 防隐式建库；schema 缺失诚实非零）；缺 DB 配置 fail-closed **去 SQLite 回退**（飞轮是企业多租户运维命令，隐式本地库无意义——与 product/cli bootstrap 工具场景不同，不强行一致）；`--open-tickets` 校验前置到一切 I/O 之前。
13. **durable 存储走文件态，DB 三表随 F2.4 投影同批落地（阻断4 裁决，与 codex 方案分歧点）**：codex 提议即刻占 migration 0010 建 flywheel 三表（checkpoints/observations/gaps）。裁决：**本 PR 用文件态闭环**——游标文件 + 缺口状态文件（跨周期累计/reopened：上轮输出=下轮输入）+ 观察队列导出，满足现行 spec 的持久化与可消费语义且保持 dry-run 优先的运维形态；**DB 化与 ReviewItem 投影是同一次域设计**（subject 形态 + 表 + 事务边界一起定，避免先建表后返工），随 F2.4 落地时正式占号迁移。此为有意识取舍，codex 可在复核中挑战。
14. **诚实声明修正（High-3）**：validation-report §3 曾残留被红队推翻的"取最强置信层"旧设计描述（正文与裁决 7 矛盾）→ 改为跨层唯一终版；"候 PR#9" 全部改为"PR#9 已合入，剩余依赖=subject 设计"；F1.1/F3.1 完成度按实际重标。

约束：不改 WeKnora；新 HTTP 客户端 `trust_env=False`；批量开单默认 dry-run（`--open-tickets` 才落单）；问题原文脱敏后才入库；送审前过 21 号自测 gauntlet。
状态：**T1 完成 + T2/T3 全部 unblocked 段完成 + 提交前红队自测收口（2026-07-17）**——F1 信号提取 / F2 缺口聚合+F2.1 对齐 / F3.1 报表 + F3.3 编排与 CLI，经独立红队 live 复现修 4+1 个缺陷后共 **52 用例**绿，全量 **1317 passed 零破坏**，mypy 197 文件 + ruff 全绿。剩余仅 gated 段：ReviewItem(knowledge_gap) 投影候 PR#9 + 域协调（CLI `--open-tickets` 已埋位、受阻非零退出）；009 概念对齐 / 011 报告合流候 PR#12；空知识信号 CLI 路径需 claim 后端（报表已自陈未评估）。依赖：007/003 已交付。

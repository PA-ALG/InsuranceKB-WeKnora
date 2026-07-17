# 任务

按 specs 逐条落 pytest（测试名引用条款号 F1~F4），TDD 实现至门禁全绿；validation-report + HANDOFF 更新收尾。零真实模型调用；新包 `harness/src/insurance_harness/flywheel/`。

## 依赖门控（诚实标注——不预支未合入的域）

- **T1（F1 信号提取）＝unblocked**：识别器/脱敏/游标自包含；空知识信号用注入式 claim_lookup（DI），不硬依赖 knowledge。
- **T2（F2 对齐开单）＝部分 gated**：003 产品路由器**可用**；009 概念词表候 PR #12；`ReviewItem(type=knowledge_gap)` 候 018/021（PR #9）——先落对齐+开单**接口与幂等逻辑**（对 ReviewItem 走服务层接口），knowledge 落地段候依赖。
- **T3（F3 报表 CLI）＝部分 gated**：报表/CLI 自包含；011 报告合流候 PR #12。

## 任务

- [x] **T1 · F1 信号提取器**（unblocked，完成）
  - F1.2 四类识别器（可配置启停）+ "拒答不误报为编造"判别；F1.3 证件→手机→保单号顺序脱敏（业务数字保留）；F1.1 Langfuse 客户端 `trust_env=False` + 增量游标（(ts,trace_id) 决胜/幂等/单调）。**21 用例；commit 4c7b321**。
- [~] **T2 · F2 对齐与开单**（对齐+聚合核心完成；ReviewItem 落地段 gated）
  - [x] F2.2/F2.3 **缺口聚合核心**（`gaps.py`，纯逻辑 unblocked）：稳定 ID、hit_count 累计、样例≤5、幂等不重复开单、resolve→reopened。**8 用例**。
  - [x] F2.1 产品级对齐（复用 003 路由器）（`align.py`，unblocked）：question 当单页文档路由；candidates 只含 exact/alias（可归属），fuzzy/歧义进 unassigned；全部 actionable 唯一产品→对齐，≥2 产品/无命中→None（观察队列不开单，fail-safe）；字段级先剔除产品名表面串再注入词表匹配；概念级候 009。**10 用例（护栏成对：对齐侧+拒绝侧+2 红队用例）**。
  - [ ] ReviewItem(type=knowledge_gap) 投影：`ensure_review_item` 收自由 type_ 但 `_require_scoped_review_subject` 期望 change_item 语义；knowledge_gap 无 change_item → **需 knowledge 域协调新 subject 形态**（边界，不单方改 knowledge/），候 PR#9 后与域主协商。CLI `--open-tickets` 已埋位，受阻期非零退出不假装开单。
- [~] **T3 · F3 报表与 CLI**（报表+CLI 编排完成；011 合流 pending）
  - [x] F3.1 **报表核心**（`report.py`，unblocked）：分状态计数 + TopN 答不上 + 新增 + 产品分布。**4 用例**。（时序"闭环平均周期"需 first_seen/resolved_at 时间字段，随扩展补齐——诚实边界。）
  - [x] F3.3 CLI `flywheel pull`（`pull.py` 纯编排 + `cli.py` I/O，unblocked）：编排 F1(游标+信号)→F2(对齐+聚合)→F3(报表)；默认 dry-run 只出报表、不推进游标（预览不改状态）；`--open-tickets` 受阻→非零退出诚实告警不开单；空知识未接 claim 源时报表自陈未评估。**9 用例（5 编排 + 4 CLI glue）**。
  - [ ] F3.2 与 011 健康度报告合流：候 PR#12。
- [ ] **T4 · 收尾**：validation-report（条款→测试名 + 依赖门控清单）+ HANDOFF B17。

## 裁决记录（设计判断及依据）

1. **RED 落行为断言（doc-21）**：所有识别器/聚合用 wrong-value 骨架（非 NotImplementedError），红墙 13+5 条全是 AssertionError，非 ImportError/mypy。
2. **F1 不硬依赖 knowledge**：空知识信号用注入式 `claim_lookup`（DI），F1 完全自包含可测；对齐在 F2 回填 `aligned_entity`。
3. **游标 (timestamp, trace_id) 二元决胜**：同 timestamp 多 trace 时以 trace_id 稳定决胜，避免漏/重处理；游标单调不回退。
4. **缺口聚合与 ReviewItem 投影解耦**：聚合（稳定 ID/计数/样例/reopen）是纯 flywheel 逻辑，unblocked 且可测；ReviewItem 落地是**独立的 knowledge 域投影**——`ensure_review_item` 虽收自由 type_，但 subject 校验期望 merge 域 change_item，knowledge_gap 无此语义，故不单方改 knowledge/，留待与域主协调新 subject 形态（硬边界：对 knowledge/ 只经服务层且不擅改契约）。
5. **脱敏在归一化时施加**：Trace 从不承载原始 PII（`_to_trace` 内即 `redact_pii`），比"入库时才脱敏"更安全；业务数字（位数少）不被长数字串规则误遮。
6. **报表诚实边界**：时序类指标（缺口→闭环平均周期）需 first_seen/resolved_at 时间字段，本版未建模，validation-report 显式标注不虚报。
7. **F2.1 对齐 fail-safe（护栏成对，经提交前红队修正）**：复用 003 `route_document`——candidates 只含 exact/alias，fuzzy/歧义别名进 unassigned。对齐规则（**终版**）：**全部 actionable 命中唯一产品才对齐，≥2 个不同产品→None**，无 candidates→None。初版按"取最强置信层（exact>alias）再判唯一"，红队 live 复现出其对称性漏洞——"A 全名(exact)+B 别名(alias)"会绕过歧义误挂 A，而"两个全名→None"，同一语义因表面形式不同而结果不对称；因产品别名是产品专属（非通用词）我先前顾虑的误拒风险可忽略，故改为跨层唯一，更对称更 fail-safe。字段级：先**剔除已命中的产品名/别名表面串**再用注入词表匹配（否则字段名是产品名子串时——如"养老"∈"…养老年金…"——会对该产品任意问题误挂字段，红队#1 复现）；剔除只删整段 span，正文里独立出现的字段词仍保留可命中。同长字段以字典序确定性决胜。测试覆盖对齐侧+拒绝侧（含跨层歧义、产品名子串两个红队用例）。概念级候 009 → concept_id 恒 None。
8. **F3.3 dry-run 不推进游标 + `--open-tickets` 受阻不假装**：dry-run 是预览，预览不改状态——故默认路径**不写游标文件**（下轮可复现同报表），游标只在真正开单（durable action）后才前移。`--open-tickets` 投影候 PR#9+域协调，受阻期**非零退出（rc=2）+ stderr 诚实告警"未开任何单、未推进游标"**，绝不静默假装成功（fail-honest，呼应 019 教训）。编排核心 `run_pull` 与 I/O 解耦以便纯单测，CLI 仅测渲染/退出码 glue。`run_pull` 对 `aligned_entity` 取权威：对齐→gap_key，未对齐→清空（忽略入站陈旧键，防客户端伪造键借道触发 empty_knowledge）。
9. **提交前 gauntlet（doc-21，独立 fresh-eyes 红队 live 复现）**：对 align/pull/cli 新面派红队探两侧护栏/跨层歧义/游标/CLI 健壮性并 live 复现。查实并修 4+1：**#1** 字段名是产品名子串→误挂字段（MAJOR，值粒度上线即 CRITICAL）→表面串剔除；**#2** 混合 exact+alias 绕过歧义（MAJOR 对称性漏洞）→跨层唯一（见裁决 7）；**#3** 空知识信号 CLI 路径静默不评估（MAJOR 诚实缺口）→报表自陈 `empty_knowledge_active` + CLI 显式披露"未接 claim 源，其余 3 类已评估"；**#4** 同长字段任意决胜（MINOR）→字典序；**悬疑**（入站陈旧 aligned_entity 借道触发空知识）→run_pull 取权威清空。红队 probed-and-cleared 存档：产品级两侧护栏、同层多产品歧义、字段挂空产品不可能、游标单调不回退、dry-run/gated 均不写游标、确定性零模型。**+7 用例（共 52），全量 1317 passed 零破坏**。教训：初版对齐逻辑我自认 fail-safe 并写了"护栏成对"裁决，红队仍复现出跨层不对称与子串误挂两个我没想到的洞——印证"自测要独立 fresh-eyes + live 复现，而非只测自己想到的失败模式"。

约束：不改 WeKnora；新 HTTP 客户端 `trust_env=False`；批量开单默认 dry-run（`--open-tickets` 才落单）；问题原文脱敏后才入库；送审前过 21 号自测 gauntlet。
状态：**T1 完成 + T2/T3 全部 unblocked 段完成 + 提交前红队自测收口（2026-07-17）**——F1 信号提取 / F2 缺口聚合+F2.1 对齐 / F3.1 报表 + F3.3 编排与 CLI，经独立红队 live 复现修 4+1 个缺陷后共 **52 用例**绿，全量 **1317 passed 零破坏**，mypy 197 文件 + ruff 全绿。剩余仅 gated 段：ReviewItem(knowledge_gap) 投影候 PR#9 + 域协调（CLI `--open-tickets` 已埋位、受阻非零退出）；009 概念对齐 / 011 报告合流候 PR#12；空知识信号 CLI 路径需 claim 后端（报表已自陈未评估）。依赖：007/003 已交付。

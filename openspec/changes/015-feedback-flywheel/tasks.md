# 任务

按 specs 逐条落 pytest（测试名引用条款号 F1~F4），TDD 实现至门禁全绿；validation-report + HANDOFF 更新收尾。零真实模型调用；新包 `harness/src/insurance_harness/flywheel/`。

## 依赖门控（诚实标注——不预支未合入的域）

- **T1（F1 信号提取）＝unblocked**：识别器/脱敏/游标自包含；空知识信号用注入式 claim_lookup（DI），不硬依赖 knowledge。
- **T2（F2 对齐开单）＝部分 gated**：003 产品路由器**可用**；009 概念词表候 PR #12；`ReviewItem(type=knowledge_gap)` 候 018/021（PR #9）——先落对齐+开单**接口与幂等逻辑**（对 ReviewItem 走服务层接口），knowledge 落地段候依赖。
- **T3（F3 报表 CLI）＝部分 gated**：报表/CLI 自包含；011 报告合流候 PR #12。

## 任务

- [x] **T1 · F1 信号提取器**（unblocked，完成）
  - F1.2 四类识别器（可配置启停）+ "拒答不误报为编造"判别；F1.3 证件→手机→保单号顺序脱敏（业务数字保留）；F1.1 Langfuse 客户端 `trust_env=False` + 增量游标（(ts,trace_id) 决胜/幂等/单调）。**21 用例；commit 4c7b321**。
- [~] **T2 · F2 对齐与开单**（聚合核心完成；对齐/开单段 gated）
  - [x] F2.2/F2.3 **缺口聚合核心**（`gaps.py`，纯逻辑 unblocked）：稳定 ID、hit_count 累计、样例≤5、幂等不重复开单、resolve→reopened。**8 用例**。
  - [ ] F2.1 产品级对齐（复用 003 路由器）：question→AlignedEntity——003 路由器为文档向，需薄适配（下一步）。
  - [ ] ReviewItem(type=knowledge_gap) 投影：`ensure_review_item` 收自由 type_ 但 `_require_scoped_review_subject` 期望 change_item 语义；knowledge_gap 无 change_item → **需 knowledge 域协调新 subject 形态**（边界，不单方改 knowledge/），候 PR#9 后与域主协商。
- [~] **T3 · F3 报表与 CLI**（报表核心完成；CLI/合流 pending）
  - [x] F3.1 **报表核心**（`report.py`，unblocked）：分状态计数 + TopN 答不上 + 新增 + 产品分布。**4 用例**。（时序"闭环平均周期"需 first_seen/resolved_at 时间字段，随扩展补齐——诚实边界。）
  - [ ] F3.3 CLI `flywheel pull`（dry-run/`--open-tickets`）：编排 F1→F2→F3，下一步；F3.2 与 011 报告合流候 PR#12。
- [ ] **T4 · 收尾**：validation-report（条款→测试名 + 依赖门控清单）+ HANDOFF B17。

## 裁决记录（设计判断及依据）

1. **RED 落行为断言（doc-21）**：所有识别器/聚合用 wrong-value 骨架（非 NotImplementedError），红墙 13+5 条全是 AssertionError，非 ImportError/mypy。
2. **F1 不硬依赖 knowledge**：空知识信号用注入式 `claim_lookup`（DI），F1 完全自包含可测；对齐在 F2 回填 `aligned_entity`。
3. **游标 (timestamp, trace_id) 二元决胜**：同 timestamp 多 trace 时以 trace_id 稳定决胜，避免漏/重处理；游标单调不回退。
4. **缺口聚合与 ReviewItem 投影解耦**：聚合（稳定 ID/计数/样例/reopen）是纯 flywheel 逻辑，unblocked 且可测；ReviewItem 落地是**独立的 knowledge 域投影**——`ensure_review_item` 虽收自由 type_，但 subject 校验期望 merge 域 change_item，knowledge_gap 无此语义，故不单方改 knowledge/，留待与域主协调新 subject 形态（硬边界：对 knowledge/ 只经服务层且不擅改契约）。
5. **脱敏在归一化时施加**：Trace 从不承载原始 PII（`_to_trace` 内即 `redact_pii`），比"入库时才脱敏"更安全；业务数字（位数少）不被长数字串规则误遮。
6. **报表诚实边界**：时序类指标（缺口→闭环平均周期）需 first_seen/resolved_at 时间字段，本版未建模，validation-report 显式标注不虚报。

约束：不改 WeKnora；新 HTTP 客户端 `trust_env=False`；批量开单默认 dry-run（`--open-tickets` 才落单）；问题原文脱敏后才入库；送审前过 21 号自测 gauntlet。
状态：**T1 完成 + T2/T3 unblocked 核心完成（2026-07-17）**——F1 信号提取 / F2 缺口聚合 / F3.1 报表共 33 用例绿，全量 1298 passed 零破坏。剩余：F2.1 对齐适配（003）+ CLI 编排（unblocked，下一步）；ReviewItem 投影候 PR#9 + 域协调；009 概念对齐 / 011 报告合流候 PR#12。依赖：007/003 已交付。

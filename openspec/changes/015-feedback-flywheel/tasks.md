# 任务

按 specs 逐条落 pytest（测试名引用条款号 F1~F4），TDD 实现至门禁全绿；validation-report + HANDOFF 更新收尾。零真实模型调用；新包 `harness/src/insurance_harness/flywheel/`。

## 依赖门控（诚实标注——不预支未合入的域）

- **T1（F1 信号提取）＝unblocked**：识别器/脱敏/游标自包含；空知识信号用注入式 claim_lookup（DI），不硬依赖 knowledge。
- **T2（F2 对齐开单）＝部分 gated**：003 产品路由器**可用**；009 概念词表候 PR #12；`ReviewItem(type=knowledge_gap)` 候 018/021（PR #9）——先落对齐+开单**接口与幂等逻辑**（对 ReviewItem 走服务层接口），knowledge 落地段候依赖。
- **T3（F3 报表 CLI）＝部分 gated**：报表/CLI 自包含；011 报告合流候 PR #12。

## 任务

- [ ] **T1 · F1 信号提取器**（unblocked）
  - F1.2 四类识别器（纯规则，可配置启停）：无引用回答 / 低置信·拒答 / 负反馈 / 空知识命中（后者注入 claim_lookup）；RED 落**行为断言**（骨架先行，doc-21）。
  - F1.3 PII 脱敏：手机/证件/保单号正则遮蔽，原文不落库只留 trace_id；脱敏在识别**之后**、入库**之前**。
  - F1.1 Langfuse 客户端：`trust_env=False`（坑 #9）+ 增量游标持久化（重跑不重复处理同 trace）；HTTP 以 fake transport 测。
- [ ] **T2 · F2 对齐与开单**（部分 gated）：003 产品级对齐 + 稳定 ID 幂等 hit_count + reopened 语义（接口层）；概念级/ReviewItem 落地候 009/PR#9。
- [ ] **T3 · F3 报表与 CLI**（部分 gated）：周期报告 + `flywheel pull` dry-run/`--open-tickets`；011 合流候 PR#12。
- [ ] **T4 · 收尾**：validation-report（条款→测试名 + 依赖门控清单）+ tasks 裁决记录 + HANDOFF B17。

约束：不改 WeKnora；新 HTTP 客户端 `trust_env=False`；批量开单默认 dry-run（`--open-tickets` 才落单）；问题原文脱敏后才入库；送审前过 21 号自测 gauntlet。
状态：**T1 开工（2026-07-17）**；T2/T3 依赖段候 PR #9/#12。依赖：007 已合入、003 已交付。

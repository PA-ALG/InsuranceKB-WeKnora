# 015 · 数据飞轮：Langfuse 问答信号 → 知识缺口工单

> 状态：实施中（2026-07-18，PR #18 codex 接管收口）。离线 trace foundation 可实施；
> Langfuse 直连须以真实 WeKnora observation/citation 合同为前置，合同就绪前 fail-closed。
> 补上"可进化"的主动半环：系统自己发现"答不好/答不上"，回流成知识工单。设计权威：01 §1#4（发现问题慢的痛点）、13 §2 G6 前置。

## 为什么做

被动进化（新材料→合并更新）007 已通；主动进化需要信号：哪些问题回答置信低、没有引用、被用户点踩、答不上来。WeKnora 当前把根 trace 与问答 completion/retrieve observation 分开上报，且没有可直接消费的答案 citation 字段；因此本 change 先交付归一化离线 trace → durable 飞轮闭环，直连必须等待真实生产者/citation 合同，不基于虚构根 trace 字段实现。

## 做什么

1. **信号提取器**（`harness/src/insurance_harness/flywheel/`，定时任务）：消费经合同归一化的离线问答 trace，规则识别四类信号；Langfuse 直连 gated——
   - 无引用回答（回答无 source_refs/chunk 引用 → 疑似编造或知识缺失）；
   - 低置信/拒答（"无法回答/没有找到"模式 + score 字段）；
   - 用户负反馈（Langfuse score/annotation，若前端已上报）；
   - 高频问题聚类中命中知识库为空的（问题实体对齐到产品/概念后查无 published Claim）；
2. **信号→durable 缺口**：实体对齐（复用 003/009 对齐器）→ 定位到 (product, field/concept) 粒度 → 以 Space-scoped 数据库 observation/gap/checkpoint 单事务聚合，重试 exactly-once；ReviewItem 投影候 knowledge_gap 动作合同定稿后接入，不生成点击即失败的假工单；
3. **回流路径**：缺口工单在 008 工作台展示（按触发次数排序）→ 处理动作：补材料重编（挂 004 管道）/人工补录（走审核）/标注"知识库外问题"（拒答口径归档）；
4. **飞轮报表**：周期报告——新增缺口/已闭环缺口/答不上 TopN 问题/缺口→补齐的平均周期（这就是"知识更新滞后"痛点的量化改善指标）；
5. 隐私与合规：问题文本脱敏规则（手机号/证件号正则遮蔽）后才入库。

## 验收

归一化夹具 trace（四类信号各 ≥2）→ 提取、对齐、Space 隔离、数据库原子持久化/重试 exactly-once、计数聚合、报表正确；对齐不到实体的进入可查询观察队列且不误开单。零模型调用。真实 PostgreSQL 双会话同源并发为独立门禁；Langfuse live 在直连 gated 期间明确 NOT RUN。

## 不做什么

不改 WeKnora；不做前端点踩组件（用 Langfuse 已有能力）；Deep Research 自动补源仍在 P2。

# 015 规格（验收条款）

## F1 信号提取

- F1.1 Langfuse API 客户端（trust_env=False，坑清单 #9）；增量拉取（游标持久化，重跑不重复处理同 trace）；
- F1.2 四类信号识别器（纯规则）：无引用回答（响应无 source_refs/chunk 引用特征）、低置信/拒答（拒答话术模式表 + score 阈值）、负反馈（Langfuse score/annotation）、命中空知识（问题实体对齐后查无 published Claim）；识别器可配置启停；
- F1.3 问题文本入库前脱敏（手机号/证件号/保单号正则遮蔽），原文不落库只留 trace_id 回指。

## F2 对齐与开单

- F2.1 实体对齐复用 003 路由器 + 009 概念词表（确定性）；对齐输出 (product_id?, concept_id?, field_id?) 粒度，置信不足进观察队列**不开单**；
- F2.2 缺口工单 ReviewItem(type=knowledge_gap)：稳定 ID = 对齐粒度派生 → 同一缺口重复触发只累计 hit_count 与最近 trace 样例（≤5 条），不重复开单；
- F2.3 已 resolve 的缺口再次触发 → 重新打开并标注 reopened（知识补了还答不好=新问题）。

## F3 报表与闭环

- F3.1 周期报告：新增/累计/已闭环缺口数、TopN 答不上问题（按 hit_count）、缺口→闭环平均周期、按产品与险种分布；
- F3.2 与 011 报告合流：健康度报告含飞轮小节（供给侧巡检 + 需求侧反馈同页呈现）；
- F3.3 CLI：`flywheel pull`（拉取+识别，默认 dry-run 出报告）、`flywheel pull --open-tickets`。

## F4 验收

- F4.1 夹具 trace（四类各 ≥2 + 1 条含手机号需脱敏 + 1 条对齐不到实体）→ 识别正确、开单幂等、hit_count 聚合、观察队列不误开单、脱敏生效、游标增量；
- F4.2 零模型调用（语义聚类 stub 默认关）；门禁全绿。

# 011 · 知识健康度巡检（语义 lint）

> 状态：**已条款化（正式 delta；三版 2026-07-18 按 codex PR #12 复审收口：三方对账/typed provider/持久基准/typed subject），规格复审收口前不可认领**。含 H1.7 任务可靠性（同事 WeKnora 实证反馈吸收：死信/解析失败不得沉底）。迁移占号 0010（completeness_snapshots + health_runs/health_findings）。Owner=C；typed subject 接线与迁移 Owner-A 复审。
> 设计权威：13 §2 G3、LLM Wiki #12 思想（结构性 lint 高频确定性 / 语义性低频审计分层）、master plan P1-1 质量与缺口、20（企业运行约束）。

## 为什么做

"知识入库即死"的解药除了更新链路（007），还要有**主动巡检**：过期、悬而未决、漂移、退化要被系统发现而不是等用户答错。这是数据飞轮的"平台自检"半环。

## 做什么（全部确定性，零模型调用；LLM 审计通道留接口）

1. **过期扫描**：Claim 生效/失效日期 vs 当前日期；产品销售状态变化（010 直入的最新 meta）连带其 published Claim 标记"需复核"；
2. **积压扫描**：pending_judge/ReviewItem 超时（阈值可配）升级提醒；conflict 长期未决清单；
3. **漂移检测**：已发布 wiki 页内容 hash vs 按当前 published Claims 重编译结果——不一致说明有人绕过链路改页或编译器变更未重发（对账）；
4. **退化检测**：完整度快照（产品×字段填充率）定期落表，环比下降告警（如金标/schema 升版后覆盖率跌）；
5. **孤立检测**：无任何互链/概念关联的发布页清单（结构信号，WeKnora graph API 可取）；
6. **产出**：健康度报告（markdown + 结构化）+ 整改项自动生成 ReviewItem（复用受限动作）；CLI `health-check`，可挂 cron；
7. **LLM 语义审计接口**（默认关）：抽样页面的矛盾/过期语义检查，claude-session 队列形态，成本可控后再开。

## 验收

用 007/010 夹具构造五类问题各 ≥1（过期 Claim、超时 conflict、被手改的页、覆盖率下降快照、孤立页）→ `health-check` 全部检出且生成对应 ReviewItem；无问题时报告干净。门禁全绿。

## 不做什么

问答日志信号接入（依赖 WeKnora 侧日志导出，列后续）、自动修复（只发现+开工单）。

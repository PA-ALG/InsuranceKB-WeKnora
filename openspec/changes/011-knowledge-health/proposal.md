# 011 · 知识健康度巡检（语义 lint）

> 状态：**已条款化（正式 delta；PR #12 主规格已合入，PR #22 fast-follow 已在本规格补齐远端/输入/工具链独立证据轴及 durable provider 边界），011 本体可认领**。含 H1.7 任务可靠性（同事 WeKnora 实证反馈吸收：死信/解析失败不得沉底）。迁移占号 0010（completeness_snapshots + health_runs/health_findings）。020 registry 未就绪时相应 provider 按合同 degraded，不阻塞软件实现；Owner=C，typed subject 接线与迁移 Owner-A 复审。
> 设计权威：13 §2 G3、LLM Wiki #12 思想（结构性 lint 高频确定性 / 语义性低频审计分层）、master plan P1-1 质量与缺口、20（企业运行约束）。

## 为什么做

"知识入库即死"的解药除了更新链路（007），还要有**主动巡检**：过期、悬而未决、漂移、退化要被系统发现而不是等用户答错。这是数据飞轮的"平台自检"半环。

## 做什么（全部确定性，零模型调用；LLM 审计通道留接口）

1. **过期扫描**：Claim 生效/失效日期 vs 当前日期；产品销售状态变化（010 直入的最新 meta）连带其 published Claim 标记"需复核"；
2. **积压扫描**：pending_judge/ReviewItem 超时（阈值可配）升级提醒；conflict 长期未决清单；
3. **漂移检测**：以冻结页面 A、远端实读页面 B、当前重编页面 C 做三方对账；远端页面关系、冻结/当前输入身份、冻结/当前工具链身份独立取证并允许多信号并报。身份变化只作为证据，不冒充页面差异的唯一因果；缺身份或无法解释的 A≠C 明确 degraded；
4. **退化检测**：完整度快照（产品×字段填充率）定期落表，环比下降告警（如金标/schema 升版后覆盖率跌）；
5. **孤立检测**：无任何互链/概念关联的发布页清单（结构信号，WeKnora graph API 可取）；
6. **同类对比缺口**：同险种多数产品已 present、个别产品仍 unknown 时生成“疑似未抽到/材料未提供”整改项；
7. **任务可靠性**：通过 typed provider 汇总 compiler attempt/dead-letter/judge、017 桥接失败与 018 reconciliation；任一必需来源缺失或过期时报告 degraded，不得把零发现写成健康；
8. **产出**：健康度报告（markdown + 结构化）；CLI `health-check` 默认只读，`--open-tickets` 仅为条款允许的整改项生成 ReviewItem，孤立页只进信息清单；
9. **LLM 语义审计接口**（默认关）：抽样页面的矛盾/过期语义检查，claude-session 队列形态，成本可控后再开。

## 验收

用 007/010/018 夹具覆盖七类扫描器，并对 H1.3a 使用远端/输入/工具链真值表：单轴、多轴、身份缺失、A=C 抵消与无法解释的 A≠C 均不得漏报或伪归因。H1.8 用多 run registry snapshot 验证稳定选择、watermark、过期/回退/工件不完整 fail-closed。`health-check` 默认只读；仅 `--open-tickets` 为条款允许的整改项开 ReviewItem，H1.5 孤立页仍只进信息清单。全 provider ok 的干净夹具才允许报告 healthy；门禁全绿。

## 不做什么

问答日志信号接入（依赖 WeKnora 侧日志导出，列后续）、自动修复（只发现+开工单）。

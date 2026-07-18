# 011 知识健康度巡检验收规格

> 三版（2026-07-18）：codex PR #12 复审收口——H1.3 改 A/B/C 三方对账（原两方比较无法观察人工绕改、原因分类不成立）；新增 H1.8 typed provider 合同（缺数据不得误报健康）；H2 补 health run 持久基准；字段/状态名对齐实际模型（`claims.effective_to`、`ReviewItem.status=open`）。二版（2026-07-16）Wave 2 条款化。原 H1~H3 条款 ID 沿用。定位：**运维离线扫描**——可读主链表（不受在线读模型限制），但涉及"已发布内容"的比较一律以 018 冻结快照为基准。

## ADDED Requirements

### Requirement: H1 七类确定性扫描器

扫描器 SHALL 全部确定性、按 KnowledgeSpace 执行（显式 space 或枚举全部 space，工单带 space）；条款中的字段/状态名 SHALL 对齐实际模型（规格即执行合同，不留实现者猜）：

- H1.1 过期：`claims.effective_to < today` 且 published → ReviewItem(type=expired)；产品停售但 Claim 无失效标记 → 检出；
- H1.2 积压：pending_judge / `ReviewItem(status=open)` 超阈值天数（默认 7）→ 升级清单；conflict 未决按产品聚合；
- H1.3 漂移（**三方对账**，见 H1.3a）；
- H1.4 退化：completeness_snapshots 定期落表（产品×字段三态计数）；环比覆盖率下降超阈值 → 检出并注明可能原因；
- H1.5 孤立：发布页无任何 in/out wikilink 且无概念关联 → 信息级清单（不开工单）；**依赖 009 概念表——009 未落地时本扫描器 SHALL 报 `not-applicable`**，SHALL NOT 因表不存在而报 clean 或把全部产品页判孤立；
- H1.6 同类对比缺口：同险种产品群多数 present 而某产品 unknown（阈值可配，默认 ≥60%）→ "疑似有此信息未抽到/未提供材料"工单，与 015 问答信号互补；
- H1.7 任务可靠性：经 H1.8 typed provider 消费 compiler 死信、judge-queue 长期 unresolved、017 桥接解析失败、018 reconciliation 未决 → 计数+样本进报告，任一非零在报告顶部显式呈现（不得沉底），超阈值升级 ReviewItem。

#### Scenario: 七类问题各检出一例

- **WHEN** 夹具构造七类问题各 ≥1（过期/积压/漂移/退化/孤立/同类缺口/死信）并运行扫描
- **THEN** 七类全部检出且工单/清单带 space；无问题的干净夹具（全 provider ok）→ 报告干净零工单

#### Scenario: 009 未安装时孤立扫描 not-applicable

- **WHEN** 009 概念表尚未落地时运行扫描
- **THEN** H1.5 报 not-applicable（报告显式呈现），零误报孤立、零误报 clean

### Requirement: H1.3a 漂移三方对账（A/B/C，原因互斥）

漂移检测 SHALL 为三方对账，SHALL NOT 只做两方比较：

- **A** = current snapshot 的冻结 rendered page（018）——"应在线"内容；
- **B** = 经现有 WeKnora adapter 只读回读的**实际远端页面**——A≠B ⇒ `remote_drift`（人工绕改/远端异常），这是唯一能观察到人工绕改的比较；
- **C** = 按当前 mutable Claims + 显式 compiler/schema/purpose 版本重编译结果——A≠C ⇒ `pending_content_change`（待发布事实变化）或 `compiler_version_change`（以 run manifest 的版本 digest 区分，SHALL NOT 以"compiler version 相同 ⇒ 绕改"推断）。

三类原因 SHALL 互斥归因；比较 hash SHALL 基于规范化 content/source_refs/chunk_refs/稳定 metadata（排除时间戳等易变字段）；**远端不可用/超时 SHALL 报 `unknown/unavailable`，SHALL NOT 计为 healthy**。

#### Scenario: 三类原因互斥命中

- **WHEN** 分别构造：仅改远端 B、仅改 mutable Claim、仅 bump compiler digest 三个夹具
- **THEN** 依次仅命中 remote_drift / pending_content_change / compiler_version_change，互不串扰

#### Scenario: 远端不可用不出干净报告

- **WHEN** WeKnora 回读 5xx/超时
- **THEN** 漂移维度报 unknown/unavailable 且报告整体 degraded，零"healthy"结论

### Requirement: H1.8 数据源 typed provider（缺数据不得误报健康）

四类可靠性信号源 SHALL 经 typed provider 合同消费：每个 provider 返回 `ok | unavailable | stale` + source namespace + watermark + observed_at；**任一必需 provider unavailable/stale 时报告 SHALL 标记 degraded**，SHALL NOT 以"零发现=健康"呈现。数据源发现方式 SHALL 明确：compiler 死信/judge-queue 以 020 approved run artifact 目录（run registry）为准；018 reconciliation 读其数据库表；**017 桥接失败当前无 durable failure ledger——该 provider SHALL 显式报 unavailable（合同：ledger 由后续 change 提供后接入），SHALL NOT 假装可读**。

#### Scenario: provider 缺失报告 degraded

- **WHEN** compiler run registry 不可达（或 017 ledger 未提供）时运行扫描
- **THEN** 对应维度报 unavailable、报告整体 degraded 且顶部显式呈现；其余维度正常输出

### Requirement: H2 产出、持久基准与工单集成

`health-check` CLI SHALL 全量扫描输出 markdown 报告 + 结构化 JSON；默认只读，`--open-tickets` 才生成 ReviewItem（dry-run 规范）。**持久基准**：迁移 0010 SHALL 同时落 `completeness_snapshots` 与 `health_runs / health_findings`（不可变 run 快照：scanner/config 版本、各 provider watermark、分维度分数与发现）——健康度总分（维度加权可配）与环比趋势 SHALL 从持久 run 基准计算、可重放，SHALL NOT 依赖进程内状态。**工单 subject Space 闭合**：health finding 开单 SHALL 经受 Space 约束的 typed subject——ReviewItem 引用带复合 FK 的 `health_finding_id`（health_findings 行带 space_id），SHALL NOT 借用现有 `ensure_review_item` 对未知 subject 字段 extra=ignore 的路径绕过归属校验；**该接线触及 review 服务，属 Owner-A 复审项**。ReviewItem 复用 007 稳定 ID——同一问题重复扫描不重复开单、已 resolve 不复活（问题于新版本复现除外）；LLM 语义审计接口仅留 stub（默认关）。

#### Scenario: 工单幂等且 subject 闭 Space

- **WHEN** 同一问题连续两次扫描（第一次已开单）；另尝试以跨 Space finding 开单
- **THEN** 第二次零新工单、resolve 后未复现不复活；跨 Space subject 在服务层被拒（错误指明两个 space）

#### Scenario: 趋势可重放

- **WHEN** 三次扫描落三条 health_runs 后重算趋势
- **THEN** 趋势/环比与三次 run 的持久分数逐点一致（可从表复算，不依赖内存态）

#### Scenario: 默认只读

- **WHEN** 不带 `--open-tickets` 运行
- **THEN** 产出报告但 ReviewItem 零新增

### Requirement: H3 工程边界

实现 SHALL 为独立巡检模块（新包）：只读主链表 + 冻结快照 + WeKnora adapter 只读回读（H1.3a 的 B 侧，复用现有 adapter 不新增 API 面）；写路径仅 007 服务层开 ReviewItem + 0010 自有表（health_runs/health_findings/completeness_snapshots）；不改 compiler/goldenset；**typed subject 接线（review 服务）与 0010 迁移列 Owner-A 复审——不再宣称"独立新包零接线"**；零真实模型调用、门禁全绿、不破坏既有测试。

#### Scenario: 写路径受限

- **WHEN** 静态检查巡检模块
- **THEN** 对业务主链表无直接 INSERT/UPDATE/DELETE（开单只经 007 服务层函数；自有 0010 表除外）

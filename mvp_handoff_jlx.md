# Enterprise LLM Wiki 项目交接文档（mvp_handoff_jlx · v3）

> 日期：2026-07-28
> 版本标识：728-v3
> 文件名：`mvp_handoff_jlx.md`
> 面向对象：完全没有历史上下文的新会话、新开发者、新架构师、外部评审模型
> 整理范围：2026-07-28 讨论窗口 + v2 三轮独立架构评审 + Codex/Web GPT v3 复评
> 文档性质：持续更新的项目交接，不是代码 Review，不代表本文提到的能力已经实现
> 使用方式：接手者先完整阅读本文，再阅读需求、技术方案和难点文档；在用户要求实施前，不要擅自把讨论结论改回旧架构。

---

## M0 · 2026-07-29 当前执行状态

当前仓库基线与原始 2026-07-28 文档状态已有变化。以下状态优先于本文后续历史
段落：

本文是 informative 交接与设计输入，不单独授予实现权。规范层级依次为 Sole
Serving Active Release Authority ADR → Authority Amendment 2 → 适用 OpenSpec。

```text
main:
1650f3bb26fd92af554c22f45d7df0a45e29c160

upstream capability:
80a5003cc99a427098afe184eee6601916d3d156

trusted image build source:
a8bf55ae18441abd380e594afba5000c51cc9633

source adoption / 000066 bridge / image digest:
COMPLETE

Full Artifact/W1 runtime probes:
OPEN

source_reader authority:
BLOCKED

runtime transition:
NO_PRODUCTION_ACTIVE_RELEASE

S0-R third-run:
RELEASE_PATH_FEASIBLE / EXPERIMENTAL ONLY / MERGED

S0-R reviewed candidate / merge:
c78053113e01355b1b03174d229633f27da2f478
b278b71502e7d5e65e63b248648be6685e596d03

S0-Q:
BLOCKED_ON_INPUT / SCHEMA AUTHORITY ADMITTED / FULL GOLDEN NOT FROZEN
```

S0-R 第三轮已在隔离 PostgreSQL 16.14 证明：legacy/fresh migration matrix、
enterprise `000002` up/down/restart、同 base 双 Candidate 单赢家、loser
零残留、CAS 阻塞期完整 R0/R1 pinned read、双当前 ACL fail-closed 与
active-managed Wiki PUT/DELETE 拒绝。独立 Spec 与 Quality/Delivery review
均通过，PR #73 已合入。该结果不是生产 Kernel、Artifact、部署或 MVP 完成；
默认 production signer 仍为空 key map 并 fail closed。

S0-Q 已于 2026-07-30 进入批准的两 PDF 窄切片运行。两份仓库 PDF 的 bytes 与
SHA-256 均精确匹配，但固定 WeKnora 输入画像所需的百炼 embedding credential
在创建任何 model/RAW KB/scratch KB/API key/knowledge 之前的一次维度探测返回
HTTP 401。静态 exact source inspection 还确认 current W1 v1 manifest 只绑定
text chunk id/index/content，不绑定 S0-Q 所需的 page/block/table-cell identity
或表格结构 digest。按输入门禁，本轮交付 `BLOCKED_ON_INPUT`：W1 bundle、
完整 Golden 的四条诊断投影、模型画像和 A–D 均未运行，Harness 弱/强模型
调用均为零。临时
fresh stack 与其容器、网络、卷、运行配置目录已精确删除，原有固定 WeKnora
环境保持健康且未被重置。

业务方原始
`docs/insurance-kb/schema-authority/产品知识库字段标签维度-20240205.xlsx`
已按 exact bytes 登记，SHA-256=
`5cd0ed8af0bc10fec488d0d83e8e28c7c0d64408c4fc25cca92b2a365355fdb6`。
现有目标医疗产品 Golden WIP 覆盖当前 60/60 个可抽取字段（49 个工作簿权威
字段 + 11 个后续 v1.1 扩展），但仍只是覆盖证据。禁止另建四字段 Golden；
S0-Q 只从获批完整 Golden 投影四条诊断记录。R2 须等待独立 Golden Mission
使用 `gpt-5.6-sol` 全字段统一候选生成或复核，完成 Evidence 回验、既定人工
批准和不可变 artifact identity/digest。

外部配置动作是刷新/替换已批准的百炼 embedding credential。开发侧下一条唯一
主航道是另行批准一个最小 W1 page/block/table-cell identity +
table-structure digest 绑定补丁；不建设表格平台。两项就绪后才在同固定镜像、
同两份 PDF、同隔离 capture 流程重试一次。不要建立通用凭据治理、替代
embedding、人工清洗文本，也不要提前实现 A–D、Release/Wiki 接线。

当前唯一执行顺序：

```text
Mission 0
├── S0-R merged FEASIBLE
└── S0-Q 独立执行（必须使用冻结 parsed artifact）
           ↓
S0-R merged PASS AND S0-Q PASS
           ↓
MVP 纵向闭环
```

执行限定：

1. 043 只保留通用安全合同，状态为
   `SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`；
2. S0-R 两工作日是输入就绪后的证伪窗口，不是生产 Kernel 交付期限；
3. MVP 使用 `1 RAW KB + 1 release-managed Wiki KB`，不冻结永久企业
   cardinality；
4. S0-Q 必须使用 WeKnora/W1 冻结解析制品，不得用人工清洗 Markdown；
5. S0 双 PASS 后只改接首个纵切真实调用入口，legacy 清理后置；
6. `80a5003`、`a8bf55ae...` 与 `529d72c...` 是三个不同身份。

正式裁决见 2026-07-29 Sole Serving Active Release Authority ADR 与 Authority
Amendment 2。

---

## 0. 新会话先读这一段

我们正在建设一家大型寿险公司的 Enterprise LLM Wiki。

这不是普通 RAG，也不是单纯给人看的 Wiki。目标是把几十万份文档、FAQ、PPT、表格和历史片段，持续编译成：

- 有实体；
- 有产品版本；
- 有时间；
- 有适用范围；
- 有 Evidence；
- 有缺口；
- 有冲突；
- 可审核；
- 可整版发布；
- 可回滚；
- 人和 Agent 使用同一版本；
- 能根据新材料和反馈持续演进；

的知识基础设施。

架构已收敛：

```text
WeKnora
= 企业平台底座
+ 原始材料和 SourceRevision 权威
+ ACL / 审计 / API / Wiki UI
+ 唯一在线 Wiki Release 权威

Python Harness
= 寿险语义知识编译器
+ 校验、缺口、融合、冲突
+ Candidate、审核决策、发布授权
+ Golden 评估
+ 【无 Active Head】
```

明确否决：

```text
Harness ActiveRelease
→ 异步投影到 WeKnora managed Wiki
→ freshness / fencing / 双 ACL / 对账 / 迟到写
```

不要再把它作为默认方案重新带回来。

### 0.1【v2】但请精确理解"否决投影"是什么意思

**否决的是**：第二个可变 Active Head、异步 freshness、迟到投影写、双 serving
authority 对账、读取时跨系统协商。

**没有否决、且必须做对的是**：跨系统发布、数据物化（payload 落在 WeKnora）、
digest 校验、幂等键、CAS。

正确措辞：**Harness 编译并冻结 Candidate，WeKnora 接收一个不可变发布制品并
成为唯一服务权威。**

若你读到"不做投影 = 不复制任何数据"，那是误读。

### 0.2【v3】三件最容易犯的错

1. **把 S0-R 或 S0-Q 当成 MVP**。二者分别只有发布可行性和窄切片质量可行性
   状态；任一通过不得声明 MVP、质量或生产架构已通过。
2. **按编号取消能力项**。必须按能力分档
   （`KEEP / REWIRE / SUPERSEDE / DEFER / DELETE`）。全部能力项中只有
   Projector 一项是 DELETE。
3. **写裸数字**。所有质量数字必须带 Metric ID 合同。已经因此发生过一次口径
   混淆。

---

## 1. 我们在做什么任务

### 1.1 业务任务

把寿险公司过去以"文档 + 文档片段 + chunk"存在的静态知识，升级为 Enterprise LLM Wiki。

它既要服务：

- 产品、核保、理赔、保全、权益、销售等业务人员；
- 专家和合规审核；
- 知识运营；
- Agent 和 API；

又要保证：

- 事实可验证；
- 版本可固定；
- 更新可追踪；
- 冲突可治理；
- 错误可回滚；
- 权限不泄漏。

### 1.2 当前文档任务

基于讨论窗口整理五份文档：总体需求与验收口径、MVP + 企业级完整技术方案、
技术难点与核心问题、本交接文档、完整合订本。

要求：不压缩；不遗漏讨论过程；不把项目当成新项目重头设计；不进行代码 Review；
写给无上下文的新会话；可供其他模型评估和提出调整意见。

**v2 追加要求**：把三轮评审的收敛裁决全部写入，并对每条涉及"当前实际情况"的
断言标注证据状态（[已核验] / [未核验] / [待核对]）。

---

## 2. 为什么需要重新收敛

用户对项目产生了强烈疑问：

- 项目推进很久；
- 代码很多；
- MVP 仍未令人满意；
- 不清楚究竟完成了什么；
- 当前抽取准确率低；
- 担心总体技术架构不合理；
- 担心当前实现无法承担最初提出的企业问题；
- 怀疑"薄补丁"和双系统投影会把项目拖成长期 WeKnora fork；
- 不希望再反复推倒重来。

本轮讨论形成的判断：

> 项目不是完全没做东西，而是底层原语、任务框架、接口和局部设计推进较多，但真正能证明业务价值的纵向闭环没有清晰跑通。

之前方案把大量复杂度放在 Harness ActiveRelease、WeKnora managed Wiki 投影、
freshness、fencing、迟到写保护、ACL 双重检查、reconciliation、上游跟版。

这使 MVP 变重，同时没有把主要开发力集中在抽取准确率、ProductVersion、
Evidence、Gap、Conflict、Golden。

因此本轮不是从零设计，而是纠正权威边界并重新排序已有工作。

### 2.1【v2 已核验】"纵向闭环没跑通"这一判断的具体证据

已合入并可用的能力项：任务运行时（含事务 Outbox、状态机、lease/generation
fencing）、Canonical Envelope、容量合同、Revision 合同 spike 与实现、
API/Worker shell、ProductVersion resolver（exact 层）、只读 fence verifier、
Space 安全边界规格。

**这些项中没有任何一项产出用户可见的知识输出。** 这不是说它们无用——它们大多
在新架构下仍为 KEEP——而是说"已完成量"与"业务可感知进度"之间确实存在结构性
落差。S0-R 与 S0-Q 的设计目的正是尽快把“发布路径”和“知识质量”分别变成
可见、可证伪的证据。

### 2.2【v2 已核验】质量落差也有量化证据

| 指标 | 值 | 备注 |
|---|---|---|
| micro F1（真实弱模型，2 产品合计） | 0.231 | calibration-only |
| 目标（G0b） | precision ≥0.95 / recall ≥0.90 | |
| 检出后值一致率 | 0.273 | **塌陷点** |
| 引文逐字回验 | 1.000 | **已解决** |
| 报告结论 | "不是调参距离，是结构距离" | |

完整 Metric ID 合同见需求文档 §10.2.1。

---

## 3. 业务背景

公司是一家大型寿险企业，知识材料包括产品条款、产品说明书、宣传文档、PDF、
PPT、FAQ、表格、文档片段、销售知识、客户经营、销售经验、理赔、核保、保全、
权益、产品服务、医学术语。

材料规模可能达到几十万份文档或片段。

当前问题分为四组：

### 3.1 知识静态

- 业务规则变化后知识不自动更新；
- 入库以后基本封存；
- 答错后不会形成自我修正；
- 错漏和冲突难维护；
- 产品责任变化后很难知道要改哪些知识。

### 3.2 知识离散

- 同一概念散落多份材料；
- 多业务线缺少联系；
- 代理人回答复杂问题容易缺漏；
- 平台不知道知识覆盖、缺失和重复；
- 概念和产品义项没有统一组织。

### 3.3 加工准确率低

- 复杂 PDF、跨页表格、嵌套规则处理失败；
- 弱模型漏条件、错实体、错版本；
- 没有稳定 Evidence；
- 没有独立校验；
- 失败只能丢弃或人工返工。

> **[v2 已核验]** 其中"没有稳定 Evidence"这一项**已经改善**：引文逐字回验达
> 1.000。当前真正的瓶颈是 typed value 归一与值一致性（0.273），以及尚未测量的
> Evidence 语义支持。

### 3.4 更新发现慢

- 依赖人工抽检；
- 平台不知道回答对不对；
- 新材料无法稳定补旧缺口；
- 冲突发现滞后；
- 没有反馈飞轮。

---

## 4. 最初目标

用户最初明确希望结合 Karpathy / LLM Wiki 范式，把知识从"给人看的文档库"升级为"给 Agent 用的知识基础设施"。

需要：

1. 知识自动更新；
2. 知识可以进化；
3. 有版本；
4. 可溯源；
5. 可以回退；
6. 人类友好；
7. Agent 友好；
8. 知识可关联；
9. 概念有多个义项；
10. 能识别缺口；
11. 能发现冲突；
12. 弱模型抽取后有校验；
13. 支持寿险 Schema；
14. 能处理几十万材料；
15. 有 Golden Set。

---

## 5. 参考过什么

### 5.1 WeKnora

定位：企业平台、上传解析、OCR、chunk、检索、Source、ACL、审计、API、Agent、
Wiki UI。

讨论结论：

- WeKnora 本身有 Wiki，但其原生 Wiki 不等于寿险 LLM Wiki；
- 它没有寿险 ProductVersion、Claim、Evidence、Conflict、Gap、批次审核和整版
  Release 语义；
- 应增强领域无关 Release Kernel；
- 不应把全部寿险语义塞进 WeKnora；
- 最终实施时要基于最新 WeKnora 主线核对可复用能力。

#### 5.1.1【v2 已核验】exact identity 与已发生的撞号

| 项 | 值 |
|---|---|
| 项目当前锁定 | `v0.6.3` / `5eefa70e6fc8f9ec27958779f91ece6cf685598c` |
| 官方稳定版 | `v0.7.1`（`c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`） |
| 正式稳定候选 | `v0.7.1` / `c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb` |
| post-release 对照候选 | snapshot `80a5003cc99a427098afe184eee6601916d3d156`，含官方 `000075_wiki_page_revisions` |
| v3 选择状态 | **尚未选择**；稳定版默认优先，须用双基线能力矩阵证明 snapshot 的长期收益大于迁移与跟版风险 |
| 已发生的冲突 | 项目 `000066_knowledge_revision_manifest` 与上游 `000066_expand_knowledge_span_name` 同号不同义 |
| 当前运行制品 | 仍从 `5eefa70e` 构建，**不含**项目已合入的 revision 合同 |

**这是本项目最贵的一次教训**：在上游活动区域自建同号 migration，代价是一个
采用 Mission 至今未关闭。**Release Kernel 与官方 wiki page revision 同区域**，
所以有了门禁一（能力矩阵）。

### 5.2 `nashsu/llm_wiki`

地址：<https://github.com/nashsu/llm_wiki>

借鉴：Raw Sources / Wiki / Schema；Ingest / Query / Lint；index.md / log.md；
原子页；LLM 持续维护；人机协作；冲突和缺口；一份材料可能更新多个 Wiki 页面。

限制：个人级；Markdown/Obsidian 形态；无企业 ACL；无寿险版本语义；无批次
Release；无强一致发布；无大规模生产治理。

结论：

> 它是**方法论来源，不是代码来源，也不是企业生产运行时**。

**[v2 澄清]** 曾有一个疑问是"把个人级项目合并到企业平台是否合理"。准确回答：
**没有发生这样的合并**。承载运行时的是 WeKnora（企业平台）+ Python Harness
（领域编译器）；从该项目吸收的是三层结构与 ingest/query/lint 的**思想**。

### 5.3 `LLM-wiki-black` 定制分支

地址：<https://github.com/silvielala412-lab/LLM-wiki-black/tree/feature/product-catalog-domain>

项目团队已在开源项目基础上做过寿险定制，docs 中有设计。

可吸收：产品目录；taxonomy；Schema/Template 想法；产品/服务/模块层级；
routing；cleaning；compat；weak-value；概念聚合原型；冲突和字段处理思路；
领域样例和测试资产。

不能直接照搬：Evidence 可能只到文件级；ProductVersion 身份链不完整；
Concept/Sense 不完整；Release 不完整；Golden 不完整；TypeScript/localStorage/
Markdown 不作为生产主链；需要 provenance/license 核验。

结论：

> 旧分支是第一方领域资产和迁移来源，不是必须保留的第二套运行时。

---

## 6. 讨论过程完整记录

### D1：用户质疑整体路线

用户提出：MVP 做了很久；实际进度不满意；不只是体感问题，还担心架构不合理；
当前设计是否能承担最初提出的各种企业问题。

这使讨论从"继续实现已有任务"转向"重新验证架构边界"。

### D2：追问 W1 所谓薄补丁

讨论中提到 fencing、freshness、ACL 双重检查、对账、迟到写保护、长期跟版、
W1 已涉及约 30 个文件、后续还有 P11–P14。

结论：若 Harness 保持 ActiveRelease 再投影到 WeKnora，就必须做这些机制；
逻辑上成立但复杂度很高，会增加长期维护 fork 的风险；必须先决定是否真的需要
双 Active。

### D3：厘清"投影"

解释：投影是把 Harness 中的权威知识状态复制成 WeKnora 中可展示的 managed
page。若只是缓存可以重建；但若人和 Agent 同时依赖 WeKnora 页面，就必须判断
页面是否与 Harness Active 一致，从而带来 freshness、epoch、fencing、
reconciliation 和 ACL 问题。

不做投影不是"不在 WeKnora 展示 Wiki"，而是：

> 不再让 Harness 先成为另一个线上 Active 权威；Harness 生成 Candidate 和发布包，WeKnora 原子激活后成为唯一 Active。

### D4：WeKnora 原生 Wiki 和项目 Wiki 的差异

WeKnora 原生能力可以解决页面、内容组织、基础生成和查询、平台集成。

但没有系统性解决寿险 Schema、产品和版本消歧、Claim/Evidence、材料分级、
弱模型独立校验、缺口、冲突、增量更新、批次审核、整版 Release、Golden。

因此 Harness 仍然必要，但职责要聚焦在领域编译，而不是维护第二个 Wiki。

### D5：重申最初架构

用户给出原设计：

```text
WeKnora 企业平台底座
├─ 文档接入、解析、索引、权限、审计、API、Agent、Langfuse
├─ 寿险领域抽取层
├─ LLM Wiki 式知识编译器
└─ Agent 调用层
```

这一路线方向合理，但需要调整"发布权威"：抽取和编译仍由 Harness；WeKnora 承担
平台和唯一 Release；不再通过第二 Active 做长期投影。

### D6：确认 LLM Wiki 是项目核心

保留 LLM Wiki 的 ingest/query/lint、原子页、人机协作和持续演进；把企业级治理
补齐；不把 LLM Wiki 方法误解为"必须维护一套 Markdown 主库"。

### D7：用户列出八类核心问题

0. 大规模知识融合和冲突；
1. 弱模型下稳定抽取、准确率和校验；
2. 缺口识别；
3. 第二、第三批材料补充和更新；
4. 版本和回退；
5. 人类友好 Wiki、概念关联和多义项；
6. 数十万材料和模板化；
7. 片段准确关联、合并、冲突和溯源；
8. Golden Set 和模型切换评估。

这些成为需求主轴，后续不能只讨论发布系统而忽略语义质量。

### D8：用户要求更新 WeKnora 最新主线

用户一度要求先更新，随后明确"先不做了，继续讨论技术方案"。

因此：技术方案必须充分利用最新 WeKnora；但本轮不执行更新；实施前单独核对最新
上游能力。

> **[v3 更新]** 这项核对现已成为**门禁一**（技术方案 §7.10 双基线能力矩阵），
> 比较稳定 `v0.7.1/c64a486` 与 `80a5003`，并带入已知 `000066` 撞号风险。

### D9：MVP 主航道

```text
WeKnora 上传解析
→ SourceRevision
→ 知识编译
→ Evidence / Claim / Conflict
→ Candidate
→ 可配置机器或人工审核
→ Active Release
→ 带引用的 Wiki 查询
```

用户要求样本更真实：10 多份；有代表性；有冲突；多种数据样式。

结论：10–15 份；两个批次；一个产品族；两个相似产品或版本；PDF/PPT/FAQ/表格/
片段；40–60 条事实；5–10 个页面。

### D10：审核语义

用户明确：有些内容可以机器审核；有些必须人工；不能每个页面人工点击；必须可
配置。

结论：审核单元是 CandidateRelease；ReviewPolicy 按 Space 配置；默认
human_batch；机器审核独立存在；高风险、冲突、版本歧义强制人工；低风险可机器
建议；MVP 最终发布采用 human_batch；machine_auto 放到企业阶段。

### D11：不要把项目当新项目

用户多次强调：项目已经做了很久；应吸收旧系统；不要全部从头讨论；但也不要被
沉没成本限制；追求企业落地的合理方案；复杂度过高要取舍；避免再次推倒重来。

形成两条同时成立的原则：

1. 旧资产要迁移和复用；
2. 错误权威边界不因已有代码而保留。

### D12：第一性原理比较架构

A. WeKnora 直接承担全部寿险 LLM Wiki — 单系统，但把大量寿险逻辑塞进上游，
形成重 fork。

B. WeKnora 单一 Release 权威 + Harness 编译治理 — 权威唯一，领域边界清晰，
可跟随上游；需要 WeKnora 增强 Release Kernel。**结论：推荐。**

C. Harness Active + WeKnora 投影 — Harness 自治；但双权威、一致性、ACL、跟版
复杂。**结论：否决。**

### D13：抽取准确率重新成为核心

用户指出 MVP 描述里没有充分体现抽取准确率，而当前准确率很低。

结论：Harness 的核心不是流程编排，而是 weak-model-first 的寿险知识编译；必须
拆出分类、路由、消歧、Schema、Evidence、独立审核、Gap、Conflict 和 Golden；
这些不是企业版装饰，而是 MVP 的关键验证项。

### D14：材料分类和采信

结论：少量材料类型；自动分类；低置信批量确认；字段级 TrustPolicy；来源权威
不等于全局分数；时间和产品版本共同决定采信。

### D15：Schema 缺口反向查询

结论：tri-state；GapTask；定向检索；field-specific extraction；Evidence 校验；
增量 enrich/add/conflict；保持已有正确字段稳定。

### D16：双时态

结论：业务时间 effective_from/effective_to；系统时间 observed_at/recorded_at/
activated_at；MVP：current/as_of_date/release_id；known_at 后置。

### D17：修改历史

用户确认修改也要有历史、最终有人记录、类似维基百科；同时确认放到比较后的位置，
不进入 MVP。

### D18：确认执行

用户逐项确认材料分类、审核语义、双时态、修改历史后置、MVP/企业版分层，
可以按此执行。

### D19：文档交付纠偏

用户明确：不需要 Mission Card（**指本轮纯文档整理**）；不需要代码 Review；
只基于本窗口完整整理；输出技术文档、需求、难点、核心问题、交接；四份独立文档
加一份完整合订本；不要压缩；交接文件名必须是 `mvp_handoff_jlx.md`。

> **[v2 重要澄清]** D19 的"不需要 Mission Card"只适用于**那一轮纯文档整理**，
> **不是**全局废止仓库治理规则。仓库治理文件中 Mission Card 是硬门禁，
> BLOCKER/BACKLOG 分类与停线判据均挂在该名称上 **[已核验]**。S0-R / S0-Q
> 开工前仍须提交对应 Mission Card。

---

## 6A【v2 新增】第二阶段：三轮独立架构评审记录

728 v1 完成后交由两个独立强模型评审，形成三轮往返。本节记录每一处分歧与最终
裁决，供后续评审者判断结论是否可靠。

### R1：评审 A 的四项指摘

| # | 指摘 | 最终裁决 |
|---|---|---|
| A-1 | Release Kernel 成本被低估（7 类对象 + 协议 + CAS + nonce，是长期 fork 面积） | **成立**。改为先填能力矩阵再定表 |
| A-2 | 728 并未消灭数据复制，只消灭第二 Active Head；应精确表述 | **成立**。写入 §5.6 |
| A-3 | 丢失了已有质量基线、过程护栏、Amendment 1 裁决与状态台账 | **成立**。写入 §10.2.1 / §13.2 / §13.3 / §13.4 |
| A-4 | 台账为空即宣称"切换代价低"不成立 | **成立**。改为分档台账 + 5 项未核验条目 |

### R2：评审 B 的四处纠偏

| # | 纠偏 | 最终裁决 |
|---|---|---|
| B-1 | 引用的 F1 数字口径需核对 | **方法成立，数字维持**。经查证：`0.231` 确为 micro F1（新报告），评审 B 读到的是另一份旧报告中 high-confidence 桶的值级正确率——两个不同报告的巧合同值。由此确立 **Metric ID 合同** |
| B-2 | 上游有 PageRevision ≠ 有整版 Release，不可推断"只剩一张 Head 表" | **成立**。评审 A 撤回该乐观推断；采用 B 的能力矩阵 |
| B-3 | `subject_ref = ProductVersion` 不应作为全域规则 | **成立**。改为"产品特定知识须约束到 ProductVersion，subject 不必恒等"，见 FR-05.1 |
| B-4 | 极薄切片不能替代正式 MVP，应分两级 | **成立**。确立 S0 / MVP-728 两级 |

### R3：评审 A 反向纠正评审 B 两处

| # | 纠正 | 最终裁决 |
|---|---|---|
| A-5 | ADR 不应占用 OpenSpec 编号（会重演已发生过的注册表漂移） | **成立**。评审 B 撤回示例性编号；ADR 用日期设计文档 + 决策记录 |
| A-6 | Mission Card 是已合入的硬门禁，不能在架构 Amendment 中夹带改名 | **成立**。保留原名，日后若需精简单独开治理变更 |

### R4：评审 B 最终纠正评审 A 一处实质错误

| # | 纠正 | 最终裁决 |
|---|---|---|
| B-5 | **不得按 P 编号笼统取消 P4a/P4c/P11–P14** | **成立，这是本轮最重要的一处纠正**。P4a 是 Source Inbox、P4c 是 Revision Capture，都是 728 自身 FR-01 与 Evidence pin 的实现；P13 是审核台；P10/P14 属修改历史。改为五档能力台账，最终只有 Projector 为 DELETE |

### R5：评审 A 补充的仓库已核验事实

| # | 事实 | 用途 |
|---|---|---|
| A-7 | `active_release` 在 Harness 源码与迁移中出现 **0 次** | 证明旧设计的 Harness Active Head 从未落地为代码，权威反转不新增代码报废 |
| A-8 | 但存在旧 018 路线的 `current_release` / `reconciliation_jobs` 等，且**在旧设计下即已判定被取代** | 说明现有报废项不是本次切换造成的 |
| A-9 | Canonical Envelope 已实现，含 `HASH_SCHEMA_VERSION` 与 domain-separated `canonical_hash` | 说明 payload 信封的 `canonicalization_version` / `semantic_contract_hash` 不需新发明 |
| A-10 | 防绕过 guard 在既有设计中已是允许的最小改动 | v2 时为 NFR-08 第 7 条；v3 重排为第 10 条，不是新增 fork 面积 |
| A-11 | `absent_explicitly` 是三态中最薄弱档（5 样本：2 对 1 错 2 漏） | 用于确定 S0 负例的选取依据 |

### R6：v2 当时共识（由 v3 精化，不删除历史）

```text
架构方向：采用 728（WeKnora 唯一 Active Release 权威）
文档治理：四层（728 / ADR / 033 Amendment 2 / 状态台账）
能力处置：五档台账，唯一 DELETE 是 Projector
开发第一刀：当时定义为单一 S0；v3 已拆为 S0-R 与 S0-Q
正式验收：MVP-728 保留两批次、增量、冲突、R1/R2、rollback
开工门禁：上游能力矩阵 + 代码状态台账 + 历史指标证据清单
质量工作：不等 Release Kernel，立即并行推进
过程护栏：全部继承，Mission Card 保留原名
```

**该段是 v2 历史记录，不再作为 v3 当前状态块。**

---

## 6B【v3 新增】Codex 与 Web GPT 复评记录

用户将 v2 交给 Claude 与 Web GPT 多轮讨论后，又要求 Codex 从第一性原理独立
复评。Web GPT 随后对 Codex 意见给出 90%–95% 认可，并提出一项关键程序性修正：
**ADR 现在就写，但状态必须是 `Accepted Conditionally`，而不是等待所有实验后
才补写。**

### v3 共同保留

- “线上只有一个 Active Release 权威”是硬不变量；
- Harness 是寿险知识编译器与治理控制面，不拥有第二 Active Head；
- Projector 仍是唯一 DELETE 能力；
- Candidate 是批审单元，MVP 不逐页审核；
- MVP-728 的两批次、增量补缺、冲突、R1/R2、rollback 范围不缩水；
- 质量线与发布线并行，不以重做架构替代抽取质量提升。

### v3 必须修正

1. WeKnora 作为权威**载体**改为条件接受，须经双基线能力矩阵与 S0-R 证伪门；
2. 单一 S0 拆为 S0-R（发布路径）与 S0-Q（知识编译质量），两者都 PASS 才进入
   MVP-728；
3. MVP 冻结一个 Space 只绑定一个 release-managed Wiki KB，避免 Space 级
   Release 与 KB 级 Head 粒度矛盾；Mission 0 修订后 MVP 同时固定一个 RAW KB，
   未来多 RAW 需另开 ADR/OpenSpec/migration；
4. S0-Q 使用四字段而非“三字段 + 一个模糊负例”；
5. P0 合同由 7 条扩展并重排为 10 条，补齐 Release scope、Claim identity、
   完整 PublishAuthorization 与合法删除语义；
6. 上游选择必须比较 `v0.7.1/c64a486` 与 `80a5003`，不预设 snapshot；
7. “值一致性主要是工程问题”降级为待消融验证的共同瓶颈假设；
8. Release Kernel 是长期存在但可封顶的低频协议成本，不再称为一次性成本。

### v3 当前裁决

```text
SINGLE_ACTIVE_AUTHORITY_PRINCIPLE = ACCEPTED
WEKNORA_AS_AUTHORITY_CARRIER = ACCEPTED_CONDITIONALLY
RELEASE_KERNEL_PHYSICAL_DESIGN = PENDING_DUAL_BASELINE_CAPABILITY_MATRIX
KNOWLEDGE_COMPILATION_FEASIBILITY = PENDING_S0_Q
RELEASE_PATH_FEASIBILITY = PENDING_S0_R
MVP_728_INTEGRATION = BLOCKED_UNTIL_S0_R_AND_S0_Q_PASS
```

这不是重新设计项目，而是给 v2 增加可证伪条件，防止再次凭“听起来合理”冻结
一个尚未通过真实纵切的载体选择。

---

## 7. v3 当前目标架构（原则确定，载体条件接受）

```text
WeKnora 企业平台底座
├─ 文档上传、解析、OCR、chunk、检索
├─ SourceRevision 和原文 Evidence 权威
├─ Tenant / Space / KB / ACL / 审计 / API / Agent
├─ Wiki UI
├─ 唯一 Wiki Release Kernel（逻辑对象；物理构成待能力矩阵确定）
│  ├─ WikiPageRevision
│  ├─ WikiRelease（含 base release + base epoch）
│  ├─ WikiReleaseMember（页面成员 + canonical 知识成员）
│  ├─ ReleaseSourcePin
│  ├─ WikiReleaseHead（唯一，CAS + epoch）
│  ├─ ReleasePreparation
│  ├─ ReadyPreparationReceipt
│  └─ ReleaseReceipt
└─ 禁止普通 PUT/DELETE 绕过 Kernel 的 guard

Python Harness
├─ 材料分类
├─ TrustPolicy（唯一命名、单一求值入口）
├─ ProductVersion Resolver
├─ Schema / Template
├─ Claim / Relation / Evidence
├─ 弱模型抽取
├─ 独立机器审核
├─ Gap 定向补抽
├─ Fusion / Conflict / ChangeSet
├─ CandidateRelease（冻结 base release + base epoch）
├─ ReviewPolicy / ReviewDecision
├─ PageReleaseBundle + PublishedPayloadEnvelopeV1
├─ PublishAuthorization
├─ Golden Evaluation
└─ 【无 Active Head】

消费层
├─ 人类 Wiki
├─ Agent / API / MCP
├─ 产品比较和规则查询
├─ Evidence 下钻
├─ Feedback
└─ 全部 pin 同一 release_id（含检索层）
```

### 7.1 发布流程

```text
ChangeSet
→ deterministic PageReleaseBundleDraft
→ Candidate 封存 exact bundle（+ base release + base epoch）
→ ReviewDecision（绑定 exact Candidate digest）
→ WeKnora 不可见 preparation
→ ReadyPreparationReceipt
→ Harness PublishAuthorization（nonce + TTL + expected head/epoch）
→ WeKnora CAS 激活 Head
→ ReleaseReceipt
```

### 7.2 关键不变量

- WeKnora 只有一个 Active Head；
- Harness 没有第二 Active；
- Ready 后不可变；
- Active Release 不可变；
- PageRevision 不可变；
- 发布使用 expected head / epoch CAS；
- nonce、CAS、receipt 同事务；
- 幂等先查结果（先于过期判断）；
- 请求固定 release_id；
- rollback 是受审核和授权的 Head 切换（整版，无单页 cherry-pick）；
- 当前 ACL 始终生效；
- Evidence 权限收缩时 fail closed；
- **[v2]** ACL 不得经 Claim / excerpt / 页面放大；
- **[v2]** 同一 Release 内每个 Claim/Relation/Evidence 只有一个 canonical
  member digest；
- **[v2]** 检索层受同一 release_id 约束；
- **[v2]** managed 页面拒绝绕过 Kernel 的普通写入。

---

## 8. MVP 是什么

### 8.0【v3】三道里程碑

```text
S0-R（发布可行性）────┐
                      ├── 两者均 PASS → MVP-728 集成与正式验收
S0-Q（质量可行性）────┘
```

#### S0-R

使用 fixture Candidate，在一个 Space、一个 RAW KB、一个 release-managed
Wiki KB 中验证集合级原子性：

- R0=A/B/C，R1=A 更新/B 删除/C 不变/D 新增；
- 从同一 R0 base 构造两个不同 Candidate 并发竞争；
- 在 preparation、index、CAS、receipt 边界做有界失败注入；
- 激活前后并发 current/pinned read，任何读取只见完整 R0 或完整 R1；
- 当前 ACL 使用两个 principal，并在 pinned 内容上验证一次 ACL shrink；
- 普通写守卫有效，Harness 无第二 Active。

开工前独立 OpenSpec/Mission Card 冻结 exact 路径、表/索引、migration、read
surface、升级责任、验证命令预算，以及暂定 `PublishAuthorization` canonical
bytes/nonce/校验顺序/失败零写。两工作日终态只能是
`RELEASE_PATH_FEASIBLE` 或 `RELEASE_PATH_NOT_FEASIBLE`。

#### S0-Q

使用 2 份真实材料、1 个预置 ProductVersion 和四类字段（present 基线、typed
present、absent_explicitly、unknown），验证候选定位、抽取、归一化、Evidence
语义支持、abstention、错误分桶和人工修订时间。状态只能是
`KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`。

任一 S0 都不做 R2、完整冲突、增量、rollback、完整 gap engine、完整 resolver、
完整 Golden、完整 UI 或 machine_auto，也不得声明 `MVP_APPROVED` /
`PRODUCTION_READY`。只有两者都 PASS，才进入 MVP-728。

#### MVP-728：只验证四件事

1. 弱模型在 Schema/Evidence/校验下能否产生可用知识；
2. 第二批材料能否增量补缺和发现冲突；
3. 机器审核与人工批审能否按策略协作；
4. WeKnora 能否原子发布、固定版本查询和回滚。

### 8.2 MVP 数据

- 10–15 份材料；
- 两批上传；
- 一个产品族；
- 两个相似产品或版本；
- PDF/PPT/FAQ/表格/片段；
- 有冲突；
- 有缺口；
- 有实体歧义；
- 一项跨产品概念。

### 8.3 MVP 知识

- 40–60 条事实；
- 5–10 个页面；
- 产品身份；
- 版本；
- 责任；
- 除外；
- 关键时间；
- 少量核保/理赔规则；
- 权益服务概念。

### 8.4 MVP 完整闭环

```text
Upload
→ SourceRevision
→ Classification
→ ProductVersion
→ Schema Extraction
→ Claim / Evidence
→ Validation / Machine Review
→ Gap / Conflict
→ Candidate（+ base epoch）
→ Human Batch Review
→ Release R1
→ Query R1
→ Batch 2
→ Incremental Update
→ Release R2
→ Query R2
→ Rollback R1
```

### 8.5 MVP 不做

- 全量几十万材料；
- 所有业务域；
- 完整 Concept/Sense；
- 完整修改历史；
- 逐页社区编辑；
- machine_auto；
- 完整双时态查询；
- 多区域 HA；
- 全量 Agent 生态。

---

## 9. 企业级版本是什么

### E1：语义编译器生产化

产品目录；ProductVersion；Schema Registry；Template Catalog；材料分类；
TrustPolicy；多领域抽取；Evidence；Gap/Conflict；编译任务；Canonical Golden；
模型升级门禁。

### E2：知识治理

Concept/Sense；Wiki Lint；批次 diff；Conflict/Gap workbench；审核台；changelog；
修改提案（P10，DEFER）；修改历史；贡献者；讨论和审批；紧急撤回；ACL 漂移治理。

### E3：Agent 和应用

Active Query；MCP；结构化规则；产品比较；图谱关系；citation；Evidence；
insufficient/needs_qualification；feedback。

### E4：规模化运营

几十万材料；增量 backfill（含既有 stock_backfill 资产）；micro-batch；
retry/replay；dead letter；capacity；partition；retention/GC；SLO；cost；
shadow/canary；machine_auto；多 Space、多租户。

---

## 10. 已经完成了什么

### 10.1 已完成的方案收敛（v1 + v2）

v1 收敛：

- 明确项目不是普通 RAG；
- 明确 LLM Wiki 是核心方法论；
- 明确 WeKnora 和 Harness 的职责；
- 明确 WeKnora 为唯一 Active Release；
- 否决双系统投影；
- 明确 Release Kernel；
- 明确 Claim/Relation/Evidence；
- 明确 ProductVersion 是 P0；
- 明确弱模型抽取和独立校验；
- 明确 Gap 定向补抽；
- 明确六类变化动作；
- 明确 Candidate batch 审核；
- 明确 human_batch-first；
- 明确材料自动分类和字段级 TrustPolicy；
- 明确双时态兼容；
- 明确修改历史后置；
- 明确 Golden；
- 明确 MVP 数据和页面规模；
- 明确 MVP 和企业版边界；
- 明确旧资产迁移原则。

v2 追加收敛：

- 精确界定"被否决的是什么"（§0.1 / 需求 §5.6）；
- 权威位置的第一性原理论证 + 代价清单；
- Release Kernel 改为"先能力矩阵后定表"；
- `PublishedPayloadEnvelopeV1` 七字段信封 + canonical member 合同；
- `subject_ref` 恒等规则显式废止，新不变量确立；
- Metric ID 合同 + 已测基线写入（calibration-only）；
- 两级里程碑 S0 / MVP-728（历史，v3 已精化）；
- 五档能力台账（唯一 DELETE 为 Projector）；
- 七条 P0 合同（历史，v3 已重排为十条）；
- 四层文档治理 + ADR 不占 OpenSpec 编号；
- 过程护栏继承 + Mission Card 保留原名；
- Amendment 1 逐项去向；
- 三道开工前门禁。

v3 追加收敛：

- 单一 Active 原则正式接受，WeKnora 载体条件接受；
- ADR 立即写为 `Accepted Conditionally`；
- S0 拆为 S0-R / S0-Q，分别验证发布与质量；
- 一个 Space 在 MVP 中只绑定一个 release-managed Wiki KB；
- Claim identity / comparison / comparator 合同；
- PublishAuthorization 完整绑定；
- 删除、撤回、retention、legal hold、legal erasure 分义；
- 双基线上游能力矩阵；
- weak-model 共同瓶颈结论降级为假设，并增加消融实验；
- 十条 P0 合同。

### 10.2 已完成的文档

- `jlx_enterprise_llm_wiki_requirements_728.md`；
- `jlx_enterprise_llm_wiki_technical_solution_728.md`；
- `jlx_enterprise_llm_wiki_challenges_728.md`；
- `mvp_handoff_jlx.md`；
- `jlx_enterprise_llm_wiki_complete_728.md`（v1）；
- `jlx_enterprise_llm_wiki_complete_728_v2.md`（上一版）；
- `jlx_enterprise_llm_wiki_complete_728_v3.md`（本文）。

### 10.3 没有完成或没有在本轮验证的内容

- **[未核验]** WeKnora 最新主线 exact capability（门禁一未完成）；
- **[未核验]** P1/P3 接口是否隐含 Harness serving；测试是否把 Harness reader
  当线上读取；publisher 是否与 Candidate lifecycle 耦合；status/receipt 是否以
  旧 Snapshot 为领域结果；对外 API 是否暴露 `current_release`；
- **[未核验]** Evidence 语义支持率；
- 未执行 WeKnora 升级；
- 未写条件接受 ADR / Amendment 2 / S0-R 与 S0-Q OpenSpec；
- 未实现 Release Kernel；
- 未实现 S0-R、S0-Q，也未实现 MVP-728；
- 未建立 Canonical Golden；
- 未运行端到端验收。

**不要把文档完成误写成产品能力完成。**

### 10.4【v2 新增】已核验的仓库事实（可直接引用）

| 事实 | 状态 |
|---|---|
| 已合入能力项：任务运行时 + 事务 Outbox、Canonical Envelope、容量合同、Revision 合同 spike 与实现、API/Worker shell、ProductVersion resolver（exact 层）、只读 fence verifier | **[已核验]** |
| Space 安全边界为**规格已合入、实现被阻断** | **[已核验]** |
| `active_release` 在 Harness 源码与迁移中出现 0 次 | **[已核验]** |
| 旧 018 路线的 `current_release` / `snapshot_facts` / `release_operations` / `publish_attempts` / `reconciliation_jobs` 存在，且在旧设计下即已判定被取代/废弃 | **[已核验]** |
| Canonical Envelope 含 `HASH_SCHEMA_VERSION = "1"` 与 domain-separated `canonical_hash` | **[已核验]** |
| 项目 `000066` 与上游 `000066` 同号不同义 | **[已核验]** |
| 当前 trusted 运行制品不含项目已合入的 revision 合同 | **[已核验]** |
| 已合入能力项中**没有任何一项产出用户可见的知识输出** | **[已核验]** |
| micro F1 0.231 / 值一致率 0.273 / 引文回验 1.000（calibration-only） | **[已核验]** |

---

## 11. 当前卡在哪里

当前不是卡在某个具体代码 Bug。

真实状态：

1. 单一 Active 原则已接受，WeKnora 载体经复评后改为条件接受；
2. MVP 前置可行性门拆为 S0-R 与 S0-Q；
3. 能力处置已形成五档台账；
4. 指标证据清单已完成；双基线能力矩阵与代码台账未完成；
5. 下一步是写条件接受 ADR、Amendment 2，填两张表，并行启动 S0-R 与 S0-Q。

尚未解决的 P0：

- weak-model extraction 值一致性（0.273）；
- Evidence 语义支持（未测量）；
- 双基线上游 Release 能力矩阵（未核对）；
- Canonical Golden（未建立）；
- MVP 真实样本（业务输入，未齐备）；
- Release Kernel（未实现）；
- S0-R 发布纵切与 S0-Q 质量纵切（均未实现）。

### 11.1【v2】卡点的性质变化

v1 时的卡点是“要不要继续双系统投影”。这个问题已经关闭。v3 不重开双 Active，
但不再把 WeKnora 载体当作无条件事实。

**当前卡点是条件接受的证据尚未形成**：双基线能力矩阵、代码台账、S0-R 和
S0-Q。质量线不受上游矩阵阻塞；S0-R 的物理实现受矩阵约束。

---

## 12. 下一步计划

### Step 0【v2 新增】：并行启动质量线（不等任何门禁）

```text
真实样本
→ Seed Golden
→ 错误分桶
→ 候选区域定位
→ 字段小任务
→ Schema / typed output / comparator
→ deterministic validation
→ Evidence semantic verification
```

**理由**：架构切换不改变 0.231。这条路径的每一步都不依赖 Release Kernel。

### Step 1：立即写条件接受 Authority ADR

载体：`docs/superpowers/specs/2026-07-28-weknora-sole-release-authority-adr.md`
+ 决策记录 `D-2026-07-28-1`。

状态写为 `Accepted Conditionally`。无条件冻结的是：只有一个 Active Release
权威；Harness 无第二 Active Head；正式消费必须 pin release_id。条件接受的是：
WeKnora 作为该权威的物理载体，须通过双基线能力矩阵和 S0-R。

**不冻结物理表数量。不占 OpenSpec 编号。**

### Step 2：写 033 Amendment 2

内容：

- 显式废止旧权威方向裁决；
- 五档能力台账（唯一 DELETE 为 Projector）；
- Amendment 1 逐项去向（含 `subject_ref` 部分废止及其保留部分）；
- 已合入代码如何重新归位；
- 继承 G0 门禁结构与已测基线（Metric ID 合同）；
- 保留全部过程护栏。

### Step 3：填两张表（门禁二、门禁一）

- 代码状态台账：关闭 5 项 [未核验] 条目；
- 上游双基线 Release Capability Matrix：17 行，同时比较稳定
  `v0.7.1/c64a486` 与 `80a5003`，每行带 exact 证据位置。

**门禁一完成前不写 Release Kernel 实施规格，不新增 project-owned WeKnora
migration。**

### Step 4：起草 S0-R 与 S0-Q OpenSpec + Mission Card

- 两个 scope 分开验收、分开记状态；OpenSpec **先占号后建目录**；
- Mission Card 保留原名，可由同一 program 统筹，但不能合并 PASS 判定；
- S0-Q 固定四字段；S0-R 可用 fixture Candidate。

### Step 5：并行实现并验收 S0-R / S0-Q

分别只能得到 `RELEASE_PATH_FEASIBLE` 与
`KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`。任一路径 FAIL 都先处理
证伪结果；两者都 PASS 才进入 MVP-728。

### Step 6：写 Release Kernel 实施规格（门禁一之后）

面积由能力矩阵决定。必须包含防绕过 guard 与 Go 端 canonical adapter（跑同一
vectors）。

### Step 7：MVP-728 实施与验收

按纵向闭环拆，不按横向框架拆。每项必须回答：业务价值；exact 输入输出；错误
状态；Golden；验收命令或场景；是否影响权威边界；是否增加长期复杂度；本阶段
质量证据的 Metric ID。

**MVP-728 不得在 §8 NFR-08 十条 P0 合同未关闭时宣称通过。**

---

## 13. 绝对不要再踩的坑

### 13.1 不要再做双系统 Active 投影

可以有准备区、缓存、索引和可重建视图，但不能有两个正式 Active Head。

### 13.2 不要把所有东西都塞进 MVP

完整修改历史、Concept/Sense、machine_auto、几十万规模、多区域、完整 Agent
生态后置。

### 13.3 不要做过渡性架构

MVP 使用最终权威边界。通过缩小数据、领域、Schema 和页面实现速度，而不是先做一个
以后必须推翻的双系统。

### 13.4 不要只看代码量和底层原语

MVP 的唯一有效证据是纵向链路：

```text
Source
→ Claim/Evidence
→ Gap/Conflict
→ Candidate
→ Review
→ Release
→ Query
→ R2
→ Rollback
```

> **[v2 已核验]** 这条坑已经踩过：已合入能力项没有一项产出用户可见知识输出。

### 13.5 不要忽略抽取准确率

抽取、Evidence、ProductVersion 和 Golden 是项目核心，不是后续优化项。

### 13.6 不要让模型直接生成正式页面

先抽结构化 Claim/Relation/Evidence，再确定性编译页面。

### 13.7 不要依赖强模型在线兜底

强模型用于离线 Seed Golden 和评估；生产按弱模型能力设计。

### 13.8 不要把向量相似度当实体确认

向量召回候选，确定性标识和 resolver 决定 ProductVersion。

### 13.9 不要把一个来源权威分用于所有字段

TrustPolicy 必须字段化、版本化、场景化，且只有一个名称与一个求值入口。

### 13.10 不要把 unknown 当 absent

缺材料时保持 unknown，Schema 缺口触发定向补抽。

### 13.11 不要每批材料全量重跑

计算影响范围，使用 GapTask 和 ChangeSet 做增量更新。

### 13.12 不要把不同值全部当冲突

先比较实体、版本、时间、地区、渠道、人群和条件。

### 13.13 不要让审核变成逐页面点击

审核绑定 CandidateRelease，页面只是预览和定位。

### 13.14 不要让 Agent 绕过正式 Release

原始 chunk 用于证据核查和补编，不直接成为正式答案旁路。检索层也必须
release-aware。

### 13.15 不要在发布后忽略 ACL

读取时重新校验当前 ACL；权限收缩时 fail closed；且不得经 Claim/excerpt/页面
发生权限放大。

### 13.16 不要把回滚实现为重新生成

回滚是原子切换到历史不可变 Release，整版粒度，不支持单页 cherry-pick。

### 13.17 不要被沉没成本绑架

旧资产要吸收，错误的权威边界和运行时不要保留。

### 13.18 不要每个新会话重新发明架构

新会话先读本文和配套文档。若要推翻已确认结论，必须给出清晰证据和复杂度评估，
并说明改哪条决策、为何原决策不成立、新增多少复杂度、对 MVP 有什么直接价值、
是否导致推倒重来。

### 13.19 不要把方案文档当实现验收

下一阶段必须做代码映射和真实 MVP 验证。

### 13.20【v2 新增】不要在上游活动区域自建同号 migration

**[已核验] 已发生一次。** 官方链与企业链必须独立 ledger；不得静默重命名或删除
legacy 编号；必须有编号 × schema object × patch surface 三层碰撞 CI；能力矩阵
填完前不新增 project-owned WeKnora migration。

### 13.21【v2 新增】不要用裸数字传递质量结论

**[已核验] 已发生一次**（两份报告的 `0.231` 含义不同）。所有质量数字必须带
Metric ID 合同，包含 scope 与 admission_status。

### 13.22【v2 新增】不要按编号而非按能力做取舍

**[已核验] 差点发生。** 架构切换必须按能力分档
（`KEEP / REWIRE / SUPERSEDE / DEFER / DELETE`）。

### 13.23【v3 重写】不要把 S0-R 或 S0-Q 当作 MVP

S0-R 只证明发布路径可行，S0-Q 只证明窄切片知识编译可行。任一通过都不能证明
增量补缺、六类变化动作、版本串扰、Candidate 批审适用性、R2 混版或 rollback；
两者都 PASS 也只是允许进入 MVP-728，不是 MVP 已通过。

### 13.24【v2 新增】不要在未核对上游能力前冻结 Release Kernel 表结构

先填能力矩阵。真正可能被上游消掉的是自建 PageRevision、单页 history/diff、
部分 preparation 存储；不可能被消掉的是整版 manifest、唯一 Head、epoch/CAS、
整版 rollback、SourcePin、幂等 receipt。

### 13.25【v2 新增】不要把逐字引文回验当作 Evidence 正确

引文回验 1.000 只证明"这段话在原文里"，不证明"这段话支持这条 Claim 的主语/
字段/条件/时间"。二者是两个独立指标。

---

## 14. 接手者必须保持的词义

### 投影

将一个系统中的权威状态复制为另一个系统中的读模型或页面。

### 不做双系统投影

不是不在 WeKnora 显示页面，也不是不复制任何数据，而是**不让 Harness 维护第二个
ActiveRelease**。跨系统发布与 payload 物化仍然存在。

### SourceRevision

可冻结、可引用、可定位的原始材料版本。

### Claim

某实体、字段、条件、时间下的结构化事实。其 subject 不必是 ProductVersion，但
产品特定事实必须约束到某个 ProductVersion。

### Evidence

支持 Claim 的 exact SourceRevision 位置和内容快照。**逐字回验与语义支持是两个
不同概念。**

### Gap

根据 Schema、关系或反馈发现的可执行知识缺口。

### Conflict

在同一实体、版本、时间和适用范围中存在不可兼容 Claim。

### CandidateRelease

冻结、可审核、尚未上线的一整批知识版本。必须同时冻结 base release_id 与
base activation_epoch。

### Active Wiki Release

WeKnora 中唯一对人和 Agent 正式提供的线上知识版本。

### Pinned Read

一个请求从开始到结束固定使用同一 release_id，检索层同受约束。

### 回滚

把 Active Head 原子指向历史不可变 Release。整版粒度，不支持单页 cherry-pick。

### human_batch

人对 Candidate 批次做最终审核，不是逐页面审核。

### machine_auto

在 exact scope 和质量准入下无人发布；不属于 MVP。

### canonical member【v2】

Release 中 Claim/Relation/Evidence 的唯一权威成员。页面 payload 中的快照必须
能证明来自同一 canonical member digest。

### S0-R / RELEASE_PATH_FEASIBLE【v3】

发布可行性纵切。证明当前 WeKnora 载体和最小 Release 协议在窄范围可实现，不表示
知识质量达标或 MVP 成功。

### S0-Q / KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE【v3】

质量可行性纵切。证明弱模型在四字段窄切片上经 Schema/Evidence/校验可形成可用
知识，不表示发布架构成立或企业级质量达标。

### 五档台账【v2】

`KEEP / REWIRE / SUPERSEDE / DEFER / DELETE`。架构切换按能力分档，不按编号
批量取消。

### Metric ID 合同【v2】

质量数字必须绑定 report path、commit、dataset id、evaluator version、metric
definition、分子/分母、scope、admission_status。

### calibration-only【v2】

离线校准测量。可用于定位问题与标定阈值，**不得授予任何验收状态**。

---

## 15. 接手者的第一周建议

### 第一天

- 完整阅读本文与配套文档，特别是 §0.1、§0.2、§6A；
- 输出疑问和冲突清单；
- 不立即改代码；
- 不重开已经确认的词义与权威方向。

### 第二天

- 由业务和架构共同评审；
- 确认 MVP 产品族和字段；
- 确认两批材料构成；
- 确认 Seed Golden 标注格式；
- 确认 S0-Q 的四字段与 S0-R 的 fixture Candidate。

### 第三天

- 填双基线上游 Release Capability Matrix（门禁一），每行带 exact 证据位置；
- **[v2]** 填代码状态台账（门禁二），关闭 5 项未核验条目。

### 第四天

- 写 Authority ADR 与 033 Amendment 2；
- 拆 S0-R、S0-Q 与 MVP-728 的纵向任务；
- 为每项写 exact acceptance；
- 定义 R1/R2/rollback 演示脚本。

### 第五天

- 确认实施顺序；
- 起草 S0-R / S0-Q OpenSpec（先占号）+ Mission Card；
- **[v2]** 质量线已在第一天就并行启动，不等到此时。

---

## 16. 外部模型评审提示词

可直接把文档交给其他模型，并要求：

```text
请从企业级寿险知识基础设施的第一性原理评审这些文档。

重点判断：
1. WeKnora 作为唯一在线 Wiki Release 权威是否合理；
2. Python Harness 的领域编译职责是否清楚；
3. 是否彻底避免了双系统 Active 和长期投影一致性；
4. 弱模型抽取、ProductVersion、Evidence、Gap、Conflict、Golden 是否足以形成核心壁垒；
5. MVP 是否足够小，但能验证最高风险问题；
6. 企业版路线图是否遗漏关键治理、安全、运营能力；
7. 双时态、审核、回滚和 ACL 设计是否合理；
8. 哪些地方仍然过度设计；
9. 哪些地方可能导致未来推倒重来；
10. 请把建议分为"必须修改、建议修改、企业版后置、不同意"，并说明理由和复杂度。

v3 专属追问：
11. §5.6 对"被否决的究竟是什么"的精确表述是否成立；
12. §7.10 双基线上游能力矩阵的 17 行是否完整，稳定版优先规则是否合理；
13. §8 NFR-08 的 10 条 P0 合同是否完整且没有把企业版实现塞入 MVP；
14. canonical member 合同是否足以防止同一事实多份真相；
15. PublishedPayloadEnvelopeV1 是否泄漏寿险语义到上游；
16. FR-05.1 的新 subject 不变量是否覆盖寿险全部事实形态；
17. 五档台账是否有错档（特别是 P11 的拆分与 P10/P14 的 DEFER）；
18. S0-R / S0-Q 的边界、状态和联合门禁是否足以防止假阳性；
19. Metric ID 合同是否足以防止裸数字误读；
20. 在 F1 基线 0.231（calibration-only）前提下，S0-Q 的四字段与消融实验能否
    回答弱模型可行性；
21. `WEKNORA_AS_AUTHORITY_CARRIER = ACCEPTED_CONDITIONALLY` 的证伪条件是否
    足够明确；
22. Claim identity、完整授权绑定和 legal erasure 合同是否可实现且不过度设计。

不要仅按现有代码或沉没成本评价，也不要建议重新引入第二 Active 权威，除非能证明
单一 Release 架构不成立。
若要推翻已确认结论，必须说明：改哪条决策、为何原决策不成立、新增多少复杂度、
对 MVP 有什么直接价值、是否导致推倒重来。
```

---

## 17. 文件导航

- 总体需求与验收：`jlx_enterprise_llm_wiki_requirements_728.md`
- 完整技术方案：`jlx_enterprise_llm_wiki_technical_solution_728.md`
- 技术难点与核心问题：`jlx_enterprise_llm_wiki_challenges_728.md`
- 本交接文档：`mvp_handoff_jlx.md`
- 完整合订本 v1：`jlx_enterprise_llm_wiki_complete_728.md`
- 完整合订本 v2（上一版）：`jlx_enterprise_llm_wiki_complete_728_v2.md`
- **完整合订本 v3（当前）**：`jlx_enterprise_llm_wiki_complete_728_v3.md`

实施侧载体（尚未创建）：

- Authority ADR：`docs/superpowers/specs/2026-07-28-weknora-sole-release-authority-adr.md`
- 决策记录：`D-2026-07-28-1`
- 033 Amendment 2
- 状态台账（控制板）
- 上游能力矩阵
- S0-R / S0-Q OpenSpec（先占号）+ Mission Card

---

## 18. 当前状态块

### 当前任务

完成 728 v3 合订本，交付外部复评。

### 已完成

- 架构收敛（含 v2 三轮评审与 v3 Codex/Web 复评）；
- 单一 Active 原则接受，WeKnora 载体条件接受；
- MVP 前置门拆为 S0-R / S0-Q；
- 五档能力台账（唯一 DELETE 为 Projector）；
- 十条 P0 合同；
- payload 信封与 canonical member 合同；
- `subject_ref` 恒等规则废止与新不变量；
- Metric ID 合同与已测基线写入；
- 四层文档治理与编号纪律；
- 过程护栏继承；
- Amendment 1 逐项去向；
- 三道开工门禁定义（其中指标证据清单已完成）。

### 当前卡点

无架构层技术阻断。

待完成：

- 门禁一：双基线上游 Release Capability Matrix（17 行，**未核验**）；
- 门禁二：代码状态台账剩余 5 项（**未核验**）；
- 条件接受 ADR / Amendment 2 / S0-R / S0-Q OpenSpec / Mission Card 尚未撰写；
- Canonical Golden 与 MVP 真实样本（业务输入）；
- Evidence 语义支持率尚未测量。

### 下一步

1. 写 `Accepted Conditionally` ADR + Amendment 2；
2. 质量线立即并行启动（不等上游矩阵）；
3. 填两张表；
4. S0-R / S0-Q OpenSpec + Mission Card；
5. 并行实现并分别验收 S0-R / S0-Q；
6. 门禁一之后写 Release Kernel 规格；
7. 两者均 PASS 后进入 MVP-728。

### 最重要提醒

```text
不要再把 Harness ActiveRelease → WeKnora managed Wiki 投影作为默认架构。
不要用更多框架代码替代抽取准确率、Evidence、增量冲突和 R1/R2/rollback 的实际证明。
不要把 S0-R 或 S0-Q 当作 MVP。
不要按编号取消能力项。
不要写裸数字。
不要在填完能力矩阵前冻结 Release Kernel 表结构。
架构切换不会把 0.231 变成 0.95——质量线必须并行。
```

---

## 19. 交接结论

新会话接手时，不需要从"我们是不是要做一个 Wiki"重新讨论，也不需要重开
"Active Head 应该放在哪里"。

已经确认的是：

> 我们要做 Enterprise LLM Wiki。线上只有一个 Active Release 权威；WeKnora
> 是该权威的条件接受载体，须经双基线矩阵和 S0-R 验证。Python Harness 承担
> 寿险知识编译和治理，且不保有第二 Active Head；
> Claim/Relation/Evidence 是事实核心；Candidate 是审核单元；Release 是人和
> Agent 的共同版本边界。S0-R 用 fixture Candidate 验证发布，S0-Q 用 2 份材料 /
> 4 个字段验证知识编译；两者都 PASS 后，MVP-728 再用 10–15 份代表性材料跑通
> 弱模型抽取、补缺、冲突、批审、R1/R2 和回滚。完整修改历史、Concept/Sense、
> machine_auto 和大规模运营在企业阶段逐步完成。

下一位接手者的第一项工作不是继续堆代码，而是：

1. 让用户和外部评审者确认本文是否准确表达了项目目标；
2. 填两张表（双基线上游能力矩阵、代码状态台账）；
3. **同时立即启动 S0-Q**——因为架构切换不会改善 0.231；矩阵完成后启动 S0-R。

---

## 20【v3 重写】评审者速查：本版最需要被挑战的 10 个判断

供评审者优先攻击，每条都是可能出错且后果显著的判断。

| # | 判断 | 若判断错误的后果 |
|---|---|---|
| 1 | 单一 Active 原则与 WeKnora 条件接受载体的区分成立 | 把协议原则与产品选型混为一谈 |
| 2 | 集中、长期但可封顶的发布复杂度低于双 Active 的持续复杂度 | 发布路径成为新的长期负担 |
| 3 | Release Kernel 面积可通过复用上游显著缩小 | fork 面积失控，重演跟版困境 |
| 4 | 五档台账中只有 Projector 需要 DELETE | 误留死代码或误删有效资产 |
| 5 | `active_release` 出现 0 次 ⇒ 权威反转不新增代码报废 | 低估切换成本 |
| 6 | S0-R 与 S0-Q 能分别在短周期给出可判定结论 | MVP-728 的规模估计需整体重做 |
| 7 | 值一致性低主要来自共享工程瓶颈 | 若消融不支持，模型/任务范围判断错误 |
| 8 | 引文回验 1.000 说明 Evidence 机制已成立 | 可信度虚高，语义支持缺口被忽略 |
| 9 | 十条 P0 合同足以覆盖 MVP 的发布、身份、合规与权限正确性 | MVP 通过但生产出现混版、错并或越权 |
| 10 | 质量线与架构线可以并行且互不阻塞 | 资源分散，两条线都不成 |

**评审要求**：对每条给出"成立 / 不成立 / 需要补充证据"，并对"不成立"给出替代
方案与复杂度评估。

---

> **本文档结束。**
>
> 版本：728-v3 · 2026-07-28
> 上一版：`jlx_enterprise_llm_wiki_complete_728_v2.md`
> 变更摘要见 §0
> 本文不是代码 Review，不代表相应能力已经实现。
> 标注 **[已核验]** 的断言基于仓库 `main=e4039457`（2026-07-28）或指名报告；
> 标注 **[未核验]** 的必须在开工门禁中关闭，不得当作已知。

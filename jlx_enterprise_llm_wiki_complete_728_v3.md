# 企业级寿险 LLM Wiki：四文档完整合订本（JLX 728 · v3）

> 日期：2026-07-28
> 版本标识：728-v3
> 文档类型：完整合订本（第三版）
> 上一版：`jlx_enterprise_llm_wiki_complete_728_v2.md`（728 v2，2026-07-28）
> 整理依据：728 v2 全文 + Codex 第一性原理复评 + Web GPT 复核裁决
> 内容说明：本文逐字收录总体需求与验收口径、MVP + 企业级完整技术方案、技术难点与核心问题、项目交接文档，不做摘要式压缩。
> 独立文档与本文应同步维护。本文不是代码 Review，不代表相应能力已经实现。
> 阅读须知：v3 不推翻 v2 总体方向，而是把其从“最终冻结”调整为“有条件接受并可证伪”，同时补齐 Release 范围、质量门与关键合同。

---

# §M0 · 2026-07-29 执行修订（优先于本文历史状态）

本文原始评审基线为 2026-07-28。Mission 0 已核对后续仓库事实，以下内容优先于
正文中“尚未升级”“尚未选择 upstream”或“双基线选择矩阵”的历史表述：

- 本文是 informative 设计输入与历史合订说明，不单独授予实现权；规范层级为
  Sole Serving Active Release Authority ADR → Authority Amendment 2 → 适用
  OpenSpec；
- 单一 serving Active Release 原则保持 `ACCEPTED`；
- WeKnora 作为该 authority 的载体保持 `ACCEPTED_CONDITIONALLY`；
- 当前运行态是 `NO_PRODUCTION_ACTIVE_RELEASE`；目标 Release Kernel 未实现，
  P3 生产 Worker 未注册发布业务 Handler；
- upstream 选择已经完成：功能基线固定
  `80a5003cc99a427098afe184eee6601916d3d156`，不再重选 v0.7.1；
- trusted image 构建源码是
  `a8bf55ae18441abd380e594afba5000c51cc9633`；Mission 0 基线 main 是
  `529d72c994369750b26e352a70fd6284e8b0fd9d`，两者不得混写；
- source adoption、legacy `000066` bridge、trusted images 与 digest pin 已完成；
  Full Artifact/W1 runtime probes 和 `source_reader` authority 仍开放；
- 下一步填的是已采用 `80a5003` 的 Release capability gap matrix，不是版本选择
  矩阵；
- OpenSpec 043 保留 Space/principal/epoch/ACL/跨 Space/失败零写合同，但状态为
  `SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`，不得按旧 `wiki_projector`
  语义直接实现；
- MVP profile 是 `1 Space = 1 RAW KB + 1 release-managed Wiki KB`，不是永久
  企业 cardinality；
- S0-R 是输入就绪后的两工作日证伪窗口，只能输出
  `RELEASE_PATH_FEASIBLE` 或 `RELEASE_PATH_NOT_FEASIBLE`，不承诺两天交付生产
  Kernel；
- S0-Q 必须消费 WeKnora/W1 冻结解析制品或身份、digest、页码和表格结构完全
  冻结的等价制品，禁止用人工清洗 Markdown 绕过真实难度；
- S0 双 PASS 后只按首个纵切需要改接入口；legacy 物理清理不作为 MVP 前置。

正式执行裁决见：

- `docs/superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md`；
- `docs/superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md`。

---

# §0 v3 变更记录（评审者请先读本节）

## 0.1 v3 的产生过程

728 v2 完成后，Codex 从第一性原理独立复评，认可总体架构方向，但指出六类仍需
修订的问题：

1. 架构可立即记录，但 WeKnora 作为权威载体只能“有条件接受”，必须保留明确
   证伪条件；
2. 文档同时出现“Space 级整版发布”和 `(tenant, space, wiki_kb)` Head，Release
   原子范围不完整；
3. 当前最大存在性风险是知识编译质量，不应只有 Release 通电纵切；
4. `absent_explicitly` 与“证据不足的 unknown”被混为同一种负例；
5. canonical member 之外仍缺 Claim 身份、完整发布授权绑定、Retention/Legal
   Erasure 等合同；
6. 上游能力矩阵应同时比较正式稳定版与 post-release snapshot，不应提前锁定
   未发布主线。

Web GPT 对上述意见进行复核，认可度约 90%–95%，并做出一项关键修正：

> ADR 不需要等待所有验证完成后再写；应立即记录当前决策，但状态必须是
> `Accepted Conditionally`，并明确硬原则、当前载体、未决问题、证伪条件和回退
> 规则。

v3 采纳该复核意见。

## 0.2 v3 相对 v2 的实质修改

| 编号 | v2 | v3 |
|---|---|---|
| V3-01 | 架构方向被描述为“不再重开” | 单一 Active 原则 `ACCEPTED`；WeKnora 载体 `ACCEPTED_CONDITIONALLY` |
| V3-02 | 无明确证伪门 | 增加能力矩阵、S0-R、release-aware retrieval 三类载体证伪条件 |
| V3-03 | Space 级发布与 wiki_kb 级 Head 并存 | MVP 冻结“一个 Space 只绑定一个 release-managed Wiki KB” |
| V3-04 | 单一 S0 通电纵切 | 拆为 S0-R（Release 可行性）与 S0-Q（知识编译可行性） |
| V3-05 | S0 三字段、一个负例 | S0-Q 四字段：两个 present、一个 absent_explicitly、一个 unknown |
| V3-06 | 7 条 P0 合同 | 重排为 10 条 P0 合同，新增 Release 范围、Claim 身份、完整授权绑定，并重写删除语义 |
| V3-07 | 能力矩阵只面向 `80a5003` | 同时比较 `v0.7.1/c64a486` 与 `80a5003` |
| V3-08 | “值一致性是工程问题”作为结论 | 降级为“共同瓶颈假设”，必须通过消融实验确认 |
| V3-09 | Release Kernel 被称为一次性成本 | 改为集中、边界明确、长期存在的协议成本 |
| V3-10 | S0 完成即进入完整 MVP 的表达不够精确 | `S0-R PASS AND S0-Q PASS` 后才允许进入 MVP-728 集成开发 |

## 0.3 v3 正式状态

```text
SINGLE_ACTIVE_AUTHORITY_PRINCIPLE:
ACCEPTED

WEKNORA_AS_AUTHORITY_CARRIER:
ACCEPTED_CONDITIONALLY

RELEASE_KERNEL_PHYSICAL_DESIGN:
PENDING_DUAL_BASELINE_CAPABILITY_MATRIX

KNOWLEDGE_COMPILATION_FEASIBILITY:
PENDING_S0_Q

RELEASE_PATH_FEASIBILITY:
PENDING_S0_R

MVP_728_INTEGRATION:
BLOCKED_UNTIL_S0_R_AND_S0_Q_PASS
```

## 0.4 不变的硬原则

- 正式线上知识只能有一个 serving Active Release 权威；
- 不允许 Harness 与 WeKnora 同时拥有正式 Active Head；
- 即使 WeKnora 载体假设被证伪，也不得自动退回双 Active；
- Claim / Relation / Evidence 仍是事实核心；
- Candidate 批次仍是审核单元；
- human_batch-first、弱模型优先、双时态兼容、修改历史后置均不改变。

---

# §0A v2 变更记录（历史，评审者可追溯）

## 0.1 本版产生的过程

728 v1 完成后，该文档被交给两个独立强模型评审，形成三轮往返：

1. 第一轮：评审 A 判断 v1 的架构方向成立，但指出四类问题——Release Kernel
   成本被低估、仍存在数据物化（不是"消灭了投影"）、丢失了已有质量基线与过程
   护栏、状态台账为空即宣称切换代价低；
2. 第二轮：评审 B 同意其中三类，纠正四处（G0 指标口径、上游 PageRevision 不
   等于整版 Release、`subject_ref` 全域规则、极薄切片不能替代正式 MVP），并
   提出四层文档治理结构；
3. 第三轮：评审 A 接受全部纠偏，反向纠正评审 B 两处（ADR 不占 OpenSpec 编号、
   Mission Card 不在架构变更中夹带改名），并补充仓库已核验事实；评审 B 最终
   纠正评审 A 一处实质错误——**不得按 P 编号笼统取消能力项**。

三轮结束后不再重开"Active Head 应该放在哪里"这一层总体架构讨论。

## 0.2 v2 相对 v1 的实质修改清单

| 编号 | v1 的表述 | v2 的表述 | 证据状态 |
|---|---|---|---|
| C-01 | "明确否决双系统投影"，读作已消除数据复制 | 消除的是**第二个可变 Active Head + 长期异步对账**；跨系统发布与数据物化仍然存在，由发布协议加栅栏 | 概念澄清 |
| C-02 | Release Kernel 列出 7 类对象，读作必须新建 | **先填上游能力矩阵，再定物理表**；本文只冻结 Release 不变量，不冻结表数量 | 上游能力**未核验** |
| C-03 | 结构化 payload 字段清单 | 定为 `PublishedPayloadEnvelopeV1`（7 字段，含 `canonicalization_version` / `semantic_contract_hash`）+ canonical member 合同 | 底座已存在（已核验） |
| C-04 | Claim 同时有 `subject_ref` 与 `product_version_ref`，未说明与旧裁决冲突 | 显式废止"`subject_ref` 恒等于 `product_version`"，新不变量见 §7 FR-05 | 旧裁决已核验 |
| C-05 | "阈值应由 Golden 与业务风险共同确定"，无历史数据 | 引入 **Metric ID 合同**并写入已测基线（calibration-only） | 数字已核验 |
| C-06 | 单级 MVP | **两级**：S0 通电纵切 → MVP-728 Core Acceptance | 范围裁决 |
| C-07 | §14.3 代码现状映射为空表 | 五档台账 `KEEP / REWIRE / SUPERSEDE / DEFER / DELETE`，并填入已核验部分 | 部分已核验 |
| C-08 | 无过程章节 | 新增过程护栏继承章节（停线、单迁移、双独立评审、并发测试、Mission Card） | 治理规则已核验 |
| C-09 | 五份文档自成权威 | 四层文档治理：728 / ADR / 033 Amendment 2 / 状态台账 | 载体裁决 |
| C-10 | 未提 Amendment 1 | Amendment 1 逐项去向表 | 已核验 |
| C-11 | §12.1 "参考 WeKnora 最新版本" | 锁定 exact upstream identity 并说明已发生的 `000066` 撞号 | 已核验 |
| C-12 | 未列发布前必须解决的合同 | 新增 7 条 P0 合同（§8 NFR-08 与难点文档 §22） | 合同清单 |

## 0.3 v2 明确**没有**改变的内容

- WeKnora 是唯一在线 Active Wiki Release 权威；
- Harness 不保有第二个 Active Head；
- Claim / Relation / Evidence 是事实核心，页面不是事实源；
- Candidate 批次是审核单元，不逐页点击；
- 新 Space 默认 `human_batch`，`machine_auto` 后置；
- 弱模型优先、强模型仅离线；
- 数据模型第一版兼容双时态，MVP 只做 `current / as_of_date / release_id`；
- 修改历史必须做但后置；
- MVP-728 的正式验收范围（10–15 份材料、两批次、R1/R2/rollback）。

## 0.4 证据状态图例

本文对每一处涉及"当前实际情况"的断言使用统一标注：

- **[已核验]**：本轮已在仓库 `main=e4039457`（2026-07-28）或指名报告中直接读取确认；
- **[未核验]**：尚无证据，必须在开工门禁中核对，不得当作已知；
- **[待核对]**：有证据但来自不同快照/不同口径，须绑定 exact 身份后使用。

未标注者为目标设计陈述，不表示已实现。

---

# 企业级寿险 LLM Wiki：总体需求与验收口径（JLX 728 · v3）

> 日期：2026-07-28
> 版本标识：728-v3
> 文档类型：总体需求文档
> 整理依据：2026-07-28 讨论窗口 + 三轮 v2 评审 + Codex/Web GPT v3 复评裁决
> 适用读者：业务负责人、产品经理、架构师、研发、测试、知识运营、外部评审模型
> 重要说明：本文只整理已经讨论和确认的需求，不代表相应代码已经完成，也不是代码 Review 结论。

---

## 1. 文档目的

本文回答以下问题：

1. 我们究竟要建设什么；
2. 为什么现有"文档库 + chunk + RAG"不能解决问题；
3. WeKnora、Python Harness、LLM Wiki 方法分别承担什么职责；
4. MVP 必须验证什么，什么明确不进入 MVP；
5. 企业级完整版本最终要具备哪些能力；
6. 如何判断 MVP 和企业版本是否真的成功；
7. 哪些业务和技术边界已经确认，不应在后续执行中被重新解释。

本文与另外四份文档配套：

- `jlx_enterprise_llm_wiki_technical_solution_728.md`：技术实现方案；
- `jlx_enterprise_llm_wiki_challenges_728.md`：技术难点与核心问题；
- `mvp_handoff_jlx.md`：无上下文接手文档；
- `jlx_enterprise_llm_wiki_complete_728_v3.md`：四份文档的完整合订本（本文）。

---

## 2. 项目背景

我们是一家大型寿险公司，长期积累了大量知识材料，覆盖但不限于：

- 产品条款、产品说明书、产品宣传材料；
- PDF、PPT、Word、表格、FAQ；
- 销售、客户经营、销售经验；
- 理赔、核保、保全；
- 权益、产品服务；
- 医学术语、疾病定义、核保结论；
- 历史知识库中的文档片段和 chunk；
- 不同系统、不同团队、不同时间维护的零散文本。

材料总量未来可能达到几十万份文档或文档片段。当前知识主要以"文件、文档片段、检索切片"的形式存在，虽然可以被搜索或用于 RAG，但没有形成可以持续维护、自动演进、明确版本、可靠引用的知识体系。

---

## 3. 当前业务问题

### 3.1 知识静态，入库后基本不再演进

1. 业务规则持续变化，知识入库后却被"封存"；
2. 除非人工重新整理，否则新材料不会自动补充旧知识；
3. 答错一次以后，平台不会自动把问题反馈到知识维护流程；
4. 产品责任、理赔规则、服务权益发生变化时，难以确认哪些知识应该更新；
5. 旧版本和新版本之间缺乏明确关系，容易混用。

### 3.2 知识仍停留在文档和片段层

1. 同一概念散落在多份材料中；
2. 同一产品的责任、除外、等待期、核保规则缺少统一组织；
3. 不同产品、不同版本、不同适用范围之间缺少关系；
4. 多份材料对同一事实口径不一致时，平台不会系统性发现和处理；
5. "在线问诊"等跨产品复用概念没有独立概念页和分产品义项；
6. 专家难以看到知识全貌，也难以知道哪些已覆盖、哪些缺失、哪些重复。

### 3.3 知识加工准确率低且不可证明

1. 复杂条款 PDF、跨页表格、嵌套条件、脚注和限定语容易被抽错；
2. 弱模型容易遗漏条件、混淆实体、错误归属产品版本；
3. 当前抽取准确率相当低，而准确率是项目是否有价值的关键；
4. 抽取结果缺少稳定的 Evidence，无法回到原文核验；
5. 没有独立校验机制时，模型可能既负责抽取又负责自我证明；
6. 没有稳定 Golden Set 时，切换模型或提示词无法判断是否真正变好。

> **v2 补充 [已核验]**：第 3 点"准确率相当低"已有量化测量，见本文 §10.2.1
> Metric ID 合同。当前实测严格口径 micro F1 合计 `0.231`，距 G0b 目标
> （precision ≥0.95 / recall ≥0.90）约 3–4 倍，报告结论为"不是调参距离，
> 是结构距离"。该测量为 calibration-only，不构成任何验收结论。

### 3.4 知识更新、冲突和缺口发现依赖人工

1. 第二批、第三批材料无法稳定补充第一批未抽到的字段；
2. 缺少字段后往往只能全量重跑，而不能定向反查；
3. 冲突发现晚，通常依赖人工抽检；
4. 平台不知道 Agent 答过什么、哪里答错、哪里证据不足；
5. 没有自动反馈飞轮，知识更新严重滞后；
6. 错误更新后缺少整版回退机制。

### 3.5 企业治理能力不足

1. 人和 Agent 可能读到不同版本或不同口径；
2. 页面更新过程中可能出现半新半旧的混版；
3. 权限变化后，已发布知识和 Evidence 可能继续暴露；
4. 审核若按页面逐个点击，面对大规模知识无法运营；
5. 需要保留版本、审核、发布、回滚和后续修改历史；
6. 需要明确原始材料、编译知识和线上发布版本各自的权威边界。

---

## 4. 项目目标

### 4.1 一句话目标

在 WeKnora 企业平台之上，建设一套面向寿险业务的 Enterprise LLM Wiki，把原始材料持续编译为：

- 有明确实体；
- 有适用产品和产品版本；
- 有业务时间；
- 有来源证据；
- 有冲突和缺口治理；
- 有可配置机器审核和人工批审；
- 有不可变版本；
- 可整版发布和回滚；
- 可供人和 Agent 使用；
- 可基于新材料和反馈持续演进；

的企业知识基础设施。

### 4.2 项目不是什么

本项目不是：

- 普通文档库；
- 只做向量检索的 RAG；
- 让模型直接把文档改写成 Markdown 页面；
- 把 `nashsu/llm_wiki` 原样搬入企业平台；
- 在 Harness 和 WeKnora 中各维护一套 Active Wiki；
- 通过长期异步投影维持两个线上权威；
- 一开始就覆盖所有寿险领域和几十万材料；
- 用强模型在线兜底掩盖弱模型生产问题。

### 4.3 项目核心价值

项目的核心价值不是"多生成一些 Wiki 页面"，而是建立一条可证明、可维护、可演进的知识编译链：

```text
原始材料
→ 可冻结的 SourceRevision
→ 寿险 Schema / Template
→ Claim / Relation / Evidence
→ 校验 / 缺口 / 融合 / 冲突
→ Candidate
→ 可配置审核
→ 唯一 Active Wiki Release
→ 人和 Agent 同版本消费
→ 新材料和反馈驱动下一版
```

---

## 5. 已确认的总体边界

### 5.1 WeKnora 的定位

WeKnora 是：

- 企业平台底座；
- 文档接入、解析、OCR、chunk 和检索平台；
- 原始材料及其 SourceRevision 的权威载体；
- 租户、Space、知识库、ACL、审计和 API 平台；
- 人类浏览 Wiki 的载体；
- 唯一在线 Wiki Release 权威；
- 后续 Agent、Langfuse 和应用集成底座。

WeKnora 不负责理解全部寿险业务语义，也不应被改造成寿险规则引擎。

### 5.2 Python Harness 的定位

Python Harness 是：

- 寿险领域知识编译器；
- 材料分类和采信策略执行器；
- ProductVersion 和实体消歧层；
- Schema / Template 运行时；
- Claim / Relation / Evidence 抽取层；
- 独立机器校验层；
- 缺口识别、融合、冲突治理层；
- Candidate、审核策略和发布授权层；
- Golden Set 和质量评估层。

Harness 不再维护第二个线上 Active Wiki Head。

### 5.3 LLM Wiki 的定位

LLM Wiki 是项目核心方法论，不是独立线上系统。应吸收：

- Raw Sources / Wiki / Schema 三层思想；
- ingest / query / lint；
- 原子知识页；
- index / log；
- LLM 辅助维护、发现矛盾和缺口；
- 人机协作；
- 知识持续更新和演进。

但必须补齐企业级能力：

- ACL；
- 审计；
- 寿险 Schema；
- Evidence；
- 产品版本；
- 批次审核；
- 整版 Release；
- 原子激活；
- 回滚；
- Golden Set；
- 弱模型质量控制；
- 大规模增量编译。

### 5.4 权威边界

| 问题 | 唯一权威 |
|---|---|
| 原文内容是什么 | WeKnora SourceRevision |
| 谁可以查看原文和证据 | WeKnora 当前 ACL |
| 寿险知识如何抽取、归一、融合和审核 | Python Harness |
| 当前线上 Wiki 使用哪一版 | WeKnora Active Wiki Release |
| 人和 Agent 应使用什么知识 | 同一 Active Wiki Release |

### 5.5 明确否决的双系统投影

明确不采用：

```text
Harness ActiveRelease
→ 异步投影到 WeKnora managed Wiki
→ freshness 检查
→ fencing
→ 双 ACL
→ 对账和修复
→ 读取时在两个系统之间判断
```

原因：

- 产生两个 Active 权威；
- 需要处理迟到写、重复写、乱序、重放；
- 权限必须双重校验；
- 页面与 Evidence 可能混版；
- 需要长期 reconciliation；
- WeKnora 每次升级都可能增加跟版成本；
- 项目容易演变为长期维护 WeKnora fork；
- 开发资源被一致性机制消耗，反而削弱寿险抽取、冲突和评估这些核心能力。

### 5.6 【v2 新增】被否决的究竟是什么：精确边界

v1 的"不做投影"表述在评审中被指出容易误读。v2 明确区分：

**本方案删除的：**

```text
第二个可变 Active Head
长期异步 freshness 判定
迟到投影写保护
两个 serving authority 之间的对账与修复
读取时跨系统版本协商
```

**本方案没有删除、且必须正确实现的：**

```text
跨系统发布（Harness → WeKnora 一次性传输不可变发布制品）
数据物化（结构化 payload 落在 WeKnora 供 Agent 同版读取）
digest 校验
幂等键
CAS（compare-and-swap）
```

因此推荐的措辞不是"不做投影"，而是：

> **Harness 编译并冻结 Candidate，WeKnora 接收一个不可变发布制品并成为唯一
> 服务权威。**

它仍然是一次物化传输，但不是"另一个 Active 数据库向 WeKnora 异步投影当前
状态"。评审者判断本方案是否成立时，应针对这一精确表述，而不是针对"消灭了
所有数据复制"这一不成立的强主张。

### 5.7 【v2 新增】权威方向的第一性原理论证

为什么 Active Head 放在 WeKnora 而不是 Harness：

决定权威位置的问题不是"谁生产知识"，而是**谁服务读取、谁执行授权**。

- 人在 WeKnora UI 浏览；
- 原文与当前 ACL 在 WeKnora；
- Agent 平台在 WeKnora；
- 查询是高频操作；
- Candidate 发布是低频操作（按批次）。

把 Active Head 放在 Harness，等于让**每一次读**承担跨系统版本协商与双 ACL
校验；放在 WeKnora，只有**每一次发布**承担一次跨系统事务。用稀疏操作的复杂度
换取常态操作的简单性，是本决策的核心理由。

其代价必须被诚实记录：**WeKnora 侧需要承载整版 Release 语义与 pinned read，
patch 面积不为零**，见技术方案 §7 与 §7.10 能力矩阵。

### 5.8【v3 新增】条件接受、证伪门与回退规则

v3 将两个层次明确分开：

**已经接受的硬原则：**

```text
正式线上知识只能有一个 serving Active Release authority。
Harness 与 WeKnora 不得同时拥有正式 Active Head。
```

**有条件接受的实现载体：**

```text
当前选择 WeKnora 承担唯一在线 Active Release。
状态：ACCEPTED_CONDITIONALLY。
```

以下任一条件成立时，允许重新评估 serving authority 的承载位置：

1. 双基线能力矩阵证明 WeKnora 无法以有界 patch 实现整版 manifest、pinned read
   或 release-aware retrieval；
2. S0-R 证明整版原子激活、幂等或固定版本读取无法在可接受复杂度内实现；
3. Release Kernel 必须侵入寿险领域语义或持续修改大量上游核心路径；
4. 后续上游升级反复造成同区域大面积冲突，使跟版成本不可接受。

回退规则：

- 重新评估的是**单一 serving authority 的载体**；
- 不自动恢复 Harness Active + WeKnora Active 的双权威；
- 任何替代载体仍必须满足唯一 Head、整版不可变、pinned read、rollback 和当前
  ACL。

ADR 应立即创建，状态写为 `Accepted Conditionally`，通过载体证伪门后更新为
`Accepted`；不需要重新创建另一份 ADR。

### 5.9【v3 新增】Release 原子范围

MVP 与当前企业路线冻结以下产品约束：

```text
一个 LLM Wiki Space
只能绑定一个 release-managed Wiki KB。
```

建议绑定模型：

```text
KnowledgeSpaceBinding
  tenant_id
  space_id
  raw_kb_id                       // MVP exactly one，提供 Source
  release_managed_wiki_kb_id     // exactly one，承载正式发布知识
```

因此：

- MVP 中一个 Raw KB 向该 Space 提供 SourceRevision；
- 产品页、责任页、概念页和结构化 payload 全部进入同一个
  `release_managed_wiki_kb_id`；
- `(tenant_id, space_id, wiki_kb_id)` Head 在该约束下等价于 Space 的正式知识
  原子边界；
- Space 级发布和回滚不会跨多个 Head。

企业后续若出现“一个 Space 必须拥有多个 RAW KB 或多个正式 Wiki KB”的真实
需求，必须另开 ADR、OpenSpec 和 migration；多个正式 Wiki KB 还需引入
`SpaceRelease` 聚合多个 `WikiKBRelease`。这些能力不进入 MVP-728。

---

## 6. 用户与使用场景

### 6.1 人类用户

- 寿险产品专家；
- 核保、理赔、保全专家；
- 合规和知识运营人员；
- 销售支持人员；
- 审核和发布人员；
- 平台管理员；
- 研发和评估人员。

### 6.2 Agent 和应用

- RAG 快答；
- 产品比较；
- 规则查询；
- 核保、理赔、权益辅助；
- Wiki 原子页引用；
- 关系和图谱推理；
- 反馈和缺口上报。

### 6.3 人类友好的 Wiki

人类应可以：

- 以产品、责任、除外、服务权益、医学概念等方式浏览；
- 查看当前发布版本；
- 查看来源引用并下钻原文；
- 查看相关概念和关联页面；
- 查看冲突、缺口、变更摘要；
- 后续查看修改历史、贡献者、讨论和审批记录。

### 6.4 Agent 友好的知识

Agent 不应只读 Markdown 文本，应同时得到：

- 结构化 Claim；
- Relation；
- typed value；
- applicability；
- effective interval；
- Evidence；
- release_id；
- page revision；
- 可引用的稳定标识；
- 不足、未知和需补充条件的明确状态。

---

## 7. 功能需求

### FR-01：文档接入与 SourceRevision

系统必须：

1. 复用 WeKnora 上传、解析、OCR、chunk 和原文能力；
2. 为每次材料内容形成稳定 SourceRevision；
3. 后续 Claim/Evidence 必须引用 exact SourceRevision；
4. 来源内容变化时产生新 revision，不覆盖旧证据；
5. 支持页码、表格、段落、chunk、结构化路径等 locator；
6. 保留内容 hash 或 manifest digest；
7. 证据访问必须服从当前 ACL。

> **v2 补充**：本项对应既有能力项 P4a（Source Inbox）与 P4c（Revision
> Capture），二者在本方案下为 **KEEP/REWIRE**，不因权威反转取消。见 §13.4
> 五档台账。

### FR-02：材料自动分类与采信策略

系统不要求用户逐文件配置。应先配置少量材料类型，由模型和规则自动识别，例如：

- 正式条款；
- 产品说明书或面客材料；
- 内部制度；
- 核保或理赔规则；
- 培训材料；
- 销售经验；
- FAQ；
- PPT；
- 普通文档片段；
- 未知或混合材料。

每类材料绑定版本化 TrustPolicy。

采信不是一个全局权威分，而是按字段和用途判断。例如：

- 正式条款对保障责任、除外、等待期等法定字段更权威；
- 面客说明书权威度较高，但不能自动覆盖正式条款；
- 内部核保规则对核保结论可能高于面客文档；
- 销售经验可作为线索或解释，不应自动覆盖正式规则；
- 普通片段只能作为候选证据，不能仅凭高相似度发布高风险事实。

分类不确定时必须降级到人工批审或隔离，不得静默猜测。

> **v2 命名统一裁决**：本能力在历史文档中出现过 `TrustPolicy`、
> `SourcePrecedencePolicy`、`AuthorityPolicy` 三个近义名称。v2 起
> **统一为 `TrustPolicy`，且必须只有单一求值入口**。不允许并存两套采信规则
> 或两个 evaluator。

### FR-03：产品、版本和实体消歧

系统必须识别：

- 产品主实体；
- 产品版本；
- 产品代码；
- 条款编号；
- 备案号；
- 正式名、简称和别名；
- 生效时间；
- 适用地区、渠道、人群；
- 文档级产品归属；
- 概念与具体产品义项。

优先级：

1. 产品代码、备案号、条款号等确定性标识；
2. 主数据和别名表；
3. 文档上下文和版本时间；
4. 检索召回；
5. 模型判别。

无法确定产品或版本时必须 quarantine 或人工审核，不能把正确事实写到错误实体。

> **v2 补充 [已核验]**：该能力的第一层（exact ProductVersion resolver）已在
> 仓库中实现并合入（OpenSpec 041），本方案下为 **KEEP**。

### FR-04：Schema、Template 与三态

针对结构明确的材料，必须使用可加载 Schema / Template。

Schema 至少描述：

- 字段定义；
- 数据类型；
- 枚举和单位；
- 是否必填；
- 适用条件；
- 风险等级；
- 允许材料类型；
- 冲突策略；
- 验证规则；
- Evidence 要求；
- 页面映射；
- 版本。

字段状态必须至少支持：

- `present`：材料明确存在该值；
- `absent_explicitly`：材料明确说明不存在或不适用；
- `unknown`：当前材料不足以判断。

`unknown` 不得被自动等同于没有。

允许模型发现 Schema 外的重要信息，但必须进入扩展字段或 Schema 演进候选，不能静默改变正式结构。

> **v2 补充**：每字段还须标注 provenance class
> （`source_evidence / human_attestation / external_sync / derived / undefined`），
> MVP 只发布 `source_evidence` 类；覆盖率报表按此口径呈现。此项继承自既有
> 修正案裁决，见 §13.5。

### FR-05：Claim / Relation / Evidence

正式知识必须以 Claim 和 Relation 为核心，而不是直接以生成页面为事实源。

每条 Claim 至少包含：

- stable claim id；
- subject_ref；
- product_version_ref；
- predicate / field id；
- tri-state；
- normalized typed value；
- unit；
- applicability；
- effective interval；
- evidence refs；
- source classification；
- trust policy version；
- schema/template version；
- extraction and validation identity；
- revision/event history。

Relation 至少支持：

- 产品—保障责任；
- 责任—除外；
- 产品—权益服务；
- 疾病—核保结论；
- 概念—具体义项；
- 新旧产品版本；
- supersede / coexist / conflict 等知识关系。

#### FR-05.1【v2 新增】subject 与 ProductVersion 的关系（废止旧裁决）

**被废止的旧规则**：`subject_ref` 恒等于 `product_version`。

该规则来自既有知识编译层修正案（Amendment 1 第 4 节 D-6/D1），原文标注
"P5a2 据此建模，不可逆" **[已核验]**。v2 显式废止其中"恒等"部分。

**废止理由**：并非所有 Claim 的主体都是产品版本。例如：

```text
Coverage      --has_waiting_period-->    90 days
Disease       --has_underwriting_rule--> manual_review
ServiceSense  --available_in-->          ProductVersion-A
```

若强制 subject 恒等于 ProductVersion，上述事实无法自然表达。

**新的不变量**：

> **所有产品特定知识必须被明确约束到某一个 ProductVersion；但 Claim 的
> subject 不必恒等于 ProductVersion。**

即：

- `subject_ref` 表达事实真正描述的实体（可以是 Coverage / Disease /
  ServiceSense / ProductVersion 本身）；
- `product_version_ref` 表达该事实所属的产品版本语境，**产品特定事实不得为空**；
- 产品版本自身的 effective interval、region、channel 构成外层包络；
- Claim 可以在包络内进一步收窄，**不得静默扩大**。

**旧裁决中继续有效的部分**（不随"恒等"一起废止）：

- 版本间天然零冲突（同一字段不同版本不构成冲突）；
- 文档正文不携带自身生效区间，产品特定事实的有效期**从 ProductVersion 主数据
  继承**；
- 版本编译的真实前置是文档归属判定，不是抽取。

**迁移成本 [已核验]**：依赖该旧裁决建模的能力项 P5a2 **尚未实现**，因此本次
废止的迁移成本为零。

### FR-06：弱模型抽取和独立机器校验

生产环境假设使用较弱模型，如 Qwen、MiniMax 等能力档，不能依赖强模型在线兜底。

系统必须：

1. 先路由材料和定位候选区域；
2. 按 Schema 做小任务抽取；
3. 输出 typed data；
4. 绑定 Evidence；
5. 做确定性规则校验；
6. 使用与抽取隔离的独立机器审核；
7. 校验产品版本、单位、枚举、条件和引文支持；
8. 失败时输出 typed failure、unknown、GapTask 或 ReviewItem；
9. 不得以空结果或静默降级伪装成功。

> **v2 补充 [已核验]**：已测数据显示，当前管道的薄弱点**不在三态判定，而在
> 检出后的值一致性**。实测 present 检出精度 0.948、金标 unknown 有 37/39 被
> 正确预测为 unknown，但 present 检出后值一致率仅 0.273（15/55），报告标注
> 其为"全部分数塌陷点"。因此第 3–5 步（typed data 归一 + Evidence 绑定 +
> 确定性校验）是质量工作的最高优先级，而不是提示词或三态逻辑。详见 §10.2.1。

### FR-07：缺口识别与定向补抽

系统必须能根据：

- Schema 必填字段；
- 条件必填字段；
- 相似产品；
- 同产品其他版本；
- 关系完整性；
- Wiki Lint；
- 用户和 Agent 反馈；

发现知识缺口。

发现缺口后应：

1. 形成 GapTask；
2. 定向检索可能材料；
3. 只补抽缺失字段及其关联条件；
4. 保留第一次抽取和补抽历史；
5. 不对整个产品无差别重跑；
6. 无证据时保持 unknown。

### FR-08：增量更新、融合和冲突

第二批、第三批材料进入后必须与现有知识增量比较，并产生明确动作：

- `add`：新增事实；
- `enrich`：同一事实增加 Evidence 或说明；
- `coexist`：因产品、版本、时间、地区、渠道或条件不同而并存；
- `supersede`：新权威来源或新版本替代旧值；
- `conflict`：同一适用范围内无法自动裁决；
- `retract`：来源撤回、失效或错误修正后撤回。

系统不得把所有差异都当冲突，也不得只按材料权威分自动覆盖。

冲突处理必须考虑：

- 是否同一实体；
- 是否同一产品版本；
- 是否同一业务时间；
- 是否同一适用范围；
- 是否同一字段语义；
- 材料类型对该字段的采信能力；
- Evidence 是否支持；
- 是否需要人工批审。

### FR-09：Candidate 与审核

审核必须按 CandidateRelease 或知识批次进行，而不是要求每个页面逐个点击。

ReviewPolicy 应按 Space 版本化配置，支持：

- `human_batch`；
- `hybrid`；
- `machine_auto`；
- `trusted_import`。

已确认规则：

- 新建 Space 默认 `human_batch`；
- MVP 可以产生机器审核建议和审核回执；
- 高风险字段、冲突、产品版本歧义进入人工批审；
- 人工动作绑定完整 Candidate；
- 正式无人发布放到企业阶段；
- machine_auto 必须有明确的 Golden、AutomationScope、质量准入、shadow/canary、回滚和监控；
- 任一自动资格缺失或漂移时回落 `human_batch`。

> **v2 补充**：CandidateRelease 必须冻结 `base_release_id` **与**
> `base_activation_epoch`，防止 ABA 问题（基线 Release 在审核期间被切走又切回，
> 单看 release_id 无法察觉）。见 §8 NFR-08 第 1 条。

### FR-10：Wiki 页面和概念组织

系统需要同时支持：

- 产品主页；
- 产品版本页；
- 责任页；
- 除外页；
- 权益服务页；
- 概念页；
- 产品义项或 Sense；
- Evidence 引用页或下钻；
- 关联页面；
- 目录和索引；
- 变更摘要；
- Lint 结果。

例如"在线问诊"应有独立概念页，说明通用概念，并关联多个产品下的具体义项，而不是在每个产品页面里复制一段无法统一维护的文字。

完整 Concept/Sense 系统不进入 MVP，但数据结构和页面映射不能阻断后续演进。

### FR-11：发布、固定版本读取和回滚

发布必须以不可变 Wiki Release 为单位。

必须支持：

- Candidate 封存；
- 页面集合和结构化 payload manifest；
- Evidence/source pins；
- 审核决策；
- 准备区；
- 原子激活；
- 唯一 Active Head；
- release_id 固定读取；
- 回滚到指定历史 Release；
- 发布和回滚回执；
- 幂等和并发保护；
- 页面、Claim、Relation、Evidence 同版读取。

不能出现：

- 一部分页面是 R1、一部分页面是 R2；
- 页面是 R2、Evidence 却来自另一个未封存版本；
- 人类浏览和 Agent 查询默认读不同版本。

> **v2 补充**：回滚粒度为 Space 级整版切换 + 经 SourceRetraction /
> emergency_withdrawal 的定向撤回（撤回 = 生成新 Release，不是回退指针）；
> **不支持单页 cherry-pick 回退**。此口径继承既有裁决 **[已核验]**，且须写入
> 给业务方的上线材料。上游若提供单页 revert，不改变本项目的整版回滚语义。

### FR-12：双时态兼容

已确认：数据模型从第一版兼容双时态，但 MVP 只做必要查询。

业务时间：

- `effective_from`；
- `effective_to`；
- 使用 Space 业务时区解释的 ISO 日历日；
- 推荐半开区间 `[from, to)`。

系统时间：

- `observed_at`；
- `recorded_at`；
- `activated_at`；
- 使用服务端数据库 UTC 时间；
- 追加式保存，不覆盖历史。

MVP 查询：

- `current`；
- `as_of_date`；
- `release_id`。

企业版再扩展：

- `known_at`；
- 更完整的业务时间与系统时间组合；
- 历史知识状态重建。

### FR-13：修改历史

已确认：正式上线后必须保留类似维基百科的修改历史，包括：

- 修改前后内容；
- 修改人或执行主体；
- 修改原因；
- Evidence；
- 提案；
- 审核；
- 发布时间；
- 版本关系；
- 可追溯的历史视图。

该能力放在企业级后续阶段，不进入 MVP 核心范围。MVP 只保留 Candidate、ReviewDecision、Release 和 rollback 的必要审计。

> **v2 补充**：本项对应既有能力项 P10（ChangeProposal domain/API，含 Proposal、
> base release/page CAS、事实变更必带新 provenance、编辑必经新
> Candidate/Decision）与 P14（Proposal Edit UX）。二者为 **DEFER**，不是
> 因权威反转而取消。见 §13.4。

### FR-14：Golden Set 和模型评估

必须建立版本化 Golden Set，覆盖：

- 材料分类；
- 产品和版本消歧；
- 字段抽取；
- 条件和适用范围；
- Evidence 支持；
- 表格和复杂 PDF；
- unknown / absent；
- 缺口；
- 冲突；
- 第二批材料增量更新；
- 页面编译；
- release pinned query；
- rollback。

阶段：

1. Seed Golden：由强模型辅助生成，人做初步确认，用于研发；
2. Canonical Golden：由专家确认，成为正式质量门禁；
3. 自动化准入 Golden：验证 machine_auto 覆盖范围；
4. 跨版本 Golden：验证 as-of、版本消歧和回滚。

强模型可以用于隔离的离线标注和评测，但不成为生产在线依赖。

> **v2 强化**：任何被引用的质量数字必须绑定 Metric ID 合同（§10.2.1），
> 禁止在文档中书写裸数字。历史测量不得因架构切换而清零。

### FR-15：反馈飞轮

系统最终需要把以下信号变成可治理任务：

- Agent 回答证据不足；
- 用户纠错；
- 专家标记错误；
- 低置信度；
- Lint 发现孤立页、冲突页、过期页或缺口页；
- 来源变更；
- ACL 收缩；
- 模型或模板升级后的回归。

反馈不得直接修改 Active Release，应先形成补编、ReviewItem 或新的 Candidate。

---

## 8. 非功能需求

### NFR-01：一致性

- 一个请求开始时固定一个 release_id；
- 页面、Claim、Relation、Evidence 和引用不得混版；
- Active Head 切换必须原子；
- 失败不能产生半发布。

### NFR-02：可追溯

- 每条正式知识可回到 exact SourceRevision；
- 每次抽取、校验、审核、发布和回滚可审计；
- 配置、Schema、TrustPolicy、模型、prompt 和运行指纹应版本化。

### NFR-03：安全和权限

- 所有对象显式绑定 tenant / Space；
- 当前 ACL 是最终读取门禁；
- 发布前、激活时和读取时均需校验关键权限；
- ACL 收缩后 fail closed；
- 不允许 Agent 绕过 Active Release 直接把原始 chunk 当正式答案。

### NFR-04：可配置

- 材料类型是少量可配置类别，不要求逐文件配置；
- ReviewPolicy 可配置；
- Schema / Template 可配置和版本化；
- 容量和批次大小来自配置，不写死为产品上限。

### NFR-05：可演进

- MVP 使用正式数据模型和权威边界；
- 不建设过渡性双系统架构；
- 后续企业能力通过增加组件和策略扩展；
- 不要求推倒 MVP 主链。

### NFR-06：模型可替换

- 模型调用通过能力配置和运行指纹管理；
- 同一 Golden 可比较不同弱模型；
- 质量下降可阻断发布；
- 不把某个模型的自由文本格式写死为领域合同。

### NFR-07：规模化

企业版应支持：

- 几十万材料或片段；
- 增量编译；
- micro-batch；
- 可重试和可回放任务；
- 分区、归档、retention 和 GC；
- 运营指标、SLO 和成本治理；
- 多 Space、多租户和多业务域。

### NFR-08【v3 重写】：MVP-728 前必须解决的 10 条 P0 合同

以下合同不要求全部由 S0-R/S0-Q 实现，但必须在 MVP-728 正式验收前全部关闭。

1. **Release 原子范围唯一**：一个 Space 在 MVP 中只能绑定一个
   `raw_kb_id` 与一个 `release_managed_wiki_kb_id`。未来多 RAW 或多正式 Wiki
   必须先经 ADR/OpenSpec/migration；多个正式 Wiki 还必须引入真正的
   `SpaceRelease`，不得用多个 Head 冒充 Space 级原子发布。
2. **Candidate 防 ABA**：`CandidateRelease` 同时冻结 `base_release_id` 与
   `base_activation_epoch`。
3. **Claim 逻辑身份与比较合同**：必须冻结 logical family、comparison identity、
   revision 规则、typed value comparator 和 applicability relation；否则无法
   确定性判断 enrich / coexist / supersede / conflict。
4. **SourceRevision、Retention 与 Legal Erasure**：普通逻辑删除不得静默破坏
   Evidence；同时必须区分 logical_delete、source_withdrawal、retention_expiry、
   legal_hold、legal_erasure。法律清除可使历史 Release 变为 revoked /
   non_serviceable / non_rollbackable，并保留不含原文的 tombstone 和清除回执，
   不得承诺 Evidence 无条件永久保存。
5. **ACL 不得经知识放大**：Source 侧 ACL 不得通过 Claim、excerpt、页面文本或
   payload 扩大；若同一事实能被低敏来源独立证明，必须走显式重新举证或降敏流程。
6. **检索必须 release-aware**：页面、结构化 payload、检索和 Agent 召回必须受
   同一 release_id 约束。
7. **canonical member，不按页面各持真相**：同一 Release 中
   Claim/Relation/Evidence 只有一个 canonical member digest，页面快照必须能
   证明同源。
8. **payload canonical serialization 固定**：digest 算法、序列化和语义合同版本
   必须显式声明并跨语言一致。
9. **PublishAuthorization 完整绑定**：授权必须绑定 preparation、candidate、
   manifest、ready receipt、review decision、review policy version、scope、
   expected head/epoch、action、expiry、nonce 和 signer，防止审核后替换、
   跨 Space 复用或旧策略授权重放。
10. **禁止绕过 Release Kernel 写 managed Wiki**：`release_managed` 页面拒绝
    普通 PUT/DELETE，只允许经 Release Kernel 专用入口写入。

---

## 9. MVP 范围

### 9.0【v3 重写】双 S0 可行性门 + MVP-728

v3 将“链路是否可实现”和“知识编译是否可行”拆成两个互不混淆、可并行推进的
Go/No-Go 门：

```text
S0-R（Release Skeleton） ──┐
                            ├── 两者均 PASS → 进入 MVP-728 集成开发
S0-Q（Quality Feasibility）┘
```

#### S0-R：Release Skeleton

**证伪对象**：WeKnora 作为唯一 Release 权威载体的实现可行性。

输入可以使用冻结的、人工确认的最小 Candidate fixture，不把抽取质量作为发布链
测试的前置条件。

范围：

- 1 个 Space；
- exactly 1 个 RAW KB；
- exactly 1 个 release-managed Wiki KB；
- R0 manifest 含 A/B/C 三个页面成员；
- R1 同时更新 A、删除 B、保持 C、新增 D；
- 从同一 R0 base 构造两个内容不同的 Candidate 并发竞争；
- 每个页面引用冻结的 canonical Claim/Evidence members；
- 人工直接批准；
- 两个当前 ACL principal，并在 pinned 内容上执行一次 ACL shrink；
- pinned read。

必须验证：

- R1 经目标 preparation/index/CAS/receipt 路径激活，不是旁路；
- manifest、canonical member 与页面 payload 同版；
- 重复提交幂等；
- expected head/epoch CAS，同 base 双 Candidate 只有一个赢家；
- 在 preparation、index、CAS、receipt 边界做有界失败注入；
- 激活前后并发 current/pinned read，一次请求固定同一 release_id，任何读取只能
  看到完整 R0 或完整 R1；
- 检索或最小读取路径不召回其他 Release；
- ACL shrink 后无权 principal 不能从 pinned 页面、payload 或最小检索旁路读取；
- 普通 Wiki 写接口无法修改 release-managed 页面；
- Harness 不保存第二 Active Head。

完成状态：

```text
RELEASE_PATH_FEASIBLE
or
RELEASE_PATH_NOT_FEASIBLE
```

S0-R 失败只证伪当前 WeKnora 载体或实现复杂度假设，不证明单一 Active 原则错误。
开工前的独立 OpenSpec/Mission Card 必须冻结 exact fork 路径、表/索引、
migration、read surface、升级责任和验证命令预算，并冻结暂定
`PublishAuthorization` 字段、canonical bytes、nonce、校验顺序与失败零写。
超预算或协议不成立时直接输出 `RELEASE_PATH_NOT_FEASIBLE`，不得延长窗口。

#### S0-Q：Quality Feasibility

**证伪对象**：弱模型条件下寿险知识编译链的可行性。

输入：

- 2 份真实材料；
- 1 个预置 ProductVersion；
- 4 个经过 Seed Golden 确认的字段：
  1. `present A`：基础成功路径；
  2. `present B`：必须验证 typed value、单位、条件或日期归一；
  3. `absent_explicitly`：原文明确否定，并有正向否定 Evidence；
  4. `unknown`：材料不足，必须 abstain，不能猜值。

必须验证：

- 候选区域可定位；
- ProductVersion 不发生静默错配；
- 四字段得到预期值或 typed fail-closed；
- 引文可回验；
- Evidence 语义支持可由独立判定器和人工核对；
- 抽取、归一、comparator、Evidence verifier 的错误可以分桶；
- 记录 abstention、错误类型和人工修订时间；
- 不依赖强模型在线兜底。

完成状态：

```text
KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE
```

S0-Q 不授予 `QUALITY_APPROVED` 或生产准入。若失败，暂停完整 MVP 投入，优化
Schema、定位、normalizer、comparator、模型或字段范围；它不直接证伪 WeKnora
Release 架构。

#### MVP-728 Core Acceptance

只有 `S0-R PASS AND S0-Q PASS` 后才进入 MVP-728 集成开发。MVP-728 保留
10–15 份材料、两批次、增量补缺、冲突、批审、R1/R2/rollback 的完整范围，见
§9.1–§9.5 与 §10。

### 9.1 MVP 目标

MVP 不证明"企业平台全部完成"，只验证四个最高风险假设：

1. 弱模型在 Schema、Evidence 和独立校验下能否稳定抽取；
2. 新材料能否增量补缺并发现冲突；
3. 可配置机器审核建议与人工批审能否形成可运营闭环；
4. WeKnora 是否可以成为唯一 Active Wiki Release 权威并支持固定版本读取和回滚。

### 9.2 MVP 数据范围

建议：

- 10–15 份代表性材料；
- 两个上传批次；
- 一个产品族；
- 两个名称相似或版本相近的产品；
- PDF、PPT、FAQ、表格和文档片段；
- 有意放入知识冲突；
- 有意保留缺失字段；
- 包含相似实体和版本陷阱；
- 包含一项跨产品复用概念，如"在线问诊"。

这些数字是验收样例，不是产品硬上限。

### 9.3 MVP 知识范围

建议：

- 40–60 条高价值事实；
- 5–10 个 Wiki 页面；
- 产品身份；
- 产品版本；
- 保障责任；
- 除外责任；
- 等待期或犹豫期；
- 少量核保或理赔规则；
- 1–2 个权益或复用概念。

### 9.4 MVP 必须跑通的闭环

```text
WeKnora 上传解析
→ SourceRevision
→ Harness 材料分类
→ ProductVersion 消歧
→ Schema 抽取
→ Claim / Relation / Evidence
→ 独立校验
→ Gap / Conflict / ChangeSet
→ CandidateRelease
→ 可配置审核
→ WeKnora Active Wiki Release R1
→ 人和 Agent 带引用查询
→ 上传第二批材料
→ 定向补缺、融合和冲突
→ CandidateRelease R2
→ 发布 R2
→ 回滚到 R1
```

### 9.5 MVP 明确不做

- 全量几十万材料编译；
- 所有寿险业务域；
- 完整 Concept/Sense；
- 完整维基百科式人工编辑和讨论历史；
- 复杂 `known_at` 查询；
- 全量 Agent 工具生态；
- HA、多区域和极限容量；
- 无人 machine_auto 发布；
- 为迁就旧实现保留双 Active；
- 长期异步投影和双系统对账。

---

## 10. MVP 验收口径

### 10.1 数据链路验收

- 10–15 份样本均形成可定位 SourceRevision；
- 每条正式 Claim 至少有一条可访问 Evidence；
- Evidence 可回到页码、表格、段落或结构化路径；
- 第二批材料不会覆盖或丢失第一批 Evidence；
- 所有对象可定位到 Space、Candidate 和 Release。

### 10.2 抽取质量验收

至少分别评估：

- 产品身份准确率；
- 产品版本归属准确率；
- 字段 precision；
- 字段 recall；
- 条件和适用范围准确率；
- Evidence support rate；
- unknown 识别；
- absent_explicitly 识别；
- 复杂表格和跨页字段准确率。

具体阈值必须由样本 Golden 和业务风险共同确定，不应在没有 Golden 的情况下拍脑袋承诺一个总准确率。

### 10.2.1【v2 新增】Metric ID 合同与已测基线

**为什么需要这一节**：三轮评审中出现过一次真实的数字混淆——两份不同报告里
各有一个 `0.231`，但含义完全不同（一个是全局 micro F1，一个是 high-confidence
桶的值级正确率）。裸数字在文档间传递必然产生此类错误。

**合同**：任何被引用的质量数字必须绑定以下完整身份，缺一不可：

```text
metric_id
value
report path
commit
dataset id
schema identity
evaluator identity / version
metric definition
numerator / denominator
run count
scope
admission_status
```

**当前已测基线 [已核验]**：

| 字段 | 值 |
|---|---|
| `metric_id` | `g0_probe_20260727_deepseek_v4_flash_two_product_micro_f1` |
| `value` | `0.231` |
| report | `docs/insurance-kb/probes/2026-07-27-g0-probe-report.md` |
| commit | `c85dd9d1` |
| dataset | `dataset/goldenset/wip-gs-v0.1`（11/13 产品已标注，每产品 59–62 字段） |
| schema | `v1.1+b31a411c621c` |
| evaluator | `insurance_harness.goldenset.eval.evaluate` @ v1 严格等价 |
| definition | micro F1，2 产品合计，裁决前（pending_judge 未回写） |
| 分子/分母 | micro P 0.259 / micro R 0.208；116 可评测金标键 |
| run count | 215 次真实弱模型调用 |
| `scope` | `calibration_only` |
| `admission_status` | `not_g0_acceptance_evidence` |

**同一报告中必须一并引用的分解值**，否则 `0.231` 会被误读为均匀水平：

| 口径 | 值 |
|---|---|
| e生保尊享（medical）· deepseek-v4-flash micro F1 | 0.152 |
| 盛世金越分红（whole-life）· deepseek-v4-flash micro F1 | 0.313 |
| 对照臂 盛世金越 · qwen-flash micro F1 | 0.237 |
| 幻觉率 deepseek / qwen-flash | 0.052 / 0.220 |
| 证据引文回验（两臂） | **1.000** |
| G0b 目标 | precision ≥0.95 / recall ≥0.90 |

**第二个必须单列的 Metric ID [已核验]**：

| 字段 | 值 |
|---|---|
| `metric_id` | `g0_probe_20260727_deepseek_v4_flash_value_consistency_after_detection` |
| `value` | `0.273`（15/55） |
| definition | present 被正确检出后的值一致率（v1 严格） |
| 报告结论 | **"这是全部分数塌陷点"** |
| `scope` | `calibration_only` |

**三态混淆矩阵（合计 deepseek，2 产品，116 键）[已核验]**：

| 金标 \ 预测 | present | absent_explicitly | unknown |
|---|---|---|---|
| present (72) | 55 | 0 | 17 |
| absent_explicitly (5) | 1 | 2 | 2 |
| unknown (39) | 2 | 0 | 37 |

**必须随数字一同传递的定位声明 [已核验]**：该报告自身标注为
**CALIBRATION-ONLY**，且明确列出其未经过的门：生产模型 admission、裁决回写、
真正多模型共识、paired-scan 漏抽双扫、linked lineage 审计、发布链全部环节。
因此它能证明"当前效果差"并用于定位问题，**不能授予 G0/G0a/G0b 任何通过状态**。

**基线的解读结论 [已核验]**：报告原文判断为
"距 G0b（0.95/0.90）差约 3–4 倍，**不是调参距离，是结构距离**"。

**对项目的含义**：架构切换不会改变这个数字。见难点文档 §23。

### 10.3 增量验收

第二批材料进入后：

- 已正确且无新证据影响的字段保持稳定；
- 第一批 unknown 字段可被定向补抽；
- 同值新证据归为 enrich；
- 不同版本或适用范围的差异归为 coexist；
- 真冲突形成 ConflictSet 或 ReviewItem；
- 不进行产品级无差别全量重跑；
- 可解释每个变更动作的理由。

### 10.4 审核验收

- 材料类型能自动识别；
- ReviewPolicy 可按材料、字段风险、冲突、置信度配置；
- 人工审核按 Candidate batch 操作；
- 不要求每个页面单独点击；
- 高风险和歧义项不能静默自动通过；
- MVP 的最终发布采用 human_batch；
- 机器审核结果作为建议、证据或回执保留。

### 10.5 发布和回滚验收

- R1 可以原子激活；
- 同一次查询固定 R1；
- R2 激活时不出现半新半旧；
- R2 发布后可查询新增和冲突处理结果；
- 可回滚到 R1；
- 回滚后新请求读取 R1，已有 pinned 请求不混版；
- 发布和回滚都有 receipt；
- 重复请求幂等；
- 并发激活使用 expected head / epoch 防止覆盖。

### 10.6 人和 Agent 消费验收

- 人可以浏览产品页和相关概念页；
- 页面展示来源引用；
- Agent 读取结构化 payload 和相同 release_id；
- Agent 回答可以输出稳定 citation；
- 未发布或不足知识返回 insufficient / needs_qualification；
- 不绕过正式 Wiki 直接把原始 chunk 当正式结论；
- **[v2]** 检索层与页面同版，不出现"页面 R2、召回 R1"。

### 10.7 MVP 成功定义

MVP 成功不等于"页面看起来像 Wiki"，而是：

> 在一组有代表性、有冲突、有缺口、有相似产品版本的材料上，弱模型能够在 Schema 和 Evidence 约束下生成可校验的知识；第二批材料可以增量补缺和发现冲突；审核按批次完成；最终知识由 WeKnora 单一 Release 原子发布、固定版本读取并可回滚。

> **v3 强化**：S0-R 或 S0-Q 单独完成均不等于 MVP 成功。只有两者都通过，才
> 允许进入 MVP-728 集成开发；声明 MVP 成功还必须满足 §10.1–§10.6、
> §8 NFR-08 的 10 条 P0 合同，并附 Metric ID 合同格式的质量证据。

---

## 11. 企业级完整版本需求

### 11.1 语义编译器产品化

- 全面产品目录和 ProductVersion 主数据；
- 多领域 Schema / Template Catalog；
- 材料分类器和 TrustPolicy 管理；
- 结构化抽取、Evidence、Validation、Gap、Conflict 稳定主链；
- 可重试、可回放、可观测编译任务；
- Seed Golden 到 Canonical Golden；
- 模型、prompt、模板和策略升级门禁。

### 11.2 知识治理

- 完整 Wiki 目录和关联；
- 原子概念页和 Sense；
- 批次 diff；
- 冲突台和缺口台；
- 审核工作台；
- changelog；
- 修改提案；
- 修改历史；
- 贡献者和审批记录；
- 过期、孤立、缺引用、缺口等 Lint；
- 撤回和紧急回滚。

### 11.3 Agent 与应用消费

- 人、API、MCP、Agent 使用同一 Active Release；
- pinned read；
- 结构化规则查询；
- 图谱或关系推理；
- 产品比较；
- 引用和 Evidence 下钻；
- feedback event；
- 知识不足和需要补充条件的标准返回。

### 11.4 规模化运营

- 几十万材料增量编译；
- 批量 backfill；
- 容量画像；
- 队列、重试、dead letter；
- 分区、归档、GC；
- SLO、成本预算、质量看板；
- shadow、canary；
- 自动化资格持续评估；
- 多 Space、多租户和多团队治理。

---

## 12. 参考来源

### 12.1 WeKnora 最新版本

参考其：

- 文档上传和解析；
- OCR、chunk、检索；
- 知识库和 Wiki 载体；
- 企业权限、审计和 API；
- Agent 平台相关能力。

取舍：

- 复用平台能力；
- 增强领域无关的 Release Kernel；
- 不把寿险编译逻辑散落进 WeKnora；
- 不维护长期大规模 fork；
- 最终实施前需基于最新主线核对 exact upstream capability，但不改变本文权威边界。

#### 12.1.1【v2 新增】exact upstream identity 与已发生的撞号 [已核验]

v1 只写"参考最新版本"，不足以支撑实施。当前仓库事实：

| 项 | 值 |
|---|---|
| 项目当前锁定 | WeKnora `v0.6.3` / `5eefa70e6fc8f9ec27958779f91ece6cf685598c` |
| 官方稳定版 | `v0.7.1`（2026-07-24，`c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`） |
| 正式稳定候选 | `v0.7.1` / `c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb` |
| post-release 对照候选 | snapshot `80a5003cc99a427098afe184eee6601916d3d156`（tree `18fcf68e7a008ce69929e32233f0b6914040c223`） |
| snapshot 的潜在收益 | `v0.7.1` 不含 Wiki 单页 history / diff / manual edit / revert；该 snapshot 含官方 `000075_wiki_page_revisions` |
| v3 选择状态 | **尚未选择**；须由双基线能力矩阵比较 patch 面积、migration 稳定性和跟版风险 |
| 已发生的直接冲突 | 项目自有 migration `000066_knowledge_revision_manifest` 与上游 `000066_expand_knowledge_span_name` **同号不同义**；上游其后另有 `000067–000074` |
| 当前运行制品 | trusted local-live 仍从 `5eefa70e` 构建，**不含**项目已合入的 revision manifest |

**这段历史对本方案的直接教训**：项目曾在上游正在活动的区域自建同号 migration，
代价是一个采用 Mission 至今未关闭。**Release Kernel 与官方 wiki page revision
处于同一区域**，因此在填完能力矩阵（§7.10）前不得新增 project-owned WeKnora
migration，也不得预设物理表数量。

采用前必须闭合：
- migration identity 分离（官方链与企业链独立 ledger，不得静默重命名或删除
  legacy 编号）；
- 四种数据库状态（未执行 000066 / 上游 000066 已执行 / 项目 000066 已执行 /
  fresh target）分别探测并证明双侧结构都存在；
- 项目 patch 的 machine-readable 重放；
- 编号 × schema object × patch surface 三层碰撞 CI；
- trusted image / provenance / SBOM / exact digest 回写。

### 12.2 `nashsu/llm_wiki`

项目：

- <https://github.com/nashsu/llm_wiki>

借鉴：

- Raw Sources / Wiki / Schema；
- Ingest / Query / Lint；
- 原子页面；
- index 和 log；
- LLM 维护知识；
- 人机协作；
- 冲突和缺口发现。

不直接照搬：

- 个人级 Markdown/Obsidian 运行形态；
- 缺乏企业 ACL、批次审核和整版发布；
- 缺乏寿险版本、Evidence 和弱模型质量治理；
- 不适合直接承担几十万材料的生产运行时。

> **v2 说明**：该项目为**方法论来源，非代码来源**。它是个人级形态，本项目从
> 未、也不应把其运行时并入企业平台。评审若关注"个人级项目合并进企业平台"的
> 风险，应确认的是：本方案吸收的是三层结构与 ingest/query/lint 思想，承载
> 运行时的是 WeKnora（企业平台）+ Python Harness（领域编译器）。

### 12.3 `LLM-wiki-black` 定制分支

项目：

- <https://github.com/silvielala412-lab/LLM-wiki-black/tree/feature/product-catalog-domain>

可借鉴和迁移：

- 产品目录；
- 字段 taxonomy；
- 产品/服务/模块层级；
- 清洗和路由；
- 弱值识别；
- 部分概念聚合和冲突思路；
- docs 中的寿险领域设计和样例。

不能未经评估直接复制为生产主链：

- 文件级 Evidence 不足；
- 产品版本和多义项不完整；
- Release、Golden 和企业 ACL 不完整；
- Node/TS、localStorage、Markdown 形态不作为生产寿险运行时；
- 资产需要做 provenance 和 license 核验。

---

## 13. 已确认、不应反复重开的决策

1. 不做 Harness ActiveRelease 到 WeKnora managed Wiki 的双系统投影；
2. 单一 Active Release 权威原则已接受；WeKnora 是条件接受的当前载体；
3. Harness 是寿险语义编译和治理层，不保存第二个 Active Head；
4. MVP 使用正式目标架构，不建设过渡架构；
5. MVP 数据采用 10–15 份有代表性、多格式、有冲突、有缺口的材料；
6. 审核可配置，人工按 Candidate 批审，不逐页面点击；
7. 新 Space 默认 human_batch；
8. machine_auto 放到后续企业阶段；
9. 材料只配置少量类型，由模型和规则自动识别，不逐文件设置；
10. 材料权威度必须结合字段和场景；
11. Schema 缺失字段应触发定向反查和补抽，不全量重来；
12. 数据模型从第一版兼容双时态，MVP 只做 current、as_of_date、release_id；
13. 修改历史必须做，但放在 MVP 之后；
14. Golden Set 必须建立；
15. 强模型只用于离线标注和评估，不成为生产在线依赖；
16. 旧项目资产要吸收，但不因沉没成本保留错误边界；
17. 当前先形成完整方案和交接，再由其他模型和人员评审；
18. 本轮文档基于讨论整理，不做代码完成度推断。

### 13.1【v2 新增】四层文档治理

v1 的五份文档各自成权威，会导致接手者需要自行推导当前有效架构。v2 定义四层，
各自回答一个不同问题：

| 层 | 载体 | 回答什么 |
|---|---|---|
| 目标方案 | 728 v3（本文及四份独立文档） | 我们要建设什么 |
| 架构决策 | `docs/superpowers/specs/2026-07-28-weknora-sole-release-authority-adr.md` + 决策记录 `D-2026-07-28-1` | 权威边界为什么这样定 |
| 迁移说明 | 033 Amendment 2 | 旧设计哪些废止、哪些保留、Amendment 1 每条如何处理 |
| 实施事实 | 状态台账（§13.4） | 当前代码实际上有什么 |

**ADR 的编号裁决 [已核验]**：ADR **不占用 OpenSpec 编号**。仓库中 OpenSpec
有独立编号注册表（当前 `045` 已占、`046+` 空闲），而架构裁决的既有载体是
`docs/superpowers/specs/YYYY-MM-DD-*.md` 加控制板 `D-YYYY-MM-DD-N` 记录。
共用编号会重演已经发生过的注册表漂移（曾有目录先于注册表行创建，至今在注册表
中挂着事后补记）。真正实施时再单独占 OpenSpec 号并**先占号后建目录**。

**ADR 无条件冻结**：线上只有一个 Active Release 权威；Harness 不拥有第二
Active Head；正式消费 pin `release_id`；发布必须满足整版不可变、CAS、pinned
read、rollback。**ADR 条件接受** WeKnora 为当前物理载体，并写明双基线矩阵与
S0-R 的证伪门；不冻结物理表数量。

### 13.2【v2 新增】必须继承的过程护栏

v1 完全没有过程章节。以下护栏在既有仓库治理中已存在且已抓出过真实缺陷
**[已核验]**，不因架构切换而失效：

1. 一个 PR 一个核心不变量；
2. 一个 PR 最多一个 migration；
3. 写代码前先冻结事务边界与威胁矩阵；
4. 两轮修复—评审后仍在同一域发现新的基础不变量 → **停线，换边界，不叠补丁**；
5. 关键并发路径必须有 PostgreSQL 真并发测试（不只是 SQLite 确定性测试）；
6. 高风险项须双独立评审（规格侧 + 质量侧）；
7. 新需求不在当前 PR 无限扩域，非阻断项转 BACKLOG；
8. 开工前提交 **Mission Card** 并取得逐项批准。

**关于 Mission Card 的裁决**：保留原名，**不在本次架构切换中夹带改名或简化**。
理由：它在仓库治理文件中是硬门禁，BLOCKER/BACKLOG 分类与停线判据均挂在这个
名称上，且近期刚围绕它强化了 AI git 授权边界 **[已核验]**。若日后确需精简，
单独开一次治理变更，不隐含在架构 Amendment 中。

实践上 Mission Card 应为**一页式实施合同**，可引用 OpenSpec 而不重复其内容，
包含：目标与明确非目标、唯一职责、允许/禁止文件域、权威读写边界、事务边界、
幂等键、状态转换、并发/崩溃/重放威胁、Golden/验收案例、精确测试命令、
commit/push 授权范围。

### 13.3【v2 新增】Amendment 1 逐项去向

既有知识编译层修正案（Amendment 1）的裁决不得随文档换版静默丢失。逐项处理：

| Amendment 1 项 | v2 处理 | 说明 |
|---|---|---|
| TemplatePackage registry | **保留** | Schema/Template 运行时的核心资产 |
| SourcePrecedencePolicy | **合并** | 与 `TrustPolicy` 统一命名 + 单一求值入口，见 FR-02 |
| 标注 agent 子系统 | **保留但限定** | 仅用于 Seed Golden、标注辅助、失败分类、Evidence 对齐；**不得进入生产在线编译权威，不得成为第二个 judge 真相** |
| CAP0 stock_backfill | **保留但不阻塞 S0-R/S0-Q** | 容量假设与验收资产保留；backfill/恢复能力在主链成立后验证 |
| `subject_ref = product_version` | **显式废止（部分）** | 废止"恒等"，保留"有效期从 ProductVersion 继承"，见 FR-05.1 |
| provenance class 进 Schema | **保留** | MVP 只发布 `source_evidence` 类，见 FR-04 |
| 长文本字段 comparator | **保留** | MVP 声明 `text_keypoints_unknown` → 运行时返回 unknown → 人审 |
| 回滚粒度（整版 + 定向撤回，无单页 cherry-pick） | **保留** | 见 FR-11；上游单页 revert 不改变此语义 |
| human_batch-first | **保留** | 与 728 §FR-09 一致 |
| G0b 作为知识质量门禁 | **保留** | 人在审不等于允许知识是错的 |

### 13.4【v2 新增】能力五档台账（替代"按编号取消"）

**这是 v2 最重要的一处纠正。** 早期讨论中曾提出"取消 P4a/P4c/P11–P14"，经
评审指出该表述危险：这些编号下的能力并非双 Active 投影专属，按编号整体取消
会误删有效资产。正确做法是**按能力逐项分档**：

档位定义：

- `KEEP`：能力与实现均继续有效；
- `REWIRE`：能力有效，接线对象改变（改为消费 WeKnora Release / Candidate）；
- `SUPERSEDE`：该能力的目的被新架构消解，由别的机制承担；
- `DEFER`：能力有效但后置到企业阶段；
- `DELETE`：能力本身消失。

| 既有能力项 | 原职责（033 原文摘要）[已核验] | v2 档位 | 理由 |
|---|---|---|---|
| P1 Job Store + Outbox | 任务运行时、状态机、lease/generation fencing、事务 Outbox | **KEEP** | 通用基础设施，Gap/抽取重试仍需要 |
| P3 API/Worker Shell | 双角色、principal fail-closed、readiness、lease/drain | **KEEP** | 与权威方向无关 |
| P4a Source Inbox | WeKnora polling/event adapter、重叠窗口 reconciliation、幂等/排序、未知 lifecycle/ACL fail closed | **KEEP** | 728 FR-01 仍需 Source lifecycle |
| P4b Microbatch + Backpressure | Space debounce、有序输入批次、水位、pending queue | **KEEP** | 728 NFR-07 增量编译需要 |
| P4c Revision Capture | 消费 authoritative attempt/manifest、不可变 NormalizedSourceRevision + artifact、pin、受控原文访问 | **KEEP** | **这就是 728 §4.1 SourceRevision + Evidence pin 的实现** |
| P5a0 ProductVersion Resolver | exact 标识优先的版本解析 | **KEEP** | 728 列为 P0 |
| C0 Canonical Envelope | RFC 8785/NFC/domain-separated SHA-256、语言中立 vectors | **KEEP** | payload digest 与 canonical member 的底座 |
| CAP0 Capacity Contract | 容量画像、declared/measured、stock_backfill | **KEEP** | 不阻塞 S0-R/S0-Q |
| P1 Active Fence Verifier | 只读 DB-clock fence 校验 | **KEEP** | 只读，无权威假设 |
| P2d Space Security Boundary | Space scope、RAW/Wiki ACL 等价、跨 Space 拒绝、失败零写 | **KEEP** | 728 NFR-03 |
| P10 ChangeProposal domain/API | Proposal、base release/page CAS、事实变更须新 provenance、编辑必经新 Candidate/Decision | **DEFER** | 728 FR-13 修改历史后置；**不是投影项，不得取消** |
| P11 managed-page fencing | Go 侧 owner/Space epoch high-watermark/digest conditional API；managed read RAW ACL guard；标准 PUT/DELETE 防绕过 | **拆分** | epoch/high-watermark 部分 `SUPERSEDE`（无第二 Active 即无迟到写）；**RAW ACL guard 与"禁止普通 PUT/DELETE 绕过专用入口"必须 `REWIRE` 保留**，见 NFR-08 第 10 条 |
| P12 Projector | activation manifest Outbox → fenced managed Wiki 页面/目录/链接 | **DELETE** | **唯一真正因权威反转消失的能力项** |
| P13 Evidence + Review UX | Active Query 正文、引用侧栏、原文跳转、Candidate 摘要、一键批量审核 | **REWIRE** | 改为消费 WeKnora Release；728 §9.2 审核台需要 |
| P14 Proposal Edit UX | managed Wiki 编辑入口调用 P10 Proposal API | **DEFER** | 随 FR-13 后置 |
| 旧 018 路线：`current_release` 指针、`snapshot_facts`、`release_operations`、`publish_attempts`、`reconciliation_jobs`、逐页补偿 saga | 早于 033 的发布链 | **SUPERSEDE** | **[已核验]** 在 033 下即已被判定"被取代/废弃"；728 只改变接管者（由 WeKnora Release Kernel 接管），不新增报废 |

**关键台账事实 [已核验]**：

1. `active_release` 在 `harness/src/` 与 `harness/migrations/` 中出现
   **0 次**——033 设计的 Harness Active Head **从未落地为代码**，只存在于设计
   文档中。因此权威反转**不产生新的代码报废**。
2. 确实存在需要处置的对象，但它们来自 033 **之前**的 018 路线，且早已登记为
   被取代/废弃。
3. **[未核验，必须在开工门禁中确认]** 以下几项尚无证据，不得假设：
   - P1/P3 的接口是否隐含假设 Harness 最终 serving；
   - 现有测试是否把 Harness reader 当正式线上读取；
   - publisher 是否与 Candidate lifecycle 耦合；
   - status/receipt 是否以旧 Snapshot 为领域结果；
   - 对外 API contract 是否暴露 `current_release`。

**因此准确结论是**：

> 当前**没有发现**因权威反转而新增的大规模代码报废；已有旧发布链本来就已被
> 判定需替换。大部分基础设施与语义资产可保留，但**接口与测试仍需状态台账
> 逐项确认**，不得先行宣称"几乎不需要改代码"。

### 13.5【v2 新增】三道开工前门禁

在冻结 Release Kernel 物理设计与开始 S0-R 编码前，必须完成：

1. **上游能力矩阵**（§7.10）——回答最新 WeKnora 已有什么、Release Kernel 还需
   补什么；
2. **代码状态台账**（§13.4，含 5 项未核验条目的结论）——回答当前代码实际上
   有什么；
3. **历史指标证据清单**（§10.2.1）——回答当前质量到底是多少、基于什么数据与
   evaluator，并保留 calibration-only 定位。

---

## 14. 外部评审应回答的问题

外部模型或架构评审者应明确回答：

1. 单一 WeKnora Active Release 权威是否成立；
2. Harness 与 WeKnora 的职责是否仍有重叠；
3. Release Kernel 是否足以保证整版原子发布、固定版本读取和回滚；
4. MVP 是否真正验证抽取准确率、Evidence、消歧、补缺和冲突；
5. 是否仍混入双系统投影或第二 Active Head；
6. 10–15 份材料、40–60 条事实是否足以验证核心风险；
7. weak-model-first 的抽取与独立校验设计是否可落地；
8. TrustPolicy 是否避免了简单"权威分覆盖"；
9. 双时态兼容是否适度；
10. 哪些要求应从 MVP 移到企业阶段，或从企业阶段提前；
11. 哪些旧分支资产值得迁移，哪些应该停止维护；
12. 是否存在会导致再次推倒重来的隐含过渡架构。

### 14.1【v2 新增】v2 特别请评审回答

13. §5.6 对"被否决的究竟是什么"的精确表述是否成立，是否仍有未被识别的
    跨系统一致性负担；
14. §7.10 双基线上游能力矩阵的行项是否完整，是否遗漏会扩大 fork 的能力；
15. §8 NFR-08 的 10 条 P0 合同是否完整；
16. S0-R / S0-Q / MVP-728 的边界是否清楚，是否有单门通过即被误用的风险；
17. §13.4 的五档台账是否有错档，特别是 P11 的拆分是否正确；
18. FR-05.1 的新不变量（产品特定知识须约束到 ProductVersion，但 subject 不必
    恒等）是否足以覆盖寿险全部事实形态；
19. §10.2.1 的 Metric ID 合同是否足以防止裸数字在文档间传递造成误读；
20. 在 F1 基线为 `0.231`（calibration-only）的前提下，S0-R 与 S0-Q 并行是否
    是正确的资源分配。

---

## 15. 需求文档结论

本项目的核心不是再做一个文档系统，而是把寿险材料转化为一套可发布、可证明、可更新的知识系统。

MVP 必须把时间花在：

- 抽取准确率；
- 产品和版本消歧；
- Evidence；
- 缺口；
- 冲突；
- 批次审核；
- 单一 Release；
- 固定版本查询；
- 回滚；
- Golden 评估。

只要这条链没有跑通，再多页面、Agent 或平台功能也不能证明项目成立。反过来，只要这条链在代表性样本上跑通，后续企业化扩容才有稳定基础。

> **v2 补充**：并且这条链的每一段都必须有 Metric ID 合同格式的证据。当前
> 已知的最强证据是"证据引文回验 1.000"，最弱环节是"检出后值一致率 0.273"。
> 项目的下一阶段进度应当用这两个数字之间的差距被填平多少来衡量，而不是用
> 新增了多少组件来衡量。

---

# 企业级寿险 LLM Wiki：MVP 与企业级完整技术方案（JLX 728 · v3）

> 日期：2026-07-28
> 版本标识：728-v3
> 文档类型：总体技术方案
> 整理依据：2026-07-28 已确认架构与范围 + v2 三轮评审 + v3 复评裁决
> 重要说明：本文是目标技术方案，不是代码 Review，也不宣称当前实现已经达到本文状态。

---

## 1. 技术方案结论

最终方案不是把 WeKnora 和 LLM Wiki 做成两个互相投影的知识系统，而是一个平台、一个编译器、一个线上发布权威：

```text
WeKnora
= 企业平台底座
+ 原始材料与 SourceRevision 权威
+ ACL / 审计 / API / Wiki UI
+ 唯一在线 Wiki Release 权威

Python Harness
= 寿险领域知识编译器
+ 质量校验
+ 缺口与冲突治理
+ Candidate 与审核决策
+ 向 WeKnora 发出发布授权
```

LLM Wiki 是贯穿系统的方法论：

```text
Raw Sources
→ Schema-guided knowledge compilation
→ Atomic Wiki pages
→ Query
→ Lint
→ Feedback
→ Continuous evolution
```

它不是独立维护第二个 Active Wiki 的运行时。

---

## 2. 第一性原理

### 2.1 企业知识系统真正需要的三个权威

无论现有代码做了什么，企业级 LLM Wiki 必须回答三个问题：

1. 原文究竟是什么；
2. 当前线上知识究竟是哪一版；
3. 某条知识为什么成立。

对应权威：

| 问题 | 权威 |
|---|---|
| 原文是什么、谁可以看 | WeKnora SourceRevision + 当前 ACL |
| 寿险事实如何抽取、验证、融合和审核 | Python Harness |
| 人和 Agent 当前读哪一版 | WeKnora Active Wiki Release |

这三个权威可以分工，但不能产生两个"当前线上知识版本"。

### 2.2 为什么页面不是事实源

寿险知识的核心是：

- 产品；
- 版本；
- 责任；
- 除外；
- 条件；
- 时间；
- 适用范围；
- Evidence；
- 冲突和变更。

Markdown 页面只是呈现。若直接让模型生成页面，再从页面中推断事实，会导致：

- 字段无法稳定比较；
- 冲突无法按适用范围判断；
- 增量更新难以定位；
- 页面文案和事实混在一起；
- Agent 只能再次解析自然语言；
- Golden 评估无法精确到 Claim 和 Evidence。

因此正式知识必须先形成结构化 Claim / Relation / Evidence，再确定性编译成人类 Wiki 页面和 Agent payload。

### 2.3 为什么不做双系统投影

被否决的方案：

```text
Harness Candidate
→ Harness ActiveRelease
→ 异步投影到 WeKnora managed pages
→ Agent 或页面再判断投影是否新鲜
```

一旦 Harness 和 WeKnora 都有 Active 状态，系统必须长期解决：

- fencing；
- freshness；
- 迟到写保护；
- 乱序；
- 幂等；
- 重放；
- 双 ACL；
- 双读；
- 对账；
- 修复；
- 版本映射；
- 上游数据模型变化；
- WeKnora 每次升级的 patch 跟版。

这些复杂度并不增加寿险知识准确率。最终方案要求：

- Candidate 和编译过程可以存在 Harness；
- 正式 Active Head 只存在 WeKnora；
- Harness 通过明确协议准备并授权一个 release；
- WeKnora 原子激活；
- 之后所有正式消费都 pin 到 WeKnora release_id。

### 2.4【v2 新增】权威位置的判据，以及本决策的真实代价

**判据**：权威应放在**服务读取并执行授权**的系统，而不是放在生产数据的系统。

推导：

```text
读取是高频操作，发布是低频操作
    ↓
把跨系统成本放在低频侧
    ↓
Active Head 归 WeKnora（ACL / UI / 原文 / Agent 平台所在）
    ↓
Harness 只在发布时跨一次系统边界
```

**必须诚实记录的代价**（v1 未写）：

1. WeKnora 侧要承载整版 Release 语义与 pinned read，**patch 面积不为零**；
2. 发布从"单库事务"变为"跨系统两阶段"，需要 prepare / ready receipt /
   签名授权 / nonce / TTL / CAS / 幂等先于过期；
3. 结构化 payload 必须物化到 WeKnora 供 Agent 同版读取，因此**数据仍有两份**
   （Harness 编译态 + WeKnora 发布态不可变副本）；
4. Release Kernel 与官方 wiki page revision 处于同一代码区域，**存在与上游
   持续碰撞的风险**——项目已在该区域发生过一次 migration 撞号 **[已核验]**。

**为什么仍然优先验证它**：这些代价是**集中、边界明确、长期存在于低频发布
路径**的；可以通过协议、测试与容量边界封顶，但不会在首次实现后消失。第二
Active Head 的代价则是**持续、开放式、分布在每一次读取和每一次故障处理**的。
前者更容易被显式治理，后者只能依靠长期运维兜底。该比较支持“条件接受”，不能
替代 S0-R 的实证。

### 2.5【v2 新增】被否决与被保留的精确清单

见需求文档 §5.6。此处只重复结论：

- **删除**：第二可变 Active Head、异步 freshness、迟到投影写、双 serving
  authority 对账、读取时跨系统协商；
- **保留并必须做对**：跨系统发布、数据物化、digest 校验、幂等键、CAS。

推荐措辞：**"Harness 编译并冻结 Candidate，WeKnora 接收不可变发布制品并成为
唯一服务权威"**，而非"不做投影"。

---

## 3. 总体架构

```text
┌───────────────────────────────────────────────────────────────┐
│                       人类与 Agent 消费层                       │
│ Wiki 浏览 │ 产品比较 │ 规则查询 │ API/MCP │ Evidence 下钻 │ 反馈 │
└───────────────────────────────▲───────────────────────────────┘
                                │ pinned release_id
┌───────────────────────────────┴───────────────────────────────┐
│                         WeKnora 企业底座                       │
│                                                               │
│ 上传 / 解析 / OCR / chunk / 检索 / SourceRevision             │
│ Tenant / Space / KB / ACL / 审计 / API / Agent / Wiki UI      │
│                                                               │
│ Wiki Release Kernel                                           │
│ PageRevision / Release / Member / SourcePin / Head / Receipt  │
│ ＋ 禁止绕过写入的 guard（NFR-08 第 10 条）                      │
└──────────────▲───────────────────────────────────▲────────────┘
               │ Source lifecycle / REST           │ prepare/authorize
               │                                   │ activate/rollback
┌──────────────┴───────────────────────────────────┴────────────┐
│                      Python Harness                           │
│                                                               │
│ 材料分类 / TrustPolicy / ProductVersion Resolver              │
│ Schema / Template / Extraction / Evidence / Validation        │
│ Gap / Fusion / Conflict / ChangeSet                           │
│ Candidate / ReviewPolicy / ReviewDecision                     │
│ ReleaseBundle / PublishAuthorization / Golden Evaluation      │
│ 【无 Active Head】                                             │
└───────────────────────────────────────────────────────────────┘
```

### 3.1 WeKnora 负责什么

WeKnora 负责领域无关的企业能力：

- 上传；
- 文件和版本；
- OCR；
- 文档解析；
- chunk；
- 原文展示；
- 检索；
- 租户；
- Space；
- 知识库；
- ACL；
- 审计；
- API；
- Wiki 页面载体；
- Agent 平台集成；
- 唯一 Active Wiki Release；
- pinned read；
- rollback。

WeKnora 不负责：

- 判断某个条款属于哪个产品版本；
- 理解责任、除外、核保和理赔 Schema；
- 裁决寿险字段冲突；
- 生成寿险 Golden；
- 决定哪些字段必须人工审核；
- **[v2]** 解释结构化 payload 的寿险语义（只保证不可变存储、版本、digest、
  ACL 与原样读取）。

### 3.2 Harness 负责什么

Harness 负责领域编译和治理：

- 监听或拉取新的 SourceRevision；
- 自动识别材料类型；
- 绑定 TrustPolicy；
- 文档路由；
- 弱值和噪声清洗；
- 产品和版本解析；
- Schema/Template 选择；
- 候选区域定位；
- Claim / Relation / Evidence 抽取；
- 类型归一化；
- 独立机器审核；
- 确定性验证；
- 缺口识别；
- 定向补抽；
- 新旧知识比较；
- 融合和冲突；
- 生成 ChangeSet；
- 生成 CandidateRelease；
- 执行 ReviewPolicy；
- 记录 ReviewDecision；
- 确定性生成 PageReleaseBundle；
- 向 WeKnora 准备和授权发布；
- 运行 Golden 评估。

Harness 不负责：

- 第二个 Active Head；
- 对外提供另一套"当前线上 Wiki"；
- 允许 Agent 直接绕过 WeKnora Release；
- 复制 WeKnora 的租户和 ACL 成为另一权威。

### 3.3 消费层负责什么

消费层包括：

- 人类 Wiki 浏览；
- RAG 快答；
- 结构化规则查询；
- 产品比较；
- 关联关系和图谱推理；
- Evidence 下钻；
- 反馈采集。

所有正式消费必须：

1. 在请求开始时确定 release_id；
2. 全程使用同一 release_id；
3. 页面、Claim、Relation、Evidence 不混版；
4. 读取时重新执行当前 ACL；
5. 知识不足时返回 insufficient / needs_qualification；
6. 不直接用未发布 chunk 形成正式业务结论；
7. **[v2]** 检索层必须 release-aware，不出现页面 R2 而召回 R1。

---

## 4. 核心领域模型

### 4.1 SourceRevision

代表某份原始材料的冻结内容版本。

建议包含：

- `source_revision_id`；
- `tenant_id`；
- `space_id`；
- `source_id`；
- `source_type`；
- `content_hash`；
- `manifest_digest`；
- `created_at`；
- `parser_identity`；
- `parser_version`；
- `acl_scope_ref`；
- 页、段、表、chunk 或结构化定位信息。

原则：

- Evidence 必须 pin 到 exact revision；
- 原文更新产生新 revision；
- 旧 revision 不被覆盖；
- 当前权限仍决定能否读取。

> **v3 删除语义合同**：普通逻辑删除、来源撤回、retention 到期、legal hold 和
> legal erasure 不是同一种动作。普通删除不得静默破坏当前 Active Release 的
> Evidence；来源撤回应生成新 Release 或将受影响 Release 标记为 revoked；
> retention 到期必须按策略产生可审计结果；legal hold 阻止清除；legal erasure
> 可以依法使历史 Evidence 不再可回验，但必须保留不含被清除内容的 tombstone、
> 授权依据、影响范围和审计记录。MVP-728 只实现普通删除不破坏当前引用的最小
> 行为，但五类状态与接口合同必须在 MVP 前冻结，不能用“永久保留所有原文”代替
> 合规设计。

### 4.2 MaterialClassification

代表系统对材料类型的判定。

建议包含：

- `classification_id`；
- `source_revision_id`；
- `material_type`；
- `confidence`；
- `signals`；
- `classifier_identity`；
- `policy_version`；
- `review_state`。

MVP 只需少量类别：

- official_clause；
- product_brochure；
- internal_rule；
- training_material；
- faq；
- ppt；
- ordinary_fragment；
- unknown_or_mixed。

不是每个文件由人工设置。模型和规则先识别，低置信或混合材料进入批量确认。

### 4.3 TrustPolicy

TrustPolicy 不能只是一个全局分数。

建议表达：

- 哪类材料；
- 对哪些字段；
- 在什么适用范围；
- 可作为主要 Evidence、辅助 Evidence 还是仅线索；
- 是否允许自动生成 Candidate；
- 是否要求第二来源；
- 是否强制人工；
- 与其他来源冲突时的处理。

示例：

| 材料类型 | 字段 | 采信方式 |
|---|---|---|
| 正式条款 | 保障责任、除外、等待期 | 主要 Evidence |
| 产品说明书 | 产品亮点、面客描述 | 高可信，但不得覆盖正式条款 |
| 内部核保规则 | 核保结论 | 主要 Evidence，受内部 ACL |
| 培训材料 | 解释、示例 | 辅助 Evidence |
| 销售经验 | 经验性建议 | 线索，不自动成为正式规则 |
| 普通片段 | 任意 | 候选线索，需加强校验 |

> **v2 命名裁决**：`TrustPolicy` 是唯一名称，禁止并存
> `SourcePrecedencePolicy` / `AuthorityPolicy`，且必须只有单一求值入口。

### 4.4 ProductIdentity 与 ProductVersion

产品版本是寿险知识归属的核心。

建议实体：

- Product；
- ProductVersion；
- ProductAlias；
- ClauseIdentity；
- FilingIdentity；
- Channel / Region / Population；
- VersionRelation。

ProductVersion 解析顺序：

1. 产品代码；
2. 条款编号；
3. 备案号；
4. 明确版本名称；
5. 主数据别名；
6. 文档级归属；
7. 生效时间；
8. 检索候选；
9. 模型判别。

结果状态：

- resolved；
- ambiguous；
- unresolved；
- quarantined。

向量只负责召回，不负责最终身份确认。

> **[已核验]** 该 resolver 的 exact 标识层已实现并合入（OpenSpec 041），
> 台档为 KEEP。S0-Q 阶段允许使用**预置** ProductVersion 以缩小范围，但
> MVP-728 必须走完整 resolver。

### 4.5 Schema / Template

Schema 是领域合同，Template 是面向材料和页面的编译策略。

Schema 建议包含：

- `schema_id`；
- `schema_version`；
- entity type；
- field definitions；
- typed value；
- enum；
- unit；
- required rule；
- conditional required rule；
- applicability；
- evidence requirement；
- accepted material types；
- validation rules；
- conflict rules；
- page mapping；
- field risk；
- **[v2]** provenance class（`source_evidence / human_attestation /
  external_sync / derived / undefined`）。

Template 建议包含：

- 适用材料类型；
- 定位策略；
- 抽取任务；
- 字段分组；
- prompt identity；
- model capability；
- validator；
- retry/fallback；
- 输出映射。

允许模型提出 extra field，但必须：

- 标注为 extension candidate；
- 绑定 Evidence；
- 不直接改变正式 Schema；
- 通过 Schema 演进流程确认。

> **[v2]** TemplatePackage registry 为既有资产，档位 KEEP（见需求文档 §13.3）。

### 4.6 Tri-state

字段状态：

- `present`；
- `absent_explicitly`；
- `unknown`。

必要性：

- "没有发现等待期"不等于"明确无等待期"；
- 第二批材料可以把 unknown 补成 present；
- absent_explicitly 需要明确 Evidence；
- 缺口引擎只对 unknown 或条件缺失触发补抽；
- 避免模型编造默认值。

> **v2 实测提示 [已核验]**：三态判定本身当前表现尚可（金标 unknown 39 个中
> 37 个预测正确，present 检出精度 0.948），但 `absent_explicitly` 是最薄弱档
> （5 个样本：2 正确、1 错判 present、2 漏为 unknown）。v3 的 S0-Q 同时保留
> 一个 `absent_explicitly` 字段和一个 `unknown` 字段：前者验证明确否定与
> Evidence，后者验证模型能否克制猜值。见需求文档 §9.0。

### 4.7 Claim

Claim 是正式事实单元。

建议字段：

```text
claim_id
tenant_id
space_id
subject_ref            ← 事实真正描述的实体（不必是 ProductVersion）
product_version_ref    ← 所属产品版本语境（产品特定事实不得为空）
predicate
state
typed_value
unit
applicability
effective_from
effective_to
evidence_refs[]
schema_identity
template_identity
trust_policy_identity
extraction_run_identity
validation_identity
status
revision
```

Claim 应稳定标识"哪个实体的哪个字段在什么条件和时间下是什么值"。

> **v2 不变量（替代旧"subject 恒等 ProductVersion"裁决）**：
> 所有产品特定知识必须被明确约束到某一个 ProductVersion；`subject_ref` 不必
> 恒等于 ProductVersion。产品版本自身的 effective interval / region / channel
> 构成外层包络，Claim 可在包络内收窄、**不得静默扩大**。产品特定事实的有效期
> 仍**从 ProductVersion 主数据继承**。详见需求文档 FR-05.1。

#### 4.7.1【v3 新增】Claim 身份与比较合同

`claim_id` 不能由随机 UUID 或页面位置决定，否则第二批材料到来时无法可靠判断
“同一事实的补证、改值、并存还是新事实”。MVP-728 前至少冻结三层键：

```text
claim_family_key
  = H(tenant_id, space_id, subject_ref, product_version_ref, predicate)

claim_comparison_key
  = H(claim_family_key, canonical_applicability)

claim_identity_key
  = H(claim_comparison_key, effective_from)
```

- `canonical_applicability` 必须把地区、渠道、人群、责任层级和业务条件按固定顺序
  规范化；不得直接 hash 模型生成的自由文本；
- `effective_to` 是可修订边界，不进入稳定身份键；其变化作为时间区间修订处理；
- 同一 `claim_comparison_key` 下，系统才允许调用 typed comparator 判断
  `same / enrich / coexist / supersede / conflict / unresolved`；
- 不同 `product_version_ref` 的事实默认不可自动合并；
- identity、comparison 和 comparator 的版本号必须写入 Candidate 与评估报告。

以上是逻辑合同，不预设物理表或索引实现；其 exact canonical vectors 必须在
MVP-728 前以跨语言测试冻结。

### 4.8 Relation

Relation 表达知识之间的结构：

```text
product_version --has_coverage--> coverage
coverage --excluded_by--> exclusion
product_version --provides_service--> service_sense
concept --has_sense--> service_sense
disease --has_underwriting_rule--> underwriting_rule
new_version --supersedes--> old_version
claim_a --conflicts_with--> claim_b
```

### 4.9 Evidence

Evidence 不能只写文件名。

建议字段：

```text
evidence_id
source_revision_id
locator_type
page_number
chunk_id
table_id
cell_range
json_pointer
quote_or_value_snapshot
content_hash
context_before
context_after
evidence_role
extraction_run_identity
```

Evidence 校验：

- locator 必须存在；
- quote/value 必须与冻结 source 对应；
- 支持该 Claim 的主语、字段、值、条件和时间；
- 访问必须经过当前 ACL；
- SourceRevision 不可用时正式查询 fail closed。

> **v2 实测提示 [已核验]**：引文逐字回验当前已达 **1.000**（两个模型臂
> 均为 1.000），说明 Evidence 绑定与回验机制是**已经成立**的一环。塌陷发生在
> 其后的"值一致性"（0.273）。质量工作应集中在 typed value 归一与语义支持
> 判定，而不是重做引文回验。
>
> **同时注意**：引文回验 1.000 ≠ Evidence 语义支持正确。逐字命中原文不等于
> 该段原文支持该 Claim 的主语/字段/条件/时间。语义支持校验是独立的一环，
> 尚未测量 **[未核验]**。

### 4.10 GapTask

GapTask 代表可执行的知识缺口。

来源：

- Schema required；
- conditional required；
- similar product comparison；
- version comparison；
- relation completeness；
- Lint；
- feedback；
- conflict resolution needs。

建议字段：

```text
gap_id
subject_ref
field_or_relation
reason
expected_evidence_type
candidate_sources
search_plan
status
attempt_history
result_claim_refs
```

### 4.11 ConflictSet

ConflictSet 不是简单保存两个不同值，而是保存：

- 同一字段；
- 涉及的实体和版本；
- 适用范围；
- 业务时间；
- 候选 Claim；
- 各自 Evidence；
- 来源采信规则；
- 可自动裁决与否；
- 建议动作；
- 人工决定；
- 解决后动作。

### 4.12 ChangeSet

ChangeSet 描述本次编译相对于基线 Release 的知识变化：

- add；
- enrich；
- coexist；
- supersede；
- conflict；
- retract。

每个 change 必须说明：

- old state；
- new candidate；
- reason；
- Evidence；
- policy；
- validation；
- review requirement。

### 4.13 CandidateRelease

CandidateRelease 是一个冻结的待审核知识版本。

应绑定：

- **base release_id**；
- **base activation_epoch**（**[v2 新增]** 防 ABA）；
- exact ChangeSet；
- exact Claim/Relation/Evidence；
- exact page bundle draft；
- Schema/Template/Policy；
- model and run fingerprint；
- quality report；
- conflict and gap summary；
- review policy；
- immutable digest。

人工不是逐页审核，而是对 CandidateRelease 及其中需要关注的 ReviewItem 做批量决策。

> **v2 为什么必须加 epoch**：只冻结 `base_release_id` 时，若基线在审核期间被
> 切走又切回（R1 → R2 → R1），digest 与 release_id 都看不出变化，Candidate
> 会基于一个"看起来相同、实际经历过变更"的基线激活。这是典型 ABA 问题。

---

## 5. 双时态设计

### 5.1 业务时间

表达知识在业务世界何时有效：

```text
effective_from
effective_to
```

规则：

- 使用 Space 业务时区解释的 ISO 日历日；
- 推荐半开区间 `[from, to)`；
- null 表示无穷；
- 同一产品版本同一字段若时间段重叠且值不兼容，应形成冲突。

### 5.2 系统时间

表达系统何时观察、记录和发布：

```text
observed_at
recorded_at
activated_at
```

规则：

- 服务端数据库 UTC；
- 追加式；
- 纠错产生新 event/revision；
- 不覆盖历史记录。

### 5.3 MVP 查询

MVP 只支持：

- `current`；
- `as_of_date`；
- `release_id`。

这保证数据模型不返工，但避免 MVP 过早实现完整双时态查询语言。

### 5.4 企业版查询

后续支持：

- `known_at`；
- "某业务日期、某系统认知时点"的组合查询；
- 历史审计重建；
- 新材料迟到后的认知变化分析。

---

## 6. 知识编译流水线

### 6.1 Stage A：接入和冻结

输入：

- WeKnora source lifecycle event；
- source_revision_id。

动作：

- 拉取 exact revision 元数据；
- 校验 ACL scope；
- 冻结 content hash / manifest digest；
- 建立不可变 NormalizedSourceRevision 与原文件 artifact；
- 未知 lifecycle 或 ACL 状态 fail closed。

输出：可 pin、可回验的 SourceRevision。

> **[已核验]** 本阶段对应既有能力项 P4a + P4c，档位 KEEP。

### 6.2 Stage B：材料分类

- 规则 + 模型联合判定 material_type；
- 输出 confidence 与 signals；
- 低置信/混合材料进入批量确认，不静默猜测；
- 绑定版本化 TrustPolicy。

### 6.3 Stage C：路由和清洗

- 按材料类型与结构特征路由到 Template；
- 弱值与噪声清洗（页眉页脚、水印、目录、无信息段）；
- 保留清洗前后对应关系，不破坏 locator。

### 6.4 Stage D：产品和版本消歧

- 按 §4.4 优先级顺序解析；
- 输出 resolved / ambiguous / unresolved / quarantined；
- 非 resolved 一律不得写入产品特定 Claim；
- 向量只召回，不定身份。

### 6.5 Stage E：Schema 选择

- 选定 schema_id + schema_version；
- 确定本次要抽的字段集合与条件必填规则；
- 绑定 provenance class（MVP 只发布 `source_evidence`）。

### 6.6 Stage F：候选区域定位

- 先定位候选区域，再抽取；
- 输出 locator 候选集；
- 定位失败即为 GapTask 来源，不进入大 Prompt 兜底。

> **v2 说明**：本阶段是当前质量提升的关键杠杆之一，且**不依赖 Release
> Kernel**，可立即开始，见 §16。

### 6.7 Stage G：结构化抽取

- 按字段小任务抽取，不做整文档大 Prompt；
- 输出 typed data + tri-state；
- 每个 present 值必须绑定 Evidence；
- 输出模型/prompt/run 指纹。

### 6.8 Stage H：确定性校验

- 类型、枚举、单位、区间、格式；
- 字段-值兼容性；
- 占位值与弱值清洗；
- 引文逐字回验（当前实测 1.000 **[已核验]**）；
- 失败输出 typed failure，不静默降级。

### 6.9 Stage I：独立机器审核

- 审核器与抽取器隔离（不同 prompt identity，不共享中间状态）；
- 校验产品版本归属、条件、适用范围、时间；
- 校验 Evidence 是否**语义支持**该 Claim（不只是逐字命中）**[未核验]**；
- 输出 machine review status，作为 ReviewPolicy 输入。

### 6.10 Stage J：缺口引擎

- 依 Schema required / conditional required / 关系完整性 / 对比同族产品与
  相邻版本生成 GapTask；
- 定向检索候选材料；
- 只补抽缺失字段及其关联条件；
- 保留 attempt_history；
- 无证据保持 unknown。

### 6.11 Stage K：增量比较和融合

- 与基线 Release 比较，产生六类动作
  （add / enrich / coexist / supersede / conflict / retract）；
- 比较前先判定实体、版本、时间、地区、渠道、人群与条件是否同一；
- 不把差异一律当冲突，也不按单一权威分自动覆盖；
- 输出 ChangeSet，每项带 reason 与 Evidence。

### 6.12 Stage L：页面编译

- 由 Claim/Relation/Evidence **确定性**编译页面，不由模型自由生成正式页面；
- 同时产出 `PublishedPayloadEnvelopeV1`（§8）；
- 页面 payload 中的快照必须能证明来自同一 canonical member digest。

### 6.13 Stage M：Candidate 和审核

- 冻结 CandidateRelease（含 base release_id + base activation_epoch）；
- 执行 ReviewPolicy；
- 高风险/冲突/版本歧义强制人工；
- ReviewDecision 绑定 exact Candidate digest。

### 6.14 Stage N：发布

- prepare → ready receipt → authorize → activate（CAS）→ release receipt；
- 全程见 §7。

---

## 7. WeKnora Wiki Release Kernel

### 7.0【v2 前置约束】本节是不变量规格，不是表结构规格

**v1 在本节直接列出 7 类对象，评审指出这在未核对上游能力前是过早冻结。**

v2 的处理：

- 本节 §7.1–§7.9 冻结的是**不变量与协议**；
- **物理表数量与归属（上游原生 / 可组合 / 必须新增）由 §7.10 能力矩阵决定**；
- 在能力矩阵填完前，不得编写 Release Kernel 实施规格，也不得新增
  project-owned WeKnora migration。

**特别提示 [已核验]**：目标 upstream snapshot 含官方
`000075_wiki_page_revisions`，且官方已提供 Wiki 单页 history / diff /
manual edit / revert。**但单页版本能力 ≠ 整版 Release 能力**——官方 revert 是
逐页语义，本项目要求的是整版切换且明确不支持单页 cherry-pick 回退
（需求文档 FR-11）。因此不得据此推断"Release Kernel 只剩一张 Head 表"。

### 7.1 目标

WeKnora 需要增加的不是寿险编译器，而是领域无关的整版发布能力。

它解决：

- 页面集合不可变；
- 结构化 payload 同版；
- Evidence source pin；
- 原子激活；
- 固定版本读取；
- 回滚；
- 并发保护；
- 审计回执；
- **[v2]** 禁止绕过 Kernel 的写入。

### 7.2 核心对象（逻辑对象，非表结构承诺）

#### WikiPageRevision

不可变页面修订：

- page logical id；
- revision id；
- rendered content；
- structured payload（见 §8）；
- content digest；
- created by；
- created at；
- visibility state。

#### WikiRelease

不可变发布版本：

- release_id；
- tenant/space/wiki_kb；
- candidate digest；
- manifest digest；
- base release；
- **base activation_epoch**；
- created at；
- activated at；
- release metadata。

#### WikiReleaseMember

完整成员关系。**[v2 强化]** 成员不只是页面，还包括 canonical 知识成员：

```text
WikiRelease
├── canonical ClaimRevision members
├── canonical RelationRevision members
├── canonical Evidence members
└── WikiPageRevision members
      └── 引用上述 canonical object IDs
```

每个 member 至少含：release_id、member kind、logical id、revision id、
order/path、member digest。

**为什么必须有 canonical member**：同一 Claim 可能出现在多个页面。若每个页面
各自持有一份独立的 Claim 快照，同一事实在一个 Release 内可能出现多个互不一致
的真相。页面 payload 允许包含便于 Agent 读取的快照，但必须能证明其来自同一
canonical member digest。（NFR-08 第 5 条）

#### ReleaseSourcePin

固定 Release 使用的来源：

- release_id；
- source_revision_id；
- evidence refs digest；
- ACL scope ref；
- pin status。

#### WikiReleaseHead

每个 `(tenant_id, space_id, wiki_kb_id)` 唯一：

- active_release_id；
- activation_epoch；
- updated_at。

#### ReleasePreparation

不可见准备区：

- preparation_id；
- candidate identity；
- manifest；
- expected base；
- status；
- expiry；
- digest。

#### ReadyPreparationReceipt

证明：

- exact preparation 完成；
- exact manifest 已写入；
- 内容不可变；
- 可进入授权。

#### ReleaseReceipt

证明：

- activate 或 rollback 结果；
- previous head；
- new head；
- new epoch；
- idempotency key；
- actor；
- timestamp。

### 7.3 Prepare

Harness 提交：

- tenant / Space / wiki_kb；
- candidate identity；
- page revisions；
- canonical knowledge members；
- structured payload；
- source pins；
- manifest digest；
- expected base release **+ expected base epoch**。

WeKnora：

- 校验权限；
- 校验成员完整性（含 canonical member 引用闭合）；
- 创建不可见 page revision；
- 创建 preparation；
- 计算或核对 digest；
- Ready 后冻结；
- 返回 ReadyPreparationReceipt。

### 7.4 Authorize

Harness 只有在：

- Candidate exact digest 未变化；
- ReviewDecision 有效；
- ReviewPolicy 有效；
- Conflict/Gaps 满足门禁；
- quality report 满足门禁；
- current ACL 校验通过；
- base release **与 base epoch** 均未漂移；

时签发短时 PublishAuthorization。

授权应绑定：

- preparation id；
- candidate digest；
- manifest digest；
- ReadyPreparationReceipt digest；
- ReviewDecision digest；
- ReviewPolicy version identity；
- tenant / Space / release-managed wiki_kb；
- expected head；
- expected epoch；
- action 与 exact scope；
- expiry；
- nonce；
- signer identity。

Activate 必须逐项验证上述绑定，不能只验证“某个审核已通过”或“某个 Candidate
存在”。任何 digest、policy version、scope、head/epoch 漂移都使授权失效。

### 7.5 Activate

WeKnora 在短事务中：

1. 先按幂等键查是否已有结果；
2. 校验授权签名、TTL 和 nonce；
3. 校验 preparation Ready 且 digest 一致；
4. 校验 current ACL；
5. 校验 expected head / epoch；
6. 创建不可变 WikiRelease 和 members；
7. CAS 更新 WikiReleaseHead；
8. 消费 nonce；
9. 写 ReleaseReceipt；
10. 提交事务。

### 7.6 关键不变量

- Ready 后不可修改；
- Active Release 不可修改；
- 页面 revision 不可修改；
- 一个 scope 只有一个 Active Head；
- Head 更新只能 CAS；
- nonce、CAS、receipt 同事务；
- 幂等查询先于过期判断，避免"已成功但重试得到过期"；
- 读取固定 release_id；
- rollback 也是正式授权动作；
- 当前 ACL 始终是最终门禁；
- **[v2]** `release_managed` 页面拒绝普通 PUT/DELETE，只允许经 Kernel 专用
  入口写入；
- **[v2]** 同一 Release 内每个 Claim/Relation/Evidence 只有一个 canonical
  member digest。

### 7.7 Pinned Read

请求开始：

1. 若显式给 release_id，验证存在和权限；
2. 否则读取当前 active_release_id 和 epoch；
3. 把 release_id 放入 request context；
4. 所有页面、Claim、Relation、Evidence 都使用该 release_id；
5. 不在请求中途重新读取 Active Head；
6. **[v2]** 检索/Agent 召回也必须受同一 release_id 约束，或明确标注为非正式
   来源。

### 7.8 Rollback

回滚不是删除 R2，也不是直接修改数据库。

流程：

```text
选择历史 release R1
→ 生成 rollback review/authorization
→ 校验当前 head 是预期 R2（含 epoch）
→ CAS 将 head 指向 R1
→ activation_epoch + 1
→ 写 ReleaseReceipt
```

R2 保留，便于审计和以后重新发布。

> **[v2] 粒度声明**：整版切换 + 经 SourceRetraction / emergency_withdrawal 的
> 定向撤回（撤回 = 生成新 Release，不是回退指针）；**不支持单页 cherry-pick
> 回退**。上游若提供单页 revert，不改变本项目语义，且必须确认其不会绕过
> Release Kernel。

### 7.9 ACL 漂移

发布后 Source 或 Evidence ACL 可能收缩。

读取时必须：

- 校验当前 Space/KB/Page ACL；
- Evidence 下钻校验 source 当前 ACL；
- 若已发布 Claim 依赖现在不可访问的关键 Evidence，fail closed；
- 形成 ReviewItem；
- 必要时紧急撤回或重编译最小受影响 Release。

不能假设"发布时有权限"就永久有效。

> **[v2] 补充禁止项**：Source 侧 ACL 不得通过编译后的 Claim、excerpt 或页面
> 文本发生**权限放大**——高权限材料抽出的事实出现在低权限页面即为放大
> （NFR-08 第 3 条）。

### 7.10【v3 重写】双基线上游能力矩阵（开工门禁一）

**在此表填完并经评审确认前，不得选择升级目标，不得冻结 Release Kernel 物理
设计，不得新增 project-owned WeKnora migration。**

必须同时比较：

- 官方稳定候选：`v0.7.1` /
  `c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`；
- post-release 对照 snapshot：
  `80a5003cc99a427098afe184eee6601916d3d156`
  （tree `18fcf68e7a008ce69929e32233f0b6914040c223`）。

| Release Kernel 能力 | v0.7.1 / c64a486 | 80a5003 snapshot | 项目必须新增 | exact 证据 | 选择影响 |
|---|---|---|---|---|---|
| 不可变 PageRevision | | | | | |
| 单页 history / diff | | | | | |
| 单页 manual edit / revert | | | | | |
| 多页 Release manifest（成员集合） | | | | | |
| canonical 知识成员（Claim/Relation/Evidence） | | | | | |
| 唯一 Active Head | | | | | |
| activation_epoch / CAS | | | | | |
| pinned read（页面 + payload 同版） | | | | | |
| 整版 rollback | | | | | |
| structured payload 存储 | | | | | |
| SourceRevision / Evidence pin | | | | | |
| ReleasePreparation（不可见准备区） | | | | | |
| ReadyPreparationReceipt | | | | | |
| activation receipt（幂等键） | | | | | |
| 读取时 ACL recheck | | | | | |
| **禁止普通 PUT/DELETE 绕过 Kernel 的 guard** | | | | | |
| 检索层 release-aware | | | | | |

**填表与选择规则**：

1. 每个“已有/可组合”判断必须给出 exact 文件路径、API、migration 或测试证据，
   不接受“新版应该有”；
2. “项目必须新增”必须估算 patch 面积、migration 面积、上游同区域碰撞风险与
   未来跟版责任；
3. 默认优先官方稳定版；只有 snapshot **显著减少长期 patch**、关键能力无法安全
   回移、migration 链已验证、未来跟版路径明确且风险被正式接受时，才选择 snapshot；
4. PageRevision、history/diff、部分 preparation 和内容存储可能被上游复用；
   整版 manifest、唯一 Head、epoch/CAS、整版 rollback、SourcePin、幂等 receipt
   不能仅因上游有“版本历史”就被推定存在；
5. guard 在本方案中保护唯一 Active Release，属于最小但不可省的边界能力；
6. 选择结果写入条件接受 ADR。矩阵未完成时，
   `WEKNORA_AS_AUTHORITY_CARRIER` 仍是 `ACCEPTED_CONDITIONALLY`。

---

## 8. PublishedPayloadEnvelopeV1【v2 重写】

### 8.1 为什么要有信封

页面除 rendered content 外还需结构化 payload，供 Agent 精确读取、页面引用、
产品比较、规则查询、citation 和 Golden 回归，避免 Agent 再从 Markdown 猜字段。

但 payload 内容是**寿险语义**，不能让 WeKnora 理解它——否则寿险概念
（Claim / Coverage / WaitingPeriod / UnderwritingRule）会渗入上游通用领域模型，
形成本方案明确要避免的重 fork。

v1 只给了字段清单，未解决"WeKnora 该理解多少"。评审提出两个方案并收敛：

- 完全不透明 bytes：能防渗透，但 digest 计算方式与语义合同版本不明确；
- **带最小通用元数据的信封（采用）**：既不渗透语义，又保住版本管理与可验证性。

### 8.2 信封定义

```text
PublishedPayloadEnvelopeV1
  payload_type              ← 通用类型标识，WeKnora 不解释其寿险含义
  payload_schema_version    ← payload 自身的结构版本
  semantic_contract_hash    ← 对应领域语义合同的 hash
  content_type              ← 序列化格式
  canonicalization_version  ← 规范化/摘要算法版本
  payload_digest            ← 内容摘要
  payload_body              ← 载荷
```

绑定关系：

```text
release_id
page_id
page_revision_id
→ PublishedPayloadEnvelopeV1
```

### 8.3 职责边界

**WeKnora 负责**：

- 不可变存储；
- 版本固定；
- digest 校验；
- ACL；
- 原样读取。

**WeKnora 不负责**：

- 理解寿险字段；
- 执行寿险 comparator；
- 解释 Claim 语义。

**Harness 或领域 Query Adapter 负责**：

- 解释 payload；
- 提供寿险结构化查询；
- **不拥有第二个 Active Head**。

### 8.4 底座已存在 [已核验]

`canonicalization_version` 与 `semantic_contract_hash` **不需要新发明**，仓库中
已有 Canonical Envelope 实现（OpenSpec 034 / C0）：

| 信封字段 | 已有实现 |
|---|---|
| `canonicalization_version` | `harness/src/insurance_harness/canonical/hashing.py` 中的 `HASH_SCHEMA_VERSION = "1"` |
| `payload_digest` / `semantic_contract_hash` | 同文件 `canonical_hash(object_type, value)`，算法为 `DOMAIN_SEPARATOR ‖ 0x00 ‖ HASH_SCHEMA_VERSION ‖ 0x00 ‖ object_type ‖ …` 的 domain-separated SHA-256 |
| 变更纪律 | 既有设计明文规定"更换算法或编码规则必须升 `hash_schema_version`，不得静默重算历史对象" |
| 跨语言一致性 | C0 已冻结语言中立 expected bytes/hash vectors + Python reference codec |

**Go 端 adapter 的时机**：既有设计将其挂在"首次真正消费时实现，并跑同一
vectors"。**Release Kernel 就是那个首次消费点。** 因此 Go adapter 属于 Release
Kernel 实施范围，且必须通过同一套 vectors 验证，不允许另写一套算法。

### 8.5 canonical member 与页面快照的关系

```text
Release
├── canonical Claim/Relation/Evidence member（各持 canonical_hash）
└── PageRevision
      └── PublishedPayloadEnvelopeV1
            └── 内含便于 Agent 读取的快照
                  └── 必须能对上同一 canonical member digest
```

违反此约束即触发 NFR-08 第 5 条问题：同一事实在一个 Release 内出现多个独立
真相。

---

## 9. 审核架构

### 9.1 为什么不能逐页人工审核

知识编译可能一次影响多个页面和几十条 Claim。逐页点击会：

- 丢失批次上下文；
- 无法看清同一变更对多页面影响；
- 审核成本随页面数线性上升；
- 无法形成整版发布决定；
- 难以规模化。

### 9.2 审核单元

人工审核单元是 CandidateRelease。

UI 可提供：

- 总体 diff；
- 高风险字段；
- ConflictSet；
- ProductVersion 歧义；
- machine review failure；
- Gap summary；
- 页面预览；
- Evidence 下钻；
- 批量 approve/reject；
- 对单个 ReviewItem 处理。

但最终 ReviewDecision 必须绑定 exact Candidate digest。

> **[已核验]** 本能力对应既有能力项 P13（Evidence + Review UX），档位
> **REWIRE**——能力保留，接线对象由投影页面改为 WeKnora Release 与 Candidate。

### 9.3 ReviewPolicy

输入维度：

- material type；
- field risk；
- ProductVersion confidence；
- extraction confidence；
- machine review status；
- conflict status；
- Evidence count/type；
- Schema；
- Space；
- automation approval。

输出：

- machine recommendation；
- human required；
- block；
- trusted import；
- future machine_auto eligibility。

### 9.4 MVP 审核

- 默认 human_batch；
- 机器先审核并标出重点；
- 低风险字段可以"机器建议通过"；
- 高风险、冲突和歧义强制人工；
- 人工一次批准 Candidate；
- 不逐页面点击；
- 不做无人发布。

### 9.5 企业版 machine_auto

必须具备：

- Canonical Golden；
- exact AutomationScope；
- covered capabilities；
- QualityProfileApproval；
- model/prompt/template fingerprint；
- shadow；
- canary；
- drift detection；
- rollback SLA；
- security profile；
- 实时撤销；
- 资格失效自动回落 human_batch。

> **[v2 已核验]** 该整条链在既有修正案中已被后置为条件画像，依赖知识质量门禁
> 批准后才启用。同时明确：**知识质量门禁本身不后置**——人在审不等于允许知识
> 是错的。后置的只是"质量门禁作为自动发布资格"的那一半。

---

## 10. Golden 与评估体系

### 10.1 评估对象拆分

不能只评估"最终页面看起来对不对"。至少拆为：

- material classification；
- routing/recall；
- ProductVersion resolution；
- field extraction；
- typed normalization；
- applicability；
- effective time；
- Evidence support（**语义支持**，不只是逐字命中）；
- independent review；
- gap detection；
- conflict classification；
- change action；
- page compilation；
- pinned read；
- rollback。

### 10.2 Seed Golden

在人工标注资源不足时：

1. 使用最强模型离线生成初标；
2. 对关键样本做交叉验证；
3. 人工抽检和修订；
4. 标记为 seed，不冒充专家真值；
5. 用于 prompt、模型和 pipeline 研发。

> **[v2 已核验]** 标注 agent 子系统为既有资产，档位"保留但限定"：仅用于 Seed
> Golden、标注辅助、失败分类、Evidence 对齐；**不得进入生产在线编译权威，
> 不得成为第二个 judge 真相**。

### 10.3 Canonical Golden

企业上线前：

- 专家确认；
- 按领域和风险分层；
- 版本化；
- 保留 disagreement；
- 作为发布和模型升级门禁。

### 10.4 指标

建议：

- classification accuracy/F1；
- entity resolution accuracy；
- ProductVersion exact match；
- field precision/recall/F1；
- condition exactness；
- time interval accuracy；
- citation support rate；
- **value consistency after detection**（**[v2] 当前塌陷点，必须单列**）；
- unsupported claim rate；
- wrong-entity rate；
- wrong-version rate；
- unknown/absent accuracy；
- conflict precision/recall；
- gap recovery rate；
- unchanged-field stability；
- release consistency；
- rollback correctness；
- latency/cost。

### 10.5【v2 新增】Metric ID 合同

所有指标引用必须遵守需求文档 §10.2.1 的 Metric ID 合同：绑定 report path、
commit、dataset id、schema identity、evaluator identity/version、metric
definition、分子/分母、run count、scope、admission_status。

**禁止在任何文档中书写裸数字**。三轮评审中已发生过一次因裸数字导致的口径
混淆（两份报告各有一个 `0.231`，含义不同）。

历史测量**不得因架构切换而清零**。当前基线见需求文档 §10.2.1。

---

## 11. MVP 技术方案

### 11.0【v3 重写】S0 双纵切技术方案

S0 不再用一条链同时证明发布架构和知识质量。两个最高风险必须分别取得证据，
可以并行实施，但状态独立，且只有逻辑与协议依赖，不共享第二 Active 状态。

#### S0-R：Release Skeleton

**目的**：证明确有一条最薄、非旁路、可并发验证的目标发布路径。

| 维度 | S0-R 取值 |
|---|---|
| scope | 1 个 tenant / 1 个 Space / 1 个 RAW KB / 1 个 release-managed Wiki KB |
| Candidate | 允许 fixture Candidate，避免把抽取质量混入发布实验 |
| 内容 | R0=A/B/C；R1=A 更新/B 删除/C 不变/D 新增；同 base 两个不同 Candidate |
| 审核 | 最小人工批准 + exact PublishAuthorization 绑定 |
| 发布 | R1，preparation → ReadyReceipt → CAS activation |
| 查询 | 激活前后并发 current/pinned/release-aware minimal read |
| ACL | 两个当前 principal + pinned 内容上的一次 ACL shrink |
| 故障 | preparation/index/CAS/receipt 边界的有界失败注入 |
| 守卫 | 普通 PUT/DELETE 不能修改 managed 页面 |

必须证明：重复提交幂等；并发激活只有一个赢家；expected head/epoch 漂移被拒；
任何读取只见完整 R0 或完整 R1；ACL shrink 后无权 principal 无旁路；Harness
无第二 Active Head；同一 Space 不产生第二个
release-managed Wiki KB；授权绑定 Candidate、manifest、receipt、审核和 scope；
普通写入不能绕过 Kernel。

两工作日窗口只能以以下二者之一结束：

```text
RELEASE_PATH_FEASIBLE
or
RELEASE_PATH_NOT_FEASIBLE
```

#### S0-Q：Quality Feasibility

**目的**：证明弱模型在极窄寿险切片上不是只能产出格式正确、语义错误的结果。

| 维度 | S0-Q 取值 |
|---|---|
| 材料 | 2 份真实、有代表性且可标注的材料 |
| ProductVersion | 1 个预置身份，跳过完整 resolver |
| 字段 1 | 普通 present 基线 |
| 字段 2 | present + typed normalization / comparator |
| 字段 3 | `absent_explicitly` + 明确 Evidence |
| 字段 4 | `unknown`，验证 abstention / 不猜值 |
| 输出 | Claim / Evidence / validator / error bucket，不要求接正式发布 |

必须证明：候选 span 命中；不串产品版本；typed normalization 失败时 fail closed；
Evidence 在主语、字段、条件和时间上语义支持 Claim；明确否定与 unknown 不混淆；
错误能够落入可行动桶；记录弱模型、强模型上限以及人工修订时间。

通过状态只能是：

```text
KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE
```

#### S0 联合门禁

```text
S0-R PASS
AND S0-Q PASS
→ 才允许进入 MVP-728 集成开发
```

任一通过都不能推出 `MVP_APPROVED`、`PRODUCTION_READY` 或载体已最终冻结。
S0 不验证 R2、完整 ConflictSet、增量补缺、rollback、完整 gap engine、完整
ProductVersion resolver、完整 Golden、完整 UI、machine_auto。S0-R 失败触发
WeKnora 载体复议；S0-Q 失败触发 Schema/任务拆分/模型上限/人工成本复议。

### 11.1 MVP 原则

- 使用最终目标边界；
- 缩小数据和 Schema，不缩小正确性；
- 不做过渡性双 Active；
- 不做完整企业功能；
- 优先验证最危险假设；
- 每个结果都能解释和回溯。

### 11.2 MVP 数据

- 10–15 份材料；
- 两个上传批次；
- 一个产品族；
- 两个相似产品或相邻版本；
- PDF；
- PPT；
- FAQ；
- 表格；
- 普通片段；
- 人为设置冲突；
- 人为设置缺口；
- 一项跨产品概念。

### 11.3 MVP Schema

只做少量高价值字段：

- product identity；
- product version；
- coverage；
- exclusion；
- waiting/cooling period；
- 1–2 个 underwriting/claim rule；
- 1–2 个 service concept。

### 11.4 MVP 页面

建议 5–10 页：

- 产品总览；
- 产品版本页；
- 责任页；
- 除外页；
- 权益/服务概念页；
- 一个多产品义项示例；
- 变更摘要或 release 页面。

### 11.5 MVP 组件

Harness：

- material classifier；
- ProductVersion resolver；
- TemplateCatalog；
- structured extractor；
- deterministic validator；
- independent reviewer；
- Evidence verifier（含语义支持判定）；
- gap detector；
- fusion/conflict engine；
- Candidate builder；
- human_batch ReviewPolicy；
- page compiler；
- release client；
- Seed Golden runner。

WeKnora：

- SourceRevision 接口；
- Release Kernel（**物理构成待 §7.10 能力矩阵确定**）；
- pinned query；
- 禁止绕过写入的 guard；
- Wiki UI。

> **v3 提示**：本清单共 14 + N 个组件，是 MVP-728 的规模，不是 S0-R/S0-Q 的规模。
> S0-R 与 S0-Q 分别只验证发布可行性和知识编译可行性，不能用任一纵切替代本清单。

### 11.6 MVP 全流程

#### 批次一

1. 上传 6–8 份材料；
2. 形成 SourceRevision；
3. 自动分类；
4. 产品和版本消歧；
5. Schema 抽取；
6. Evidence 回验；
7. 机器审核；
8. 输出 unknown 和 GapTask；
9. 与空基线比较，形成 add；
10. 构建 Candidate R1（冻结 base release + base epoch）；
11. 人工批审；
12. prepare/authorize/activate；
13. 查询 R1。

#### 批次二

1. 上传 4–7 份补充材料；
2. 定向关联已有产品和版本；
3. 对第一批 unknown 定向补抽；
4. 同值新证据形成 enrich；
5. 不同版本形成 coexist 或 supersede；
6. 真冲突形成 ConflictSet；
7. 构建 Candidate R2；
8. 人工批审；
9. 激活 R2；
10. 验证 R1/R2 pinned read；
11. 回滚到 R1。

### 11.7 MVP 验收

必须证明：

- 每个 Claim 有 Evidence；
- 产品版本错配可被阻断；
- unknown 不被猜值；
- 第二批可以补缺；
- 已正确字段稳定；
- 同值证据可以 enrich；
- 冲突能被发现并分流；
- 人工按批次审核；
- R1/R2 不混版；
- 可以回滚；
- 人和 Agent 使用同一 release；
- **[v3]** §8 NFR-08 的 10 条 P0 合同全部关闭；
- **[v2]** 质量证据以 Metric ID 合同格式提交。

### 11.8 MVP 不做

- 全量领域；
- 全量规模；
- 完整 Concept/Sense；
- 逐条 Wiki 社区编辑历史；
- machine_auto；
- 复杂双时态查询；
- 多区域高可用；
- 全量图谱推理；
- 完整运营控制台。

---

## 12. 企业级完整路线图

### Phase E1：语义编译器生产化

目标：把 MVP 编译链变成可扩展产品能力。

能力：

- Product Catalog；
- ProductVersion 主数据；
- Schema Registry；
- Template Catalog；
- Material Classifier；
- TrustPolicy 管理；
- 多领域抽取；
- Evidence verifier；
- independent reviewer；
- Gap/Conflict engine；
- 编译任务重试、回放和可观测；
- Canonical Golden；
- 模型和模板升级门禁。

### Phase E2：知识治理和人类体验

目标：让专家可以持续维护。

能力：

- 概念和 Sense；
- 关联页面；
- Lint；
- diff；
- changelog；
- Conflict workbench；
- Gap workbench；
- 批量审核；
- 页面编辑提案（对应 P10，DEFER 档）；
- 修改历史；
- 贡献者；
- 讨论和审批；
- 紧急撤回；
- ACL 漂移处理。

### Phase E3：Agent 和业务应用

目标：让人和 Agent 使用同一知识权威。

能力：

- Active Query API；
- MCP adapter；
- typed rule query；
- product comparison；
- relationship query；
- citation；
- Evidence drill-down；
- insufficient/needs_qualification；
- feedback event；
- Agent trace 与知识版本关联。

### Phase E4：规模化运营

目标：支持几十万材料和多团队长期运行。

能力：

- 增量 backfill（含既有 stock_backfill 资产）；
- micro-batch；
- priority queue；
- capacity profile；
- dead letter；
- 分区；
- retention；
- GC；
- 成本看板；
- 质量 SLO；
- shadow/canary；
- machine_auto；
- 多租户、多 Space、多业务域；
- 应急回滚和业务连续性。

---

## 13. 旧资产吸收方案

### 13.1 WeKnora

复用：

- 上传解析；
- Source；
- 检索；
- 权限；
- 审计；
- Wiki UI；
- API；
- Agent。

增强：

- SourceRevision 的稳定对外合同；
- Wiki Release Kernel（面积待 §7.10 确定）；
- pinned read；
- structured payload；
- rollback；
- 禁止绕过 Kernel 的写入 guard。

限制：

- patch 必须保持领域无关；
- 不把寿险语义嵌入上游；
- 尽量使用插件/API；
- 最终实施时基于最新主线确认已经存在的上游能力，避免重复开发；
- **[v2]** 在能力矩阵填完前不新增 project-owned WeKnora migration。

### 13.2 `nashsu/llm_wiki`

吸收方法：

- 三层架构；
- ingest/query/lint；
- 原子页；
- index/log；
- LLM 维护；
- 人机协作。

不吸收为生产权威：

- 本地 Markdown 文件就是线上数据库；
- 个人级权限；
- 无批次发布；
- 无产品版本和寿险治理。

> **v2 明确**：该项目是**方法论来源，非代码来源**。承载运行时的是 WeKnora
> （企业平台）+ Python Harness（领域编译器）。不存在"把个人级项目合并进企业
> 平台"这一动作。

### 13.3 `LLM-wiki-black`

优先评估迁移：

- 产品目录 taxonomy；
- Schema 想法；
- 内容寻址和迁移凭证思路；
- routing；
- cleaning；
- compat；
- weak-value；
- 产品/服务/模块组织；
- 概念聚合原型；
- 领域样例和测试资产。

迁移时必须：

- 重构到 Python Harness；
- 接入当前 Claim/Evidence 主链；
- 增加 ProductVersion；
- 增加 exact Evidence；
- 增加 Golden；
- 增加 Release 语义；
- 核对 provenance/license；
- 不保留独立 Node/TS 生产事实库。

### 13.4【v2 新增】既有已合入资产的处置

见需求文档 §13.4 五档台账。技术方案侧的要点：

**不需要重写的（KEEP）**：Job Store + Outbox 任务运行时、API/Worker shell、
Source Inbox、Microbatch、Revision Capture、ProductVersion resolver、
Canonical Envelope、Capacity Contract、Active Fence Verifier、Space Security
Boundary。

**改接线的（REWIRE）**：Evidence + Review UX（改为消费 WeKnora Release 与
Candidate）；managed-page 的 RAW ACL guard 与防绕过 guard（保留并提升重要性）。

**目的被消解的（SUPERSEDE）**：managed-page 的 epoch high-watermark / 迟到写
保护（无第二 Active 即无迟到写）；旧 018 路线的 `current_release` 指针与逐页
补偿 saga（**[已核验]** 在 033 下即已判定被取代，728 只改变接管者）。

**唯一删除的（DELETE）**：Projector（activation manifest → 异步投影页面）。

**后置的（DEFER）**：ChangeProposal domain/API、Proposal Edit UX。

**必须核对而非假设的 [未核验]**：P1/P3 接口是否隐含 Harness 最终 serving；
测试是否把 Harness reader 当正式线上读取；publisher 是否与 Candidate lifecycle
耦合；status/receipt 是否以旧 Snapshot 为领域结果；对外 API 是否暴露
`current_release`。

---

## 14. 实施顺序建议

### 14.0【v2 新增】三道开工前门禁

**在任何 Release Kernel 物理实现或 S0-R 编码之前**，必须完成：

| 门禁 | 产出 | 当前状态 |
|---|---|---|
| 一 · 上游能力核对 | §7.10 能力矩阵填满，每行带 exact 证据位置 | **[未核验]** |
| 二 · 代码状态台账 | 需求文档 §13.4 五档表 + 5 项未核验条目结论 | **部分已核验** |
| 三 · 历史指标证据清单 | 需求文档 §10.2.1 Metric ID 合同 | **[已核验]** |

三道门禁**不阻塞**质量线（§16）并行启动。

### 14.1 先冻结方案

外部评审本文及配套文档，重点审查：

- 权威边界；
- MVP 范围；
- 弱模型质量链；
- Release Kernel 不变量（**不是表结构**）；
- 双时态；
- 自动审核边界；
- **[v3]** §5.6 精确否决清单、§7.10 双基线矩阵完整性、§8 NFR-08 十条合同、
  S0-R/S0-Q 联合门禁、五档台账正确性。

### 14.2 再形成实施规格

拆为独立、可验收任务：

1. S0-R Release Skeleton；
2. S0-Q Quality Feasibility（四字段 + 消融）；
3. SourceRevision / retention / erasure contract；
4. ProductVersion + Schema；
5. Claim identity / Evidence extraction；
6. machine review；
7. Gap/Conflict；
8. Candidate/human_batch（含 base epoch 冻结）；
9. WeKnora Release Kernel（在门禁一之后）；
10. pinned query/rollback；
11. Seed Golden；
12. MVP 数据和验收。

### 14.3 再做代码现状映射

实施前才需要回答：

- 哪些已经有；
- 哪些部分有；
- 哪些需要替换；
- 哪些旧组件应冻结；
- 哪些 WeKnora 最新上游能力可直接复用。

> **v2 变化**：本步已由需求文档 §13.4 部分完成（五档台账 + 三条已核验事实），
> 剩余 5 项 [未核验] 条目必须在门禁二中关闭。

### 14.4 最后执行 MVP

按纵向闭环交付，不按"先把所有底层框架做完"推进。

每个阶段都必须能回答：

- 对抽取准确率有什么改善；
- 对 Evidence 有什么改善；
- 对冲突/缺口有什么改善；
- 是否更接近可发布的 R1/R2；
- 是否产生新的长期双系统复杂度；
- **[v2]** 本阶段产出的质量证据的 Metric ID 是什么。

### 14.5【v2 新增】文档与载体清单

七项资产，各自回答一个问题：

| # | 资产 | 回答什么 | 载体 |
|---|---|---|---|
| 1 | 728 v3（本文） | 要建设什么 | 本文件 + 四份独立文档 |
| 2 | Sole Release Authority ADR | 权威边界为何如此 | `docs/superpowers/specs/2026-07-28-weknora-sole-release-authority-adr.md` + `D-2026-07-28-1` |
| 3 | 033 Amendment 2 | 旧设计如何被取代、Amendment 1 逐项去向、五档台账 | 仓库 specs 目录 |
| 4 | 状态台账 | 当前代码实际有什么 | 控制板 |
| 5 | 历史指标证据清单 | 当前质量是多少、基于什么 | 见 §10.2.1 |
| 6 | Upstream Release Capability Matrix | 上游已有什么、还需补什么 | 见 §7.10 |
| 7 | S0-R / S0-Q OpenSpec + Mission Card | 两条窄纵切如何分别实现和验收 | 两个 scope，先占号；可共用 program 但不得混用通过状态 |

**编号纪律 [已核验]**：ADR 不占 OpenSpec 编号；OpenSpec 一律**先占号后建目录**
（仓库曾发生目录先于注册表行创建的漂移）。

---

## 15. 技术方案最终判断

该方案相较之前双系统投影路线，MVP 会明显简单，原因不是删掉核心能力，而是删掉了没有业务价值的第二 Active 权威和长期投影一致性。

仍然困难的地方集中在真正值得做的部分：

- 弱模型抽取；
- ProductVersion 消歧；
- Evidence；
- 增量融合；
- 冲突；
- Golden；
- 原子 Release。

这些难点无法通过换一个 Wiki UI 或增加更多 Agent 掩盖。它们正是企业级寿险 LLM Wiki 的核心壁垒。

最终技术路线：

```text
以 WeKnora 作为企业平台、原始材料权威和唯一在线 Wiki Release 权威；
以 Python Harness 作为寿险知识编译与治理层；
以 Claim / Relation / Evidence 作为事实核心；
以 Candidate batch 作为审核单元；
以不可变 Release 作为人和 Agent 的共同消费边界；
以 Golden、Gap、Conflict 和反馈形成持续演进闭环。
```

### 15.1【v2 新增】必须与"更简单"一起说清的代价

"MVP 明显简单"这一判断只在**分布式一致性维度**成立。诚实的完整表述是：

| 维度 | 相较双 Active 投影路线 |
|---|---|
| 跨系统一致性复杂度 | **大幅下降**（无第二 Active、无 freshness、无对账、无迟到写） |
| 高频读路径复杂度 | **下降**（读只在一个系统内完成） |
| 低频发布路径复杂度 | **上升**（两阶段 + 签名授权 + nonce + CAS + 幂等先于过期） |
| WeKnora patch 面积 | **上升**（整版 Release 语义 + pinned read + 防绕过 guard；具体面积待 §7.10） |
| 与上游碰撞风险 | **上升**（Release Kernel 与官方 wiki page revision 同区域；已发生过一次撞号 **[已核验]**） |
| 领域质量能力 | **不变**（架构切换不改变 F1） |

选择本方案的理由是前两项的收益是**持续的**，而后三项是**集中、边界明确、
长期存在于低频发布路径、可用协议与门禁封顶的成本**。它们不会在首次实现后
消失；该判断必须由 S0-R 与双基线矩阵验证，不能被当作已成立的前提。

### 15.2【v2 新增】本方案不解决的问题

必须明确写出，避免下一轮再次误判进度：

1. **不解决抽取准确率**。当前 micro F1 `0.231`、值一致率 `0.273`
   （calibration-only，见 §10.2.1）不会因为权威反转而改变一格；
2. **不解决 Golden 缺位**。Canonical Golden 仍需专家投入；
3. **不解决样本缺位**。MVP-728 需要 10–15 份带冲突、带缺口、带版本陷阱的真实
   材料，这是业务输入，不是工程产出；
4. **不解决上游跟版**。它把跟版面积从"投影 + fencing + 双 ACL"缩小到"Release
   Kernel + guard"，但不为零；
5. **不解决 Evidence 语义支持**。引文逐字回验已达 1.000，但"该段原文是否支持
   该 Claim 的主语/字段/条件/时间"尚未测量 **[未核验]**。

### 15.3【v2 新增】过程护栏与治理

技术方案的执行必须继承既有过程护栏（详见需求文档 §13.2）：

1. 一个 PR 一个核心不变量；
2. 一个 PR 最多一个 migration；
3. 写代码前先冻结事务边界与威胁矩阵；
4. 两轮修复—评审后仍在同一域发现新的基础不变量 → **停线，换边界，不叠补丁**；
5. 关键并发路径必须有 PostgreSQL 真并发测试；
6. 高风险项须双独立评审（规格侧 + 质量侧）；
7. 非阻断项转 BACKLOG，不在当前 PR 无限扩域；
8. 开工前提交 Mission Card 并取得逐项批准（**保留原名，不在本次架构切换中
   夹带改名** **[已核验]**）。

这些护栏在既有交付中已抓出过真实缺陷（过期 lease 仍持写权威、崩溃导致 attempt
不递增、领域写通道伪造跨 Space 终态、表名未规范化导致伪造写入等），不因架构
切换而失效。

---

# 企业级寿险 LLM Wiki：技术难点与核心问题（JLX 728 · v3）

> 日期：2026-07-28
> 版本标识：728-v3
> 文档类型：核心问题、技术难点、风险与验证重点
> 整理依据：2026-07-28 讨论窗口 + v2 三轮评审 + v3 复评裁决
> 重要说明：本文描述需要解决的问题和目标解法，不是当前代码完成度审计。

---

## 1. 结论

当前方案真正困难的地方不是 WeKnora 页面怎么展示，也不是再搭一套 Wiki，而是以下六个问题：

1. 弱模型能否稳定抽取；
2. 能否把事实放到正确的产品、版本、时间和适用范围；
3. 每条事实能否被 Evidence 证明；
4. 新材料能否增量补缺、融合和发现冲突；
5. 一批知识能否被审核、原子发布、固定版本读取和回滚；
6. 是否有 Golden Set 证明更换模型、Schema 和策略后质量没有退化。

之前双系统投影方案的困难主要来自系统复杂度；新方案删除了第二 Active 权威，但不会让上述领域难点自动消失。相反，它把开发重点重新放回真正形成企业壁垒的部分。

> **v3 证据边界**：第 1 与第 3 项已有量化测量。当前状态是
> **Evidence 逐字回验已经解决（1.000），值一致性尚未解决（0.273）**，
> 整体 micro F1 `0.231`，距目标 3–4 倍，报告判定为"结构距离，不是调参距离"。
> 这证明“值粒度与表述口径”是重要错误桶，但不能据此排除模型能力上限；须由
> S0-Q 消融区分。

---

## 2. 优先级总览

| 优先级 | 问题 | 为什么危险 | MVP 是否必须验证 |
|---|---|---|---|
| P0 | 产品和版本消歧 | 正确事实写错产品比漏抽更危险 | 是 |
| P0 | 弱模型抽取准确率 | 当前准确率低，直接决定项目成立与否 | 是 |
| P0 | **typed value 归一与值一致性** | **[v2] 已测为全部分数塌陷点（0.273）** | **是，最高杠杆** |
| P0 | Evidence 支持 | 没有证据就无法审核、纠错和合规 | 是 |
| P0 | Evidence **语义**支持 | **[v2]** 逐字命中 ≠ 支持该 Claim；尚未测量 | 是 |
| P0 | 增量补缺、融合与冲突 | 新材料不能只重复全量生成 | 是 |
| P0 | Candidate 批审 | 逐页人工无法规模化 | 是 |
| P0 | 原子 Release、pinned read、rollback | 防止人和 Agent 混版 | 是 |
| P0 | Seed Golden | 没有评估就无法判断改进 | 是 |
| P1 | TrustPolicy | 不能用一个权威分处理所有字段 | 是，先做少量类型 |
| P1 | 双时态 | 寿险版本和迟到材料不可避免 | 数据模型兼容，查询简化 |
| P1 | Concept/Sense | 跨产品概念需要统一组织 | MVP 做样例，完整能力后置 |
| P1 | 修改历史 | 企业长期维护需要 | MVP 后置 |
| P1 | **上游碰撞治理** | **[v2] 已发生过一次 migration 撞号** | 门禁一必须关闭 |
| P2 | 全量规模化 | 几十万材料需要容量工程 | 企业阶段 |
| P2 | machine_auto | 风险高，需质量准入 | 企业阶段 |

---

## 3. 核心问题一：产品、版本和适用范围消歧

### 3.1 为什么这是首要风险

寿险材料中大量实体名称非常相近：

- 产品正式名称和简称相似；
- 同一产品有多个条款版本；
- 不同渠道、地区、人群有差异；
- 新旧版本共存；
- 面客材料与正式条款用词不同。

把正确事实写到错误产品版本，比漏抽更危险——它会产生看起来完整、实际错误的知识。

### 3.2 不能采用的简单方案

- 只按文件名或目录判断；
- 只按向量相似度匹配产品；
- 只让模型自由判断；
- 用一个全局 confidence 阈值决定是否采信。

### 3.3 推荐方案

按确定性优先的顺序解析：

1. 产品代码；
2. 条款编号；
3. 备案号；
4. 明确版本名称；
5. 主数据别名表；
6. 文档级归属；
7. 生效时间；
8. 检索候选；
9. 模型判别。

结果状态必须显式：resolved / ambiguous / unresolved / quarantined。

非 resolved 一律不得写入产品特定 Claim。

### 3.4 MVP 验证

MVP 数据必须包含相似产品与相邻版本陷阱，并证明错配可被阻断而不是静默写入。

> **[已核验]** exact 标识层 resolver 已实现并合入，档位 KEEP。S0-Q 允许使用预置
> ProductVersion 以缩小范围；MVP-728 必须走完整 resolver 并证明阻断能力。

---

## 4. 核心问题二：弱模型抽取准确率

### 4.1 当前真实风险

生产必须假设弱模型（Qwen / MiniMax 能力档），不能依赖强模型在线兜底。

**[已核验] 当前实测状态**（详见需求文档 §10.2.1，全部为 calibration-only）：

| 指标 | 值 | 解读 |
|---|---|---|
| micro F1（2 产品合计） | 0.231 | 距 G0b 目标 3–4 倍 |
| micro P / micro R | 0.259 / 0.208 | 召回略低于精度 |
| 单产品区间 | 0.152 ~ 0.313 | 产品间差异显著，不可用均值代表 |
| present 检出精度 | 0.948 | **检出判断已较可靠** |
| present 检出召回 | 0.764 | 漏抽约四分之一 |
| **检出后值一致率** | **0.273** | **全部分数塌陷点** |
| 引文逐字回验 | 1.000 | **已解决** |
| 幻觉率（deepseek / qwen-flash） | 0.052 / 0.220 | 两个已测模型臂差约 4 倍，因果尚待消融 |

**跨模型对照的已测现象 [已核验]**：值一致率在两个模型上几乎相同
（约 0.27–0.28），而幻觉率差 4 倍。v3 将原来的因果结论降级为两个假设：

1. 值一致率可能主要受候选定位、口径、typed normalization 和 comparator 的
   共享工程瓶颈限制；
2. 幻觉差异可能与模型能力或提示/采样配置有关。

行动上仍应分别优化 Schema/工程链与模型/审核链，但必须用 oracle span、固定
输出、模型互换和 verifier 互换的消融证明各自贡献，不能把相关性写成因果结论。

### 4.2 为什么只改 Prompt 不够

- 无法定位错误发生在定位、抽取还是归一；
- 无法按字段分别度量；
- 无法证明改动带来提升而非过拟合；
- 大 Prompt 的失败是整体失败，没有可修复的中间态。

**[v2 已核验补充]**：实测已证明错误不在三态判定（unknown 判定 37/39 正确），
而在检出后的值表述。因此改 Prompt 的边际收益极低——问题在**值的口径与粒度
定义**，属于 Schema 与 comparator 的职责。

### 4.3 推荐的弱模型编译模式

```text
材料分类
→ 路由到 Template
→ 候选区域定位
→ 按字段小任务抽取
→ typed output + tri-state
→ Evidence 绑定
→ 确定性校验
→ 独立机器审核
→ 失败 → typed failure / unknown / GapTask
```

关键：每一步都可单独度量、单独修复。

### 4.4 抽取器与审核器隔离

- 不同 prompt identity；
- 不共享中间状态；
- 审核器不看抽取器的推理过程，只看 Claim + Evidence + 原文；
- 禁止同一次调用既抽取又自证。

### 4.5 MVP 验证

- 按字段度量 precision / recall；
- 单列**值一致率**；
- 单列 **Evidence 语义支持率**（区别于逐字回验）；
- 单列 unknown / absent_explicitly 准确率；
- 复杂表格与跨页字段单独统计；
- 全部以 Metric ID 合同格式提交。

---

## 5. 核心问题三：Evidence 粒度和可验证性

### 5.1 为什么文件级来源不够

- 审核者无法定位到具体条款；
- 无法判断该段是否真的支持该字段；
- 原文更新后无法确认证据是否失效；
- 无法做引文回验；
- 合规无法接受"来自某份 PDF"这种粒度。

### 5.2 Evidence 最小要求

- exact `source_revision_id`；
- locator（页 / 表 / 单元格 / 段 / chunk / json pointer）；
- quote 或 value snapshot；
- content hash；
- 上下文前后文；
- evidence role（主要 / 辅助 / 线索）；
- extraction run identity。

### 5.3 Evidence 支持不是字符串包含

**[v2 强化]** 这是当前最容易产生虚假信心的一点。

已达成的：**引文逐字回验 = 1.000 [已核验]**。即"这段话确实出现在冻结的原文
里"。

**尚未达成、且尚未测量的 [未核验]**：该段原文是否**支持该 Claim 的主语、字段、
值、条件和时间**。例如：

```text
原文："本产品等待期为 90 天，续保时不再计算等待期。"
Claim：waiting_period = 90 days（applicability: 首次投保）
```

逐字回验通过，但若 Claim 漏掉 applicability，则该 Evidence 并不支持这条
（被过度泛化的）Claim。

因此必须把两者作为**两个独立指标**：

| 指标 | 当前状态 |
|---|---|
| citation verbatim verification | **1.000 [已核验]** |
| evidence semantic support rate | **[未核验]**，MVP-728 必须测量 |

### 5.4 多来源 Evidence

- 同一 Claim 可有多条 Evidence；
- 不同来源可能是 enrich（同值补证）或 conflict（异值）；
- TrustPolicy 决定哪条可作主要 Evidence；
- 高风险字段可要求第二来源。

### 5.5 ACL 难点

- Evidence 下钻必须走当前 ACL，不能用发布时快照；
- ACL 收缩后必须 fail closed 并形成 ReviewItem；
- **[v2]** 不得通过 Claim、excerpt 或页面文本发生权限放大
  （NFR-08 第 3 条）——高权限材料抽出的事实出现在低权限页面即为放大；
- **[v2]** 来源删除后历史 Evidence 是否仍可回验，必须实测确认
  （NFR-08 第 2 条）。

---

## 6. 核心问题四：材料分级与 TrustPolicy

### 6.1 用户确认的要求

- 材料有分级；
- 面客说明书权威度较高但不覆盖正式条款；
- 普通片段较低；
- 只配置少量类型，模型自动识别；
- 不逐文件设置。

### 6.2 难点

- 一份材料可能混合多种类型（如培训 PPT 里引用正式条款）；
- 分类错误会连带采信错误；
- 权威度不能是单一分数；
- 时间与产品版本共同影响采信。

### 6.3 推荐结构

TrustPolicy 表达"哪类材料 × 哪些字段 × 什么适用范围 → 采信方式"，输出：

- 主要 Evidence / 辅助 Evidence / 仅线索；
- 是否允许自动生成 Candidate；
- 是否要求第二来源；
- 是否强制人工；
- 与其他来源冲突时如何处理。

> **[v2] 命名裁决**：统一为 `TrustPolicy`，禁止并存 `SourcePrecedencePolicy`
> 或 `AuthorityPolicy`，必须只有单一求值入口。历史文档中的
> `SourcePrecedencePolicy` 合并入此项。

### 6.4 分类错误处理

- 低置信 → 批量确认，不静默采信；
- 混合材料 → 分段分类或降级为线索；
- 分类被修正后，受影响 Claim 必须可重新评估（不是全量重跑）。

---

## 7. 核心问题五：增量补缺

### 7.1 用户确认的目标

第二、第三批材料应能补充第一批的缺口，而不是全量重新生成。

### 7.2 难点

- 需要知道"缺什么"，这依赖 Schema 与 tri-state；
- 需要定向检索而非全库重扫；
- 需要保证已正确字段稳定不漂移；
- 需要保留补抽历史以便审计。

### 7.3 推荐 Gap 引擎

来源：Schema required、conditional required、相似产品对比、相邻版本对比、
关系完整性、Lint、反馈、冲突解决需要。

产出 GapTask，含 subject_ref、字段/关系、原因、期望 Evidence 类型、候选来源、
检索计划、状态、attempt_history、结果 Claim 引用。

### 7.4 定向补抽

- 只抽缺失字段及其关联条件；
- 不触碰已有正确字段；
- 无证据保持 unknown，不猜值。

### 7.5 防止误补

- 补抽结果必须经同样的确定性校验与独立审核；
- 同值 → enrich；
- 异值 → 进入融合/冲突判定，不直接覆盖；
- 补抽失败不得把 unknown 改写为 absent_explicitly。

---

## 8. 核心问题六：融合、冲突和更新

### 8.1 差异不等于冲突

判定顺序：是否同一实体 → 同一产品版本 → 同一业务时间 → 同一适用范围
（地区/渠道/人群/条件）→ 同一字段语义。

任一不同即为 coexist，不是 conflict。

### 8.2 六类变化动作

`add` / `enrich` / `coexist` / `supersede` / `conflict` / `retract`。

每项必须说明 old state、new candidate、reason、Evidence、policy、validation、
review requirement。

### 8.3 自动裁决边界

可自动裁决：同实体同版本同范围同字段，新来源在 TrustPolicy 下明确更权威，
且 Evidence 支持充分。

不可自动裁决：来源权威度相当、Evidence 不足、跨版本语义变化、高风险字段。
一律进人工批审。

### 8.4 冲突展示

ConflictSet 必须保留双方 Claim、各自 Evidence、采信规则、建议动作与人工决定，
不能只显示"两个不同值"。

---

## 9. 核心问题七：Candidate、审核和发布

### 9.1 为什么审核必须按批次

一次编译可能影响多个页面与几十条 Claim。逐页点击会丢失批次上下文、成本随
页面数线性上升、无法形成整版决定。

### 9.2 审核配置

ReviewPolicy 按 Space 版本化，输入 material type、field risk、版本置信度、
抽取置信度、机器审核状态、冲突状态、Evidence 数量与类型、Schema、Space、
自动化批准。

### 9.3 MVP 的正确边界

- 默认 human_batch；
- 机器审核作为建议与回执；
- 高风险、冲突、版本歧义强制人工；
- ReviewDecision 绑定 exact Candidate digest；
- 不做无人发布。

### 9.4【v2 新增】Candidate 的 ABA 风险

Candidate 必须同时冻结 `base_release_id` **与** `base_activation_epoch`。

失败场景：

```text
t0  Candidate 冻结，base = R1
t1  R1 → R2 激活
t2  R2 → R1 回滚（Active 又回到 R1）
t3  Candidate 激活：base release_id 仍等于 R1，检查通过
    但基线实际经历过 R2，中间的知识变更被静默丢弃
```

只有同时校验 epoch 才能发现 t1–t2 的变更。这是 NFR-08 第 1 条。

---

## 10. 核心问题八：原子 Release、固定版本读取和回滚

### 10.1 如果没有 Release

- 页面可能半新半旧；
- 人和 Agent 读到不同版本；
- Evidence 与页面不同版；
- 无法回滚，只能重新生成（会重新调模型，结果不确定）。

### 10.2 为什么 Active Head 必须唯一

两个 Active Head 意味着必须长期回答"哪个更新""哪个是真的"，并为此维护
freshness、fencing、对账。本方案把 Active Head 唯一化到 WeKnora。

### 10.3 Release 难点

- 准备区必须不可见；
- Ready 后不可变；
- 激活必须 CAS + epoch；
- 幂等查询必须先于过期判断（否则"已成功但重试得到过期"）；
- nonce / CAS / receipt 必须同事务；
- **[v2]** 必须有 canonical member，页面快照须能对上同一 digest；
- **[v2]** 必须禁止普通 PUT/DELETE 绕过 Kernel；
- **[v2]** 物理实现面积待上游能力矩阵确定，不得预设。

### 10.4 MVP 必须证明

R1 原子激活、R2 无半新半旧、pinned read、回滚到 R1、receipt、幂等、并发激活
只有一个赢家。

### 10.5【v2 新增】与上游单页能力的关系

**[已核验]** 目标 upstream snapshot 含官方 `000075_wiki_page_revisions` 与
单页 history / diff / manual edit / revert。

必须明确：

- 单页能力**不能**替代整版 Release 语义；
- 官方 revert 是**逐页**语义，本项目明确**不支持单页 cherry-pick 回退**；
- 若采用官方 PageRevision 作为底层存储，必须确认其写入路径**不会绕过**
  Release Kernel（否则唯一 Active Release 会被旁路写穿）；
- 究竟哪些可复用、哪些必须新增，由能力矩阵（技术方案 §7.10）决定，
  当前 **[未核验]**。

---

## 11. 核心问题九：双时态

### 11.1 为什么一开始兼容

寿险产品版本、迟到材料、追溯生效不可避免。若第一版只有 `updated_at`，后续
补双时态需要重迁移全部历史知识。

### 11.2 为什么 MVP 不做完整查询

完整 `known_at` × `as_of` 组合查询语言成本高，且 MVP 不需要。数据模型兼容 +
三种查询（current / as_of_date / release_id）即可避免返工。

### 11.3 实现风险

- 业务时间与系统时间混用；
- 区间开闭不一致；
- 时区解释不统一；
- 覆盖历史记录而非追加；
- **[v2]** 产品特定事实的有效期必须**从 ProductVersion 继承**，Claim 只能在
  包络内收窄，不得静默扩大（见需求文档 FR-05.1）。

---

## 12. 核心问题十：Golden Set

### 12.1 没有 Golden 的后果

- 换模型无法判断好坏；
- 改 prompt 无法证明提升；
- 无法阻断质量退化发布；
- 无法定位错误类型。

### 12.2 Golden 的层级

Seed（强模型初标 + 人工抽检，研发用）→ Canonical（专家确认，正式门禁）→
自动化准入 Golden → 跨版本 Golden。

### 12.3 Golden 必须覆盖的过程

不只最终页面，还包括分类、路由召回、版本解析、字段抽取、typed 归一、
适用范围、生效时间、Evidence 支持、独立审核、缺口检出、冲突分类、变化动作、
页面编译、pinned read、rollback。

### 12.4【v2 新增】Golden 的证据纪律

- 所有引用必须遵守 Metric ID 合同；
- 必须保留 scope（`calibration_only` / `acceptance`）与 admission_status；
- calibration-only 测量**不得**用于授予任何验收状态；
- 历史测量**不得**因架构切换清零；
- 当前基线见需求文档 §10.2.1。

---

## 13. 核心问题十一：人类 Wiki 与 Agent 知识的一致性

### 13.1 不能只优化一种消费方式

只给人看 → Agent 需要再解析自然语言；只给 Agent → 专家无法维护。

### 13.2 双表示、单一事实

同一 Claim 同时编译为人类页面段落与结构化 payload，二者来自同一 canonical
member，**不允许各自演化**。

### 13.3 Concept/Sense 难点

跨产品复用概念（如"在线问诊"）需要独立概念页 + 分产品义项。MVP 只做样例，
但数据结构与页面映射不得阻断后续演进。

---

## 14. 核心问题十二：修改历史和反馈闭环

### 14.1 已确认需求

正式上线后必须保留类似维基百科的修改历史：修改前后内容、修改人、原因、
Evidence、提案、审核、发布时间、版本关系、可追溯视图。

### 14.2 为什么后置

它依赖 Release、Candidate、Proposal 与页面编译全部稳定；提前做会与 Release
语义反复冲突。

> **[v2 已核验]** 本项对应既有能力项 P10（ChangeProposal domain/API）与 P14
> （Proposal Edit UX），档位 **DEFER**。**它们不是投影专属能力，不得按编号
> 取消。** P10 已冻结的关键约束（Published 不可直改、stale base 拒绝、事实
> 编辑无新 provenance 拒绝、编辑必经新 Candidate/Decision）在本方案下继续有效。

---

## 15. 规模化难点

### 15.1 几十万材料不能一次性全编译

必须支持增量编译、micro-batch、优先队列、可重试与可回放任务、容量画像、
dead letter、分区、retention 与 GC。

> **[已核验]** 任务运行时（状态机、lease/generation fencing、事务 Outbox）与
> 容量合同已实现并合入，档位 KEEP。stock_backfill 资产保留但不阻塞 S0-R/S0-Q。

### 15.2 模板和 Schema 的平衡

- Schema 太细 → 维护成本高、抽取任务爆炸；
- Schema 太粗 → 无法比较与判定冲突；
- Template 必须能按材料类型复用，不能一产品一模板。

### 15.3 重编译影响范围

- Schema 升级、模板升级、模型升级都会引发重编译；
- 必须能计算影响范围（哪些 Claim / 页面 / Release 受影响）；
- 不能每次升级全量重跑；
- 重编译结果仍需走 Candidate 与审核，不得直改 Active。

---

## 16. 之前路线踩过的坑

### 16.1 把"薄补丁"低估为局部改动

一旦涉及：

- fencing；
- freshness；
- ACL 双检；
- 对账；
- 迟到写；
- rollback；
- 上游跟版；

它就不是薄补丁，而是长期分布式一致性子系统。

### 16.2 用大量底层原语代替纵向闭环

项目可以拥有很多：

- job；
- handler；
- manifest；
- event；
- store；
- migration；
- spec；

但如果没有：

```text
SourceRevision
→ Claim/Evidence
→ Conflict/Gap
→ Candidate
→ Review
→ Active Release
→ Query
→ R2
→ Rollback
```

业务仍然感受不到 MVP。

> **[v2 已核验] 这条坑在本项目已经发生。** 已合入的能力项（任务运行时、
> Canonical Envelope、容量合同、Revision 合同、API/Worker shell、
> ProductVersion resolver、fence verifier、Space 安全边界规格）**没有任何一项
> 产出用户可见的知识输出**。这正是 S0-R / S0-Q 存在的理由：在 MVP-728
> 完成前分别拿到发布路径与知识质量的可判定证据。

### 16.3 重新讨论已经确认的边界

反复重开"是否双系统""是否逐页审核""是否需要时间"等问题，会导致设计漂移。

后续评审可以提出证据充分的修改，但必须说明：

- 改哪个已确认决策；
- 为什么原决策不成立；
- 新增多少复杂度；
- 对 MVP 有什么直接价值；
- 是否导致推倒重来。

> **[v3]** 单一 Active 原则不因偏好反复重开；WeKnora 载体则明确允许在双基线
> 矩阵或 S0-R 证伪后按同一程序复议。`subject_ref` 的修改同样走此程序
> （见需求文档 FR-05.1）。

### 16.4 把旧资产等同于必须保留旧运行时

旧分支有价值的是领域知识、taxonomy、Schema、routing、cleaning、样例与评估
资产；不是旧技术栈、旧事实库、旧 Active、旧投影边界。

### 16.5 把高权威来源理解为自动覆盖

权威性必须绑定字段、产品版本、时间、适用范围与来源状态，不能"分数高者覆盖
分数低者"。

### 16.6 把模型置信度当正确率

模型 confidence 不是可校准的业务正确率。

> **[v2 已核验] 实测证据**：high-confidence 桶的三态正确率 0.923，但同一桶的
> **值级正确率只有 0.231**（78 样本）。同时 low 桶值级正确率反而是 0.688
> （因其多为 unknown 预测）。**这直接证明 confidence 不可直接当正确率用**，
> 且 confidence 分层在不同指标上的区分度方向甚至相反。
>
> 注：此处的 0.231 与需求文档 §10.2.1 的 micro F1 0.231 是**两个不同报告中的
> 巧合同值**，含义完全不同。这正是 Metric ID 合同存在的原因。

### 16.7 把空值当没有

`unknown != absent_explicitly`。这是缺口补抽、冲突与业务回答能否正确的基础。

> **[v2 已核验]** 实测 `absent_explicitly` 是最薄弱档（5 样本：2 正确、1 错判
> present、2 漏为 unknown）。v3 的 S0-Q 用独立字段同时覆盖
> `absent_explicitly` 与 `unknown`。

### 16.8 把 rollback 理解为重新生成

回滚必须是指向历史不可变 Release、原子切换 Head、保留审计、不重新调用模型、
不重新生成页面。

### 16.9【v2 新增】在上游活动区域自建同号 migration

**[已核验] 已发生**：项目自有 `000066_knowledge_revision_manifest` 与上游
`000066_expand_knowledge_span_name` 同号不同义，上游其后另有 `000067–000074`。
代价是一个采用 Mission 至今未关闭，且 trusted 运行制品仍不含项目已合入的
revision 合同。

**教训**：Release Kernel 与官方 wiki page revision 处于同一区域。因此：

- 在能力矩阵填完前不新增 project-owned WeKnora migration；
- 官方链与企业链必须独立 ledger；
- 不得静默重命名或删除 legacy 编号；
- 必须有编号 × schema object × patch surface 三层碰撞 CI。

### 16.10【v2 新增】用裸数字在文档间传递质量结论

**[已核验] 已发生**：两份不同报告各有一个 `0.231`（一为全局 micro F1，一为
high-confidence 桶值级正确率），在评审往返中造成过一次口径混淆。

**教训**：所有质量数字必须绑定 Metric ID 合同（report path + commit +
dataset id + evaluator version + metric definition + 分子/分母 + scope +
admission_status）。禁止裸数字。

### 16.11【v2 新增】按编号而非按能力做取舍

**[已核验] 差点发生**：早期讨论中曾提出"取消 P4a/P4c/P11–P14"。但 P4a 是
Source Inbox、P4c 是 Revision Capture，二者是 728 自身 FR-01 与 Evidence pin
的实现；P13 是审核台；P14 与 P10 属于修改历史。按编号整体取消会误删有效资产。

**教训**：架构切换必须按**能力**分档（`KEEP / REWIRE / SUPERSEDE / DEFER /
DELETE`），不按编号批量处理。最终只有 Projector 一项为 DELETE。

---

## 17. MVP 最需要快速验证的风险

### 验证一：弱模型是否接得住

不是问强模型能不能写代码，而是验证生产弱模型在真实样本上能否正确定位、
正确抽取、正确给 Evidence、正确识别 unknown、被独立审核发现错误。

> **[v3 证据边界] 当前答案是"还接不住"**：既有 calibration-only 报告中
> micro F1 0.231，值一致率 0.273。两个模型结果接近只支持“共享工程瓶颈可能
> 主导”的假设，**不能证明**问题完全不受模型能力限制。

S0-Q 必须做最小消融，分离候选定位、模型抽取、规范化和验证器的贡献：

1. 给定 Golden/oracle span，测抽取与 typed normalization；
2. 固定 span 与 Schema，只替换弱/强模型，测模型上限；
3. 固定模型原始输出，只替换 normalizer/comparator，测工程层增益；
4. 固定 Claim，只替换 Evidence semantic verifier，测校验层召回与误杀；
5. 记录各桶错误数、abstention、人工修订时间，不用单一 F1 掩盖瓶颈。

### 验证二：产品版本错配能否阻断

必须有相似产品和版本陷阱，并证明错配被阻断而非静默写入。

### 验证三：第二批能否只补缺

第一批故意保留缺失字段，第二批提供 Evidence，验证定向补抽且已有正确字段稳定。

### 验证四：差异能否正确分类

至少覆盖 enrich / coexist / supersede / conflict。

### 验证五：批次审核是否可用

审核者应能在一个 Candidate 中看清变化、Evidence、风险、冲突、页面预览。

### 验证六：单一 Release 是否成立

必须演示 R1、R2、pinned read、rollback、人和 Agent 同版。

### 验证七【v2 新增】：Evidence 语义支持能否度量

逐字回验已达 1.000，但语义支持率尚未测量。必须证明"该段原文支持该 Claim 的
主语/字段/条件/时间"可被独立判定，否则 Evidence 的可信度是虚高的。

### 验证八【v3 重写】：S0-R 与 S0-Q 能否分别在短周期内给出结论

S0-R 用 fixture Candidate 验证发布协议，S0-Q 用 2 份真实材料和 4 个字段验证
知识编译。若任一路径都无法在短周期内得出明确 PASS/FAIL，则必须分别重估
Release Kernel 或 weak-model pipeline，而不是用另一条路径的进度掩盖问题。

---

## 18. 难度判断

### 18.1 MVP 难度

总体为中高难度，但比双系统投影方案明显可控。

主要难度不再是大范围 WeKnora fork 和跨系统一致性，而是：

- 样本和 Golden；
- ProductVersion；
- Evidence（含语义支持）；
- weak-model pipeline（尤其 typed value 归一）；
- ChangeSet；
- Release Kernel（面积待定）。

只要严格限制为一个产品族、少量 Schema、两批材料和 5–10 个页面，强工程模型可以
承担实现辅助，但模型能力不能替代明确规格、真实样本、Golden、专家验收与原子
发布不变量。

### 18.2【v2 新增】对 MVP-728 规模的诚实评估

MVP-728 需要 14 + N 个组件（技术方案 §11.5）、10–15 份材料、两批次、
40–60 条事实、5–10 页、R1/R2/rollback 全套，外加 §8 NFR-08 的 10 条 P0 合同。

按既有交付节奏（单个基础设施能力项曾经历四轮独立评审才合入），这一级不是
数周量级。这不是反对 MVP-728 的范围——那些验证项确实是项目价值所在——而是要求：

1. **不得**把 MVP-728 的完成时间当作"很快能看到东西"的承诺；
2. **必须**先让 S0-R 与 S0-Q 分别在短周期内拿到可判定证据；
3. **必须**同时并行推进质量线，不等 Release Kernel。

### 18.3 企业版难度

高难度，原因：多业务域、大规模增量、Schema 演进、ACL、双时态、Concept/Sense、
人工治理、machine_auto、多租户运营。因此企业版必须按阶段扩展，不应塞回 MVP。

---

## 19. 风险登记

| 风险 | 后果 | 早期信号 | 缓解 |
|---|---|---|---|
| 抽取仍然端到端大 Prompt | 难定位错误 | 页面漂亮但字段不稳 | 拆阶段、typed output、Golden |
| **值口径/粒度不统一** | **[v2] 已发生，F1 塌陷** | 检出对但值不一致（0.273） | Schema 值定义、comparator、归一层 |
| ProductVersion 不稳定 | 高危错答 | 相似产品互串 | 确定性标识优先、quarantine |
| Evidence 只到文件 | 无法审核 | 找不到具体原文 | exact locator + hash |
| **Evidence 语义支持未度量** | **[v2] 可信度虚高** | 只报逐字回验 1.000 | 单列语义支持率指标 |
| TrustPolicy 只用总分 | 错误覆盖 | 新文档覆盖正式规则 | 字段级、场景级策略 |
| 缺口引擎全量重跑 | 成本高且旧值漂移 | 每批都重新生成 | GapTask + 定向补抽 |
| 差异都当冲突 | 审核爆炸 | 不同版本也报警 | applicability/time/version 比较 |
| 差异都自动覆盖 | 错误发布 | 旧值无痕消失 | 六类动作 + 人工门禁 |
| 双 Active 回归 | 一致性复杂度复发 | 出现 projection freshness | 单一 WeKnora Head |
| 按页审核 | 无法运营 | 审核点击量随页面增长 | Candidate batch |
| machine_auto 过早 | 合规风险 | 无 Golden 就无人发布 | human_batch-first |
| 双时态后补 | 数据迁移重 | 只有 updated_at | 第一版建模，MVP 简化查询 |
| 全量企业能力进入 MVP | 再次延期 | 页面/历史/Agent 同时开工 | 只验四个核心假设 |
| **Candidate ABA** | **[v2] 静默丢失中间变更** | 只冻结 base release_id | 同时冻结 base epoch |
| **Release Kernel 面积失控** | **[v2] 长期 fork** | 未核对上游即写规格 | 门禁一：能力矩阵 |
| **与上游同区域撞号** | **[v2] 已发生一次** | 新增 project migration | 独立 ledger + 三层碰撞 CI |
| **ACL 经知识放大** | 权限泄漏 | 高权限事实出现在低权限页 | 发布前 + 读取时双向校验 |
| **检索不 release-aware** | 混版答案 | 页面 R2、召回 R1 | 检索受同一 release_id 约束 |
| **绕过 Kernel 写 managed 页** | 唯一 Active 被写穿 | 普通 PUT 可改 managed 页 | 防绕过 guard |
| **按编号取消能力** | **[v2] 误删有效资产** | 出现"取消 Pxx"表述 | 五档能力台账 |
| **裸数字传递质量结论** | **[v2] 已发生一次** | 文档写"F1=0.231" | Metric ID 合同 |
| **S0-R 或 S0-Q 被当作 MVP** | 假阳性结论 | 任一纵切通过即宣称架构或质量成立 | 两条状态独立，且必须同时 PASS 才进入 MVP-728 |

---

## 20. 外部评审检查表

评审者应逐项给出"成立 / 不成立 / 需要补充证据"：

- [ ] 权威边界是否唯一；
- [ ] 是否彻底删除第二 Active；
- [ ] ProductVersion 是否优先于语义相似；
- [ ] Claim 是否有 typed value、applicability 和 time；
- [ ] Evidence 是否可回到 exact SourceRevision；
- [ ] unknown 与 absent 是否分开；
- [ ] TrustPolicy 是否字段化；
- [ ] 抽取器和审核器是否隔离；
- [ ] GapTask 是否支持定向补抽；
- [ ] 六类 change action 是否足够；
- [ ] Candidate 是否 immutable；
- [ ] 人工是否按批次审核；
- [ ] WeKnora Release 是否原子；
- [ ] 查询是否 pinned；
- [ ] rollback 是否只切 Head；
- [ ] ACL 漂移是否 fail closed；
- [ ] MVP 是否包含代表性冲突和版本陷阱；
- [ ] Golden 是否评估中间环节；
- [ ] 企业能力是否被正确后置；
- [ ] 是否还有过渡性架构。

### 20.1【v3 重写】v3 专属检查项

- [ ] §5.6 对"被否决的究竟是什么"的精确表述是否成立；
- [ ] 是否仍有未被识别的跨系统一致性负担；
- [ ] §7.10 能力矩阵行项是否完整（是否遗漏会扩大 fork 的能力）；
- [ ] 十条 P0 合同（NFR-08）是否覆盖发布、身份、合规与权限边界；
- [ ] canonical member 合同是否足以防止"同一事实多份真相"；
- [ ] `PublishedPayloadEnvelopeV1` 七字段是否足够，是否泄漏寿险语义到上游；
- [ ] FR-05.1 新不变量是否覆盖寿险全部事实形态；
- [ ] 五档台账是否有错档（特别是 P11 的拆分）；
- [ ] S0-R / S0-Q 的独立状态和联合门禁是否会被误用；
- [ ] Metric ID 合同是否足以防止裸数字误读；
- [ ] 在 F1 基线 0.231（calibration-only）前提下，S0-Q 四字段与消融是否能
      回答可行性；
- [ ] 是否存在会导致再次推倒重来的隐含过渡架构（本版特别关注 Release Kernel
      的物理实现选择）。

---

## 21. 最终判断

当前技术方案可以做，但不能再把"系统搭起来"当成主要进度。真正的进度必须用以下证据衡量：

- 有一组经过确认的 Golden；
- 能看到抽取错误类型；
- 能阻断错误产品版本；
- 每条 Claim 有 exact Evidence；
- 第二批能补缺且不破坏第一批正确知识；
- 冲突能被分类和审核；
- Candidate 可以批量审批；
- WeKnora 能原子发布 R1/R2；
- 人和 Agent 同版；
- 可以回滚。

只要这些证据没有出现，项目仍然没有完成 MVP；只要这些证据形成，项目才真正拥有向企业级扩展的基础。

---

## 22【v3 重写】MVP-728 前必须关闭的 10 条 P0 合同（汇总）

与需求文档 §8 NFR-08 相同，此处按难点视角复述验证方式：

| # | 合同 | 验证方式 |
|---|---|---|
| 1 | MVP 一个 Space 只绑定一个 RAW KB 与一个 release-managed Wiki KB | 尝试绑定第二个 RAW/managed KB，证明被拒；未来扩展必须另开 ADR/OpenSpec/migration |
| 2 | Candidate 冻结 base release_id **+ base activation_epoch** | 构造 R1→R2→R1 的 ABA 序列，证明旧 Candidate 被拒 |
| 3 | Claim identity / comparison / comparator 固定 | 用同事实补证、适用范围变化、跨产品同名和改值向量验证六类变化动作 |
| 4 | 删除、撤回、retention、legal hold、legal erasure 分义 | 对五类动作验证 serviceability、rollbackability、tombstone 与审计结果 |
| 5 | ACL 不经 Claim/excerpt/页面放大 | 高权限材料抽出的事实，用低权限账号读页面与 payload |
| 6 | 检索/Agent release-aware | 激活 R2 后立即检索，证明不召回 R1 内容 |
| 7 | canonical member，不按页面各持真相 | 同一 Claim 出现在两页，证明二者 digest 同源 |
| 8 | payload digest 的 canonical serialization 固定 | 跨语言（Python/Go）跑同一 vectors 得同一 digest |
| 9 | PublishAuthorization 完整绑定 | 逐项替换 candidate/manifest/receipt/review/policy/scope/head，证明激活被拒 |
| 10 | 禁止普通 PUT/DELETE 绕过 Release Kernel | 用普通 Wiki API 尝试改 managed 页，证明被拒 |

这些合同不要求全部进入 S0-R/S0-Q，但 **MVP-728 不得在其未关闭时宣称通过**。

---

## 23【v2 新增】架构切换不改变的事情

必须写在难点文档里，因为这是最容易被误判为进度的地方。

**权威反转解决的**：

- 开发力被错误的一致性问题消耗；
- 双权威；
- 长期投影与跟版成本；
- 服务版本不确定。

**权威反转不解决的**：

- 候选区域召回；
- ProductVersion 归属；
- 条件抽取；
- 表格理解；
- typed normalization；
- Evidence 语义支持；
- unknown / absent 区分。

**真正能提高质量的路径**：

```text
真实样本
→ Seed Golden
→ 错误分桶
→ 候选区域定位
→ 字段小任务
→ Schema / typed output / comparator
→ ProductVersion resolver
→ deterministic validation
→ independent review
→ Evidence semantic verification
```

**因此**：架构 Amendment 与质量线**必须并行**。不能等 Release Kernel 完成才开始
改善 `0.231`。这条路径上的每一步都不依赖 Release Kernel。

---

# Enterprise LLM Wiki 项目交接文档（mvp_handoff_jlx · v3）

> 日期：2026-07-28
> 版本标识：728-v3
> 文件名：`mvp_handoff_jlx.md`
> 面向对象：完全没有历史上下文的新会话、新开发者、新架构师、外部评审模型
> 整理范围：2026-07-28 讨论窗口 + v2 三轮独立架构评审 + Codex/Web GPT v3 复评
> 文档性质：持续更新的项目交接，不是代码 Review，不代表本文提到的能力已经实现
> 使用方式：接手者先完整阅读本文，再阅读需求、技术方案和难点文档；在用户要求实施前，不要擅自把讨论结论改回旧架构。

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
   Release 与 KB 级 Head 粒度矛盾；
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

使用 fixture Candidate，在一个 Space、一个 release-managed Wiki KB 中验证
preparation、完整授权绑定、CAS activation、幂等、pinned/release-aware read、
managed 写守卫以及 Harness 无第二 Active。状态只能是
`RELEASE_PATH_FEASIBLE`。

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

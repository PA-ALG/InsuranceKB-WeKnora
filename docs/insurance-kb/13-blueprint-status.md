# 13 · 整体蓝图现状与 LLM Wiki 引入缺口（2026-07-21）

> 回答两个问题：**整个体系建到哪了**；**企业级 LLM Wiki 北极星还有哪些缺口**。滚动更新，每完成一个 change 修订一次。
>
> [!WARNING]
> **历史状态账本，不是当前执行授权。** 本页保留既有 change 的交付证据；旧
> change 的“完成/验收”只表示其当时规格范围通过，不能推导为企业级能力已经
> 完成，也不能授权旧 P-1/Projector/publisher 路线。当前规范层级依次为
> [Sole Serving Active Release Authority ADR](../superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md)、
> [Authority Amendment 2](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)
> 与适用 OpenSpec；实时交接见仓库根 `HANDOFF.md`。

## 0. 当前总判断

现有代码已经形成 WeKnora 平台底座、基础 schema/goldenset、抽取/Claim/审核/发布链和部分 MCP/结构化接入的工程地基；但项目整体仍未达到企业级 LLM Wiki 产品验收。当前必须补齐的北极星工作包为：

1. **NS-RIGHTS（已记录）**：`LLM-wiki-black` 为项目方第一方资产，可按 provenance 迁移；`nashsu/llm_wiki` 等第三方许可证继续单独管理；
2. **NS-0**：彻底封死生产强模型路径，并冻结每次调用的模型身份与策略 hash；
3. **NS-A**：建立领域→险种→文档类型→产品/版本四级 `TemplatePackage` registry、准入、回滚和失配告警；
4. **NS-B**：把现有管道升级为可恢复的多 Agent Harness，完整持久化 job/stage/attempt/receipt/event/alert；
5. **NS-C**：补齐全制品 `ReleaseSnapshot`、授权人 `ReleaseApproval`、P-1 active alias receipt 与同快照回滚；
6. **NS-D～NS-F**：可信结构化直入、多产品事实级路由、知识工作台以及百千文档并发治理。

因此，以下表格中的 ✅ 均按“既有 change 范围”解读；它不代表当前生产准入。MVP 先按 027～030/032/010 thin 完成 23-entry 受控输入真实闭环；完整 NS-A～NS-F、P-1 和 13 产品 baseline 通过后，才能宣称企业生产核心完成。

## 1. 既有 change 蓝图（代码地基状态）

```
原始文档 ──► WeKnora 解析/chunk ──► [003]分类路由 ──► [004]抽取管道 ──► [007]Claim落库
                                        ▲fastpath[006]        │
结构化JSON/FAQ ──► [010 T1～T4；thin 待建]直入通道 ────────────┤
                                                              ▼
                        [007]增量合并/权威序裁决/审核门禁/ChangeSet
                                │                    ▲
                    [008 核心已交付]审核工作台    [005]评测尺子/归因 ◄── [002]金标
                                ▼
           [029]批准快照 ──► [032]Human Reader / [013]MCP（P-1 前）
                    [NS-C/P-1 seal+alias] ──► 生产 Wiki ──► Agent/人
                        │ [009 待建]概念页/义项/互链          ▲
                        ▼                                     │
                  [011 待建]知识健康度巡检          [012 待建]QA对象 · [P2]图谱/研究
```

| Change | 内容 | 状态 |
|---|---|---|
| 001 脚手架+WeKnora适配层 | | ✅ 已验收 |
| 002 金标与评估子系统 | 金标 11/13（T8 遗留 B1） | ⏳ 部分验收，完整真实运行转 020；不得计为整体完成 |
| 003 产品主数据+分类路由 | 分类/exact 路由 100% | ✅ 已验收 |
| 004 抽取管道 legacy MVP | 基线 F1 0.184(v1)/0.216(v2)，evidence 100% | ⚠️ 第一方旧规格/测试范围通过；可由 028 记录 provenance 后选择性重构，027/030 前 production-disabled |
| 005 评测尺子v2+召回归因 | 值粒度 54 为最大失分项 | ✅ 已验收 |
| 006 模板 fastpath+可喂性评分 | 费率表列直取留出验证 1.00；族指纹修复 | ⚠️ 第一方旧范围已验收；可作为 028 迁移输入，当前 production-disabled，不等于 NS-A 四级 TemplatePackage |
| 007 Claim/合并/审核/发布主链 | 端到端故事通过 | ✅ 旧范围已验收；不含 NS-C/P-1 全制品人工批准与原子 serving alias |
| 008 审核工作台 | W1–W7 条款 + T1–T8 任务（2026-07-16 基础对齐修订） | ✅ 核心 T1～T5/T7 已随 PR #15 合入；T6/W4 作为独立 follow-up |
| 009~012 | 概念层/结构化直入/健康度/QA对象 | 🚧 **010 T1～T4 已合入（PR #14），021 已合入（PR #23），010 T5～T12 现可认领**；011 主规格+PR #22 fast-follow 收口后可独立认领；009/012 分别等待 010 域段/qa_staging，不作整波无条件放行 |
| 013~014 | insurance MCP server / 批量并发调度（P0.5） | 📋 B15~B16；013 规格就绪且已由 PR #9 解锁（轨道 L3），014 仍须正式 delta；规格覆盖不等于组件或产品已实现 |
| 015 | 数据飞轮 | ✅ durable foundation 已随 PR #18 合入；Langfuse 直连与 ReviewItem 动作投影仍 gated |
| 016 | KnowledgeSpace/强制作用域 | ✅ T1～T8 完成（244 focused / 495 non-live），规格/质量双审与主代理验收通过（B18） |
| 017 | WeKnora SourceDocument Bridge/Evidence lineage | ⚠️ T1–T8 软件完成并通过双审/全量复验；真实 WeKnora/PostgreSQL live 为 NOT RUN（B19） |
| 018 | SnapshotFact/统一读取/可恢复发布 | ✅ PR #9 已合入（merge `b093a447`），作为事实快照地基；不含 NS-C 的全 manifest 真人批准或 P-1 active alias |
| 019 | Golden 工具/QualityProfile/在线 Gate | ✅ **已完成并合入 main**（PR #8，merge `4d9c84e`，非-live 1142 passed）（B21） |
| 020 | gs-v0.1 与 13 产品 baseline 真实运行 | 🚧 019/021 与 T1 零模型 run-admission 软件均已合入；canonical admission 仍 `BLOCKED`，且 NS-0 未 verified。它属于企业 M2，不阻塞 030 独立 MVP admission；T2～T7/D4b 未运行 |
| 021 | Source lifecycle ordering | ✅ 已随 PR #23 合入；durable SourceHead/Event、generation/processed_at 与 per-source lock/CAS 已落地 |
| 022×2 | 测试组合再平衡 / 复审收口 | ✅ 均已随 PR #5 合入（编号冲突已在 `openspec/changes/README.md` 注册表记案冻结） |
| 023 | 本机 WeKnora live 环境+受信门禁 | ✅ PR #10/#16/#19/#20 已合入 main；受信 app digest、provenance/SBOM、真实 provision/PDF、clean-SHA VLM 与 018 五节点均已验证 |
| 024 | 抽取召回提升（extract_empty+值粒度） | ⚠️ 旧软件已随 PR #13 合入；因依赖 004 当前 production-disabled，真实召回与非退化证据归三门禁后的 020 D4/D4b |

执行类遗留：HANDOFF ⓪-B。当前关键路径是 027→028，并行 029+010 thin、013+032 和 030；只有 `NS-RIGHTS=recorded ∧ NS-0=verified ∧ applicable admission=READY` 才能运行相应真实模型切片。020 canonical 仍保持 BLOCKED，留企业 M2。软件/CI 通过不得表述为真实 baseline 或召回提升完成。

## 2. LLM Wiki 27 项功能引入状态复盘（对照 09 文档）

**已有代码地基**（只按旧 change 范围）：WeKnora 页面/互链/目录/结构 lint/链接图；007 的 Claim/ChangeSet/Review 基础；003 产品别名对齐；Evidence、字段矩阵与业务方 schema baseline。004/006/024 及其 routing/cleaning/局部 fast path 是第一方迁移输入，但在 027/028/030 重构与验证前保持 production-disabled。它们不能被合并表述为 Enterprise LLM Wiki 已完成：生产模型硬门禁、四级模板、完整 Harness receipts/Alert、全制品 release approval、P-1 原子 serving alias、概念/QA/健康/批量闭环仍按 NS-0～NS-F 补齐。

**待引入（缺口，按价值排序）**——这就是"LLM Wiki 还需要引入的事项"：

| # | LLM Wiki 事项 | 为什么重要 | 落点 |
|---|---|---|---|
| G1 | **概念主页 + 义项索引 + wikilink 互链**（#1/#2 的编译侧） | 007 MVP 只编译产品限定页；"在线问诊"式跨产品概念页与义项消歧是业务方点名需求（01 §2#8），也是"一张知识网"的关键 | **009** |
| G2 | **Purpose 注入**（#5） | 领域意图（合规约束、口径原则）作为常驻上下文进每次抽取/编译调用，LLM Wiki 的核心机制之一，目前 prompt 里是零散写死的 | **009**（并入编译层配置） |
| G3 | **语义 lint / 知识健康度**（#12） | 过期（生效期扫描）/长期 pending 冲突/缺口/孤立页的定期巡检——"知识不会烂尾"的机制保障 | **011** |
| G4 | **结构化直入**（对应我们的 P0-2，LLM Wiki 无此项但业务方需求②） | 已有 JSON 产品库/FAQ 跳过文档解析直接成 Claim/QA | **010** |
| G5 | **QA 一等对象**（业务方需求⑤ + master plan P1-2） | 权威QA/派生QA，答案必须由 Claim 支持 | **012** |
| G6 | 知识缺口→回填闭环（#13 后半） | 自增长 | **015 已立项（B17）**：飞轮信号源=Langfuse（2026-07-12 拍板，零上游改造）；Deep Research 自动补源仍 P2 |
| G7 | 图谱洞察（Louvain/桥接/意外关联，#15 领域图谱侧） | 依赖 Claim 规模 | P2（S6），暂不立项 |
| G8 | log.md 式时间线的人类可读变更流（#3 编译侧） | ChangeSet 已有数据，缺人类可读投影 | 并入 008 工作台"变更页" |

**明确不引入**（09 已定）：桌面端/剪藏/Obsidian（#17/27）、自研检索（#24 部分）、自研解析（#25）。

## 3. 下一批 change 规划（009~012，均为"提案即交接物"）

| Change | 一句话范围 | 依赖 | 实现归属 |
|---|---|---|---|
| **009 概念层编译** | 概念抽取（从 Claim 值与术语表）→ 概念主页（聚合+跨产品差异表）→ 义项索引 → 产品页⇄概念页 wikilink；purpose 配置注入编译/抽取 prompt | 007/016/018 + 010 T5～T12 | 其他模型（B11） |
| **010 结构化直入** | JSON/JSONL/CSV/FAQ → 映射器 → Claim/QA 批次（幂等键 external_record_id+source_revision）→ 走 007 合并审核；未知 JSON 生成候选映射待确认；dry-run 预检 | 007/018/021（均已满足） | 其他模型（B12） |
| **011 知识健康度巡检** | 定时任务：过期扫描（生效/失效日期）、长期 pending 冲突、完整度退化、发布页与 Claim 漂移检测；产出健康度报告+整改工单（进 ReviewItem） | 007 | 其他模型（B13） |
| **012 QA 一等对象** | qa_items 表 + FAQ 抽取对齐（答案绑定 Claim id）+ 派生 QA 编译器（事实变更自动重编）+ 产品页聚合展示 | 007/010 | 其他模型（B14） |

L4 企业顺序：**010 T5～T12 → 009 / 012**；当前 MVP 只实施 010 已知 schema thin。004/routing/cleaning 可经 provenance + 028 重构，但任何旧测试产物都不得直接晋级生产。当前关键路径优先 027～030、032 与 030 admission，不因完整 L4 开工而插队。

## 4. 能力审计与决策记录（2026-07-21 北极星校正）

按旧 change 边界，版本、编译、结构化接入均已有可测试地基；按企业级北极星边界，六项能力仍须统一标为 **⚠️ 未完成产品验收**：版本尚缺全制品批准/原子指针不变量，编译尚缺四级模板与完整 Harness receipts，结构化接入尚缺统一可信来源治理，可进化尚缺自动健康闭环，可关联尚缺概念/关系完整编译，缺口识别尚缺面向产品的质量工作台与批量补全闭环。

既有决定继续有效：飞轮信号源走 Langfuse（015，零 WeKnora 改造），保险语义不进入 WeKnora Go/Vue。当前按 Integration-first MVP 先完成 NS-0 与最小 NS-A～NS-D 主链；完整 NS-C/P-1、NS-E/NS-F 和旧 009～012 企业范围后置，不能越过北极星门禁单独宣称产品完成。

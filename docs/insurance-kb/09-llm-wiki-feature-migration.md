# 09 · Enterprise LLM Wiki 功能继承与迁移对照表

> 回答核心问题：**Karpathy/nashsu 的持久知识编译范式与 LLM-wiki-black 的保险能力，如何成为本项目 Enterprise LLM Wiki 的产品核心，而不是散落成 WeKnora 附属功能**。
>
> 三种承接方式：**Compiler 语义所有权 + WeKnora 载体**、**Harness 选择性重构/迁移**、**不迁移**。WeKnora 内置自动 Wiki 生成在保险 KB 中关闭；“WeKnora 已有”只代表可复用通用存储/渲染/API/算法，不代表它拥有保险 Wiki 的语义与生命周期。
> 关联：[06-asset-migration.md](06-asset-migration.md)（数据资产怎么搬）——本文讲"功能"，06 讲"资产"，两文互补。

> [!CAUTION]
> **第一方能力可迁移，但历史完成状态不是生产证明。** 项目权利人已确认 LLM-wiki-black 为第一方完整著作权资产；004/006/024/routing/cleaning 可作为审计输入。每项仍须记录 provenance，按 027/028 新接口重构为 Python Harness 并通过 030 Golden Slice；原 TS 只作为迁移来源，不作为第二套生产 runtime。`nashsu/llm_wiki` 等第三方实现不得因第一方声明而直接复制。

## 1. nashsu/llm_wiki 上游功能

| # | 功能 | 承接方 | 说明 | 排期 |
|---|---|---|---|---|
| 1 | 原子概念页（markdown + frontmatter：type/title/tags/related/sources） | **Compiler + WeKnora 载体** | Compiler 从 snapshot 决定概念/产品页语义和 metadata；WeKnora 复用 WikiPage 存储与渲染 | 009 + 平台复用 |
| 2 | wikilink 互链 + 死链清理 | **Compiler + WeKnora 载体** | Compiler 决定实体关系并生成稳定 wikilink；WeKnora 承载 InLinks/OutLinks、重建与展示 | 009 + 平台复用 |
| 3 | index.md 目录 / log.md 操作日志 | **Compiler + WeKnora 载体** | Compiler 决定 snapshot 目录与语义 change log；WeKnora 提供 index/log API 与页面载体 | 009/版本链 |
| 4 | Schema（页面类型→目录路由）配置 | **Harness 重写** | 升级为版本化 schema 注册表（险种 profile + 字段级定义），远强于原 schema.md | S1（P0-1） |
| 5 | Purpose（领域意图注入每次 LLM 调用） | **Harness 重写** | 成为抽取 prompt 的领域约束段 + WikiConfig.purpose（master plan 已规划） | S1 |
| 6 | Ingest 三阶段：Analysis → Generation → Review | **Harness 重写** | 演进为八步抽取管道（04），分析/生成/审核思想保留但按 Claim 粒度重构 | S1~S2 |
| 7 | 页面合并（数组确定性 union + LLM 合并 body + 长度 sanity check + 回退备份） | **Harness 重写** | 落为 Claim 级增量合并（04 §4）；确定性身份/权威/时间/Evidence 比较优先，弱模型只产建议，无共识阻断并交人工 | S2 |
| 8 | 软去重（同实体不同名识别 + 全库交叉引用重写） | **Harness 重写** | 变为产品别名对齐 + 术语归一（确定性规则优先，LLM 只做候选）；WeKnora 内置 wiki dedup 不用于保险 KB | S1 |
| 9 | 矛盾识别（Analysis 产出 Contradictions，人工裁决） | **Harness 重写** | 升级为 ChangeSet conflict + 六步裁决（产品/版本身份→权威→可靠时间→Evidence 完整性→多弱模型建议→人工）+ 全程留痕（03 §6） | S3（P0-4） |
| 10 | Review Queue（内容稳定 ID、受限动作集、异步不阻塞） | **Harness 独立实现** | 按当前 ReviewItem 合同实现内容派生稳定 ID 与受限动作；第三方项目仅作产品行为参考，UI 在 workbench（03 §2.6） | S3（P0-5） |
| 11 | 结构性 Lint（孤立页/断链/路由不符，图算法零成本） | **Compiler + WeKnora 算法/API** | Compiler 定义实体/路由不变量和发布门禁；复用 WeKnora lint/issue API 做载体检查 | 011 + 平台复用 |
| 12 | 语义 Lint（矛盾/过期/缺口页，LLM 定期审计） | **Harness 重写** | 变为知识健康度检查：过期（生效期）、冲突（ChangeSet）、缺口（字段矩阵）——确定性信号为主，LLM 补充 | S5（P1-1） |
| 13 | 知识缺口双通道（图结构信号 + 语义信号）+ Deep Research 回填 | **Harness 重写** | 缺口主通道改为**字段填充率矩阵**（schema 驱动，比图信号更准）；图谱洞察与受控研究按 master plan P2 后置 | S5/S6 |
| 14 | 源文档溯源 sources[]（多对多、级联删除时共享页降级不删除） | **Harness 重写 + WeKnora 已有** | 升级为 Evidence 对象（chunk 级+页码+权威度）；"删源按引用计数降级 Claim"规则保留（master plan P0-4）；页面级 source_refs 由 WeKnora 承载 | S2~S3 |
| 15 | 知识图谱可视化（链接图、社区发现） | **Compiler 关系语义 + WeKnora 可视化** | 页面关系由 snapshot/Claim 编译；先复用现有链接图，P2 再扩保险本体图谱 | S6（P2-1） |
| 16 | Query（对话式问答） | **同快照 Wiki/MCP + WeKnora Agent** | 已发布 Wiki/MCP 是默认权威；WeKnora Agent 承载交互，RAW RAG 仅缺口兜底且不得覆盖 Wiki | 013 + 平台复用 |
| 17 | 浏览器剪藏 / Obsidian 兼容 / 桌面端体验 | **不迁移** | 企业场景无此需求（master plan §7 已排除） | — |

## 2. LLM-wiki-black 寿险定制功能

| # | 功能 | 承接方 | 说明 | 排期 |
|---|---|---|---|---|
| 18 | 长文档分段、定向路由与缺口补抽能力 | **Harness 选择性迁移/重构** | 可审计并迁移第一方实现中“短任务、证据优先、失败可恢复”的有效能力；任务组、顺序、路由和补漏须映射到当前 schema/027/028 接口，记录 source commit/path，并由独立 Golden Slice 验证（04 §3 Step 2/6，边界见 06） | S1~S2 |
| 19 | 跨险种字段覆盖与越域防护 | **业务 schema + 第一方工程元数据治理** | 07 的 YAML 与 LLM-wiki-black 相关模板分组、路由、白名单均可作为有权输入；进入新系统前须记录 provenance、消除旧 fast-path 耦合，并通过越域污染测试 | NS-A/028 |
| 20 | 占位/资料指针/弱值与不得降级已有事实 | **Harness 选择性迁移/重构** | 可审计迁移第一方规则、映射、prompt 与测试向量；新实现须记录 provenance，适配三态/Claim/Evidence 语义，并用独立业务样本证明不会以弱值降级已有事实 | S1 |
| 21 | 增量合并（非空不覆盖、冲突进 review 保留旧值、增量原文留存） | **Harness Python 迁移/重构** | 第一方行为与测试向量可迁移，升级为 ChangeSet 语义（03），不保留 TS runtime | S2~S3 |
| 22 | 批次 API、进度、并发限流与重试 | **Harness 独立实现** | 按当前产品需求重新定义预检/dry-run、持久任务、失败隔离和幂等合同（master plan P0-2/P0.5），不复刻旧接口/状态机 | S2/S4 |
| 23 | 抽取覆盖率审计 + knowledge_gaps 报告 | **Harness Python 迁移/重构** | 第一方统计口径可经 provenance 迁移，并入完整度矩阵与质量分（P1-1）+ 金标评估（05） | S0/S5 |
| 24 | RAG 保险证据评分、术语变体扩展、CJK 分词 | **部分迁移，平台检索优先** | WeKnora 检索为主；可审计第一方同义词、术语变体和评分经验并记录 provenance，用于定向补漏（04 §3 Step 6）与检索配置；旧自研 RRF/评分仅在对照评估证明收益且不重复平台能力时迁移 | S2、S6 |
| 25 | 解析质量检测与分层升级需求 | **不迁移实现** | WeKnora docreader 已覆盖基础解析；当前项目按 08/11 从独立语料重新设计质量门禁与对照解析器 | — |
| 26 | DomainSkill 插件架构（TS） | **迁移契约思想，不迁移 TS runtime** | “领域逻辑插件化”落实为 Python `StagePlugin/TemplatePackage`；不得部署 Node/TS DomainSkill 服务或建立 Python↔TS 调用链 | 028 |
| 27 | Tauri 桌面 / React UI / Rust axum 后端 | **不迁移** | 平台形态不同；review UI 交互思路可参考（06 §5.2） | — |

## 3. 核心结论

- **WeKnora 提供载体，不拥有保险 Wiki 语义**：页面存储/渲染、链接 API、目录、结构检查、图展示和 Agent 外壳可直接复用；页面内容、关系、目录语义、change log 和消费快照由 Enterprise LLM Wiki Compiler 决定；
- **Harness 重写的是完整知识生命周期**：`来源 → 模板/多弱模型 Agent → Claim/Evidence → 校验 → 合并/冲突 → 人工门禁 → Snapshot → 页面/关系/MCP → 反馈再编译`，不是只做一条抽取 pipeline；
- **模板效果不佳必须显式降级和告警**：重定位、定向补抽、多弱模型共识、通用 agentic 路径仍失败后停止发布并交给人，绝不静默生成空 Wiki；
- **明确不做**的：桌面端、剪藏、Obsidian、自研检索与解析（#17、#25~#27）。

# 09 · LLM Wiki 功能迁移对照表

> 回答一个此前不够明确的问题：**LLM Wiki（nashsu 上游 + LLM-wiki-black 寿险定制）到底有哪些功能，每个功能在新平台由谁承接、迁不迁、怎么迁**。
>
> 三种承接方式：**WeKnora 已有**（直接用，不开发）；**Harness 重写**（借鉴思想在 Python 重新实现，不复制 GPL 代码）；**不迁移**（明确放弃并给原因）。
> 关联：[06-asset-migration.md](06-asset-migration.md)（数据资产怎么搬）——本文讲"功能"，06 讲"资产"，两文互补。

## 1. nashsu/llm_wiki 上游功能

| # | 功能 | 承接方 | 说明 | 排期 |
|---|---|---|---|---|
| 1 | 原子概念页（markdown + frontmatter：type/title/tags/related/sources） | **WeKnora 已有** | WikiPage 模型（slug/aliases/page_type/page_metadata/source_refs）能力超集 | 无需开发 |
| 2 | wikilink 互链 + 死链清理 | **WeKnora 已有** | InLinks/OutLinks + linkify/cleanDeadLinks + rebuild-links API | 无需开发 |
| 3 | index.md 目录 / log.md 操作日志 | **WeKnora 已有** | `GET /wiki/index`、`GET /wiki/log` | 无需开发 |
| 4 | Schema（页面类型→目录路由）配置 | **Harness 重写** | 升级为版本化 schema 注册表（险种 profile + 字段级定义），远强于原 schema.md | S1（P0-1） |
| 5 | Purpose（领域意图注入每次 LLM 调用） | **Harness 重写** | 成为抽取 prompt 的领域约束段 + WikiConfig.purpose（master plan 已规划） | S1 |
| 6 | Ingest 三阶段：Analysis → Generation → Review | **Harness 重写** | 演进为八步抽取管道（04），分析/生成/审核思想保留但按 Claim 粒度重构 | S1~S2 |
| 7 | 页面合并（数组确定性 union + LLM 合并 body + 长度 sanity check + 回退备份） | **Harness 重写** | 落为 Claim 级增量合并（04 §7）；"确定性优先、LLM 兜底、失败回退"原则全保留 | S2 |
| 8 | 软去重（同实体不同名识别 + 全库交叉引用重写） | **Harness 重写** | 变为产品别名对齐 + 术语归一（确定性规则优先，LLM 只做候选）；WeKnora 内置 wiki dedup 不用于保险 KB | S1 |
| 9 | 矛盾识别（Analysis 产出 Contradictions，人工裁决） | **Harness 重写** | 升级为 ChangeSet conflict + 六级权威序五步裁决 + 全程留痕（03 §5），比原设计强 | S3（P0-4） |
| 10 | Review Queue（内容稳定 ID、受限动作集、异步不阻塞） | **Harness 重写** | ReviewItem 沿用内容派生稳定 ID 与受限动作两个关键设计（03 §1）；UI 在 workbench | S3（P0-5） |
| 11 | 结构性 Lint（孤立页/断链/路由不符，图算法零成本） | **WeKnora 已有** | wiki lint + auto-fix + issues API | 无需开发 |
| 12 | 语义 Lint（矛盾/过期/缺口页，LLM 定期审计） | **Harness 重写** | 变为知识健康度检查：过期（生效期）、冲突（ChangeSet）、缺口（字段矩阵）——确定性信号为主，LLM 补充 | S5（P1-1） |
| 13 | 知识缺口双通道（图结构信号 + 语义信号）+ Deep Research 回填 | **Harness 重写** | 缺口主通道改为**字段填充率矩阵**（schema 驱动，比图信号更准）；图谱洞察与受控研究按 master plan P2 后置 | S5/S6 |
| 14 | 源文档溯源 sources[]（多对多、级联删除时共享页降级不删除） | **Harness 重写 + WeKnora 已有** | 升级为 Evidence 对象（chunk 级+页码+权威度）；"删源按引用计数降级 Claim"规则保留（master plan P0-4）；页面级 source_refs 由 WeKnora 承载 | S2~S3 |
| 15 | 知识图谱可视化（链接图、社区发现） | **WeKnora 已有**（页面链接图）；领域图谱 **Harness** | P2 再做保险本体图谱，先复用现有图 | S6（P2-1） |
| 16 | Query（对话式问答） | **WeKnora 已有** | RAG/Agent/wiki-qa 预设 | 无需开发 |
| 17 | 浏览器剪藏 / Obsidian 兼容 / 桌面端体验 | **不迁移** | 企业场景无此需求（master plan §7 已排除） | — |

## 2. LLM-wiki-black 寿险定制功能

| # | 功能 | 承接方 | 说明 | 排期 |
|---|---|---|---|---|
| 18 | 产品目录抽取器（Section-Scan：预处理→7 组分轮抽取→桥接→二次精炼） | **Harness 重写** | 八步管道的直接前身；GROUP_KEYWORDS 路由、分轮策略、二次精炼全部继承（04 §2/§6，资产见 06） | S1~S2 |
| 19 | 6 险种字段字典 + 模块体系 + 险种白名单 | **已完成迁移** | 并入 schema 基线 v1/v1.1（07，schema-baseline/） | ✅ |
| 20 | 占位值清洗（30+ 正则）/ 弱值过滤 / 智能值替换 | **Harness 重写** | 04 §4 校验清洗层；正则数据直接翻译（06） | S1 |
| 21 | 增量合并（非空不覆盖、冲突进 review 保留旧值、增量原文留存） | **Harness 重写** | 升级为 ChangeSet 语义（03），行为原则保留 | S2~S3 |
| 22 | 服务端批量导入（批次 API、SSE 进度、并发限流、重试） | **Harness 重写** | 批次/预检/dry-run 语义继承（master plan P0-2/P0.5）；实现按 08 选型（FastAPI+队列） | S2/S4 |
| 23 | 抽取覆盖率审计 + knowledge_gaps 报告 | **Harness 重写** | 并入完整度矩阵与质量分（P1-1）+ 金标评估（05） | S0/S5 |
| 24 | RAG 保险证据评分、术语变体扩展、CJK 分词 | **部分迁移** | WeKnora 检索为主；保险术语同义词库迁给定向补漏（04 §6）与检索调优配置；自研 RRF/评分不迁 | S2、S6 |
| 25 | 4 级 PDF OCR fallback + 乱码检测 | **不迁移（思想留存）** | WeKnora docreader 已覆盖；解析质量抽检不达标时按 08 启用 MinerU 对照 | — |
| 26 | DomainSkill 插件架构（TS） | **不迁移（思想已吸收）** | "领域逻辑插件化"思想即 ADR-001 本身 | — |
| 27 | Tauri 桌面 / React UI / Rust axum 后端 | **不迁移** | 平台形态不同；review UI 交互思路可参考（06 §5.2） | — |

## 3. 一句话总结

- **不需要开发**的：原子页存储、互链、目录/日志、结构性 lint、图可视化、问答——WeKnora 全有（这正是选它做底座的原因）；
- **Harness 要重写**的核心只有一条主线：**"文档 → Claim/Evidence → 合并/冲突 → 审核 → 发布"的编译与治理链**（上表 #4~#10、#12~#14、#18~#23），其设计已全部落在 03/04/05；
- **明确不做**的：桌面端、剪藏、Obsidian、自研检索与解析（#17、#25~#27）。

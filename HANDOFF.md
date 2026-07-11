# HANDOFF — 交接文档

> 写给完全没有上下文的新会话/新成员。任何变更请持续更新本文。
> 最后更新：2026-07-11（架构讨论定稿 + 首批设计文档产出）

## 一、我们在做什么

为大型寿险企业建设企业级知识平台：以 **WeKnora（本仓库，官方 v0.6.3 零分岔 fork）为平台底座**，以**插件式 Python Harness** 承载全部寿险知识能力（抽取、校验、合并、冲突裁决、版本、审核、金标评估），把文档编译成原子化、有版本、可溯源的知识，供 Agent 与人共用。这是一个**示范性项目**（企业级 harness agent 标杆），文档与代码质量要求高于交付速度。

5 分钟了解项目：读 `docs/insurance-kb/00-project-overview.md`。

## 二、已完成

1. **三仓库深度调研**（2026-07-11）：
   - 本仓库 = 官方 WeKnora 0.6.3 原样 + 迭代规划文档，保险代码为零；Wiki 能力是官方自带（数据模型/管线/API 细节见调研结论，已固化进 02/03 文档）；
   - 确认三个平台缺口：Wiki REST 写入无乐观锁（last-write-wins）、无解析完成 webhook、`WikiEnabled=false` 时 REST 写 wiki 也 400；
   - LLM-wiki-black（旧寿险定制项目）资产盘点：可迁移的字段字典、抽取路由、清洗正则、Q001-Q027 踩坑档案 → 全部落入 `docs/insurance-kb/06-asset-migration.md`；
   - 上游 nashsu/llm_wiki（GPL-3.0）设计思想提炼 10 条，只借鉴不抄码。
2. **架构定稿（ADR-001，业务方确认）**：插件式路线 B。WeKnora 不动（补丁≤3 且提 PR 回上游），保险能力全在 `harness/`（尚未创建），自有 PostgreSQL。详见 `docs/insurance-kb/02-architecture.md`。
3. **设计文档集**：`docs/insurance-kb/` 00~10 全部完成（见该目录 README）：需求/架构/知识模型/抽取管道/金标评估/资产移植/schema 基线，外加 **08 技术选型**（逐组件开源框架与许可证核对）、**09 LLM Wiki 功能迁移对照表**（27 项功能的承接方与排期）、**10 开发规范**（SDD/TDD/边界纪律）。master plan 顶部已加架构修订说明。
4. **Schema 基线接入**：业务方 Excel（2026-07-10）已转成 `docs/insurance-kb/schema-baseline/` 13 个 YAML；我方扩展字段提案在 07 §3，**待业务方逐条确认**。
5. **样本材料**：13 产品（说明书+条款+费率表+meta）已解压到仓库外 `../samples/`（**不入 git**，公司资料）。

## 三、已拍板决策（2026-07-11 业务方确认）与剩余卡点

已拍板：
1. **范围 = 全险种覆盖，不做单险种试点**。按样本到位程度分波：第一波用现有 13 产品（终身寿/年金/两全/医疗/意外/失能），第二波（重疾/护理/补充养老/意外医疗）待样本到位并入（07 §4）。
2. **18 条扩展字段提案全部接受**，已并入 schema v1.1（`docs/insurance-kb/schema-baseline/extensions-v1.1.yaml`）。
3. **金标模型 = Claude（Fable/Opus 级）**，S0 金标注 Agent 按此接入。

剩余卡点（不阻塞开工）：
- **待业务方补样本**：重疾/护理/补充养老产品各 2~3 个、多产品混合文档 3~5 份、扫描件 1~2 份、FAQ/结构化 JSON 一份。

## 四、下一步计划（按序）

1. ✅ change 001 **开发完成并验收**（2026-07-11）：`harness/` src 布局脚手架 + WeKnora REST 适配层（httpx 客户端、错误分型、slug 串行化锁、指数退避重试、Langfuse no-op 降级）+ 23 个契约/单元测试 + harness CI。验证：ruff/mypy(strict)/pytest 全绿（21 passed，2 live 跳过）。**注意 git 提交均留在本地分支 `feature/insurance-kb-foundation`：GitHub 账号 `yiyinianhua` 对本仓库暂无写权限（push 403），业务方决定权限到位后统一推送**；
1a. ✅ change 002（金标 S0）提案已获业务方确认（2026-07-11），开发中；
2. **S0：金标与评估子系统**（change 002，`harness/goldenset`，设计见 05）——用 `dataset/shouxian_product/` 13 产品跑出金标 v0.1；注意每个产品的 `product_meta.json` 含 planCode/versionNo/备案文号/销售状态/生效日期，是产品主数据与 B-1/B-2 字段的 ground truth；
3. S1（master plan P0-1）：产品主数据/别名 + 文档分类与产品路由（change 003）；
4. 向腾讯上游开 3 个 Issue/PR（02 §5 补丁清单）。

样本语料：业务方 2026-07-11 提供 `shouxian_product`（13 产品，39 PDF + 12 meta json）并确认拷入仓库 → `dataset/shouxian_product/`，作为测试验证集原料。仓库外 `../samples/` 的早期解压副本作废，以 dataset 内为准。

## 五、踩过的坑（绝对不要再踩）

1. **不要把保险逻辑写进 Go/Vue**——02 §3 三条硬边界是 code review 检查项；违反 = 每次跟版人肉解冲突。
2. **`WikiEnabled=false` 会连 REST 写 wiki 一起封掉**（`validateWikiKB`）；"关自动生成、留 API 写入"必须等 P-3 补丁；过渡方案：Wiki KB 不上传任何原始文档。
3. **Wiki REST 是 last-write-wins**，`version` 字段不做并发校验；P-1 合入前 Harness 必须自行对 slug 串行化写入。
4. **旧项目（LLM-wiki-black）的教训**：抽取无重试机制导致 section 失败即丢数据（新管道必须指数退避+死信）；向量维度硬编码 384 vs 实际 1152 曾丢 768 维语义（凡模型返回维度一律运行时探测）；`product_meta.json` 不算有效源资料（Q020）。
5. **"未抽取到"绝不能写成"不存在"**——三态字段是硬约束（03），豁免类字段尤其如此。
6. **GPL 边界**：nashsu/llm_wiki 及 LLM-wiki-black 代码不得复制进本仓库；字段字典等自研数据可迁移（06 §合规），最终需法务确认一次。
7. **本仓库 git 历史是压平的单提交**；`upstream` remote 指官方 Tencent/WeKnora，跟版走版本列车（02 §8），不要直接跟 main。
8. 样本语料经业务方确认已入库（`dataset/shouxian_product/`）；但金标产物含模型输出，release 前检查敏感信息。
9. **本机 shell 有 SOCKS 代理环境变量（ALL_PROXY 等），曾导致 httpx 全部请求挂掉**——适配层已用 `trust_env=False` 修复；新写任何 HTTP 客户端都要注意这一点。GitHub 访问也受此影响（SSL 间歇性失败，重试即可）。

## 六、工作方式约定（业务方明确要求）

- 动手前先讨论；文档驱动：先设计文档 → OpenSpec（`openspec/changes/`）→ 开发；SDD/TDD。
- Python 优先；能用成熟开源不自研。
- 金标 = 最强模型标注（本阶段无人工），金标子系统必须独立可持续维护。
- 每次重大变更更新本文。

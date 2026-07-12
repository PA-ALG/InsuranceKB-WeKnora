# HANDOFF — 交接文档

> 写给完全没有上下文的新会话/新成员。任何变更请持续更新本文。
> 最后更新：2026-07-12（006 模板 fast path 完成；005 评测尺子升级与召回归因完成；金标标注 11/13 后因 token 限额搁置，现场已固化）

## ⓪ 当前最优先事项（接手先看这里）

1. **T8 金标标注剩 2 个产品未标**（因会话 token 限额搁置，业务方决定换模型接手）：完整交接文档在 `openspec/changes/002-goldenset-s0/T8-HANDOVER.md`，按步骤执行即可；已完成的 11 份在 `dataset/goldenset/wip-gs-v0.1/`（dry-run 验证 disputed 率 3~5%，达标）。
2. ✅ **change 003 已完成并验收**（2026-07-12）：产品主数据/别名/版本/文档登记（幂等）+ 文档分类器 + 章节级产品路由 + unassigned 池 + CLI。验收：39 PDF 分类 100%、exact 路由 100%、零 LLM 调用（validation-report.md）；门禁 89 passed 全绿。别名剥后缀的歧义教训见 003/tasks.md 裁决记录。
3. ✅ **change 004（抽取管道 MVP）完成并验收**（2026-07-12）：compiler/ 全链路（切分→7组路由→分批抽取→回验→清洗→补漏→投票→置信分级），langgraph 可恢复编排+死信；门禁 135 tests 全绿。**首个真实弱模型基线**（deepseek-v4-flash vs gs-v0.1，3 代表产品，含 Claude 裁决回写）：micro F1 0.184 / 幻觉率 8.2% / **evidence 准确率 100%** / high 桶三态正确率 92%——反幻觉链已验证有效，失分主因是长文本字段的"值粒度/表述差异"被 eval 逐字等价误判 + present→unknown 漏抽 25 条（validation-report.md 有全量明细）。
3a. ✅ **change 007（Claim 落库/增量合并/审核门禁/WeKnora 发布，S2→S3 主链）完成**（2026-07-12）：
   `harness/src/insurance_harness/knowledge/` 新包 + Alembic 0002（claims/claim_evidence/claim_revisions/
   change_sets/change_items/conflicts/review_items/release_snapshots/snapshot_claims/current_release）。
   pred JSONL 导入器（记录级+批级幂等）、五种 ChangeItem 合并引擎（裁决序严格 03 §6.2，④=claude-session
   judge-queue 占位零模型调用）、ReviewItem 稳定 ID + approve/reject/defer、页面编译（分组渲染+证据角标）、
   发布器（03 §7 契约，respx 全 mock）+ 快照回滚。端到端两批材料故事（说明书→条款）验收通过；
   门禁 192 passed 全绿。live 发布契约用例（-m live）待测试实例。文档 03 已同步修订
   （pending_judge/schema_version 串/source_kind/rendered_pages 物化/④队列化）。
3b. ✅ **change 005（评测尺子升级与召回归因）完成**（2026-07-12，零真实模型调用）：
   ① eval v2 "关键要点匹配"（`--metric v1|v2` 可切换；金标旁挂 keypoints.jsonl，3 基线产品 59 条
   rule-split 小样已入库，全量强模型要点列 B6）——3 产品离线重评 micro F1 **0.184(v1) → 0.216(v2)**，
   long 字段逐字等价误判被修正、真实缺口（值粒度 54 条）凸显；② 报告五类错误归因
   （值粒度/漏抽/幻觉/三态混淆/证据错位）+ 工单化明细；③ eval-judge-queue 落盘（默认关，格式对齐
   compiler JudgeRequest/Judgement）；④ 漏抽归因工具 `compiler/recall_attribution.py`（纯确定性）：
   26 条漏抽 = routing_miss 3 / extract_empty 23 / cleaning_kill 0；⑤ 零成本路由修复
   `GROUP_KEYWORD_SUPPLEMENTS_005`（趸交/费率表→basic_info；入出院记录/出院小结/结算清单→claim_service），
   routing_miss 3→1、13 条款压缩比仍 ≤0.40；清洗白名单经证据判定不需要改（cleaning_kill=0）。
   报告：`openspec/changes/005-eval-refinement-recall/validation-report.md`（004 报告已附"尺子修正后"章节）。
3c. ✅ **change 006（模板抽取 fast path 与表格结构识别）完成并验收**（2026-07-12，零真实模型调用）：
   `harness/compiler/templates/` 新包——模板 schema（YAML 数据，注册表机制对齐 schemas，发布目录
   `dataset/templates/`）+ **确定性模板归纳器**（族内 ≥2 产品金标挖锚点：表格列名/引文上下文正则，
   全产品回放验证 hit_rate=1.0 才发布；LLM 润色留 claude-session 队列 stub）+ 运行时 fast path
   （族命中 → 锚点直取 → 既有校验链，未命中降级通用管道；命中字段退出通用抽取/补漏/投票）+
   `TableStructureProvider` Protocol（pdfplumber 首实现，费率表数字走列定位直取 12 #1；
   PP-StructureV3 留接口+配置位 `HARNESS_TABLE_PROVIDER`）+ 可喂性评分（12 #4，manifest 记录+
   隔离区目录，CLI 默认 dry-run）+ pred 增加 `data_quality`（12 #2，007 Claim 端衔接）。
   **修复 004 族指纹疑点**：无标题文档（说明书/费率表）曾全部退化为空串指纹 fam-e3b0c44298fc，
   现走 fallback（文档类型+页数桶+表头 token），有标题文档指纹零漂移。**留出验证**（盛世金越族，
   两分红产品归纳 → 尊享26终身寿留出）：fast path 命中字段正确率 1.00 vs 通用管道 0.00
   （交费期限 unknown→列直取全对），预估节省 1 次调用/产品（锚定字段尚少；随模板铺开增长）；
   发现分红说明书两版式不同构（归纳报告与 validation-report.md 有全量明细）。门禁 239 passed 全绿。
4. **下一步**：抽取召回主战场是 extract_empty 24 条（prompt 变体/补漏增强，见 005 归因清单）；模型配置：harness/.env（不入库）——弱模型 deepseek-v4-flash、裁决 claude-session 模式（judge-queue → apply-judgements CLI，本轮已实跑 3 条闭环）、兜底 deepseek-v4-pro。
5. **分工定位（2026-07-12 业务方定）**：本会话（Claude）负责**整体架构、代码设计、功能规划、技术方案**（产出设计文档与 OpenSpec change 提案）；**大批量 token 消耗的执行任务一律进下方遗留清单，交由其他模型/会话推进**。

## ⓪-B 遗留执行任务清单（交由其他模型推进，按优先级）

| # | 任务 | 怎么做 | 预估成本 |
|---|---|---|---|
| B1 | 金标 T8 收尾：剩 2 产品标注 + gs-v0.1 打包 | `openspec/changes/002-goldenset-s0/T8-HANDOVER.md` 四步走 | ~2×10万 token（标注模型） |
| B2 | 全量 13 产品弱模型基线 | `cd harness && uv run python scripts/baseline_004.py run --products <逗号分隔剩余10个> --resume`，跑完 `report`；进程要 nohup 脱离会话（坑清单 #9 网络注意） | 网关 ~6-12万 token/产品 |
| B3 | B2 产生的 judge-queue 批处理 | 各 run 目录 judge-queue.jsonl → 强模型逐条裁决出 judgements.jsonl（格式见 compiler/models.py Judgement，evidence 页码需从原 PDF 定位保证回验）→ `python -m insurance_harness.compiler.cli apply-judgements <run_dir> <judgements.jsonl>` → 重出 report | 视队列量，单条很小 |
| B4 | 死信复跑 | e生保尊享 coverage 组 s016+s017 截断死信：调大 max_tokens 或分段后 `--resume` | 极小 |
| B5 | 向腾讯上游提 3 个 Issue | 文案已备好：`deploy/patches/upstream-issues.md`，提交后回填链接 | 人工 |
| B6 | gs-v0.1 全量 11 产品 long 字段要点清单（强模型一次性产出，替换 005 的 rule-split 小样） | 逐产品读 `dataset/goldenset/wip-gs-v0.1/<产品>/golden.jsonl`，对 present 且归一化 ≥30 字的字段产出要点清单，写同目录 `keypoints.jsonl`（行格式 `goldenset/keypoints.py KeypointEntry`，`golden_value_sha` 用 `value_sha(金标值)`；可从 `harness/scripts/eval_005.py gen-keypoints` 的规则版起步做人工/强模型精修） | ~1×10万 token（强模型） |
| B7 | 005 路由修复后的真实弱模型对比出分（before/after 基线回归） | `cd harness && uv run python scripts/baseline_004.py run --products 平安盛世金越（尊享版26）终身寿险,平安e生保（尊享版）医疗保险,平安守护百分百（2026）两全保险`（新 run 目录或备份旧 runs/ 后跑），完成后 `uv run python scripts/baseline_004.py report` + `uv run python scripts/eval_005.py report` 对比；重跑盛世金越时可加 `--templates-dir dataset/templates` 验证 fast path 实跑效果（006） | 网关 ~6-12万 token/产品 ×3 |
| B8 | PP-StructureV3 表格结构识别部署（006 遗留） | 重依赖（paddlepaddle/paddleocr）按 08 选型进程隔离部署；实现 `compiler/templates/tables.py` `PPStructureV3Provider.extract_tables`（协议 F5.1），配置 `HARNESS_TABLE_PROVIDER=pp-structure-v3`，用金标回归 A/B 验证（11 §2）后替换默认 | 部署人工 + 金标回归 |
| B8 | **008 审核工作台实现** | 提案即交接物：`openspec/changes/008-review-workbench/proposal.md`（四页面+四动作，FastAPI+Jinja2+HTMX，复用 007 服务层与夹具；先补 specs/tasks 再 TDD） | 开发型任务，中等 |
| B9 | PP-StructureV3 表格结构识别服务部署接入 | 006 已留 TableStructureProvider 接口与配置位；部署独立服务进程（AGPL 隔离，08 §2）后接入并跑费率表对比 | 部署+联调 |
| B10 | WeKnora 测试实例搭建 + live 契约测试 | **完整 Runbook 已备好：`docs/insurance-kb/14-deployment-runbook.md`**（双库初始化/L1~L6 验收路径/完成定义清单） | 部署+联调 |
| B11 | 009 概念层编译实现（概念主页/义项/wikilink/purpose） | `openspec/changes/009-concept-layer/proposal.md`，先补 specs/tasks 再 TDD | 开发型，中等 |
| B12 | 010 结构化直入通道实现（JSON/FAQ→Claim/QA，幂等+dry-run） | `openspec/changes/010-structured-import/proposal.md`；建议最先做（见效最快） | 开发型，中等 |
| B13 | 011 知识健康度巡检实现（过期/积压/漂移/退化/孤立） | `openspec/changes/011-knowledge-health/proposal.md` | 开发型，中小 |
| B14 | 012 QA 一等对象实现（权威/派生QA，Claim绑定硬门禁） | `openspec/changes/012-qa-objects/proposal.md`，依赖 B12 | 开发型，中等 |
| B15 | 013 insurance MCP server 实现（4 个只读工具：产品对齐/按日期取事实/证据链/跨产品对照） | `openspec/changes/013-insurance-mcp/proposal.md` | 开发型，中小 |
| B16 | 014 批量并发调度实现（三级任务模型/分片advisory lock/五级限流/批次控制台API） | `openspec/changes/014-batch-orchestration/proposal.md`；同分片锁顺带解决 007 多实例发布竞争 | 开发型，中等 |
| B17 | 015 数据飞轮实现（Langfuse 信号→缺口工单→回流报表） | `openspec/changes/015-feedback-flywheel/proposal.md`；依赖 007，008 展示 | 开发型，中小 |

> 以上任务的验收都以既有门禁与 report 为准，不需要新设计。设计类工作（005+ change 提案、架构文档）由架构会话产出。

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
9. **本机 shell 有 SOCKS 代理环境变量（ALL_PROXY 等），曾导致 httpx 全部请求挂掉**——适配层已用 `trust_env=False` 修复；新写任何 HTTP 客户端都要注意这一点。**git push 大提交会在 sideband 中途断连**——解法（已配置进本仓库）：`git config http.postBuffer 524288000` + `http.version HTTP/1.1`，并用 `env -u ALL_PROXY -u HTTPS_PROXY …` 绕开代理变量执行 push。

## 六、工作方式约定（业务方明确要求）

- 动手前先讨论；文档驱动：先设计文档 → OpenSpec（`openspec/changes/`）→ 开发；SDD/TDD。
- Python 优先；能用成熟开源不自研。
- 金标 = 最强模型标注（本阶段无人工），金标子系统必须独立可持续维护。
- 每次重大变更更新本文。

# Enterprise LLM Wiki 技术蓝图 1001 · 架构重置版

> 修订日期：2026-10-01 ｜ 设计：Claude Code ｜ 决策：用户
> 状态：**当前唯一技术蓝图**。取代 830 蓝图、`docs/insurance-kb/28-*` 执行章程、`29-*` Goal Cards
> 与 `docs/design/00-架构总览.md`。
> 后续开发只需读：本文 + [`AGENTS.md`](AGENTS.md)（协作约束）+ [`docs/design/slices/`](docs/design/slices/)
> （切片 Spec）。事实依据见 [`docs/design/01-调研结论.md`](docs/design/01-调研结论.md)。

## 0. 本文怎么用

- **权威顺序**：本文 → 切片 Spec（只细化本文，冲突即停下回到本文）→ `AGENTS.md`（协作与工程约束）。
  `01-调研结论` 只记录事实与证据，不决定方案。
- **历史文档**：728 v3 只有 §2–§4（业务背景、问题与目标）仍有效；830 蓝图、28/29 号文档、`HANDOFF.md`、
  `openspec/`、`docs/insurance-kb/`、`docs/superpowers/` 都是历史背景，不作为实现依据。
- **修改本文**：Claude 提 PR，用户合并；每项决定写入 §14 决策记录。
- **进度**：只看 GitHub Issue 与 PR。本文不写运行状态，避免再出现"文档状态落后于实际"。

## 1. 为什么重置

815 证明了主链在物理上可行：WeKnora 解析 → Harness 编译 → Candidate → 审核 → 唯一 Active → 来源点击。
830 在此基础上用 29 天完成了 12 张卡中的 4 张（B0、G1、G2、G3），另在队列外插入了 G3.5 与 WeKnora 0.8.2
升级。复盘发现的问题集中在以下几点（详见 01 调研结论）：

1. **核心价值没有被验证。** 准确率是项目价值的关键，但至今没有 Golden，也没有逐字段质量指标。字段覆盖率在
   35%–43%，质量门 Q0 排在 12 张卡的第 11 位。
2. **可替换编译协议只存在于测试中。** 生产路径硬连 G3 执行器，"先做平台、以后换实现"在代码上不成立。
3. **代码按 Goal 堆叠。** Harness 17.1 万行，约四成从生产入口不可达，15 个合同族多版本并存，生产代码中
   写死了本机路径与特定 release ID。
4. **领域逻辑进入了 Go。** 约 3.2 万行项目自有 Go 代码，其中有一份在 Go 里重放的 Python 批量编译与实体消歧。
5. **读写一致性有缺口。** MCP、KnowledgeQA、原生 wiki 读取未绑定 Release；受管 KB 的部分写路由未加守卫。
6. **治理成本高于产出。** 文档与证据是生产代码的 2.3 倍；权威文档 23 天未同步；本机构建多次因环境失败。

同期出现三项新输入：同事与业务专家做的 **V5 抽取线**（专家反馈驱动，质量明显更好）；生产模型确定为
**DeepSeek v4 flash**；WeKnora 原生 **discover/cite** 被确定为开放知识主路径。

**重置原则**：目标不变（728 §2–§4 与 830 产品要求），技术方案从目标重新推导；能复用的复用，被替代的删除。

## 2. 目标（已确认）

### 2.1 定位

建设大型寿险公司的**企业知识底层服务**。输入覆盖产品条款/说明书/宣传材料，核保、理赔、保全规则，权益与产品
服务，医学术语、疾病定义与核保结论，销售与客户经营经验，FAQ，历史知识库的文档片段与 chunk，以及各系统维护
的零散文本；格式含 PDF、扫描件、图片、Word、PPT、Excel 与结构化数据；规模目标为几十万份文档或片段。

输出是持续演进的知识：有明确实体、有适用产品与产品版本、有业务时间、有来源证据、有冲突与缺口治理、有机器审核
与人工抽检、有不可变版本、可整版发布与回滚。它通过统一的**知识服务接口**同时服务人（Wiki 浏览、抽检、专家修订）
与 Agent/应用（快答、产品比较、规则查询、关系推理、反馈与缺口上报），双方读取同一个 Release。新材料、专家修订
与使用反馈驱动下一版。

不是：普通文档库；只做向量检索的 RAG；让模型把文档直接改写成 Markdown；在两个系统里各维护一套线上知识；用强
模型在线兜底。

### 2.2 业务问题 → 架构能力

| 业务问题 | 架构能力 | 位置 |
|---|---|---|
| 知识入库后静态，新材料不补旧知识 | 增量编译；GapTask 定向反查补抽 | §6.5、§6.6 |
| 答错不回流，更新滞后 | 反馈飞轮：回答日志、纠错、证据不足 → ReviewItem/GapTask → 新 Candidate | §6.6 |
| 停留在文档/片段层，概念散落 | 实体 + Claim/Relation 统一知识模型；概念与分产品义项 | §5、§7.2 |
| 多份材料口径不一致 | TrustPolicy 按字段 × 材料角色裁决；不能裁决即冲突 | §7.3 |
| 专家看不到全貌 | 覆盖、缺口、冲突、重复工作台 | §6.6 |
| 准确率低且不可证明 | 原文优先编译、Evidence 回验、独立审核、Golden + Evaluator | §7.1、§7.7 |
| 人和 Agent 读到不同版本、混版 | 唯一 Head；所有读入口按 Release 读取；原子激活 | §7.5 |
| 权限变化后知识继续暴露 | 访问范围随 Evidence 传播，读时校验，收缩即不可见 | §7.5 |
| 逐页审核无法运营 | 先发布后抽检：确定性检查 + 独立审核打分，高分上线，低分进人工，上线后抽检校准 | §6.3 |
| 错误更新无法回退 | 不可变 Release；整版与实体级回退都生成新 Release | §6.2、§6.5 |

### 2.3 830 产品要求（全部保留为目标）

- 一个统一知识库；产品、权益、服务是分类视图，不是独立库；实体 ID 稳定，重新分类不改变 ID、Evidence 与历史。
- 11 类险种 Schema 从工作簿（v5，SHA `8feb33a1…`）数据化导入为版本化 SchemaPack；各 pack 有自己的展示分组，
  共用一个渲染器，不写死节点数。
- 每个 Schema 字段有独立页面与稳定 URL，unknown 也有页面并说明原因；字段先进本产品的页，再链接共享概念。
- Schema 是下限不是上限：有 Evidence、有稳定身份、有价值的 Schema 外知识可以进入；噪声、重复、无依据内容不进入。
- 原文优先、保义压缩；数字、否定、条件、例外、主体、版本、时间不丢；重编回读原材料，不反复压缩上一版摘要。
- 专家修订自动成为来源，优先于模型；模型只能带新证据发起冲突，不能覆盖。
- PDF、扫描件、图片、Word、PPT、Excel 精确回跳原文；失败返回明确错误，不打开当前版本、不猜相似文本、不跳第 1 页。
- 增量更新、专家编辑、来源撤回都形成新 Release；新 Release 激活前旧版完整服务。
- 批量新实体：身份明确的自动建候选，歧义进人工；某实体的错误不阻塞其他实体，发布与回退以实体为单位。
- Wiki、搜索、Agent 读取同一 Release；检索覆盖字段值、条件与开放知识正文，不只标题。
- 编译器可替换，替换不改平台；质量按险种 pack 逐包准入。

### 2.4 首期范围（2026-10-01 确认）

- 只做**产品知识域**，作为一个统一体系；含权益服务、共享概念、权威 FAQ。
- **11 类险种每类至少一款产品**，合计几十款。
- 消费方：业务人员（Wiki 浏览与抽检）、问答 Agent（经通用知识服务接口）。
- 一个企业 Space，按业务属主分模块管理，知识不割裂。
- 后续：第二期核保、理赔、保全与医学术语；第三期销售经验、培训材料、历史 chunk 与外部系统数据。

### 2.5 上线判断标准

每项独立判断，不互相推导：

| 维度 | 标准 |
|---|---|
| 质量 | 每个 pack 在 Golden 上：有材料字段 recall ≥ 90%、present precision ≥ 95%；幻觉事实 = 0；已发布事实来源回跳 = 100%。用生产目标模型测得 |
| 流程 | 上传/导入→解析→编译→发布→Wiki、知识服务接口、搜索、Agent、MCP 同版读取→回跳原文，覆盖六类格式；增量、专家编辑、反馈补编都形成新 Release |
| 服务 | 接口返回结构化 Claim/Relation、typed value、适用范围、有效期、Evidence、release_id、稳定标识与维护记录，并明确表达 unknown/不足 |
| 安全 | 一个 Space 一个 Head；所有读入口只读 Active 或指定 Release；受管 KB 写入口拒绝旁路；访问范围不经知识放大；私有化时材料不出内网 |
| 成本与恢复 | 未变化材料不重解析、不重调用；成功结果跨中断复用；成本随新增量增长，不随历史总量增长 |
| 规模 | 按 CapacityProfile 验证十万级材料/片段；抽检工作量不随页面数线性增长 |
| 可维护 | 新增知识域、pack 或字段规则只改数据配置；新增格式只加解析适配与渲染器；核心代码不出现险种名、字段 key、样本身份 |
| 跟版 | 跟随 WeKnora 正式版本升级；上游补丁文件数只减不增 |

## 3. 与 830 的差异

### 3.1 保留不变

WeKnora 作为唯一 Wiki、审核、Release、Head 与读取权威；Harness 只做领域编译，不保存线上 Head；两者只经版本化
REST 与事件集成。不可变 Release + Head CAS；Claim + Evidence 作为唯一事实层；三态；稳定实体 ID 与分类分离；
SchemaPack 参数化与 PresentationProfile；来源定位失败即拒绝；所有变化都走 Candidate → Release。

### 3.2 改变的方案

| 主题 | 830 / 728 方案 | 1001 方案 | 理由 |
|---|---|---|---|
| Goal 顺序 | B0→G1…G6D→Q0→G7，质量放最后 | 切片路线 S0–S12；质量标尺放在第三片（S2） | 准确率是核心价值，必须先能测 |
| 编译执行 | 协议只在测试里；生产硬连 G3 执行器 | 统一 CompileJob + 编译器插件协议在生产入口生效；V5 字段编译器为第一个插件 | 可替换编译需要真实入口 |
| 字段抽取 | G3 bounded executor | 迁入 V5：全页召回、组成要素检查、原文回验、保守替换 | V5 有专家反馈驱动的质量提升 |
| 开放知识 | Harness 自有发现 + 原生发现两条路 | 只保留原生 discover/cite 作为候选源，Harness 负责准入 | 充分利用原生能力，去掉双路径 |
| 平台模型 | Go 侧 7 种 variant、5 套 hash、领域重放 | Go 只认通用 CandidateBundle/成员/Evidence/Locator；合同由 pydantic 导出 JSON Schema | 领域逻辑只在 Harness；减少 Go 侧耦合 |
| 页面存储 | 每个字段页作为成员存进 Release（PageManifest） | 存实体、Claim、Relation、概念定义等知识；页面按同一 Release 的数据生成 | 百万级页面成员不可持续；概念页汇总始终完整 |
| 知识准入 | 100 分六维 + 80/60 固定阈值；G3.5 另加 64/80 | 证据与身份是确定性硬门；独立审核打分路由；门槛可人工调整并校准 | 原阈值无校准依据 |
| 审核 | 三种发布前策略；新 Space 默认全人工 | 先发布后抽检：高分上线并标注"机器审核"，低分进人工，上线后抽检校准门槛 | 人工昂贵；规模化必须依赖机器审核 |
| 时间 | 七语义 + ClaimRevision + 双时态 | 五类判定；Claim 带业务有效期与维护记录；系统时间轴由 Release 历史提供 | 能回答"何时维护"，不另建时态引擎 |
| 专家来源 | 专家修订伪装为 SourceRevision + 文本偏移 | 独立不可变 ExpertRevision，Evidence 直接指向它 | 模型更直接 |
| 发布授权 | ed25519 签名信封 | 审核记录绑定 digest + 审计日志 + 服务间认证 | 审核与发布在同一系统，签名增加密钥管理成本 |
| 质量评判 | 专家 Canonical Golden（专家休假则阻塞） | 评判模型（Opus 5.5 / GPT-6.1 sol / GPT-6 Astra）校准后产出 Golden，专家回归后抽检 | 不因专家缺席停摆 |
| 模型 | 生产只用 MiniMax/Qwen 弱模型 | DeepSeek v4 flash（官方 API，开发可用 Gemini 降本），上线切私有化；只改配置 | 用户确认 |
| 知识服务 | 页面 + 原生检索 | 一等的 Knowledge Query API，Wiki/Agent/MCP/外部应用都是消费者 | 知识底层服务的定位 |
| 反馈、权限、规模 | 推到企业阶段 | 合同现在定下，按切片逐步实现 | 首期就要能演进 |
| 上游耦合 | "不深 fork"原则；补丁台账低报 | 自有包 + 扩展点；补丁登记，数量只减不增；每个上游版本一个升级切片 | 持续跟版 |
| 交付 | 本机 Colima 构建与唯一运行环境 | CI 构建镜像，环境按 digest 拉取 | 本机构建不稳定 |
| 治理 | Mission Card、OpenSpec、六维台账、HANDOFF 状态块、证据入库 | GitHub Issue → PR → Claude 审计 → 用户合并；证据为 SHA + 报告 | 降低治理成本，状态只有一处 |

## 4. 总体架构

### 4.1 分工

```text
                ┌──────────── 消费者 ────────────┐
                │ Wiki UI · 抽检/审核台 · 专家编辑 │
                │ 问答 Agent · MCP · 外部业务应用   │
                └───────────────┬────────────────┘
                                │ Knowledge Query API（版本化 REST，按 release_id 读取）
┌───────────────────────────────▼────────────────────────────────┐
│ WeKnora（Go/Vue）：唯一知识与发布权威                            │
│  source    上传、SourceRevision、ParseArtifact、原件与查看器       │
│  release   Candidate 接收/预览/决定、Release、Head CAS、回退       │
│  read      Knowledge Query API、Wiki 渲染、搜索、Agent/MCP/QA 绑定 │
│  feedback  回答日志、纠错、证据不足、抽检结论                      │
│  原生 Wiki 在受管 KB 中只作开放知识候选生成器                       │
└──────────────▲──────────────────────────────────┬───────────────┘
   CandidateBundle（REST，contracts/ JSON Schema）│ Source/反馈事件
┌──────────────┴──────────────────────────────────▼───────────────┐
│ Harness（Python）：保险领域编译与治理                              │
│  ingest → identity → compile（CompileJob + 编译器插件）→ evidence  │
│  → review（硬门 + 打分路由）→ changes（与 Active 比对）→ bundle     │
│  governance（GapTask/ReviewItem/Lint）· eval（Golden，离线）        │
│  catalog（SchemaPack 等数据）· jobs/models（任务与模型调用治理）     │
└──────────────────────────────────────────────────────────────────┘
```

两者不共享数据库、Redis/Asynq 或队列。Harness 不保存线上 Head；WeKnora 不包含险种、Schema、消歧、质量评分等
领域规则。

### 4.2 目标代码布局

**Harness**（`harness/src/insurance_harness/`）——新代码只进下列目录：

| 目录 | 职责 |
|---|---|
| `contracts/` | pydantic 合同定义；导出到仓库根 `contracts/*.schema.json` |
| `catalog/` | SchemaPack、FieldExtractionConfig、PresentationProfile、TrustPolicy、ReviewPolicy 的加载与校验 |
| `ingest/` | 读取 SourceRevision/ParseArtifact，按页重建 PageText；结构化导入 |
| `identity/` | 材料角色、产品/版本身份（MATCH/CREATE/MULTI/NEEDS_CONFIRM/QUARANTINE） |
| `compile/` | CompileJob 状态机、任务键、恢复、插件协议 |
| `compilers/` | `schema_fields`（V5）、`discovery`（原生候选准入）、`concepts`、`qa` |
| `evidence/` | quote 回验、locator 投影 |
| `review/` | 确定性检查、独立审核打分、路由 |
| `changes/` | 与当前 Active 比对、增量判定、维护记录 |
| `governance/` | GapTask、ReviewItem、Lint、覆盖统计 |
| `bundle/` | CandidateBundle 组装与提交 |
| `eval/` | Golden、Evaluator、评判模型适配 |
| `jobs/`（保留） | JobStore、租约、代次、outbox |
| `models/` | 按阶段配置的模型执行器、预算、重试、调用记账 |
| `service_shell/`（保留） | wiki-api / wiki-worker 进程外壳 |

其余现有目录只减不增：可以修改、搬出、删除，不得新增文件（守卫 G11）。

**WeKnora Go**：项目代码集中在 `internal/enterprise/{source,release,read,feedback,expertedit}`，通过一处挂载
（`internal/enterprise/mount.go`）接入 `container` 与 `router`；上游包里只保留无法避免的接缝。
**前端**：项目页面与组件集中在 `frontend/src/enterprise/`，经路由注册接入。
**合同**：仓库根 `contracts/`，由 Harness 导出，Go 与前端只读。

### 4.3 跟随 WeKnora 升级

- 项目代码放在自有包与扩展点中，经上游接口、路由挂载、配置与依赖注入接入。
- 修改上游文件只在没有其他办法时进行；每处登记在 `docs/design/upstream-patches.md`（文件、原因、能否提交上游、
  退出条件），数量只减不增（守卫 G10）。当前被改或删除的上游文件 440 个，其中 `internal/` 非测试文件 222 个（实质补丁 47 个，其余为格式改动），S7 回退格式改动。
- 上游出现可用的同类能力时，迁移过去并删除自有实现。
- 每个上游正式版本发布后开一个升级切片：隔离分支合并上游、跑全部门禁与 Golden 回归、记录冲突文件数与耗时；
  冲突集中的补丁优先改为扩展点或提交上游。
- 以最终效果为准：确需改上游或重写接口才能保证结果时可以做，但必须登记并说明升级成本。

## 5. 知识模型与数据合同

合同唯一来源：Harness pydantic → 仓库根 `contracts/*.schema.json`。Go 用已有依赖
`santhosh-tekuri/jsonschema/v6` 校验结构，再做平台不变量校验；前端按 JSON Schema 生成类型。

### 5.1 知识层（进入 Release）

```text
Entity          entity_id, entity_type（Catalog 配置：product/product_version/coverage/exclusion/
                service/concept/sense/...）, names[], aliases[], identifiers{product_code, filing_no,
                clause_no, ...}, classification_labels[], owner_module
Claim           claim_id, logical_key, subject_ref, product_version_ref（产品特定事实必填）,
                predicate（field_key 或 Catalog 谓词）, state, value（typed）, unit,
                applicability{region, channel, population, scenario}, effective_from, effective_to,
                evidence[], provenance, origin, expert_lock, unknown_reason,
                review{mode: machine|human, score, reviewer, reviewed_at},
                maintenance{revision_no, changed_at, changed_by: compile|expert|feedback|import,
                            reason, first_release_id, last_changed_release_id}
Relation        relation_id, predicate（Catalog 声明：relates_to_concept/sense_of/has_coverage/
                excludes/provides_service/supersedes/...）, from, to, applicability, effective_*,
                evidence[], provenance
QAItem          qa_id, question, intent, answer, supporting_claims[], related_entities[], evidence[]
                （首期只做来自已批准 FAQ 的权威 QA）
Evidence        source_ref, file_sha256, locator{kind, ...}, quote, quote_sha256,
                match: EXACT|NORMALIZED|FUZZY_REVIEW, access_scope
ExpertRevision  revision_record_id, actor, role, recorded_at, target, before, after,
                reason?, attachments?（不可变，WeKnora 保存）
SchemaSnapshot  本 Release 使用的 SchemaPack 与 PresentationProfile 标识与内容 digest
```

- **三态**：`present` 必须有值与已回验 Evidence；`absent_explicitly` 表示材料明确声明不存在或不适用，value 为空，
  必须有否定原文；有内容的禁止或限制规则（如"不接受增加基本保额"）属于 `present`；`unknown` 无值无证据，带
  typed reason。
- **来源分类**：`SOURCE_SUPPORTED`、`MIXED`、`MODEL_GENERATED`、`EXPERT_REVISION`、`STRUCTURED_IMPORT`。具体产品
  事实只能来自原文、专家修订或权威结构化导入；`MODEL_GENERATED` 只允许通用概念解释，显示为"模型补充"。
- **Locator.kind**：`PDF_TEXT_SPAN`、`OCR_REGION`、`DOCX_BLOCK`、`DOCX_TABLE_CELL`、`PPTX_SHAPE`、
  `XLSX_CELL_RANGE`、`CHUNK_SPAN`（历史片段，无原件）、`STRUCTURED_PATH`（结构化导入）、`EXPERT_REVISION`。
- **比较合同**：`logical_key` = subject + product_version + predicate + 适用范围维度；每种值类型有 typed
  comparator。历史测量中最弱的是"检出后值一致率"（0.273），typed 归一与比较器是质量工作的最高优先级。
- **两种时间**：Claim 带业务有效期（半开区间、Space 业务时区日历日，来自材料或继承 ProductVersion，只能收窄不能
  扩大，模型不得猜测）与维护记录；"系统在某时刻知道什么"读取该时刻的 Active Release。
- **成员存储**：成员 payload 按 digest 存一次，Release 只存 slug → digest 清单，未变化成员跨 Release 复用。

### 5.2 页面（不存储，由同一 Release 的数据生成）

产品树与分类视图、实体总览、分组页、字段页、概念页、义项页、Schema 外知识页、QA 页、变更摘要。

- **字段页** = 实体 × Schema 字段，聚合该字段下全部 Claim：值、条件、Evidence、审核方式（机器/人工）、维护记录。
  每个字段一个稳定 URL，unknown 也有页。
- **概念页** = 概念定义 + 同一 Release 内所有 `relates_to_concept` 指向该概念的字段 Claim。新增产品后汇总自动完整。
- 删除任何生成结果后都能由知识层重建；页面不维护独立可改的事实副本。

### 5.3 编译与治理层（Harness，不进入 Release）

```text
PageText        source_revision_id, parse_artifact_digest, document_role, page_number, text,
                text_origin: NATIVE|OCR, blocks[{block_id, start, end, locator}]
CompileTask     task_key, kind: schema_fields|discovery|concepts|qa|gap_fill, entity_version,
                material_set, targets, config_ref, budget
CompileResult   task_key, status, claims[], relations[], candidates[], diagnostics, call_receipts[]
GapTask         gap_id, target(entity, predicate), trigger: schema|feedback|lint|new_material,
                search_scope, attempts[], status
ReviewItem      item_id, kind: conflict|low_score|feedback|lint|acl_shrink|regression|sample,
                target, evidence, status, resolution_candidate
CandidateBundle contract_version, base_release_id, base_epoch, origin: compile|expert_edit|revert|
                incremental|feedback|import, members[{kind, logical_slug, payload, member_digest,
                evidence_refs, access_scope}], removals[], review_plan, compiler_identity
```

### 5.4 状态的唯一权威

| 状态 | 唯一权威 | 其他方 |
|---|---|---|
| 原件、SourceRevision、ParseArtifact、ExpertRevision | WeKnora | Harness 只读 |
| 编译任务、任务结果、调用记账 | Harness `jobs` | WeKnora 不感知 |
| SchemaPack / 抽取配置 / Profile / TrustPolicy / ReviewPolicy | Harness `catalog`（版本化数据） | Go 只校验 digest |
| Candidate、ReviewDecision、Release、Head | WeKnora | Harness 不保存 Head |
| 已发布知识 | Release 成员 | 受管 KB 中原生 `wiki_pages` 不是读源 |
| 回答日志、纠错、抽检结论 | WeKnora `feedback` | 以事件交给 Harness |
| GapTask、ReviewItem、Lint | Harness `governance` | WeKnora 审核台按 Candidate 展示 |
| Golden、评测结果 | Harness `eval`（离线） | 不进入生产读取 |

## 6. 核心流程

### 6.1 CompileJob（Harness 唯一编排入口）

```text
RECEIVED
 → MATERIALS_READY      读取 SourceRevision + ParseArtifact，按页重建 PageText；材料角色来自元数据与识别
 → IDENTITY_RESOLVED    MATCH / CREATE / MULTI / NEEDS_CONFIRM / QUARANTINE；歧义不自动合并
 → TASKS_PLANNED        按产品版本组装材料集；按 SchemaPack + FieldExtractionConfig 生成 CompileTask
 → TASKS_EXECUTED       插件执行；每个任务独立成功 / 失败 / 结果未知
 → CHANGES_COMPUTED     与当前 Active 比对（§6.5）
 → REVIEWED             确定性检查 + 独立审核打分（§6.3）
 → SUBMITTED            按实体组装 CandidateBundle，提交 WeKnora（digest 幂等）
 → 终态 DONE / PARTIAL / FAILED
```

- **任务键** = hash(产品版本, 相关材料 revision 集, 任务规格, 抽取配置版本, 编译器版本, 模型身份与参数)。键不变即
  复用成功结果，不重新调用模型。展示分组与分类标签变化不进入任务键，只影响页面生成。
- **恢复**：从任务状态与失效依赖推导待做任务；结果未知先对账，不自动补发。每条外部调用链只有一个重试 Owner 与预算。
- **部分成功**：一个实体失败不阻塞其他实体；实体及其强依赖作为一个原子单元提交。

### 6.2 平台链（WeKnora）

```text
POST /candidates                 接收 CandidateBundle（digest 幂等），结构校验 + 平台不变量
GET  /candidates/:id/preview     预览及与 Active 的差异
POST /candidates/:id/decisions   ReviewDecision（机器或人工；绑定 digest 与审核主体；可按整包）
POST /activations                expected_release + epoch CAS；单赢家；不同实体自动 rebase
POST /expert-edits               保存 ExpertRevision，发事件给 Harness
POST /samples/:id/verdicts       上线后抽检结论
GET  /releases/:id/...           指定 Release 的成员、页面与检索
回退                              以旧成员生成新 Candidate，走同一审核与 CAS
```

平台不变量（Go）：canonical JSON 与 digest、成员闭包与引用双射、Evidence 指向的原件或专家记录存在且 quote hash
一致、访问范围、base epoch CAS、审核记录绑定 digest、服务间认证。不做：字段是否齐全、实体消歧、质量评分、文案。

并发：一个 Space 一个 Head。Candidate 是相对 base Release 的实体级 delta；激活时若 Head 已前进而本 Candidate 触及
的实体期间未变，自动 rebase；否则重新比对再审。

### 6.3 发布：先发布后抽检

```text
确定性检查（不通过 → 不发布，生成 GapTask/ReviewItem）
  Evidence 可回验 · 类型与三态 · 无冲突 · 产品事实有原文/专家/权威导入来源 · 所属 pack 已通过质量准入
→ 独立审核打分（与编译隔离；分数校准到评判集）
  ≥ 门槛 → 直接上线，页面与接口标注"机器审核"
  < 门槛 / 冲突 / 版本歧义 → 人工队列，暂不上线
→ 上线后：按风险与字段分层抽检；系统挑出一批"请确认"交人工批量确认
  发现错误 → 修正 Candidate，必要时实体级回退；抽检结论写回 Golden 并校准门槛
```

- ReviewPolicy 按 Space 版本化：门槛按 pack/字段可分别设置，人工调整，每次调整留版本。首期不设必须人工先审的字段。
- 门槛以"达到门槛的成员在评判集上 precision ≥ 95%"来设定和复核；分数来自独立审核，不用编译模型的自评。

### 6.4 专家编辑

```text
WeKnora 编辑界面（复用上游编辑器、diff、history 组件）
 → POST /expert-edits {base_release_id, base_epoch, claim logical_key, base_member_digest, after}
 → WeKnora 保存不可变 ExpertRevision
 → 事件 → Harness 生成替换该 Claim 的 Candidate（origin=expert_edit，expert_lock=true，
   Evidence 为 EXPERT_REVISION）→ 同一发布流程
```

不在原生 `wiki_pages` 上原地编辑。expert_lock 的 Claim 面对后续模型新值只产生冲突 ReviewItem，不被覆盖；只有具名
专家的新决定可以更新或解锁。来源点击打开"谁、何时、把什么改成什么"。

### 6.5 增量更新

- 以现有增量判定器（`knowledge_compiler/incremental_changes.py`）为唯一语义 Owner，输入改为已发布 Claim，按
  `logical_key` 与 typed comparator 输出 Claim 级 delta；未受影响的 Claim 沿用旧成员与 digest。
- 五类判定：**不变**（含只补充 Evidence）、**替代**（同适用范围的新权威值，旧值留在历史 Release）、**并存**（版本/
  地域/渠道/人群/有效期不同）、**冲突**（同范围矛盾且 TrustPolicy 不能裁决）、**撤回**（来源撤回或失效）。
- 冲突不进 delta，保留旧成员并生成 ReviewItem；撤回显式移除成员；唯一支持失效的知识及时撤回。
- 触发与处理：新材料 → 定向补编或比对；Schema 新增字段 → 建 unknown 页与 GapTask，不需重传；字段语义变化 → 新
  field_key，旧字段 deprecated；TrustPolicy 变化 → 只重算裁决不重抽；展示或标签变化 → 只影响页面生成。
- 实体级回退：以该实体旧成员作为 delta 生成新 Release，保留其他实体的后续修订。

### 6.6 反馈飞轮与治理

```text
信号：Agent 证据不足 · 用户纠错 · 抽检错误 · 低分 · Lint（孤立/断链/过期/冲突/缺口）
      · 来源变更 · 访问范围收缩 · 模型或配置升级后的评测回归
  → WeKnora feedback 记录（绑定 release_id 与被引用成员）→ 事件
  → Harness governance 去重归并为 ReviewItem 或 GapTask
  → GapTask：只在本实体/版本已有材料中定向检索与补抽，保留历史尝试；相似产品只提示缺口，不提供替代证据
  → 新 Candidate → 正常发布流程（从不直接改 Active）
```

工作台复用 WeKnora 审核台：按实体与模块展示覆盖率、unknown 原因、冲突、重复、待处理 ReviewItem 与 GapTask。

## 7. 关键机制

### 7.1 Schema 字段编译器（迁入 V5）

- **接口**：输入同一产品版本的全部 PageText、目标 FieldDefinition 与 FieldExtractionConfig；输出逐字段 Claim、
  准入决定、缺失组成要素、执行完整性状态（`REPAIR_REQUIRED` / `REVIEW_REQUIRED` / `EXECUTION_CHECKS_PASSED`）。
- **内部**（调用方不可见）：全页召回与打分 → 上下文与预算 → 字段微批与长字段分片 → Schema 引导调用 → JSON 合同
  校验 → Evidence 原文回验 → 组成要素与值约束检查 → 保守替换 → 定向补抽。
- **FieldExtractionConfig**：键为 `schema_pack_id + field_key + field semantic_sha256`，内容含关键词、语义词、值形态、
  文档角色要求、邻页范围、分片、组成要素、省略禁用词、字段指令、`audit_kind`。与 FieldDefinition 分开存放，改规则不
  改变 pack hash。首批由 V5 现有规则（约 55 个字段）转换，其余字段使用通用默认配置。
- **必须保持的质量规则**：先扫全部页面再按预算截断；关键词未命中不证明字段不存在；quote 只允许 NFKC、去空白、
  去列表符、去脚注号归一，不跨页拼接，不能消歧即不采纳；模糊匹配单列为 `FUZZY_REVIEW`，不能单独支撑发布；长字段
  每个原子项都有直接证据，一个分片失败不能被其他分片掩盖；已知字段不得退化为 unknown；数字、否定、期限不改写；
  附加险不继承主险权益；输出截断（finish_reason ≠ stop）整批拒绝。
- **不迁**：V5 的 m15x 试验编排、预览 API、搜索问答页面、pdfplumber 读取（改用 WeKnora 解析）、硬编码 Provider。

### 7.2 开放知识、概念与 QA

- **开放知识**：受管 KB 内，WeKnora 原生 discover/cite 只产生候选，不直接写页面；Harness 负责身份、去重与归属
  （新建、更新已有、写入实体字段、别名、线索待处理、拒绝），按 §6.3 发布。Harness 自有发现路径退役。
- **概念与义项**：跨产品概念（如"犹豫期""在线问诊"）有一个概念实体承载通用定义；各产品下的具体规定是该产品的
  Claim，经 `relates_to_concept` 关联；概念页的汇总表由同一 Release 生成。
- **模型补充**：允许模型补充通用概念解释，标注"模型补充"并与原文依据分开显示；出现具体产品事实即被确定性检查拦下。
- **QA**：首期只做来自已批准 FAQ 的权威 QA；由 Claim 自动生成问答暂不做。

### 7.3 材料采信

- 材料角色是少量可配置类型（正式条款、说明书/面客材料、内部制度、核保/理赔规则、培训、销售经验、FAQ、普通片段、
  未知/混合），自动识别，不逐文件配置；不确定时进人工或隔离。
- TrustPolicy 唯一求值入口，按"字段 × 材料角色 × 产品版本 × 有效期"裁决：正式条款对责任、除外、等待期更权威；
  说明书不能自动覆盖条款；销售经验只作线索或解释；普通片段不能单独支撑高风险事实。策略变化只重算，不重抽。

### 7.4 多格式解析与定位

- 所有解析结果统一为版本化 ParseArtifact（由现有 NativeStructure 泛化），带 locator 空间与精度声明。
- 文本 PDF：保留现有 pdfium 字符框链路。
- 扫描件与图片：自建 MinerU（或 PaddleOCR-VL），解析其 content_list，locator 标明块级精度；无坐标的 VLM 纯文本结果
  不能作为可回跳 Evidence。
- Word、PPT、Excel：用 python-docx、python-pptx、openpyxl 采集原生结构（段落、表格单元格、slide/shape、sheet/cell
  与值快照）；DOCX/PPTX 预览用 soffice 转 PDF 快照复用 pdf.js 高亮，XLSX 原生渲染；转换确定性先验证。
- 回跳顺序固定：按 Release 读 Evidence → 打开指定 SourceRevision → 核对 hash → 按 kind 解析 → 回验 quote → 渲染；
  失败返回 typed error。

### 7.5 读写一致性与访问控制

- managed 判定统一为一个函数；所有 Wiki 写路由（含 POST pages、revert、folders、rebuild-links、auto-fix）挂同一守卫。
- 受管 KB 的所有读入口（Wiki、搜索、Agent、KnowledgeQA、MCP、聊天引用）只读 Active 或指定 Release；Agent 每轮固定
  一个 release_id；指定 Release 读取支持真正的历史版本。
- 每个成员携带由其 Evidence 来源推导的 `access_scope`，读时按调用者当前权限过滤；权限收缩后对无权主体立即不可见，
  并生成 ReviewItem 重新举证或降敏。
- 首期实现来源撤回与权限收缩；保留期与法律清除按合规要求另行设计，合同上预留"历史 Release 中被清除的来源不可服务"。

### 7.6 模型接入与调用治理

- OpenAI 兼容接口，按阶段配置 provider、endpoint、model 与输出预算；当前 DeepSeek v4 flash 官方 API，开发可用 Gemini，
  上线切私有化部署，只改配置。代码中不出现模型家族特判。
- 输出预算同时计入推理与正文 token（DeepSeek 曾出现推理耗尽 16K、正文为 0）。
- 每条调用链一个重试 Owner；限流按供应商提示有界退避；结果未知先对账。发送次数、耗时、用量在成功、失败、取消、
  超时路径都记录，复用与新调用分开统计。
- 模型输入只含本次所需字段、规则、去重后的原文与短引用编号；完整来源身份与审计对象留在服务端。

### 7.7 质量闭环

- **评判模型**（业务专家回归前）：Opus 5.5、GPT-6.1 sol 或 GPT-6 Astra（取高推理档位），实际所用模型与档位记入 Golden 的 judged_by 与 manifest；只做离线评测，不进生产流程，与生产编译/审核模型不同族。
  先在已有人工结论上校准（V5 的 30 条业务反馈与 31 项原文回归集、`gs-s0q-596-v1`）；一致性达标后，对每个 pack 的
  冻结样本逐字段核对原文产出 Golden，标记"模型评判"，专家回归后抽检复核。开发阶段允许把产品材料发给评判模型。
- **Golden 行**：沿用 `goldenset/records.py` 的 GoldenRecord，键为 `pack, product_version, field_key`；期望含 state、
  值或选项集、组成要素、禁止词、`document_sha256 + 页码 + quote`、评判者。
- **Evaluator**：逐字段与逐 pack 的 precision/recall（值按语义等价判定：L1 确定性、L2 独立评委、L3 回原文裁定）、组成要素召回、幻觉数、来源回跳率；零分母失败；模型原始输出与
  修订后结果分开报告；每个数字绑定 Metric ID（定义、分母、Golden 版本、模型身份）。
- **样本**：首批 7 款同条件产品（596、594、1826、1824、1814、1816、1828），之后每个 pack 至少一款上线产品。
  上线后抽检结论写回 Golden。
- CI 跑离线回放评测；真实模型评测按 Issue 预算执行，结论只认 DeepSeek v4 flash（上线后为私有化模型）。

### 7.8 知识服务接口（Knowledge Query API）

- 位于 WeKnora `read`，版本化 REST；MCP 与内部 Agent 工具是它的薄适配器。按通用知识查询设计，不绑定某个 Agent 项目。
- 能力：实体查找（名称/别名/代码/备案号）；按实体与谓词取 Claim（current / as_of_date / release_id）；Relation 有界
  遍历；Evidence 解析与回跳；按 Release 的混合检索（覆盖值、条件与开放知识正文）；同谓词跨实体比较；QA 检索；反馈与
  缺口上报。
- 每个响应携带 release_id、activation_epoch、稳定标识、provenance、审核方式、维护记录，以及 unknown/不足的明确状态。

### 7.9 规模与成本

- 编译只由变化驱动；任务按实体分区、micro-batch、有界并发，共享供应商配额；预算、速率与容量来自版本化 CapacityProfile。
- Release 成员按内容寻址，激活只切 Head；检索索引按 Release 增量构建。
- 历史 chunk 与零散片段先去重与归属，无法归属的进入隔离池。
- 运营指标：编译量、调用与费用、待处理积压、覆盖率与质量趋势、读取延迟。

## 8. 工程约束与架构守卫

工程原则（Deep Modules、Tracer Bullet、删除优于兼容、边界清晰、单文件 ≤ 500 行、禁止按样本特判等）见 `AGENTS.md`。
本节只定义可自动检查的守卫。

守卫在仓库根 `tests/architecture/`，用标准库 `ast`、正则与 git 实现，随 CI 运行。现有违例写入
`tests/architecture/baseline.json`，**只减不增**；新增违例一律失败，不设例外口。基线只能由脚本在数字下降时更新，
且只会逐项取更小值。唯一的固定容差写在 G3 一行里，不靠修改基线实现。

| 守卫 | 规则 | 生效 |
|---|---|---|
| G1 依赖方向 | Harness §4.2 目标目录不 import 旧目录；核心目录（`contracts`、`jobs`、`models`、`compile`、`evidence`、`review`、`changes`、`bundle`、`governance`）不 import `compilers`。Go 侧的隔离由 G2 与 G11 保证 | S0（基线 10 处：`jobs`、`service_shell` 对 `db`、`product_ingestion` 的引用） |
| G2 核心纯净 | Harness 核心目录、Go `internal/enterprise`、前端 `src/enterprise` 不出现险种名、field_key 字面量、Schema67、Golden（词表 `tests/architecture/domain_terms.txt`，由 Catalog v5 冻结生成）；`internal/` 其他非测试 Go 文件中的 Schema67/Golden 次数记基线 | S0（核心 0；Go 旧代码 294 处） |
| G3 文件规模 | 手写 `.py/.go/.ts/.vue`（含测试）不超过 500 行；生成代码、锁文件、迁移除外。新文件、原本不超过 500 行的文件越线一律失败；S0 时已超限的文件允许在基线行数上最多再多 50 行（固定容差，不随基线上移），超出即须拆分。这些文件在 S7 清理旧代码后一次性拆分 | S0 |
| G4 命名 | 新文件名不含 Goal、mission 或版本后缀（`_596`、`_815`、`_830`、`g3_`、`g35`、`m1NN`、`_vN` 等） | S0 |
| G5 无实例硬编码 | 非测试代码不出现本机绝对路径、`/private/tmp`、IP 字面量、release/run UUID 字面量、固定 tenant 或人名 | S0 |
| G6 私有访问 | Python 不跨模块 import 或访问 `_private` 名；生产代码不含 `_for_test` 钩子 | S0 |
| G7 写路由守卫 | 所有 Wiki 写路由都挂 managed 守卫 | S1 |
| G8 读入口绑定 | Wiki、搜索、Agent、KnowledgeQA、MCP 读入口在受管 KB 上经 release resolver | S1 |
| G9 合同漂移 | `contracts/*.schema.json` 与 pydantic 导出逐字节一致 | S3 |
| G10 上游补丁 | 相对固定上游版本被修改或删除的上游文件（`.github/` 除外）数量**只减不增**：新增一处上游改动必须同时登记 `docs/design/upstream-patches.md`（文件、原因、可否上游化、退出条件）并说明为何无法用扩展点解决；未登记的改动一律失败。登记不等于许可——该切片 Spec 必须显式允许该文件，且 Claude 在审查时逐条确认后才会更新基线。替换或回退已登记的补丁可相应下调基线（S7 回退格式改动即属此类） | S0（基线 440 个，其中 `internal/` 非测试 222 个） |
| G11 新文件位置 | Harness 新源码只能在 §4.2 目标目录，新测试只能在 `harness/tests/<目标目录>/`；Go 项目新增非测试文件只能在 `internal/enterprise/`，新迁移只能在 `migrations/enterprise/`；前端项目新增非测试文件只能在 `src/enterprise/`；测试文件可与被测代码同目录；旧位置的文件清单只减不增 | S0（基线 847 个） |

## 9. 协作与交付

流程全文与规则见 `AGENTS.md`；要点：

| 步骤 | 谁 | 做什么 |
|---|---|---|
| 1 | Claude | 写切片 Spec 与验收测试，推到 `slice/sN`，建好工作目录 `.worktrees/sN` 并装好依赖，按模板开 Issue（写明工作目录、开工方式与真实调用预算） |
| 2 | 用户 → 实现者 | 对 Codex 或 V5 同学说"做 issue #N"（交出即批准） |
| 3 | 实现者 | 在 Issue 下复述目标、范围、完成标准并列计划；小切片即开工，大切片等确认（Claude 在下一轮巡检内答复）；GitHub 上 Claude 的明确指示即确认 |
| 4 | 实现者 | 在 `.worktrees/sN`（分支 `slice/sN`）实现，本地过门禁，把最新 `main` merge 进来（不 rebase），开 PR（`Closes #N`） |
| 5 | Claude | 本地重跑验收、守卫与受影响组件门禁，检查 diff 范围，`gh pr review` 批准或列出编号修改项 |
| 6 | Claude | 审过当前 head 且 CI 通过后 Squash merge，`main` 上一个切片一个提交；合并后告知用户 |

- **仓库**：公开仓库 `PA-ALG/InsuranceKB-WeKnora`（`Tencent/WeKnora` 的 fork，本机 remote 名 `origin`）。
  2026-10-01 至 10-02 曾在私有仓库 `PA-ALG/InsuranceKB-WeKnora-private` 工作（已归档，只读）；完整备份在私有
  归档仓库 `PA-ALG/InsuranceKB-WeKnora-backup`。用 `gh` 操作时必须显式写 `--repo PA-ALG/InsuranceKB-WeKnora`，
  否则 fork 会默认指向上游 `Tencent/WeKnora`。
- **受保护路径**（实现者不改）：本蓝图、`docs/design/`、`tests/acceptance/`、`tests/architecture/`（基线只经脚本下降）、
  `contracts/`（只由 Spec 规定的导出命令生成）。
- **门禁**：Actions 在 S0 精简后启用，此前以本地门禁为准。Go 受影响包 `go test`；Harness `uv run pytest`、
  `uv run ruff check .`、`uv run mypy src tests`；前端 `npm run type-check`、相关测试、`npm run build`；守卫
  `pytest -q tests/architecture`。
- **证据**：commit SHA + 测试/评测报告摘要写在 PR 中；真实调用原始输出存仓库外私有位置；不做逐文件哈希清单，不向
  仓库提交日志与大体量回执。
- **真实调用与环境**：每个 Issue 写明"场景数 + 发送上限 + 模型"，批准即授权；部署、迁移、环境变更单独开 Issue 并附
  回滚方式。
- **构建与部署**：镜像由 CI 构建，环境按 digest 拉取；开发阶段沿用现有阿里云配置；上线前做私有化演练。
- **队列**：Claude 始终保持至少两个已就绪的 Issue。同一组件的运行时代码同时只有一个实现切片；写域不重叠的不同组件、
  CI/部署切片在各自工作目录并行。Claude 每 30 分钟巡检一次 GitHub：审计划与 PR，满足条件即合并。

## 10. 现有资产处置

KEEP = 原样保留；REWIRE = 保留行为，搬到目标位置或改接新合同；RETIRE = 在替代它的切片中删除。删除前须确认无生产
调用方、无迁移或部署依赖；历史留在 git 与私有归档中。下表"可达"指从 `wiki-api`/`wiki-worker` 入口按全部 import
（含函数内）静态可达的代码行比例（2026-10-01 测量）。

### 10.1 Harness

| 现有位置 | 可达 | 处置 | 去向 / 说明 | 切片 |
|---|---|---|---|---|
| `jobs/` | 100% | KEEP | JobStore、租约、代次、outbox，作为 `compile` 的运行时 | — |
| `service_shell/` | 100% | KEEP | 进程外壳 | — |
| `model_policy/` | 65% | REWIRE | → `models/`；删除 G3 专用 gateway 与模型家族特判 | S4 |
| `knowledge_compiler/schema_pack_catalog_*`、值约束 | — | REWIRE | → `catalog/`；去掉生产代码中的本机路径与 SHA 常量 | S3–S4 |
| `knowledge_compiler/incremental_changes.py`、`source_authority.py`、`retractions.py` | — | REWIRE | → `changes/`，作为增量唯一语义 Owner | S8 |
| `knowledge_compiler/` 其余（G1/G2/G3 编译、596/815 资产） | 52% | RETIRE | 被 `compilers/` 与 `bundle/` 替代 | S4–S7 |
| `product_ingestion/` 身份、来源几何 | 99% | REWIRE | → `identity/`、`evidence/` | S4–S5 |
| `product_ingestion/` 原生发现与准入 | 99% | REWIRE | → `compilers/discovery/`，合并为单一版本 | S6 |
| `product_ingestion/` pipeline、extraction、checkpoint 多版本、workflow v1–v3 | 99% | RETIRE | 被 `compile/` 与 `compilers/schema_fields/` 替代 | S5 |
| `run_admission/` | 94% | RETIRE | G3 运行准入；预算与授权并入 `models/` | S5 |
| `goldenset/` | 13% | REWIRE | GoldenRecord、比较器、指标 → `eval/`；修零分母；去掉 67 字段绑定 | S2 |
| `compiler/`（LangGraph） | 51% | RETIRE | 有用的 parsed_documents locator 规则先并入 `evidence/` | S5 |
| `template_packages/` | 100% | 待核实 | 确认用途后决定并入 `catalog/` 或删除 | S3 |
| `knowledge/`、`adapters/`、`runtime/`、`product/`、`workbench/`、`flywheel/`、`sources/`、`capacity/`、`schemas/`、`config/`、`mcp/`、`s0q_047.py` | 0% | RETIRE | 旧双 Head 链与早期 Mission 资产；确认 Alembic 与 CLI 不依赖后删除 | S7 |
| `structured_import/` | 0% | REWIRE | → `ingest/` 的结构化导入 | 第二期前 |
| `live_env/`、`db/` | 4% / 33% | 待核实 | 保留 Alembic 必需部分，其余删除 | S7 |

### 10.2 WeKnora（Go / 前端）

| 现有 | 处置 | 去向 / 说明 | 切片 |
|---|---|---|---|
| 五张 Release 表、Head CAS（`migrations/enterprise/000002`、`repository/wiki_release.go`） | KEEP | 加 activation_epoch 列与按 digest 去重的成员存储 | S3 |
| revision/SHA 固定、parse_attempt、NativeStructure 捕获、pdfium 字符框 | KEEP | 必要接缝；登记到 upstream-patches | S0 登记 |
| `service/wiki_release.go` 通用部分 | REWIRE | → `internal/enterprise/release`；删除按 contract 的分派 | S3 |
| `types/concept_free_wiki_830_g*.go`、`schema_wiki*.go`、`entity_page_graph_830_g1.go`、C5/C6 文件注册表 | RETIRE | 领域重放与 variant 分派；只读 adapter 也不保留，旧数据重建 | S7 |
| Agent 按轮固定 release、受管 KB 排除 | REWIRE | → `internal/enterprise/read`，扩展到 KnowledgeQA、MCP、原生 GET | S1 |
| ed25519 发布信封 | RETIRE | 改为 digest 绑定 + 审计 + 服务间认证 | S3 |
| 约 175 个纯格式改动的上游文件 | RETIRE | 回到上游原文；上游路径 lint 只检查新增改动 | S7 |
| 前端三套 Schema Wiki 页面家族、5 个 API adapter、2 套引用查看器 | RETIRE | → `src/enterprise/` 中按数据生成的页面；保留 pdf.js 高亮与坐标换算 | S3、S7 |
| 上游 WikiBrowser、WikiRevisionDrawer | KEEP | 专家编辑复用其编辑、diff、历史组件 | S9 |

### 10.3 文档与证据

| 现有 | 处置 |
|---|---|
| 830 蓝图、28/29 号、`HANDOFF.md`、`openspec/`、`docs/insurance-kb/`、`docs/superpowers/` | 冻结为历史；文件顶部注明已被本文取代 |
| 728 v3 | §2–§4 继续作为目标来源，其余为历史 |
| `docs/insurance-kb/evidence/`（1242 文件、37MB，含 44 个 `.py`） | 冻结；先去掉 14 个测试对它的依赖，再在 S7 移到私有归档 |

## 11. 实施路线

排序原则：先守住边界与安全，再建立质量标尺，然后用一条真实纵切（Tracer Bullet）验证新架构，之后沿同一条路扩展。
每个切片删除它所替代的旧实现；详细范围在各自 Spec 中冻结。

| 阶段 | 切片 | 目标 | 完成后能看到 |
|---|---|---|---|
| A 守住边界 | S0 基线与守卫 | 各组件完整门禁与失败清单；G1–G6、G10、G11 及基线；精简 CI 后启用 Actions；Dependabot 只保留实际维护的组件 | 之后每片以"不新增失败、守卫不新增违例"为准 |
| | S1 读写一致性 | managed 判定统一；全部写路由挂守卫；KnowledgeQA、MCP、原生 GET、聊天引用只读 Release；G7、G8 生效 | 受管 KB 旁路写全部被拒；各读入口返回的 release_id 一致 |
| B 标尺与纵切 | S2 质量标尺 | Evaluator 零分母失败且按 pack 参数化；V5 反馈、回归集、`gs-s0q-596-v1` 转 Golden；评判模型校准；用已有记录离线评分主项目与 V5 | 评判模型一致性报告；第一份逐字段对比报告 |
| | S3 通用平台合同 | `contracts/` 导出 CandidateBundle、成员、Evidence；Go `internal/enterprise/release` 通用接收、校验、预览、决定、激活；去掉签名；前端按数据生成产品树、字段页、概念页；G9 生效 | 样例 bundle 走完 预览→上线→字段页→概念页汇总→PDF 回跳 |
| | S4 字段编译器 | V5 引擎拆为 `compilers/schema_fields`；FieldExtractionConfig 数据化；PageText 由 ParseArtifact 重建；DeepSeek v4 flash 经 `models/` | 一款真实产品（建议 1828 重疾险）上传→编译→发布→回跳；Golden 评分不低于 V5 |
| C 统一与扩展 | S5 CompileJob 统一 | 任务键缓存与恢复、多产品批次、按实体提交；退役 workflow v1–v3、checkpoint 多版本、G3 执行器 | 7 款批次跑通；中断恢复重复调用 0；新增材料只触及所属产品 |
| | S6 开放知识与概念 | 原生 discover/cite 作为候选源；准入与归属；"模型补充"标注；Harness 自有发现退役 | 一条 Schema 外有价值知识发布并可回跳；噪声与重复被拒 |
| | S7 平台收敛与清理 | 删除 Go 领域重放与 variant、旧前端页面家族、约 175 个格式改动、Harness 不可达模块；evidence 目录移出；删除完成后一次性拆分仍超过 500 行的文件 | 守卫基线显著下降；`internal/` 上游补丁降到约 47 个且全部登记；G3 基线清零或只剩登记的例外 |
| D 上线能力 | S8 增量更新 | 判定器进生产；Claim 级 delta、显式撤回、维护记录、实体级回退 | 第二批材料生成新 Release：判定符合预期、无关 Claim digest 不变、冲突不改线上、回退 A 保留 B |
| | S9 专家编辑 | ExpertRevision、expert_lock、编辑界面 | 编辑→新 Release→来源打开修订记录；模型新值只产生冲突 |
| | S10 扫描件与图片 | 自建 MinerU/PaddleOCR-VL，content_list → ParseArtifact，OCR_REGION 回跳 | 扫描 PDF 与图片精确高亮；无坐标结果被拒 |
| | S11 Office 定位 | DOCX/PPTX/XLSX 原生结构与 locator、预览定位 | 段落、单元格、slide/shape、sheet/cell 精确回跳 |
| E 准入与上线 | S12 逐 pack 准入与联合验收 | 11 个 pack 的抽取配置与 Golden；每个 pack 至少一款产品按 §2.5 评测；门槛初值；多格式联合验收 | 11 个 pack 各自通过；流程与质量同时通过 |

并行轨道（写域不重叠时可与上表并行）：

| 切片 | 目标 |
|---|---|
| I1 CI 镜像 | App、DocReader、UI、Harness 全部由 CI 构建，build-args 完整，多架构，按 digest 发布 |
| I2 测试环境 | 开发阶段沿用现有阿里云配置；云上环境按 digest 拉取部署，附回滚步骤；Mac 不再作为唯一运行环境 |
| I3 私有化演练 | 上线前：内网 LLM、VLM、embedding、rerank、MinerU；材料不出内网的端到端演练 |
| U 上游升级 | 每个 WeKnora 正式版本一次：合并、全门禁与 Golden 回归、冲突统计 |

## 12. 风险

| 风险 | 应对 |
|---|---|
| V5 质量来自 qwen-plus，换 DeepSeek v4 flash 后不保持 | S2 先离线对比，S4 真实测量；输出预算计入推理 token；不达标时调整抽取配置或分片，结论只认生产模型 |
| 评判模型与真实专家判断不一致 | 先在已有人工结论上校准；Golden 标记"模型评判"；专家回归后抽检复核 |
| 先发布后抽检让错误知识上线 | pack 质量准入为前提；门槛按 precision ≥ 95% 设定；页面标注"机器审核"；风险分层抽检；实体级回退 |
| 新旧代码长期并存 | 每片删除被替代的实现；G11 禁止旧目录新增文件；S7 集中清理 |
| 上游升级冲突 | 自有包 + 挂载点；补丁登记只减不增；每版升级切片记录冲突 |
| 私有化后 OCR 与模型能力不足 | I3 提前演练；自建 MinerU；模型只改配置即可切换 |
| CI 用量随切片增长 | 公开仓库标准 runner 免费；仍只跑受影响组件，构建镜像按需触发 |
| 规模到十万级后 Release 成员过多 | 成员按内容寻址；页面不存储；S5 用规模夹具验证 |
| 多个业务模块同时发布互相覆盖 | 实体级 delta + 激活时 rebase |

## 13. 未决事项

1. **仓库可见性**：2026-10-02 起回到公开仓库开发（见 §14）。若日后需要转私有，先按 §12 的风险重新评估 CI 成本。
2. **缺失险种材料**：意外医疗、定期寿险、补充养老（护理险待核对）尚无真实产品，S12 前从公司官网补充。
3. **专家回归后的复核**：评判模型产出的 Golden 由业务专家抽检复核的时间与方式。
4. **Harness 现有主链细节**：JobStore、StageCall 记账、checkpoint 与 workflow v1–v3 的逐项保留范围，S5 Spec 前补入
   `01-调研结论` §9。

## 14. 决策记录

| 日期 | 决策 | 位置 |
|---|---|---|
| 2026-09-30 | 生产模型 DeepSeek v4 flash；当前官方 API + Gemini 降本，上线私有化部署 | §7.6 |
| 2026-09-30 | V5 作为 Schema 字段编译器迁入，替代 G3 字段执行器 | §7.1 |
| 2026-09-30 | 原生 discover/cite 为开放知识主路径，Harness 自有发现退役 | §7.2 |
| 2026-09-30 | 允许模型补充通用概念，显式标注 | §7.2 |
| 2026-09-30 | 上线范围含增量更新、专家编辑、扫描件 OCR、Office 定位 | §2.5、§11 |
| 2026-09-30 | 采用 GitHub Issue → PR → Claude 审计 → 用户合并 | §9 |
| 2026-10-01 | 目标沿用 728 §2–§4 与 830 产品要求；技术方案重新评估 | §1、§2 |
| 2026-10-01 | 首期只做产品知识域；11 类每类至少一款，合计几十款；消费方为业务人员与问答 Agent；接口按通用设计 | §2.4、§7.8 |
| 2026-10-01 | 存知识、生成页面；实体、概念与字段的关系作为数据保存 | §5 |
| 2026-10-01 | 每条知识记录业务生效时间与维护记录 | §5.1 |
| 2026-10-01 | 先发布后抽检；门槛可人工调整；首期不设必须人工先审的字段 | §6.3 |
| 2026-10-01 | 去掉发布签名 | §3.2、§6.2 |
| 2026-10-01 | 专家修订为独立不可变记录 | §5.1、§6.4 |
| 2026-10-01 | 一个企业 Space，按业务属主分模块，知识不割裂 | §2.4、§6.2 |
| 2026-10-01 | 业务专家回归前由 Opus 5.5 或 GPT-6.1 sol 离线担任评判，先校准；开发阶段允许材料外发评测 | §7.7 |
| 2026-10-01 | 旧数据与旧代码删除，不迁移，不保留只读 adapter | §10 |
| 2026-10-01 | V5 同学在主仓库按 Issue 流程开发 | §9 |
| 2026-10-01 | 新工作仓库为私有 `PA-ALG/InsuranceKB-WeKnora-private`；旧公开仓库只保留历史，完整备份在私有归档仓库 | §9 |
| 2026-10-02 | 合并权交给 Claude：审过当前 head、CI 通过、范围符合 Spec 即可 Squash merge，事后告知用户；部署、迁移、仓库设置、超预算真实调用仍需用户批准 | §9 |
| 2026-10-02 | 回到公开仓库 `PA-ALG/InsuranceKB-WeKnora` 开发：私有仓库 Actions 因组织计费受阻，用户确认公开不影响。私有仓库归档只读。`main` 上 `(#1)`、`(#3)`、`(#6)` 等编号指私有仓库的 PR，与公开仓库同号 PR 无关 | §9 |
| 2026-10-01 | 持续跟随 WeKnora 升级，降低耦合；以最终效果为准，必要时可改上游或重写接口，但须登记 | §4.3、G10 |
| 2026-10-01 | `absent_explicitly` value 为空且必须有否定原文；有内容的禁止规则属于 present | §5.1 |
| 2026-10-01 | 本蓝图取代 830 蓝图、28/29 号文档与 `docs/design/00-架构总览.md` | 文首 |
| 2026-10-03 | S2b 评委改用 GPT-6 Astra（xhigh），在独立 Codex 会话中以文件交换答题，不走 API | §7.7 |
| 2026-10-03 | 每个 Issue 一个独立 git worktree，写域不重叠的切片并行；GitHub 上 Claude 的明确指示即确认，Codex 只在越界、冲突、超预算、部署迁移时停下；Claude 每 30 分钟巡检 | §9、`AGENTS.md` |
| 2026-10-03 | 500 行仍是原则；S0 时已超限的文件少量增长不逼当场拆分，固定容差 50 行，S7 清理旧代码后一次性拆分 | §8 G3、§11 S7 |
| 2026-10-07 | 质量评分按语义等价：L1 确定性 → L2 独立评委判等价 → L3 回原文裁定；逐字口径只作对照（用户 2026-10-05 裁决，S2c 扩到候选评分） | §7.7 |

## 附录 A · 术语

| 术语 | 含义 |
|---|---|
| Entity | 知识主体：产品、产品版本、保障责任、服务、概念等，ID 稳定 |
| Claim | 一条可独立验证、审核、版本化的原子事实，带三态、值、适用范围、有效期、Evidence、维护记录 |
| Relation | 实体或 Claim 之间有类型的关系，如字段关联概念、产品提供服务 |
| Evidence | 指向原件或专家修订记录的精确来源与引文 |
| SchemaPack | 一类实体在一个版本下的字段定义集合（如医疗险 67 字段） |
| FieldExtractionConfig | 字段抽取规则数据：关键词、组成要素、分片、指令等 |
| PresentationProfile | 一个 pack 的展示分组与字段顺序 |
| TrustPolicy | 按字段 × 材料角色裁决采信的策略 |
| ReviewPolicy | 发布门槛与路由配置 |
| CandidateBundle | Harness 提交给 WeKnora 的一批待发布知识（相对 base Release 的实体级 delta） |
| Release / Head | 不可变的知识版本 / 指向当前线上 Release 的唯一指针 |
| CompileJob / CompileTask | 一次编译任务 / 其中可独立缓存与恢复的单元 |
| GapTask / ReviewItem | 缺口补编任务 / 待人工处理项 |
| Golden / Evaluator | 质量标尺数据 / 逐字段计算指标的程序 |
| 评判模型 | 业务专家回归前，离线担任专家评判的强模型 |
| 切片（Slice） | 一个可独立交付与验收的最小纵向改动，一个 Issue、一个 PR |











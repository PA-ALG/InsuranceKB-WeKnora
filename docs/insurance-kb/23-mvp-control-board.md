# 23 · Enterprise LLM Wiki MVP 控制板

> 状态：**业务方已批准，等待 OpenSpec 与执行窗口落地（2026-07-21）**
> 权威性：这是当前 MVP 的冻结调度基准；唯一实时状态仍在 `HANDOFF.md`。`16-roadmap.md` 保存完整企业路线，`22-parallel-execution-blueprint.md` 保存并行规则；发生冲突时由总体规划窗口修订，执行窗口不得自行解释。
> 总体规划窗口职责：只做范围、依赖、任务分发、PR/验证报告检查和 Roadmap 维护；**不写功能代码、不跑重测试、不替执行窗口修 PR**。

## 1. 北极星与本轮裁决

**Enterprise LLM Wiki 是产品本体和未来知识权威；WeKnora 是企业平台底座；Python Harness 是弱模型知识编译与治理运行时。**

本轮选择 **Integration-first Walking Skeleton**：复用已交付的 KnowledgeSpace、SourceRevision/Evidence、ReviewItem、ReleaseSnapshot、SnapshotReader、Source lifecycle 和 Golden Gate，优先组装真实多文档闭环。MVP 只简化实现规模，不删除长期对象、身份、状态或接口。

三个方案的裁决记录：

| 方案 | 日历估算 | 裁决 |
|---|---:|---|
| Integration-first：现有底座 + Python Harness 插件闭环 | **7–10 个工作日** | **采用** |
| Production-first：先补 P-1、完整预算/调度/GC 再演示 | 4–6 周 | 放入企业生产化阶段 |
| Migration-first：整套搬运旧 UI/单体 extractor | 3–4 周且耦合风险高 | 不采用 |

## 2. 第一方资产与第三方边界

- 业务方/项目权利人已于 2026-07-21 明确声明：`silvielala412-lab/LLM-wiki-black` 及 `feature/product-catalog-domain` 分支由项目方完整拥有著作权，允许本项目审计、复用和迁移其核心能力。
- 因此，`LLM-wiki-black` 的第一方能力迁移**不再受 clean-room 阻断**；已有 `routing_data.py`、`cleaning.py`、004/006/024 仍须经过新 OpenSpec、TDD、Golden Slice 与架构重构后才能进入生产，原因是质量与架构，不是第一方权利不足。
- **语言只保留一个领域运行时**：LLM-wiki-black 的 TS 源码用于能力盘点、规则/schema/prompt/test-vector 迁移和行为对照；生产保险逻辑统一重构到 Python 3.12 Harness，不引入 Node/TS 领域服务、queue、事实库或 Python↔TS 双运行时。WeKnora 上游语言不变，自有 TS 前端只能展示和调用 API。
- `nashsu/llm_wiki`、Tencent WeKnora 和其他依赖仍按各自许可证处理；未经单独确认，不把第三方实现表达当作第一方资产。
- 迁移策略是“选择性重构为 Python Harness 组件”，不是整体复制旧前端、localStorage、Markdown 事实库、双审核体系、治理旁路或巨型单体 extractor。

权利决定的详细工程边界见 [06-asset-migration.md](06-asset-migration.md)。

## 3. MVP 固定样本切片

MVP 使用仓内 `dataset/shouxian_product/` 的 5 个产品，每个产品 3 份 PDF + 1 份产品元数据，共 **20 份真实来源**：

1. 平安e生保（尊享版）医疗保险；
2. 平安e生保（悦享版）医疗保险；
3. 平安盛世金越（尊享版26）终身寿险；
4. 平安盛世金越（尊享版26）终身寿险（分红型）；
5. 平安盛世金越养老年金保险（分红型）。

该切片覆盖医疗、终身寿险、年金至少 3 类业务形态，并包含相似产品名和普通/分红型身份区分。另增加 3 份受控且有 provenance 的验收来源：

- 1 份混合两个产品的文档，用于事实级产品路由和 `unassigned`；
- 1 份同产品后续 SourceRevision，含补全和显式冲突；
- 1 份 FAQ JSON，用于跳过文档解析的结构化直入。

**总验收规模：23 份来源、5 个产品、至少 3 类产品形态。** 完整 13 产品 baseline 继续保留在企业生产化阶段，不阻塞本 MVP。

## 4. 唯一 MVP 主链

```text
WeKnora RAW / structured source
  → SourceRevision 冻结
  → 文档分类与产品/版本归属
  → TemplatePackage 选择
  → 多弱模型 Agent / 多次短任务
  → Evidence 回验 + 三态/确定性校验 + Gap 补抽
  → Claim 候选
  → ChangeSet / Conflict
  → 人工 Review
  → ReleaseManifest + 授权人批准完整 hash
  → ReleaseSnapshot / CurrentRelease
  → Harness 人类 Reader + MCP 读取同一 029 ApprovedSnapshotReader
  → 新 SourceRevision 更新、change log 与回滚
```

P-1 前，MVP 只使用 ACL 隔离且禁生产检索的 staging 与 Harness Reader，不宣称 WeKnora 生产 Wiki UI 已交付。P-1 release namespace、seal、原子 active alias 和完整 GC 在企业生产化阶段补齐，但沿用相同 `ReleaseSnapshot/ReleaseManifest/CurrentRelease` 合同。

## 5. MVP 冻结合同

以下身份和语义从 MVP 起稳定，后续只能扩展字段或 adapter，不能换一套主链：

`KnowledgeSpace / SourceRevision / Claim / Evidence / ChangeSet / ReviewItem / ReleaseSnapshot / ReleaseManifest / ApprovedSnapshotReader / TemplatePackage / CompilationJob / StageRun / Attempt / AgentReceipt / Alert`

MVP 允许的简化：

- 每类产品先使用一个批准的固定 TemplatePackage；以后扩成四级 registry 和自动草案；
- 先使用单进程持久 executor、2–4 个有限 worker；以后扩分布式 lease/fencing/fairness；
- 先用固定 attempt/time/token 上限；以后扩预算预留、结算、成本分摊和 UI；
- 先支持已知 schema 的 `product_meta.json` 与 FAQ JSON；以后扩通用映射 Workbench、CSV/API 和大批次；
- 先由 Harness Reader/MCP 服务批准 snapshot；以后把 serving commit 接到 WeKnora `active_release_id`。

## 6. 必过验收故事

MVP 只有同时满足下列条件才完成：

1. 23 份来源可按同一 run identity 重放，重复执行不重复写事实；
2. 5 个产品全部形成可阅读知识页，所有展示 Claim 都能回验到 Evidence；
3. 混合文档的事实进入正确产品，歧义项进入 `unassigned + Alert/ReviewItem`，跨产品污染为 0；
4. FAQ JSON 不经 PDF 解析，但仍经过 SourceRevision、Evidence、ChangeSet、冲突和审核；
5. 后续 SourceRevision 产生 add/enrich/supersede/conflict，而不是静默覆盖；
6. 模板失配、模型无共识、证据断链或尝试耗尽会停止候选推进并产生持久 Alert；
7. 授权人批准的 overall manifest hash 必须绑定 facts/pages/directory/relationships 四段各自的 canonical count+sha256；任一条目、Evidence、计数或段 hash 改动都阻断 promote/rollback；
8. 人类 Reader 与 MCP 导入同一个 029 serving signature/DTO/failure union，并返回同一 `snapshot_id`、manifest hash、canonical fact/Evidence tuple 与顺序；unknown 事实保留，只有 coverage gap 映射 not-found；
9. 回滚不重新调用模型，能够恢复上一批准 snapshot；
10. 失败任务可从最近 checkpoint 重试，已完成阶段不重做。

## 7. 执行窗口与文件域

| 窗口 | OpenSpec/任务 | 独占主域 | 交付顺序 |
|---|---|---|---|
| **S · Model/Runtime** | 027 弱模型生产硬门禁；028 TemplatePackage + Compilation runtime MVP | `config.py`、`compiler/` 最小接线、新 `template_packages/`、新 `runtime/` | 027 → 028；不得改 knowledge/MCP |
| **K · Knowledge/Intake** | 029 ReleaseManifest/Approval MVP；010 的已知 schema 结构化薄切 | `knowledge/`、`structured_import/`、本窗口迁移 | 029 与 010 串行；独占 DB 迁移 lane |
| **M · Human/Agent** | 013 MCP 核心只读工具；032 独立 Human Wiki Reader | `mcp/`、新 `human_reader/` | 先按 ApprovedSnapshotReader 协议开发，029 合入后做同快照 contract integration；008 审核工作台保持独立 |
| **I · Slice/E2E** | 030 MVP slice admission、受控 fixtures、端到端验收报告 | 新 `dataset/mvp-*`、新 E2E tests/runbook/report | 样本清单可先行；集成验证等 S/K/M |
| **G · 总体规划** | 控制板、Roadmap、编号、跨包合同和最终放行 | `docs/insurance-kb/{06,13,16,17,18,21,22,23}`、`HANDOFF.md`、注册表 | 不写功能代码、不替其他窗口跑重测试 |

共享文件 `pyproject.toml`、`uv.lock`、`config.py`、迁移链、`HANDOFF.md`、OpenSpec 注册表由 G 窗口或明确指定的唯一 Owner 串行收口。本轮 `config.py` 唯一 Owner 是 S0/027，M0/S1 使用包内 settings；`pyproject.toml/uv.lock` 唯一 Owner 是 M0/013。执行窗口发现跨域缺口时只报 contract issue，不直接修改另一窗口核心文件。

### 7.1 可认领实施计划索引

| 波次/窗口 | 实施计划 | 调度条件 |
|---|---|---|
| Wave 1 · S0 | [027 Production Model Gate](../superpowers/plans/2026-07-21-mvp-production-model-gate.md) | 规划基线 commit 后立即开始；先合入 |
| Wave 1 · K0 | [029 Release Authority](../superpowers/plans/2026-07-21-mvp-release-authority.md) | 独占 migration lane；可与 027 并行 |
| Wave 1 · M0 | [013 MCP Agent Reader](../superpowers/plans/2026-07-21-mvp-mcp-agent-reader.md) | 先用 029 exact fake；最终合流等 029 |
| Wave 1 · I0 | [030 Real Slice / E2E](../superpowers/plans/2026-07-21-mvp-real-slice-e2e.md) | 只做 manifest/fixtures/admission，零模型 |
| Wave 2 · S1 | [028 Template Compilation Runtime](../superpowers/plans/2026-07-21-mvp-template-compilation-runtime.md) | 027 合入后；028a pure domain → 028b deployable |
| Wave 2 · K1 | [010 Known-Schema Structured Intake](../superpowers/plans/2026-07-21-mvp-known-schema-structured-intake.md) | 029 后串行；`0007` 一次落完整 schema |
| Wave 2 · M1 | [032 Human Wiki Reader](../superpowers/plans/2026-07-21-mvp-human-wiki-reader.md) | 029 serving + 013 access contract 可用后 |

执行任务不得从当前未提交的规划 worktree 直接派生，否则会把控制文档脏改动带入功能 PR；先由人审阅并提交本规划基线，再从该 commit 创建各自独立 worktree。AI 执行任务不 commit/push。

## 8. 7–10 工作日节奏

| 日历 | 目标 |
|---|---|
| Day 1 | 占号、OpenSpec、固定 23 来源 manifest/hash、027 首个 RED |
| Day 2–4 | S/K/M 并行完成各自最小合同与 focused GREEN；I 完成 fixtures/admission |
| Day 5 | 三条链在同一数据库和 SnapshotReader contract 上第一次合流 |
| Day 6–7 | 23 来源真实运行；关闭归属、冲突、Evidence、结构化直入问题 |
| Day 8 | 更新、失败告警、批准 hash、人/MCP 同快照、回滚故事 |
| Day 9 | 独立集成审查与受控 WeKnora live smoke；功能问题退回原 Owner |
| Day 10 | 一次完整 deterministic/CI 验证、验收报告和 Roadmap 重新基线 |

外部模型/provider 不可用时只把对应 live run 标记 `BLOCKED`，不把等待时间伪装为开发工期，也不在阻塞期间扩张 MVP scope。

## 9. PR 与 TDD 提效硬规则

- 一个 PR 只交付一个验收结果；目标 5–12 个文件、300–800 行生产代码，超出必须拆分或写明例外；
- 编码前 30–60 分钟冻结接口、不变量和失败矩阵；首个 RED ≤15 分钟，首个可核验 GREEN ≤60 分钟；
- 每次 RED/GREEN 只跑精确测试，目标 ≤90 秒；任务收口跑领域套件，目标 ≤3 分钟；完整 2700+ deterministic 只在 PR ready 和 CI 跑；
- A 级（权限/迁移/发布/租户）使用完整 TDD、故障矩阵和定向红队；B 级（模板/抽取/融合）使用 focused + Golden Slice；C 级（UI/文档/接线）使用契约测试和 smoke；
- Reviewer 一次性汇总完整发现，最多两轮返工；第三轮由总体规划窗口裁决接口或拆 PR；
- 每个 PR 报告七段时间：设计、编码、focused test、review wait、rework、full CI、live；禁止只用 created→merged 推断开发效率。

## 10. 当前 Gate

| Gate | 状态 | 影响 |
|---|---|---|
| 北极星与 Integration-first MVP | **APPROVED** | 可落 OpenSpec/计划 |
| LLM-wiki-black 第一方权利声明 | **RECORDED** | 可审计和迁移第一方能力；第三方仍单独清点 |
| 027 生产弱模型硬门禁 | **PENDING** | 完成前不得真实生产 merge/release |
| 23 来源 MVP slice admission | **PENDING** | READY 前零真实模型运行 |
| P-1 WeKnora 原子 active alias | **DEFERRED, 非 MVP 阻断** | MVP 使用 Harness Reader/MCP；生产 UI 仍 fail closed |
| 完整 13 产品 baseline | **NEXT, 非 MVP 阻断** | MVP 后进入企业生产化 |

## 11. 完整企业路线不丢失

- **阶段 1：真实多文档 MVP（7–10 工作日）**——本控制板范围；
- **阶段 2：企业生产核心（MVP 后 3–5 周重新基线）**——P-1 原子发布、完整 010/013/008 与 032 扩展、13 产品与跨险种 baseline、完整 Template registry/approval；
- **阶段 3：规模运营（再 4–6 周滚动计划）**——千份并发、lease/fairness、批次控制台、知识健康、Schema/Template Workbench、完整预算与告警运营；
- **阶段 4：持续演进**——质量飞轮、更多险种、模板自动生成草案、关系/图谱、多模态和受控研究。

企业阶段的时间在 MVP 验收后依据真实 PR 七段时间重新估算，不再使用未区分等待/返工的粗粒度周期。

# 06 · LLM Wiki 资产迁移与许可证边界

> **状态（2026-07-21）**：业务方/项目权利人已明确声明 `silvielala412-lab/LLM-wiki-black` 由项目方完整拥有著作权，并授权本项目审计和迁移其核心能力。第一方迁移不再需要 clean-room，也不再作为 MVP 阻断。
> 本文是工程决策记录，不替代企业需要的正式法务签章。第三方项目与依赖仍按各自许可证管理。

## 0. 权利与工程裁决

| 资产 | 当前身份 | 工程使用规则 |
|---|---|---|
| `LLM-wiki-black/feature/product-catalog-domain` | 项目方第一方资产 | 可直接阅读、审计、测试和选择性迁移；每项迁移记录 source commit/path 和新 Harness 落点 |
| 当前仓库中由上述第一方项目迁入的 routing/cleaning/004/006/024 资产 | 第一方历史实现 | 权利不再阻断；进入生产前仍须新 OpenSpec、TDD、Golden Slice、Evidence/ChangeSet/Alert 门禁和架构复核 |
| `nashsu/llm_wiki` | 第三方 GPL 项目 | 默认只借鉴产品思想；直接使用代码或表达必须另行记录许可证兼容决定 |
| Tencent WeKnora | 第三方 MIT 平台底座 | 按 MIT 与上游版本列车使用；保险业务逻辑不进入 Go/Vue 核心 |
| 其他库、模型 SDK、数据与 FAQ | 第三方或业务数据 | 逐项记录许可证/授权、版本、来源和内容 hash |

结论：以前以 `NS-LEGAL` 表示的“LLM-wiki-black 权利未决”已由项目权利人声明解除。后续使用 `NS-RIGHTS=recorded` 表示该决定已记录；它不是要求重新实现第一方代码的门禁。仍需完成的是非阻断的第三方 inventory，以及每个迁移 PR 的 provenance。

### 0.1 语言收敛：迁移能力，不保留第二套 TS 运行时

权利确认表示可以完整阅读、测试、翻译和重构 TypeScript 源码；它不改变本项目的目标架构。`LLM-wiki-black` 不以 Node/TypeScript 服务、sidecar、npm workspace、TS queue 或 localStorage 知识库的形态进入生产。领域能力统一落到 Python 3.12 Harness：

1. 先记录 TS 来源 commit/path 与接受/拒绝行为；
2. 把 schema、prompt、规则和测试向量转成内容寻址的声明式资产；
3. 把算法行为重构为 Python ports/plugins，并复用现有 Scope/Source/Claim/Evidence/Review/Release 主链；
4. 用 characterization tests 与当前 Golden Slice 证明语义，不建立 Python→Node 运行时桥；
5. 自有 TypeScript 仅可存在于展示/API client 层，不拥有事实、任务、冲突或发布状态。

因此，后文的“选择性迁移”统一指 **TS 能力 → Python Harness**，而不是在 WeKnora 旁长期运行两套领域后端。WeKnora 上游的 Go/Vue/TypeScript 仍按平台版本列车维护，不属于这次语言迁移范围。

## 1. 迁移原则：保留能力，重构边界

迁移目标不是把旧产品整体嵌入 WeKnora，而是把真正有价值的领域能力重构为稳定的 Python Harness 组件：

```text
第一方能力盘点
  → 明确输入/输出/失败模式
  → 映射到北极星对象与接口
  → OpenSpec + 条款级测试
  → Python Harness 最小实现
  → Golden Slice / E2E 验收
  → 记录 source provenance 与取舍
```

每个迁移 PR 必须说明：

1. 来源仓库、branch/commit/path；
2. 迁移的是产品能力、规则、schema、prompt 还是测试向量；
3. 新落点及为什么符合 WeKnora adapter / Harness compiler / Wiki governance 边界；
4. 是否改变 Claim/Evidence/ChangeSet/ReleaseSnapshot 语义；
5. 用什么独立业务样本和 Golden Slice 验证；
6. 哪些旧行为明确没有迁移以及原因。

## 2. 第一批应迁移的核心能力

| 能力 ID | 第一方能力价值 | 新系统落点 | MVP 验收 |
|---|---|---|---|
| MIG-01 | 保险产品 schema、模块和文档类型约束 | `TemplatePackage` + `schemas/` | 3 类产品使用正确字段集合，越域字段不污染 |
| MIG-02 | 长文档分段、章节分组、字段组路由和跨段合并 | `orchestration/` + compiler ports | 3 PDF/产品可恢复编译，失败阶段可重试 |
| MIG-03 | 多产品材料的产品/版本归属与别名处理 | 现有 `product/` + Router stage | 混合文档事实归属正确，歧义进入 unassigned |
| MIG-04 | 字段来源、值 provenance、缺失项和补抽 | `Evidence` + Gap stage + `AgentReceipt` | 已展示 Claim 全有可回验 Evidence；unknown 不变成不存在 |
| MIG-05 | 实体身份、别名、去重和关系 | Claim subject/identity ports；完整关系层放企业阶段 | 普通/分红型和相似产品名不串知识 |
| MIG-06 | 来源权威度、更新和冲突规则 | `ChangeSet/Conflict/ReviewItem` | add/enrich/supersede/conflict 不静默覆盖 |
| MIG-07 | 批次 SHA、幂等、状态和重试 | `CompilationJob/StageRun/Attempt/Alert` | 同 run 重放不重复写，失败可恢复 |
| MIG-08 | 审核动作语义 | 现有统一 ReviewItem/Workbench | approve/reject/defer/overturn 不再存在双审核模型 |

## 3. 明确不整体迁移

- 与浏览器、Zustand、localStorage、桌面端或旧文件系统布局耦合的领域逻辑；
- 把 Markdown、目录、页面表格当作事实数据库的设计；
- 两套互不一致的审核/版本体系；
- 产品 fast-path 提前返回、绕过 identity/relation/audit/governance 的路径；
- fire-and-forget 任务、静默空结果和页面级直接覆盖；
- 4,000 行级巨型 extractor 或其他难以独立测试的单体模块；
- `project_path` 类开放文件系统 API、开放 CORS、桌面剪藏、Deep Research 等非 MVP 能力。

“不整体迁移”不等于禁止复用其中任何代码，而是必须先拆出单一职责、稳定接口和可独立验证的组件。

## 4. Provenance 台账

仓库内为每项迁移保存最小台账：

```yaml
migration_id: MIG-XX
source_repository: silvielala412-lab/LLM-wiki-black
source_branch: feature/product-catalog-domain
source_commit: <immutable sha>
source_paths: [<path>]
source_language: typescript
rights_status: project-owned
target_openspec: <NNN>
target_paths: [<path>]
target_language: python
translation_method: behavior_port_with_characterization_tests
accepted_behaviors: [<behavior id>]
rejected_behaviors: [<behavior id>]
approved_by: <project owner>
approved_at: <timestamp>
```

第三方资产必须使用自己的 `rights_status/license`，不得继承 `project-owned`。对 nashsu、WeKnora 或其他依赖的许可证判断，与 LLM-wiki-black 第一方权利声明严格分开。

## 5. 生产准入仍然存在

第一方权利已确认不代表历史代码自动达到生产质量。任何迁移能力进入生产仍须：

- 对应 OpenSpec 与条款级测试；
- 生产只依赖批准的 MiniMax/Qwen/Qwen-VL 级弱模型；
- Evidence 引文回验、三态和跨产品污染门禁；
- ChangeSet/Conflict/ReviewItem，不直接写 Wiki；
- 持久 Attempt/Alert，失败不伪装成功；
- 授权人批准完整 ReleaseManifest hash；
- 人和 Agent 读取同一 ReleaseSnapshot；
- 固定 MVP Golden Slice 非退化。

生产禁用如果仍存在，应明确写成“缺 OpenSpec/质量/模型/发布门禁”，不得再错误归因于 LLM-wiki-black 第一方权利未决。

## 6. 审查清单

- [ ] 来源是第一方还是第三方已明确；
- [ ] 第一方迁移记录了 source commit/path 与目标路径；
- [ ] 领域实现已收敛到 Python Harness，未新增 Node/TS 生产服务或双写状态；
- [ ] 第三方许可证没有被第一方声明覆盖；
- [ ] 迁移能力被拆成 Python Harness 单一职责组件；
- [ ] 未把保险业务逻辑写进 WeKnora Go/Vue；
- [ ] 未绕过 Claim/Evidence/ChangeSet/ReleaseSnapshot；
- [ ] 旧系统的静默失败、双审核、页面即事实库和单体耦合没有被带入；
- [ ] Golden Slice 与真实多文档 E2E 证明了迁移后的能力，而不只是单测数量。

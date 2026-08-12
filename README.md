# InsuranceKB —— 寿险企业级知识平台（WeKnora 底座 + AI 知识编译 Harness）

> 把散落在产品说明书、条款、FAQ、培训材料里的寿险知识，**编译**成原子化、有版本、可溯源、可进化的知识体系——既供 Agent 精准调用，也供人像维基百科一样阅读与审核。
>
> 本仓库同时是一个**企业级 Harness Agent 示范项目**：文档驱动（SDD）、测试驱动（TDD）、人机协作规范齐备，任何人/任何 AI 会话都能随时接手。

> [!IMPORTANT]
> **唯一当前执行入口。** 开工必须先读 [`AGENTS.md`](AGENTS.md)，再按其中的
> 唯一阅读序列进入适用 ADR、Amendment、`HANDOFF.md` 与 OpenSpec。下文保留的
> 2026-07 架构层级、P-1、`ReleaseSnapshot`、`CurrentRelease`、Projector 和旧
> publisher 描述均为 `HISTORY-ONLY` 背景，不构成独立当前权威或实现授权。

## 要解决的问题

| 痛点 | 本项目的答案 |
|---|---|
| 知识入库即"死"，规则变了没人更新，口径冲突无人裁决 | 增量合并引擎：新材料补全旧知识，冲突按**固定六步**（身份→来源信任→可靠时间→Evidence→多弱模型建议→人工）处理并全程留痕；模型不能冒充裁决人 |
| 更新错了无法回退 | Claim 版本链 + 不可变变更集 + release 快照，**回滚=切指针**（类 git） |
| 弱模型抽取不准、失败即丢 | 模板优先的多弱模型 Harness：引文回验、三态、定向补漏、共识、断点续跑；**2026-07-12 三产品旧基线**的 evidence 准确率为 100%，不代表 020/生产全量结果，最新以批准 baseline 为准 |
| 答得对不对平台不知道、缺口不可见 | 金标评估体系（换模型跑同一套分数）+ 字段完整度矩阵 + 同类产品对比缺口 + 问答反馈飞轮 |
| 知识只给机器用，人没法审 | WeKnora Wiki 阅读界面 + 审核工作台 + "在线问诊"式概念页与义项（一个概念跨多产品） |

完整需求对账见 [`docs/insurance-kb/15-solutions-traceability.md`](docs/insurance-kb/15-solutions-traceability.md)。

## 设计思想（五条）

1. **Enterprise LLM Wiki 是产品本体**（Karpathy LLM Wiki 范式）：知识不是检索时临时拼的 chunk，而是经治理持续编译、由人最终审核、供人和 Agent 共用的持久制品；
2. **缩小模型的战场**：凡确定性可得的绝不让模型碰——数字走表格列直取、产品对齐走备案文号锚点、校验走字符串回验；弱模型只做真正需要语言理解的部分（这是弱模型达到好效果的第一性原理）；
3. **三态语义**："文档没写"≠"不存在"（present / absent_explicitly / unknown），豁免类字段的正确性根基；
4. **一切可追溯**：每个值带证据（页码+原文引文+来源权威等级+抽取方式），引用断链即拒绝发布；
5. **插件式架构**：WeKnora 平台原样跟随开源上游（补丁≤3 且提 PR 回上游），全部保险能力在旁路 Python Harness——永远可跟版升级。

## 架构

```
原始文档 ──► WeKnora（企业平台/权限/解析/chunk/检索/页面载体）   ◄── 官方上游，零侵入
                │ REST
                ▼
        harness/（可恢复的企业知识编译运行时）
        模板路由 → 多弱模型Agent → 证据/校验 → Claim/ChangeSet → 人工门禁
                │
                ▼
        Enterprise LLM Wiki（产品/概念/FAQ/关系/版本/change log）
        → P-1 原子激活 WeKnora release namespace + 同快照 MCP → 人 / Agent
```

插件边界与历史架构背景见
[`docs/insurance-kb/02-architecture.md`](docs/insurance-kb/02-architecture.md)，
这些链接只提供上下文；当前执行入口与阅读顺序仅以 [`AGENTS.md`](AGENTS.md)
为准。
[`13-blueprint-status.md`](docs/insurance-kb/13-blueprint-status.md) 只作历史建设账本。

## 快速开始

```bash
./scripts/install.sh          # 一键安装：检查依赖→装 uv→装 harness→起数据库→跑测试
```

之后按 [`docs/insurance-kb/14-deployment-runbook.md`](docs/insurance-kb/14-deployment-runbook.md) 起 RAW、ACL 隔离 STAGING 与目标 Wiki 的分阶段环境。P-1 前只跑 L1～L3 + L4-pre/L5-pre，禁止目标 Wiki UI/RAG/Agent；P-1 + P-3 后才跑 L4-post～L6。模型/平台凭据配置见 `harness/.env.example`。

## 我该读什么

| 你是谁 | 入口 |
|---|---|
| 想 5 分钟了解项目 | [`docs/insurance-kb/00-project-overview.md`](docs/insurance-kb/00-project-overview.md) |
| 接手开发（人或 AI 会话） | 先读唯一必读/贡献规范 [`AGENTS.md`](AGENTS.md)，再按其阅读序列进入 [`HANDOFF.md`](HANDOFF.md) 与对应 OpenSpec |
| 想懂知识模型/抽取原理 | docs 03 / 04 / 05 |
| 排期与协作 | docs 16（Roadmap）/ 17（三人分工）/ 18（AI 协作机制） |
| WeKnora 平台本身 | 上游文档 [`README_CN.md`](README_CN.md)（本 fork 保持零分岔跟随 [Tencent/WeKnora](https://github.com/Tencent/WeKnora)） |

## 状态（2026-07）

- 基线：`main@1b057869` 的本地 deterministic 门禁为 **2706 passed / 30 deselected**，Ruff 与 mypy 全绿；精确 CI/live 边界见 `HANDOFF.md`；
- 关键路径：`NS-RIGHTS=recorded`，LLM-wiki-black 第一方权利已确认；当前真实运行门禁是 `NS-0=verified ∧ applicable admission=READY`。020 admission 仍 **BLOCKED**，但不阻塞独立 030 MVP slice 的规划和软件工作；
- 可并行：按 23 号 MVP 控制板推进 027～032 与 030 数据冻结；routing/cleaning/004/006/024 可作为第一方迁移输入，但须经 provenance、Python Harness 重构、OpenSpec/TDD 与 Golden Slice 后才可进入生产；
- 产品目标：按[北极星设计](docs/superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)将现有治理地基收敛为完整 Enterprise LLM Wiki，而不是把局部规格或平台组件误报为产品完成。
- 发布阻断：P-1 release namespace/active alias 尚未实现；完成 live 契约前，WeKnora 生产 Wiki UI 必须 fail closed，现有逐页发布能力只算 staging 地基。

## 许可证

WeKnora 上游按 MIT 管理。`LLM-wiki-black/feature/product-catalog-domain` 已由项目权利人确认为项目方完整著作权资产，不需要 clean-room：可完整阅读、审计并把其 TypeScript 能力迁移/重构到统一 Python 3.12 Harness。每项迁移仍须记录 source commit/path，并通过新 OpenSpec、TDD、Golden Slice 与生产门禁；这是架构和质量要求，不是权利隔离。`nashsu/llm_wiki` 与其他第三方代码继续按各自许可证和兼容决定单独管理，详见 [docs 06](docs/insurance-kb/06-asset-migration.md)。

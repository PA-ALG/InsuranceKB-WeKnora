# InsuranceKB —— 寿险企业级知识平台（WeKnora 底座 + AI 知识编译 Harness）

> 把散落在产品说明书、条款、FAQ、培训材料里的寿险知识，**编译**成原子化、有版本、可溯源、可进化的知识体系——既供 Agent 精准调用，也供人像维基百科一样阅读与审核。
>
> 本仓库同时是一个**企业级 Harness Agent 示范项目**：文档驱动（SDD）、测试驱动（TDD）、人机协作规范齐备，任何人/任何 AI 会话都能随时接手。

## 要解决的问题

| 痛点 | 本项目的答案 |
|---|---|
| 知识入库即"死"，规则变了没人更新，口径冲突无人裁决 | 增量合并引擎：新材料自动补全旧知识、冲突按**六级权威序**自动裁决并全程留痕，兜底人工审核 |
| 更新错了无法回退 | Claim 版本链 + 不可变变更集 + release 快照，**回滚=切指针**（类 git） |
| 弱模型抽取不准、失败即丢 | 八步抽取管道：引文回验（对不上原文即打回）、三态判定、定向补漏、高风险投票、断点续跑——**evidence 准确率实测 100%** |
| 答得对不对平台不知道、缺口不可见 | 金标评估体系（换模型跑同一套分数）+ 字段完整度矩阵 + 同类产品对比缺口 + 问答反馈飞轮 |
| 知识只给机器用，人没法审 | WeKnora Wiki 阅读界面 + 审核工作台 + "在线问诊"式概念页与义项（一个概念跨多产品） |

完整需求对账见 [`docs/insurance-kb/15-solutions-traceability.md`](docs/insurance-kb/15-solutions-traceability.md)。

## 设计思想（五条）

1. **编译式知识层**（Karpathy LLM Wiki 范式）：知识不是检索时临时拼的 chunk，而是编译好的、LLM 全权维护、人可审核的持久制品；
2. **缩小模型的战场**：凡确定性可得的绝不让模型碰——数字走表格列直取、产品对齐走备案文号锚点、校验走字符串回验；弱模型只做真正需要语言理解的部分（这是弱模型达到好效果的第一性原理）；
3. **三态语义**："文档没写"≠"不存在"（present / absent_explicitly / unknown），豁免类字段的正确性根基；
4. **一切可追溯**：每个值带证据（页码+原文引文+来源权威等级+抽取方式），引用断链即拒绝发布；
5. **插件式架构**：WeKnora 平台原样跟随开源上游（补丁≤3 且提 PR 回上游），全部保险能力在旁路 Python Harness——永远可跟版升级。

## 架构

```
原始文档 ──► WeKnora（解析/chunk/检索/权限/Wiki界面/Agent）      ◄── 官方上游，零侵入
                │ REST
                ▼
        harness/（Python 插件，本项目主体）
        分类路由 → 抽取管道(模板fastpath) → Claim落库 → 增量合并/权威序裁决
        → 审核门禁 → 页面编译 → 发布回 WeKnora Wiki → 快照/回滚
        配套：金标评估 · 审核工作台 · 健康度巡检 · 反馈飞轮 · MCP工具
```

详见 [`docs/insurance-kb/02-architecture.md`](docs/insurance-kb/02-architecture.md)（含 ADR 与硬边界）与 [`13-blueprint-status.md`](docs/insurance-kb/13-blueprint-status.md)（建设现状）。

## 快速开始

```bash
./scripts/install.sh          # 一键安装：检查依赖→装 uv→装 harness→起数据库→跑测试
```

之后按 [`docs/insurance-kb/14-deployment-runbook.md`](docs/insurance-kb/14-deployment-runbook.md) 起 WeKnora 双知识库并跑 L1~L6 联调。模型/平台凭据配置见 `harness/.env.example`。

## 我该读什么

| 你是谁 | 入口 |
|---|---|
| 想 5 分钟了解项目 | [`docs/insurance-kb/00-project-overview.md`](docs/insurance-kb/00-project-overview.md) |
| 接手开发（人或 AI 会话） | [`HANDOFF.md`](HANDOFF.md) → 认领任务 → 对应 `openspec/changes/` 的 specs（AI 会话自动加载 `CLAUDE.md` 约定） |
| 想懂知识模型/抽取原理 | docs 03 / 04 / 05 |
| 排期与协作 | docs 16（Roadmap）/ 17（三人分工）/ 18（AI 协作机制） |
| WeKnora 平台本身 | 上游文档 [`README_CN.md`](README_CN.md)（本 fork 保持零分岔跟随 [Tencent/WeKnora](https://github.com/Tencent/WeKnora)） |

## 状态（2026-07）

- 代码：openspec change 001~007 已交付（**239 tests 全绿**）——端到端主链（文档→抽取→合并→审核→发布→回滚）打通，真实弱模型基线已出（deepseek-v4-flash vs 金标）；
- 设计：change 008~015 条款级 specs 就绪待认领；设计文档 00~18 闭合；
- 待办：见 `HANDOFF.md` ⓪-B 遗留清单（认领制）。

## 许可证

WeKnora 上游为 MIT。`harness/` 与 `docs/insurance-kb/` 为本项目自有代码与文档。参考项目 nashsu/LLM-Wiki（GPL-3.0）仅借鉴思想未复制代码（合规说明见 docs 06）。

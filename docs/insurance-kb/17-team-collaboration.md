# 17 · 三人协作规范与分工

> 目标：三个人并行推进不踩脚、不偏航、任何时刻可互相接手。本文与 10（SDD/TDD 开发规范）配套：10 讲"一个变更怎么做"，本文讲"三个人怎么一起做"。

团队共同拥有一个产品目标：**Enterprise LLM Wiki 是本体，WeKnora 是底座，Harness 是编译运行时。** 模块 Owner 不能只对目录负责，也必须对其改动是否推进[北极星设计](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)中的 Wiki 闭环负责。

## 1. 分工（按模块所有权切，不按里程碑切）

| 角色 | Owner 模块（代码目录） | 负责的 change/遗留 | 特质要求 |
|---|---|---|---|
| **A · 平台与主链** | `knowledge/`、`adapters/weknora/`、`workbench/`、`migrations/`、部署（compose/CI） | B10 部署联调、B8 工作台、B16 批量调度、B5 上游 Issue/PR | 熟 DB/后端，懂 WeKnora 侧 |
| **B · 抽取与评测** | `compiler/`（含 templates）、`goldenset/`、`schemas/` | B1 金标收尾、B2/B3/B4 基线与裁决、B6/B7 提准迭代、B9 表格识别 | 懂 LLM 工程与评测，对分数负责 |
| **C · 知识运营与集成** | `product/`（共享）、直入/概念/QA/飞轮/MCP 新包 | B12 结构化直入、B11 概念层、B14 QA、B17 飞轮、B15 MCP | 懂业务语义，对知识质量负责 |

规则：
- **动别人的 Owner 目录必须该 Owner 审核**（PR 评审的硬规则）；共享文件（pyproject/config.py/prompts）任何人改都要在 PR 描述里点名声明；
- Owner 缺位时代理顺序 A↔B、C→A（避免决策悬空）；
- 分工是所有权不是围墙——鼓励跨模块提 PR，但合并权在 Owner。

## 2. Git 与变更流程

1. **一 change 一分支**：`feat/NNN-<change-slug>`，从 **`main`**（当前主干，基础建设已随 PR #1 合入，2026-07-16 修正旧口径）切出；禁止直接推主干；开工前先在 `openspec/changes/README.md` 注册表占号（change 号与迁移号）；
2. PR 必须包含：对应 openspec change 的 specs 条款 → 测试映射说明、门禁截图/输出（ruff+mypy+pytest 全绿）、HANDOFF 更新（若改变状态）；
3. **评审双查**：功能由模块 Owner 查；**边界纪律任何评审者都查**（见 §4 清单）；两人 approve 才合（3 人团队=另外两人至少一人 approve + Owner approve，Owner 自己的 PR 由另两人之一 approve）；
4. 合并即推送远端；每次合并后合并者负责确认 CI 绿；
5. 上游 WeKnora 跟版（02 §8 版本列车）由 A 发起，全员参与金标回归确认。

## 3. 节奏与同步

- **HANDOFF.md 是唯一实时同步事实源**：每合并一个 PR、每领一个任务包，当事人只更新 MVP-0 控制板的一行、blocker 或证据链接；[23-mvp-control-board](23-mvp-control-board.md)保存冻结范围/任务拓扑，不复制实时 checkbox；
- **认领制**：遗留清单 B 项在表上写名字即认领；一人同时在途 ≤2 项；卡住超 2 天必须在 HANDOFF 记卡点（可被接手是纪律不是羞耻）；
- 里程碑（16）收尾三件事：更新 13/15 状态、金标回归、全员 review HANDOFF 坑清单有无新增。

总体规划会话只做范围、编号、依赖、任务分发、PR/validation report 检查和最终验收，不写功能代码、不跑完整测试。执行会话拥有自己的文件域；评审会话只提交完整 finding，修复退回原 Owner。

PR 目标是一个验收结果、5–12 个文件、300–800 行生产代码；超出要拆分或在 proposal 中写明不可拆原因。每个 PR 记录 design/coding/focused-test/review-wait/rework/full-CI/live 七段时间，不能用 created→merged 代替开发工时。

## 4. 主航道守护（评审必查清单）

- [ ] proposal/PR 明确写出推进 C1–C7 中哪项 Enterprise LLM Wiki 能力；纯平台工作说明其不可替代的 Wiki 前置价值；
- [ ] 保险逻辑进 Go/Vue = 0；WeKnora API 细节只出现在 `adapters/weknora/`（02 §3 五条硬边界）；
- [ ] 新功能对应 openspec change？无 change 的代码不收（SDD 铁律，10 §1）；
- [ ] 权威顺序固定为：**北极星设计** → 已批准 OpenSpec 条款 → 02/03/04/05/11 → master backlog；发现冲突时先按该顺序修订设计/规格再改码，PR 附文档 diff；
- [ ] 三态语义（unknown≠不存在）、证据回验、dry-run 默认——三个高频翻车点；
- [ ] 人和 Agent 读取同一 ReleaseSnapshot；RAW 只作证据/标注兜底，不覆盖已发布 Wiki；
- [ ] 发布路径以 P-1 WeKnora active alias 为 serving commit，MCP 核对 alias/批准 hash；P-1 前只写隔离 staging，禁止生产 Wiki UI；
- [ ] 所有语义变更都经过 SourceRevision → Claim/Evidence → ChangeSet/Revision → snapshot manifest；禁止直接编辑/生成 Wiki 绕过治理；
- [ ] 每个生产 ReleaseSnapshot 都有该 Space 授权人的最终批准，批准绑定完整 content hash；低风险自动化、模型共识或模板达标都不能替代；
- [ ] 生产只依赖弱模型；模板失效、无共识、证据断链、预算/重试耗尽有可认领 Alert，且默认阻断不安全发布；
- [ ] 结构化直入没有借“跳过解析”绕过来源、ChangeSet、冲突、版本与审核；
- [ ] LLM-wiki-black 第一方迁移记录 source commit/path 与目标落点；nashsu/WeKnora/其他第三方许可证单独管理，第一方声明不覆盖第三方实现；
- [ ] 大批量模型调用（>10万 token）动工前必须 `NS-RIGHTS=recorded ∧ NS-0=verified ∧ applicable admission=READY`，另有 HANDOFF 预算、业务确认、签名/provenance/不可变身份/provider probe 与适用预算硬上限/账本并运行时复验；nohup 不构成授权；
- [ ] 金标/评测口径变更 = 全员知会（分数是公共语言，尺子不能悄悄换）。

## 5. 决策与升级路径

- 技术分歧：先查权威文档 → 文档没写的开 15 分钟三人会拍板 → 结论以 ADR 形式进 02 或对应文档（模板见 02 ADR-001）；
- 业务口径问题（字段含义/权威序/风险等级）：C 汇总后统一问业务方，避免三人各自打扰；
- 涉及架构边界（三条硬纪律）的例外：**必须业务方批准**，不允许团队内部豁免。

## 6. 新成员/新会话接入（含 AI 会话）

阅读顺序：北极星设计 → 00 → HANDOFF → 15（七类核心问题）→ 认领 B 项 → 按对应 change 的 specs 开工。AI 执行会话同样遵守本文（历史上 001~007 即按此模式由 AI 会话交付，验收标准无双轨）。

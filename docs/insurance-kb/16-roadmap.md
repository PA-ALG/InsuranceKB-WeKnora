# 16 · Roadmap（里程碑与关键路径）

> 与 13（蓝图现状）配套：13 讲"建到哪了"，本文讲"接下来按什么顺序建、每一站的完成定义"。排期按里程碑不按日历（团队自行映射到周）。**并行轨道结构与分工见 22（并行执行蓝图）**。

## M0 · 企业运行基础（当前里程碑）

**目标**：先消除“本地验证链 ≠ 企业生产链”，让租户隔离、WeKnora 来源、Evidence 血缘、发布快照与 Golden Gate 成为不可绕过的基础。

| 事项 | Change | 完成定义 |
|---|---|---|
| KnowledgeSpace 与 tenant/双 KB 强制作用域 | 016 | 双租户同业务键互不影响；legacy bind；跨空间 fail closed |
| WeKnora SourceDocument Bridge | 017 | upload→parse→download/chunks→compiler；Evidence 带 source revision/page/chunk |
| SnapshotFact 与统一在线读取 | 018 | Wiki/MCP 同快照；失败不移动指针；补偿精确恢复 |
| Golden 工具与自动发布质量闸门 | 019 | portable validator/profile；默认不自动 supersede；回归失败不能批准 |
| gs-v0.1 与 13 产品真实基线 | 020 | run-admission 后 13/13、裁决/死信/keypoints/approved profile 齐 |
| Source lifecycle ordering | 021 | durable current head；不同 revision 乱序/并发和 import/delete 竞争由统一 lock/CAS 裁决 |

**当前排期与硬依赖（业务方 2026-07-14 裁决）**：合并后收尾优先；随后 018 与 019 无相互前置，可独立或并行推进，019 是解锁真实基线的工具轨，价值优先级不低于 018。硬依赖为 018 → 021、019 → 020、021 → 020；020 在 019、021 均完成后先执行自身 T1 run-admission。021 不阻塞 T8 live 验收，但阻塞不同 revision 并发开放。

进度（2026-07-15）：016 与 017 软件已完成；017 的受控 WeKnora live 仍无运行证据。018 已完成不可变 SnapshotFact、pointer-only Reader、frozen renderer、可恢复 publish/rollback/reconciliation 与 curated-first RAW policy；T4 的 PostgreSQL caller-transaction 节点和 T7 的真实 WeKnora V1→V2→rollback 节点已纳入互斥 lane，但当前本机 PostgreSQL/受控 live 均为 `NOT RUN`，不能把 collection、skip 或 mock 结果记成 integration/live 成功。019/020 未因此自动完成；021 仍 proposed/pending，尚未实现不同 revision ordering。M0 继续进行，最新精确测试数见 018 validation report 与 HANDOFF。

更新（2026-07-16）：**019 已随 PR #8 合入 main**；**023（本机 live 环境+受信 workflow）已随 PR #10 合入**；018 T1～T6 软件与两轮复审完成（PR #9）、PostgreSQL 16 job 通过，T7 真实 live 凭据已补齐、收口中；021 仍 pending。多轨并行拆分（008/010/013/024 就绪）见 22 号蓝图与 HANDOFF ⓪-0h。

## M1 · 可演示闭环

**目标**：给管理层/业务方演示"文档进 → 知识出 → 人可审 → Agent 可用 → 可回滚"的完整故事。

| 事项 | 入口 | 前置 |
|---|---|---|
| WeKnora 双库跑通 + live 契约 + L1~L5 演示脚本 | B10（14 号文档 Runbook） | 无 |
| 结构化直入（存量 JSON/FAQ 变知识） | B12（010，specs 齐） | 007✅ |
| 审核工作台四页 | B8（008，specs 齐） | 007✅ |
| 金标收尾 gs-v0.1（13/13） | 020 D2（承接 B1） | 019 + 021 + 020 T1 run-admission |
| 全量基线 + judge 批处理 + 死信复跑 | 020 D3/D4（承接 B2/B3/B4/B6/B7） | gs-v0.1 |

**完成定义**：L1~L6 演示一条命令跑通；13 产品金标+基线报告齐；工作台可完成一次真实审核与回滚。
**关键路径**：B10 → L6（其余可并行）。

## M2 · 形态完整（wiki 化与运营）

| 事项 | 入口 | 前置 |
|---|---|---|
| 概念层（概念主页/义项/互链/purpose） | B11（009） | 007✅，prompts 改造等 006✅ |
| QA 一等对象 | B14（012） | 010 |
| 知识健康度巡检（含同类对比缺口 H1.6） | B13（011） | 007✅ |
| 数据飞轮（Langfuse 信号→缺口工单） | B17（015） | 007✅、009（概念对齐） |
| insurance MCP server（版本敏感问答） | B15（013） | 007✅ + 018 读模型；**业务方 2026-07-16 拍板提前（轨道 L3）：规格就绪，实现等 PR #9 合入** |
| 上游 3 Issue/PR（乐观锁/webhook/ingest_mode） | B5 | 无 |

**完成定义**：六能力审计（13 §4）全部转 ✅；"在线问诊"式概念页上线；Agent 能答历史版本问题。

## M3 · 规模化与提准

| 事项 | 入口 | 前置 |
|---|---|---|
| 批量并发调度 + 批次控制台 | B16（014） | M1 |
| 抽取提准迭代：漏抽 24 条归因修复 → 基线回归（目标由团队按 v2 分数定阶梯） | B7 + 005 归因工单 | B2 |
| 模板铺开（按族分数立项）+ PP-StructureV3 接入 | B9 + 006 机制✅ | B2（按族数据） |
| 金标要点清单精修 + 第二波险种样本（重疾/护理/补充养老） | B6 + 业务方补样本 | — |

**完成定义**：千份级批次可跑（限流/死信/控制台）；基线分数达团队设定阶梯；第二波险种入库。

## M4 · 智能演进（P2/P3，暂不细排）

领域图谱与洞察、受控 Deep Research、规则可执行化（决策表）、PPTX/音视频/图片多模态——master plan P2/P3 原文有效，待 M2/M3 数据规模触发。

## 恒定原则

- **主航道 = 15 号追踪矩阵的九问 + master plan**：任何新想法先对照"是否服务九问"，是→出 proposal，否→记 idea 不动工；
- 每个里程碑收尾：更新 13（蓝图）与 15（追踪矩阵）状态、跑金标回归、HANDOFF 对账。

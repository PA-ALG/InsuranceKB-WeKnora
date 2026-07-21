# 15 · Enterprise LLM Wiki 核心问题对账（需求→方案→状态）

> 业务方 2026-07-21 明确：Enterprise LLM Wiki 是整个项目核心，七类问题是所有规划、开发与验收的统一追踪轴。产品与架构最高层定义见[北极星设计](../superpowers/specs/2026-07-21-enterprise-llm-wiki-north-star-design.md)；精确实时状态仍以 `HANDOFF.md` 为准。

## 1. 北极星七类核心问题

| # | 核心问题 | 完整能力闭环 | 当前落点（2026-07-21） |
|---|---|---|---|
| C1 | 生产弱模型的准确率、覆盖率与断点恢复 | 模板层级 + 多弱模型 Agent + attempt/checkpoint + 定向补漏 + Evidence/三态/共识 + 告警/人工 | 019 有确定性地基；004/006/024 是可审计第一方迁移输入但当前 production-disabled。先完成 027/028，并由 030 MVP slice 验收；020 企业 baseline 后续另需 admission READY |
| C2 | JSON/产品库/FAQ 直入与知识融合冲突 | 跳过 docreader，但不跳过产品对齐、来源冻结、Claim/Evidence、ChangeSet、冲突和审核 | 010 T1–T4 已合入，T5–T12 knowledge 域可认领；012 QA 等其合同 |
| C3 | 自动校验与人工最终审核 | 确定性校验 + 多弱模型交叉验证 + 可审计 receipt + 风险门禁 + 人工接管 + 每个生产 snapshot 的真人最终批准 | Evidence/QualityGate/Review 基础已落地；NS-B/NS-C 补完整 receipts、Alert、ReleaseApproval 与全 manifest 原子门禁 |
| C4 | 智能文档/险种分类与多产品事实路由 | 文档级分类、章节级模板、事实级产品版本路由、unassigned 隔离、多产品标注回归 | 基础路由已实现；完整分类、混合文档 goldenset、模板自动选择和污染率门禁仍待补 |
| C5 | 更新、删除、change log、版本与回滚 | Source lifecycle + ClaimRevision + 不可变 ChangeSet/decision events + ReleaseSnapshot/Approval lifecycle + P-1 seal/active alias + 制品 pin/GC + 物理 preflight 回滚 | 007/018/021 有历史地基；NS-C 补完整 manifest、批准撤销/到期、Space/KB 一一绑定、namespace seal、retention、Harness receipt/MCP 核对与全制品 E2E |
| C6 | 产品仪表盘、质量、缺口与 Schema/Template 工作台 | 产品全貌、完整度/质量分、批量补全、schema/prompt/template 预览编辑、草案生成与回归 | 008 审核面已有核心；011 可认领；完整产品 Dashboard 与 TemplatePackage Workbench 由 NS-E 待正式登记 |
| C7 | 百千文档并发、冲突与合并 | 三级任务、产品版本分片、五级限流、lock/CAS、dead letter、批次控制台和成本 | 021 提供来源顺序基础；014 仍待正式实现，触发条件前需先完成容量与一致性规格 |

共同验收：人和 Agent 必须消费 WeKnora P-1 active alias 指向且经真人批准的同一 ReleaseSnapshot，MCP 核对 alias/批准 hash；P-1 前生产 Wiki UI fail closed。RAW 只能作证据/显式低保证兜底且不能覆盖 Wiki；模板或模型效果不足时必须告警并停止候选推进。生产不得依赖强模型是目标硬约束，但 NS-0 完成前运行时尚未封死，所以真实生产一律禁止；任何自动化均不能替代 release 级授权批准。

## 2. 2026-07-12 历史九问映射

以下表保留原九问的设计与证据映射，用于追溯；它不是当前完成状态的替代品。

| # | 业务问题 | 方案要点 | 状态与证据 |
|---|---|---|---|
| 0/7 | 几十万碎片（FAQ/PPT/片段）准确关联到已有 wiki；相似实体名易错；冲突采信（自证溯源，兜底人工） | **四级关联漏斗**：备案文号/planCode 精确锚点 → 别名表 → 模糊候选进 unassigned → 人工确认。**冲突固定六步**：产品/版本身份→来源 trust/authority→可靠时间→Evidence→多弱模型 receipts→人工，全留痕可翻案 | 003/007 已有局部 E2E；千份级由 NS-F/正式化 014；规则权威见 03 §6 |
| 1 | 弱模型（qwen3.6/minimax2.5 级）稳定抽取+校验机制 | 短任务、引文回验、类型/跨字段校验、定向补漏、多弱模型独立尝试与 extras 候选；可确定读取的表格值优先走独立规则 | 004/006 只有第一方历史证据；027/028/适用 admission 未通过前不得真实运行。MVP 只认 030 批准 slice；完整运行时在 M2 扩展 |
| 2 | 识别缺口（基于关联、对比 schema、相似产品） | 三信号源：schema 填充率矩阵（供给侧盘点）+ **同类产品对比**（同险种多数 present 而它 unknown → 疑似缺口，011 H1.6）+ 问答反馈（需求侧，015 Langfuse 飞轮） | ✅ 数据能力（005 归因/completeness）；📋 011 H1.6 + 008 仪表盘 + 015（B13/B8/B17） |
| 3 | 二三批材料自动补全+更新+发现冲突 | 增量合并五种 ChangeItem（add/enrich/supersede/conflict/retract），unknown 被高权威新批补全，矛盾自动裁决或停审核 | ✅ 007 端到端测试：条款批补全说明书批、冲突采信条款留痕、高风险停审核 |
| 4 | 类 git 版本与回退到指定版本 | Claim revision 链 + 不可变 ChangeSet/event + ReleaseSnapshot/Approval + 指针回滚；Claim/Wiki/QA/关系/目录/MCP/索引同一快照 | 007/018 有地基；NS-C 补完整制品与真人批准后做全链 E2E |
| 5 | 对人友好、真实 wiki 形态；概念（如"在线问诊"）多义项页 | 目标阅读=带 P-1 active release 的 WeKnora Wiki；P-1 前=Harness current-release reader；**三层页面**：概念主页/义项索引/产品限定子页；审核=008 工作台 | 007 只有产品页/旧发布地基；009、NS-C/P-1 与安全阅读路径均未完整交付，不能标生产 Wiki ✅ |
| 6 | 几十万片段不全量编译；模板保证效果；schema 防乱抽也防自缚 | 优先级驱动编译；四级 TemplatePackage 由确定性统计/生产弱模型/人工产生草案，失配按固定阶梯降级并 Alert；schema 外字段走 extras 候选 | 006 只交付族级 fast-path enabler，不能冒充完整模板；NS-A/NS-B/NS-E 分别补 registry/runtime/workbench |
| 8 | golden set：离线可插拔标注、支持换模型评估 | 独立离线金标（模型/人工候选+引文回验+disputed≤5%+不可变 release）+ 只消费冻结 comparator artifact 的 eval runner | 019 工具已完成；020 T1 软件已合入但 canonical admission 仍 BLOCKED；030 使用独立 MVP admission。027+适用 admission 前零模型、不得报告真实基线；强模型不是生产/CI 实时前置 |

**历史结论（2026-07-12）**：当时九问均已有方案，六问已有局部实现证据，三问设计到条款级。2026-07-21 起不得把“已有方案/局部测试”表述为 Enterprise LLM Wiki 已完整交付；以本页七类核心问题、HANDOFF 实时状态和端到端验收故事共同判断。

关联：[13-blueprint-status.md](13-blueprint-status.md)（蓝图与六能力审计）· [01-requirements-and-challenges.md](01-requirements-and-challenges.md)（原始需求全集）· HANDOFF ⓪-B（遗留清单）

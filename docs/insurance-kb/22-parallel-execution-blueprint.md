# 22 · 并行执行蓝图

> 本文定义“谁做什么、哪些可以并行、哪些必须串行”。稳定里程碑见 [16-roadmap.md](16-roadmap.md)，冻结 MVP 范围见 [23-mvp-control-board.md](23-mvp-control-board.md)，实时进展以 `HANDOFF.md` 的 MVP-0 控制板为准。
> 当前原则：**总体规划会话不写功能代码；一个 OpenSpec/PR 一个独立执行会话；评审会话不修代码。**

## 1. 当前事实

- 现有底座：001～008、015～019、021、023、024 有软件落点；010 只有 T1～T4；013 MCP 只有占位；020 只有 admission 软件且 13 产品 canonical run 仍 BLOCKED。
- 业务方已批准 Integration-first MVP：23 来源、5 产品、7–10 工作日。
- LLM-wiki-black 第一方权利已记录，可选择性迁移；第三方许可证继续单独管理。
- 当前真实运行前置：027 NS-0 verified + 030 MVP admission READY。P-1 与完整 020 不阻塞 MVP。
- 迁移号与共享 DB 域只能串行；其余按文件域并行。

## 2. 会话拓扑

| 会话 | 职责 | OpenSpec/计划 | 独占文件域 | 禁止修改 |
|---|---|---|---|---|
| **G · 总体规划/验收** | 范围、编号、依赖、任务卡、状态、PR/报告检查、最终放行 | 23 控制基准 + 本轮 plans | `docs/insurance-kb/{06,13,16,17,18,21,22,23}`、`HANDOFF.md`、注册表 | 所有功能代码；不跑重测试 |
| **S0 · Model Gate** | 生产弱模型硬门禁 | 027 | `config.py`、模型/CLI/judge/fallback 入口及 027 tests | `knowledge/`、`structured_import/`、`mcp/`、`workbench/` |
| **S1 · Template/Runtime** | TemplatePackage、可恢复 CompilationJob/StageRun/Attempt/Receipt/Alert | 028 | 新 `template_packages/`、新 `runtime/`；compiler 仅最小 adapter | `knowledge/`、`mcp/`、`workbench/` |
| **K0 · Release Authority** | ReleaseManifest、完整 hash 真人批准、CAS CurrentRelease、逻辑回滚 | 029 | `knowledge/`、029 migration/tests | compiler/runtime/MCP/workbench |
| **K1 · Structured Thin** | 已知 schema product_meta/FAQ 直入完整治理链 | 010 MVP 子集 | `structured_import/`；经批准的 knowledge 接线；010 migration/tests | runtime/MCP/workbench |
| **M0 · Agent Reader** | MCP core 只读工具与 snapshot/hash envelope | 013 core | `mcp/`、MCP tests | `knowledge/`、compiler/runtime |
| **M1 · Human Reader** | 独立只读产品 Wiki，与 MCP 共用批准快照 | 032 | 新 `human_reader/`、032 tests | `knowledge/`、`mcp/`、`workbench/` |
| **I0 · Slice/Data** | 23-source manifest、fixtures、MVP admission | 030 T1–T3 | 新 `dataset/mvp-*`、030 artifacts/tests | 所有生产模块 |
| **I1 · Integration QA** | 真实主链、更新/冲突/告警/同快照/回滚验收 | 030 T4+ | 新 E2E tests/runbook/validation report | 发现功能问题只退回原 Owner，不直接修 |

### 总体规划会话保留的统一权

1. OpenSpec 与迁移号分配；
2. 跨包 contract 裁决；
3. 合入顺序和 integration baseline；
4. MVP/企业里程碑最终放行。

执行会话不得顺手修改 `HANDOFF.md` 大段历史，只更新自己的控制板一行和证据链接；若改共享契约，先由 G 建立独立小 change。

## 3. 依赖与并行波次

```text
NS-RIGHTS recorded ✅
        │
        ├─► 027 Model Gate ─► 028 Template/Runtime ─┐
        │                                           │
        ├─► 029 Release Authority ─► 010 thin ──────┼─► 030 Integration/E2E
        │                                           │
        └─► 013 MCP core ─► 032 Human Reader ──────┘

030 source manifest/fixtures 可从 Day 1 开始；真实模型 run 等 027 + MVP admission READY。
```

### Wave 0 · 规划与占号（G，当前）

- 登记 027～030 与 032；031 保留给既有 operational admission；
- 产出七份可独立认领的实施计划；030 计划内含跨包验收矩阵；
- 独立 reviewer 复核计划；
- 不写功能代码。

### Wave 1 · 小 PR 建合同（Day 1–3）

- S0：027，先封模型入口；
- K0：029 的模型/服务合同与 migration RED；
- M0：013 core 基于 SnapshotReader protocol/fake 开发；
- I0：固定 23-source manifest/hash、混合文档/更新/FAQ fixture。

027 与其他包文件域不相交，可并行；K0 是唯一迁移 Owner。

### Wave 2 · 主能力实现（Day 3–5）

- S1：027 合入后实现 028；
- K0 → K1 串行：029 后实现 010 thin；
- M0 与 M1 共享 029 serving contract：013 core 与 032 可并行，最后做同快照 contract integration；
- I0 只跑零模型 admission/fixture contract。

### Wave 3 · 合流与真实运行（Day 5–8）

- 从当时最新 main 建 integration worktree；
- 只由 I1 写跨包 E2E 和报告；
- 功能失败分别退回 S/K/M Owner；
- 027 + MVP admission READY 后才调用真实弱模型；
- 验收 23 来源、更新、冲突、Alert、hash 人审、同快照和回滚。

### Wave 4 · 独立验收（Day 9–10）

- 规格 reviewer 一次性检查所有条款/退出条件；
- 质量 reviewer 检查跨包数据流、权限、模型边界和同快照；
- 各 Owner 修复自己文件域；
- 只在 PR ready 跑一次完整 deterministic，CI 独立复跑；
- G 根据实际七段时间决定放行并重估 M2。

## 4. PR 列车与合入顺序

推荐 8–10 个小 PR，而不是 3 个大 PR：

1. 027 模型硬门禁；
2. 029 ReleaseManifest/Approval 合同与迁移；
3. 013 MCP core；
4. 030 source manifest/fixtures/admission；
5. 028a TemplatePackage；
6. 028b Compilation runtime/orchestrator；
7. 010 thin structured path；
8. 032 Human Reader；
9. 030 E2E contracts；
10. 必要时单独 integration wiring/closeout。

约束：

- 一个 PR 一个验收结果；目标 5–12 文件、300–800 行生产代码；
- 数据库 migration PR 单独且串行，合入前重新确认实际 Alembic head；
- `pyproject.toml`/`uv.lock` 只由一个指定 PR 修改；
- 027 与 028 都可能触及模型/compiler 接线，必须顺序合入；
- 029 与 010 thin 都可能触及 knowledge/迁移，必须顺序合入；
- MCP/Human Reader 只消费公开 serving contract，不得跨域导入 ORM internals；008 workbench 不承担消费型产品页。

## 5. TDD 与测试分级

| 风险级 | 适用 | 每次 RED/GREEN | PR ready | 红队 |
|---|---|---|---|---|
| **A** | 权限、迁移、发布、批准、租户隔离 | 精确测试，目标 ≤90 秒 | focused + 相关 PG + 一次 full deterministic | 定向故障矩阵/对抗测试 |
| **B** | 模板、抽取、路由、融合、冲突 | 精确测试 + 小 Golden Slice | 领域套件 + 一次 full deterministic | 只攻高风险不变量 |
| **C** | UI、文档、只读接线 | 契约测试/smoke | focused + CI | 默认不跑通用红队 |

完整 2700+ deterministic 不得在每个小步骤或每轮 review 重复跑。Reviewer 首轮一次性汇总完整发现；第二轮只验关闭；第三轮不继续按条目补丁，由 G 裁决拆 PR、改接口或驳回 finding。

## 6. 每个执行会话的任务卡

任务卡必须包含：

- 目标与明确不做；
- 对应北极星 C1～C7 能力；
- 允许/禁止文件域；
- 输入、输出和稳定接口；
- 弱模型/模板/Evidence/Alert/人审/同快照不变量；
- 2–5 分钟级 TDD checklist 与精确测试命令；
- PR 风险级与全量测试时点；
- validation report 要报告的已验证事实和 NOT RUN；
- 七段时间字段：design/coding/focused-test/review-wait/rework/full-CI/live。

## 7. 会话与 worktree 纪律

- 一个 change/PR 一个独立 worktree，从当时最新 `main` 建 `feat/NNN-*`；
- `.venv`、临时 SQLite、run artifacts 不跨 worktree 共享；
- `.env` 只手工复制到 gitignored 位置，不进入输出和提交；
- 普通命令 60 秒无输出即轮询，10 分钟硬中止；子任务 2 分钟无有效结果转主线程；
- AI 会话不 commit/push，由人验收后操作；
- 规划会话只读代码和验证报告，不运行完整测试；
- I1 集成会话不“顺手修”功能，避免失去文件域 Owner 和根因上下文。

## 8. MVP 后的并行拓扑

M2 再启动：P-1/完整 NS-C、完整 Template registry/runtime、完整 010/013/008、032 扩展、009/012、13 产品 020。M3 再启动：011/014/015、NS-E/NS-F、完整预算与运营。任何 Later 项目不得借“顺手”进入当前 PR。

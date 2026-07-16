# 22 · 并行执行蓝图（轨道拆分与分工）

> 与 16（roadmap，讲**顺序**与里程碑）配套：本文讲**并行结构**——哪些 change 可以同时推进、按什么优先级、由谁执行、靠什么护栏不互相踩。实时进度以 `HANDOFF.md` ⓪ 为准（本文不放 checkbox，避免双份清单漂移）。编号占用以 `openspec/changes/README.md` 注册表为准。
> 制定：2026-07-16（总设计师裁定 + 业务方当日拍板：模型凭据已补齐交 codex 处理、013 MCP 提前、规格工作不等 PR #9）。

## 1. 现状快照（2026-07-16）

- **已合入 main**：001–007（编译主链）、016/017（Space 隔离+来源桥接）、019（质量闸门）、022×2（测试再平衡+复审收口）、023（本机 live 环境+受信 workflow，PR #10）。
- **在审**：018（PR #9，仅剩真实 WeKnora live 证据；凭据已补，codex 处理中）。
- **架构体检结论**：插件式边界零违规（WeKnora API 全封装在 adapters、无直连库/队列、Go/Vue 零污染）；企业地基超额交付；**价值面（工作台/MCP/概念层/QA）零代码**——`workbench/` 与 `mcp/` 均为空壳占位。
- **诊断**：方向未偏，瓶颈是并行度≈1。依赖图允许 5–6 条轨同时推进。

## 2. 轨道拆分（优先级即行序）

| 轨 | 内容（change） | 执行者 | 前置 | 开工条件 | 独占文件域 |
|---|---|---|---|---|---|
| **L0 解阻塞** | 018 live 收口 → PR #9 合并 | codex | 凭据 ✅ | **进行中** | 018 分支 |
| **L1 关键路径** | 021 ordering → 020 真实基线（run-admission → D2/D3/D4） | codex（A 角色） | 018 合并；020 另需 019✅ | PR #9 合并后 | `sources/`+`knowledge/` ordering、迁移 0006；020 = `dataset/` |
| **L2 审核面** | 008 审核工作台 | 会话 C1 | 007/016/019 ✅；仅 W4 等 018 | **即刻**（W4 除外） | `workbench/`（新） |
| **L3 Agent 出口** | 013 insurance MCP | 会话 C2 | 003/007 ✅ + 018 读模型 | 规格已就绪；**实现等 PR #9** | `mcp/`（新） |
| **L4 知识形态** | 010 直入 → 009 概念层 → 012 QA →（011 健康度） | 会话 C3 | 007 ✅；012 依赖 010 | 010 **即刻**；009/012 待基础对齐修订 | `knowledge/import_*`（新）、`concepts/`（新）、QA 模块（新）；迁移 0007/0008/0009 |
| **L5 抽取提准** | 024 recall uplift（005 归因清单主攻） | 会话 B | 004/005 ✅ | **即刻**（零真实模型调用） | `compiler/`（extract/gapfill/prompts） |
| **L6 治理** | 编号注册表、文档对账、已交付 change 归档流程 | 架构会话 | — | 本轮完成 | docs + openspec 元数据 |

延后（不排人）：014 批量调度（M3）、015 飞轮（M2、依赖 009）、B9 PP-StructureV3（部署型）、B5 上游 Issue（人工）。

## 3. 依赖图

```
凭据✅ ─► L0: 018 live ─► PR#9 合并 ─┬─► L1: 021(迁移0006) ─► 020 run-admission ─► 020 D2/D3/D4(真实基线)
                                    ├─► L3: 013 实现开工（规格已备）
                                    └─► L2: 008 W4 回滚页解锁
main(773f3d1) ──► L2: 008 W1–W3 ┐
             ──► L4: 010        ├── 即刻并行，互不依赖，文件域不相交
             ──► L5: 024        ┘
010 ─► 012；009 ─► 015；020 D3 ─► 024 真实回归验证（fixture 回归先行）
```

**唯一串行链** = L0→L1（018→021→020），这是"真实基线"价值出口的关键路径，其余全部旁路并行。

## 4. 合并基线政策

1. 规格/文档：以当前 main 为基，不等 PR #9；
2. 实现：不触碰 `knowledge/` 发布与快照读取路径 → 即刻从 main 开工（008 W1–W3、010、024）；
3. 触碰读模型/回滚/发布语义 → PR #9 合入后从新 main 开工（013 实现、008 W4、021）；
4. 021 的迁移必须排 018 的 `0005` 之后（已预分配 0006）。

## 5. 并行安全护栏（多轨不互踩）

1. **先占号再开工**：change 号与迁移号一律先登记 `openspec/changes/README.md`（022 撞号教训）；
2. **文件域独占**：每轨只写自己的独占目录（上表）；跨域需求（如 010 要在 `knowledge/` 挂导入入口）以"新文件+最小接线"实现，接线点在 PR 描述中显式列出；
3. **共享底座只读**：`adapters/`、`db/base`、`config.py`、既有迁移对所有轨只读；要改共享底座 = 单独小 PR 先行，不夹带在功能 PR；
4. **SDD/TDD 不变**：条款级 spec 先行；**新开 change（024 起）一律用正式 delta 格式**（`specs/<capability>/spec.md` + `### Requirement:`/`#### Scenario:`，须过 `openspec validate <id> --strict`，先例 023/024）；存量轻量规格（008/010/013 等）保持原格式不重写，两种格式下**条款 ID 均必须可被测试名引用**；
5. **复审前自测**：每轨送审前过 `docs/insurance-kb/21-selftest-before-submit.md` 的 gauntlet（019 七轮返工教训）；PR 双查照旧（17 号规范）；
6. **门禁统一**：CLAUDE.md 三件套（ruff/mypy/deterministic pytest）全绿才送审；live 缺环境一律诚实记 `NOT RUN`。

## 6. 里程碑映射

- **M1 可演示闭环** = L1 的 020（真实基线）+ L2 的 008（人可审）+ L4 的 010（存量直入）+ 023 已交付的 live 底座 → L1~L6 演示脚本；
- **M1.5（新增，业务方 2026-07-16 拍板）**：013 MCP 从 M2 提前——它是"给 Agent 用的知识"北极星的第一个真实出口，且只读、风险低；
- **M2** 剩余：009/012/011/015；**M3**：014、B9、024 的真实回归提分阶梯。

## 7. 波次

- **Wave 1（本轮已就绪，可立即认领）**：008（已条款化+基础对齐）、010（已条款化+基础对齐）、013（规格就绪，实现候 PR #9）、024（新开，规格就绪）；
- **Wave 2（待架构会话做基础对齐修订后放行）**：009、011、012（对齐 016 Space/017 lineage/018 读模型的修订条款）；
- **Wave 3（触发条件制）**：014（千份级批量需求出现）、015（009 落地后）、B9（部署资源到位）。

## 8. 认领方式

按 17 号规范在 `HANDOFF.md` ⓪-B 表登记认领人 + 开工分支（`feat/NNN-*` 从 main 切出）；每轨收尾义务照 CLAUDE.md（tasks 勾选+裁决记录 → validation-report → HANDOFF 更新）。

## 9. 并行执行形态（会话与 worktree 配方）

**原则：一个 change = 一个分支 = 一个执行会话 = 一个独立工作目录。** 并行度的上限不是算力，是**复审带宽**（PR 双查 + 21 号自测）；建议从 本机 2 轨 + 远端 1 轨 起步，节奏稳了再加。

三种形态按场景选：

1. **远端会话（codex 等）**：自带隔离环境，从 main 切 `feat/NNN-*`，PR 为唯一同步点——L0/L1 关键路径现状即此，无需改变。
2. **本机多会话 = git worktree（推荐）**：每个认领的 change 一个 worktree + 一个独立 AI 会话，互不共享上下文、互不切分支：

   ```bash
   # 目录并列在主仓旁边，一轨一个
   git worktree add ../ikb-008 -b feat/008-review-workbench origin/main
   git worktree add ../ikb-024 -b feat/024-extraction-recall-uplift origin/main

   # 每个 worktree 独立 venv；.env 是 gitignore 的，须手动带过去（勿提交）
   cd ../ikb-008/harness && uv sync && cp <主仓>/harness/.env .env

   # 每个 worktree 独立跑门禁（deterministic lane 用临时 SQLite，天然可并行）
   uv run ruff check . && uv run mypy src tests && uv run pytest -m "not live and not integration_postgres" -q

   # PR 合入后清理
   git worktree remove ../ikb-008
   ```

   注意：`.venv` 不得跨 worktree 共享（uv 有硬链缓存，重建秒级）；PostgreSQL `integration_postgres` 与 WeKnora `live` lane 只在 CI/受信 workflow 跑，本机不并行；008 工作台本地起服端口自行错开。
3. **同会话子代理（Agent worktree 隔离）**：只适合小粒度机械任务；**整条 change 的 TDD 实施一律独立会话**——spec 级工作需要完整上下文、裁决记录与复审对话。

**共享文件冲突热点**：`HANDOFF.md`（认领/状态行）与 `openspec/changes/README.md`（注册表）是唯二多轨都会碰的文件——每个 PR 只改自己那一行，行级平凡冲突，按合入序 rebase 即解；除此之外各轨文件域不相交（§2 表），worktree 之间零耦合。

# 10 · 开发规范（SDD / TDD / 示范项目标准）

> 本项目是**企业级 harness agent 的示范项目**，后续很多团队会参考它开发。本文是所有贡献者的工作契约：任何人按此文档应能独立开一个变更、写出风格一致的代码、并保证项目随时可被他人接手。

## 1. 文档驱动 + SDD（规格驱动开发）

**铁律：先文档，后代码。** 任何技术方案必须先落文档才允许动手。

变更流程（OpenSpec）：

```
设计讨论 → docs/insurance-kb/ 修订（若影响架构/模型/选型）
        → openspec/changes/<change-name>/
             ├── proposal.md   # 为什么做、做什么、不做什么
             ├── specs/        # 行为规格（可验证的验收条件）
             ├── design.md     # 怎么做（引用 02~08 的设计，不重复）
             └── tasks.md      # 任务拆解与状态
        → 评审通过 → 开发 → 验收对照 specs → 更新 HANDOFF.md
```

规则：
- proposal 必须声明影响面：动了哪个组件（02 §2 职责表）、是否触碰三条硬边界（02 §3）、是否影响 schema/金标版本；
- 设计文档（docs/insurance-kb/）是唯一权威；change 内 design.md 只写增量，与 00~09 冲突时必须先修订权威文档；
- 每个 change 合并时同步更新 `HANDOFF.md`（见 §4）。

## 2. TDD 约定

- **先写测试再写实现**。每个 change 的 specs 直接翻译成 pytest 用例（specs 条目 ↔ 测试函数一一对应，测试名引用 spec 编号）；
- 测试分层：
  | 层 | 内容 | 依赖 |
  |---|---|---|
  | 单元 | schema 校验、清洗正则、裁决序、三态逻辑、解析器 | 无外部依赖 |
  | 契约 | adapters/weknora 的每个 REST 调用（respx mock + 定期打真实测试实例） | WeKnora 测试实例 |
  | LLM 节点 | 用**录制的模型响应**回放测试管道逻辑；真实模型调用只在评估层 | 录制夹具 |
  | 金标回归 | eval runner 跑金标（05），分数不得低于门槛 | 金标 release |
- LLM 的不确定性不进单元测试：管道逻辑用固定夹具测，模型质量用金标评测——**两者严格分离**；
- CI 门禁：ruff + mypy + 单元/契约测试全绿才可合并；金标回归在升级模型/prompt/WeKnora 版本时强制执行。

### 2.1 测试组合证据与重叠审计

测试按依赖分成互斥的三条执行 lane：

| Lane | pytest 选择式 | 合并证据 |
|---|---|---|
| deterministic | `not live and not integration_postgres` | 每个 PR 必跑 |
| PostgreSQL integration | `integration_postgres` | PostgreSQL 16 Actions job，tests > 0 且 skipped = 0 |
| WeKnora live | `live` | 受控 environment 手工 workflow；未运行必须写 `NOT RUN` |

使用 coverage context 检查“多个测试是否执行了大量相同生产代码”，不得按文件行数、异常文案或 passed 数量机械删测试。标准采集与报告命令为：

```bash
cd harness
uv run pytest -m "not live and not integration_postgres" \
  --cov=insurance_harness --cov-context=test --cov-report=
uv run coverage json --show-contexts -o .coverage-contexts.json
uv run python scripts/test_portfolio_audit.py .coverage-contexts.json \
  --threshold 0.8 --minimum-shared-lines 5
```

audit 只消费 `src/insurance_harness/**/*.py`，忽略空/default context，并把 setup/run/teardown 归并为同一个 pytest identity。它固定报告有效 context 数、production line 数、候选数和阈值；解析失败或空证据非零退出，发现候选仍为零退出。候选只触发人工复审：只有输入、public boundary、失败阶段和副作用断言都同构时才可合并。核心 capability 与 consumer 接线/零副作用证明默认属于不同层。

每个 validation report 必须包含以下表格；`passed N` 不能替代风险—证据映射：

| Risk ID | Primary layer | Test node/pattern | Distinct failure surface | Execution lane |
|---|---|---|---|---|
| 示例：R-SCOPE | capability / consumer | `test_*_scope_*` | 越权输入在 query/I/O 前失败 | deterministic |

完成状态采用受证据约束的固定术语：

- `software complete`：deterministic 门禁通过；
- `integration verified`：PostgreSQL 16 Actions job 通过，JUnit tests > 0、skipped = 0，并保存 run URL、commit SHA、时间；本地运行只作调试；
- `live verified`：受控 WeKnora workflow 通过，JUnit tests > 0、skipped = 0，并保存 run URL、commit SHA、时间。没有该证据时只能写 `NOT RUN`。

## 3. 代码结构与风格

- 目录布局见 02 §7；每个 `harness/` 子包必须有 `README.md`（职责、入口、与其他包的关系）；
- 边界纪律（code review 检查项）：
  1. 保险逻辑进 Go/Vue = 0（02 §3）；
  2. 只有 `adapters/weknora/` 允许出现 WeKnora API 细节；
  3. 只有模型网关模块允许出现具体模型名。
- 风格：ruff 默认规则 + mypy strict；公共函数必须有类型标注与 docstring（说明"为什么"而非"是什么"）；
- 所有 LLM prompt 集中在 `harness/compiler/prompts/`（版本化，禁止散落在业务代码里）；
- 配置一律 Pydantic Settings + 环境变量，禁止硬编码（教训：旧项目向量维度硬编码事故，HANDOFF §五）。

## 4. HANDOFF.md 维护义务

`/HANDOFF.md` 写给完全没有上下文的新会话/新成员，固定五要素：**在做什么任务 / 已完成什么 / 当前卡在哪 / 下一步计划 / 踩过的坑绝不再踩**。

- 每个 change 合并、每次重大讨论定稿、每次踩坑后**立即更新**；
- "踩过的坑"只增不删；
- 检验标准：新人只读 00-project-overview + HANDOFF 就能接手下一步开发。

## 5. 示范项目质量清单（每次交付自查）

- [ ] 文档先行：方案能在 docs/insurance-kb/ 或 change 目录中找到，且与实现一致；
- [ ] 任何人可复现：README 内的启动/测试命令在干净环境可执行；
- [ ] 可追溯：Claim 有 Evidence、变更有 ChangeSet、决策有 ADR/讨论记录；
- [ ] 可回滚：迁移脚本有 downgrade，发布有快照；
- [ ] 可接手：HANDOFF 已更新，术语在 00 §术语表中有定义。

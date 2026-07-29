# 22 · 生产架构小 PR 并行执行蓝图

> [!WARNING]
> **SUPERSEDED EXECUTION DAG（2026-07-29）**：本文原 D0→Milestone A/B/C、
> P11/P12 Projector ownership 与 PostgreSQL Active 路线只作历史证据。当前
> active execution plan 是 Mission 0 → `80a5003` capability gap/S0-Q →
> S0-R → 双 PASS → MVP 纵切；legacy 只按真实调用改接，物理清理后置。详见
> [Authority Amendment 2](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)。
>
> 状态：D0 governance rewrite。后续窗口仅为 planned ownership，不代表已经
> 实现或可运行。
>
> 本文件不再是当前 active execution plan；实时状态、阻塞与裁决只记录在
> [23 · MVP 控制板](23-mvp-control-board.md)。任何实现窗口必须同时满足本计划
> 的依赖/文件域和控制板的当前放行状态；每个小 PR 在 Ready/merge 前必须完成
> 对应门禁及独立 Spec/Quality review，不能从旧分支或历史控制板反推授权。

## 1. 启动顺序

```text
D0 → {C0, W0}
C0 → CAP0
then Milestone A → Milestone B → Milestone C
```

D0 合入前不启动功能窗口。D0 后 C0 与 W0 文件域独立，可并行；CAP0 必须消费
C0 的 canonical 合同。后续依赖以生产架构设计 §16 的完整 DAG 为准，不从旧
分支状态反推。

## 2. 首批窗口

| 窗口 | 单一职责 | 允许域 | 禁止域 |
|---|---|---|---|
| C0 | canonical envelope、vectors、Python reference codec | 新 canonical 包、vectors、对应 OpenSpec/tests | 领域表、Candidate/Release、Go patch |
| W0 | 只读 revision/lifecycle contract spike | 证据报告、只读 probes、contract fixtures | 功能 patch、共享 DB、解析器 |
| CAP0 | CapacityProfile 与证据档位 | capacity contract、fixtures、报告 | 压测平台、分片、第二数据库 |

W0 只能输出“现有 API 合同充分”或“触发最小 W1”。W1 未被触发时不得产生
WeKnora 功能 diff。

## 3. Milestone 并行规则

- **Milestone A**：P1/P2a/P2d/P3/P4/P5/G0 分包；Schema、Evidence、
  SourceRevision 和 security authority 各自唯一。
- **Milestone B**：P2b/P2c/P6/P7/P8/P9a/G0b；同 Space publication 和 policy
  lane 串行，跨 Space 可并行。
- **Milestone C**：P10–P15；P11/P13/P14 是唯一 WeKnora patch owner，P12
  只消费 P11 contract。

## 4. 共享资源与 migration lane

- 一个 migration PR 一次只允许一个 Owner；开始时读取真实 Alembic head，
  不复用任何旧预留编号。
- `pyproject.toml`、lockfile、全局配置、主查询接口与 Space pointer 由任务卡
  明确唯一 Owner。
- 发现跨域缺口只提交 contract issue，不直接修改其他窗口核心文件。
- C0 canonical vectors 是跨语言唯一来源；Python/Go 消费者不得另立编码规则。

## 5. PR 颗粒度

- 一个 PR 一个领域不变量和主要数据流。
- 通常 10–15 个逻辑文件；规模是 review alarm，不得为数字拆坏原子事务。
- 每个 PR 先交 Contract Card，再 RED→GREEN，再独立 Spec/Quality review。
- PostgreSQL 权威、WeKnora patch、UI 和 provider 验收分别交付，不做跨域大包。
- 功能实现、migration、真实 provider/live 只能在各自明确授权窗口发生。

## 6. 测试与验证

| 风险 | 每步 | PR-ready |
|---|---|---|
| 权限/事务/migration/Release | 精确 RED/GREEN + PG 并发节点 | focused、PG、static、OpenSpec、CI |
| Schema/Compiler/Conflict | 精确节点 + dev Golden subset | 领域套件、static、OpenSpec、CI |
| UI/adapter/docs | contract/smoke | focused、compatibility、CI |

完整 deterministic、provider、WeKnora live 和 load 只在相应发布画像规定的阶段
运行，未运行必须准确写 `NOT RUN`。

## 7. 配置不是上限

文档数量、微批大小、Worker/provider 并发、Candidate 大小和保留窗口由
CapacityProfile 或 fixture 配置。任何示例值都不能升级为产品硬上限；超容量
必须排队、blocked 或进入扩容裁决，不能丢数据。

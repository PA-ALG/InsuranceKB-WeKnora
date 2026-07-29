# 033 任务（D0，治理文档；无功能代码）

> [!WARNING]
> 2026-07-29 Amendment 2 已取代本 change 的 PostgreSQL Active +
> WeKnora Projector 执行方向。既有 checkbox 是历史 D0 证据；不得据此实现
> P11/P12 或旧 Projector。Mission 0 只更新治理权威，零功能代码、零 migration。
>
## D0-M0 · V3 authority Amendment 2

- [x] M0.1 纳入 728 V3 与新会话 handoff，记录 2026-07-29 current identity。
- [x] M0.2 创建 Sole Serving Active Release Authority ADR，状态
  `ACCEPTED_CONDITIONALLY`。
- [x] M0.3 创建 Amendment 2，取代 PostgreSQL Active + Projector 执行方向，
  保留旧正文作 history-only。
- [x] M0.4 更新 AGENTS/CLAUDE、北极星、生产设计、overview、roadmap、
  execution blueprint、control board 与 legacy disposition 的优先级。
- [x] M0.5 校正 043/045 与 OpenSpec 注册表状态。
- [x] M0.6 strict 验证 033/043/045、diff-check、stale authority scan 与零功能/
  migration/workflow/deployment-lock scope。

## D0-S0 · pre-implementation spec candidate

- [x] T0 从执行时 exact `origin/main` 创建唯一隔离 worktree，验证 `.worktrees`
  被忽略；不触碰冻结 029a。
- [x] T1 校验权威生产设计 SHA-256，完整读取已批准语义；记录用户
  `2026-07-26` 最终书面批准与当前 D0 阶段，不重开设计。
- [x] T2 运行治理入口 RED 扫描，把强制人工终审、filesystem 发布、raw
  fallback、绝对零 fork patch 和旧 PR/runtime 命中分类为
  `REPLACE | HISTORY | EXPLICIT_NON_GOAL`；按 Contract Card 的 exact regex、
  20 roots、UTF-8/LF/空白归一化与 C-locale 排序保存完整 baseline manifest 和
  SHA-256。S0 未带入的批准设计只允许一条 `PENDING_ROOT`。
- [x] T3 冻结 033 proposal/spec/Contract Card，覆盖四种审核模式、
  PostgreSQL serving authority、WeKnora fenced projection、raw 边界和旧分支
  历史边界。
- [x] T4 创建 machine-readable planned patch inventory；只登记
  W1/P11/P13/P14，不产生实际 WeKnora patch。
- [x] T5 在 OpenSpec change 注册表占用 033–036；明确它们不是 Alembic 迁移号。
- [x] T6 运行 strict OpenSpec、inventory schema/scope、语义扫描和 diff/path
  检查；同一 stale scan 连续两次必须逐字同 hash，未知记录 fail closed；用
  独立 temp index 冻结 exact pre-implementation candidate。
- [x] T7 worktree2 对 exact pre-implementation tree
  `4d481d07b7cc6889053d0402d7b6023fb7fd8f98` 完成第三轮独立 Spec review：
  C0/I0/M0，Approved。

## D0-S1 · governance rewrite（已完成，待 whole-candidate 独立审查）

- [x] T8 只在以下精确 10 个治理路径执行语义改写：生产设计、旧北极星、
  `AGENTS.md`、`CLAUDE.md`、`HANDOFF.md`、insurance-kb `README.md`、
  `14-deployment-runbook.md`、`16-roadmap.md`、
  `22-parallel-execution-blueprint.md`、`23-mvp-control-board.md`。生产设计只从
  已批准 SHA-256 的权威源带入完整内容并更新状态为“用户最终书面批准
  2026-07-26 / 当前阶段 D0 实施”，不得改变设计语义。
- [x] T9 只对以下精确 6 个旧 OpenSpec 文件加顶部 prominent
  `SUPERSEDED / HISTORY-ONLY` notice 与新设计指针：
  `029-release-manifest-approval-mvp/{proposal.md,tasks.md,
  specs/release-approval/spec.md}` 和
  `032-human-wiki-reader-mvp/{proposal.md,tasks.md,
  specs/human-wiki-reader/spec.md}`。历史正文与 checkbox 不改；031 OpenSpec
  文件变更数必须为零。
- [x] T10 在已属 S0、属于 S1 incremental 19-path allowlist 的
  `openspec/changes/README.md` 只修改 change 注册表和旧计划 migration
  `0013/0014` 的状态为 `superseded / not reusable`；不预占替代 migration，
  后续实现从当时真实 `origin/main` Alembic head 重新占号。
- [x] T11 对同一词表运行 GREEN scan；所有剩余命中只能是明确历史或显式非目标。
- [x] T12 只在 033 `tasks.md` 更新 S1 checkbox/custody、在
  `validation-report.md` 更新 GREEN manifest/门禁/final identity，冻结 D0
  最终 doc-only candidate 并重新独立 Spec/Quality review；S0 proposal/spec/
  inventory blob 必须不变。

## 裁决记录

1. 阶段门优先于完整 D0 指令：S0 只交付 6 个路径，S1 不得提前开始。
2. D0 final unique 路径预算固定为 22：S0 的 6 路径加 S1 引入的精确 16
   新路径。S1 相对冻结 S0 candidate 的 incremental touched allowlist 固定为
   19：16 个新路径 + 已计入 S0 的 README/tasks/validation 三路径；第 17 个
   新路径、第 20 个 incremental touched 或第 23 个 final unique 路径均立即
   `NEEDS_CONTEXT`。
3. notice-only 仅限旧 029/032 六文件；不得新增或修改 031 OpenSpec 历史文件。
4. README/tasks/validation 只可承担上述机械账本用途；proposal/spec/inventory
   在 S1 必须保持冻结 S0 blob 不变，任一漂移立即 `NEEDS_CONTEXT`。
5. D0 不修改功能代码、迁移或 fork；planned inventory 不等于 patch authority。
6. 旧 029a、031 和 PR26/28/33 只作历史证据，禁止从其未合并实现复制 authority。

## D0-S1 · whole-candidate review corrective

- [x] T13 将 change README 的旧并行开工基线标为
  `SUPERSEDED / HISTORY-ONLY — NOT EXECUTABLE`，并建立 033、批准设计、22
  active plan、23 state board 的当前入口。
- [x] T14 在 AGENTS/CLAUDE 冻结新 Space 默认 `human_batch`、G0b 后才可由
  显式版本化 policy binding 启用生产 `machine_auto`，并限定 superadmin 只能
  对 exact CandidateRelease 执行不绕过完整性/ACL/provenance/security 的
  一次性动作；CLAUDE 恢复无条件 AI 不 commit/push。
- [x] T15 将 22 指定为 active execution plan、23 指定为实时状态/决策板，
  并在 HANDOFF 当前状态块提供批准设计、22、23 三个链接；历史正文保持不变。
- [x] T16 重新生成 GREEN scan/validation，运行文档级门禁和内部
  Spec/Quality 自审，并用全新独立 temp index 冻结 corrective candidate。

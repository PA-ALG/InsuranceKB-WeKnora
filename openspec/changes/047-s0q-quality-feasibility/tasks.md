# 047 · S0-Q Quality Feasibility Tasks

## Contract Card

- 单一职责：冻结真实 parsed artifact 输入与四字段窄切片验收。
- 当前状态：`SPEC-ONLY / BLOCKED_ON_INPUT`。
- 原始 spec-only 交付路径预算：恰好 5 个 Markdown 路径（历史事实）。
- 非目标：抽取实现、质量平台、模型调用、Release/S0-R/MVP、源码/migration/
  workflow/principal/运行时 registry。

## 2026-07-30 Schema Authority Amendment

- [x] 经业务方批准，将 exact 原始 XLSX 与嵌入截图公开入库并记录 SHA-256。
- [x] 核对八张结构化字段表与现有 YAML 逐行映射，不修改运行时 YAML bytes。
- [x] 冻结 Golden 合同：完整产品 Golden 是唯一金标来源，S0-Q 只投影四条
  诊断记录，不新增四字段 Golden。
- [x] 核对目标医疗产品历史 WIP 覆盖 60/60 个当前可抽取字段，其中 49 个来自
  工作簿权威、11 个来自后续 v1.1 扩展；该事实不等于 Golden 获批。

## 本文档 Mission

- [x] Q0 从 exact
  `origin/main=6605c703282e442a8636d7f323f17396e6f00d49` 创建 clean 独立 worktree。
- [x] Q1 冻结两份真实 WeKnora/W1 parsed artifact 的完整 identity 合同。
- [x] Q2 冻结一个 ProductVersion 与
  present/typed-present/absent_explicitly/unknown 四字段。
- [x] Q3 冻结 candidate region、复杂表格、Evidence、typed fail-closed、
  abstention、error buckets、人工修订时间与 A–D 小样本诊断消融。
- [x] Q4 冻结弱模型运行预算；正式弱模型链/feasible 分子的强模型调用上限
  为零，仅允许预批准 exact identity/budget 的隔离诊断上限。
- [x] Q5 记录仓库当前缺少完整 frozen artifact bundle，状态
  `BLOCKED_ON_INPUT`，不造身份或样本。
- [x] Q6 strict validate 047、diff-check 与 exact 五路径 scope。
- [x] Q7 独立 Spec + Quality/Delivery review。

## 后续运行（2026-07-30 已授权，仍须按门禁执行）

- [ ] R1 提供两份真实材料的完整 frozen artifact manifest。
  - 2026-07-30 首次有界输入预检结论：`BLOCKED_ON_INPUT`。两份 PDF 的
    SHA/bytes 均匹配，但固定 WeKnora 输入画像所需的百炼 embedding 凭证在
    创建 scratch KB 前的一次维度探测返回 HTTP 401；同时 current W1 v1
    exact-revision API/manifest 只绑定 text chunk id/index/content，不绑定
    page/block/table-cell identity 或表格结构 digest。未生成 W1 bundle，R1
    保持未完成。证据见 `artifacts/input-capture-report.json`。
- [ ] R2 提供预置 ProductVersion，以及从冻结完整产品 Golden 投影的四条
  诊断记录与 Evidence。
  - 当前历史 WIP 只证明 60/60 覆盖。须由独立 Golden Mission 使用
    `gpt-5.6-sol` 全部字段统一候选生成或复核，完成 Evidence 回验、既定人工
    批准和不可变 artifact identity/digest 后，R2 才可勾选。
- [ ] R3 批准 exact 弱模型画像、调用/重试/timeout、人工修订时间上限，以及
  隔离强模型诊断臂的 exact identity/有限调用预算。
- [x] R4 取得独立运行 Mission Card；模型/provider 仍须等待 R1–R3 admitted。
- [ ] R5 在同一 2 材料/4 字段完成 A–D 消融，输出逐字段结果、error buckets、
  abstention、Evidence 与人工修订时间。
- [ ] R6 仅在所有验收通过时输出
  `KNOWLEDGE_COMPILATION_FEASIBLE_ON_NARROW_SLICE`。

R1 未 admitted，因此 R2–R3 与 A–D/provider 按门禁均为 `NOT RUN`；这不是
S0-Q PASS/FAIL，也不授权用人工清洗文本、替代 embedding 或扩大环境治理。

## 047-R1E · Existing-source read-only evidence capture

- [x] E1 从 exact
  `origin/main=bb9b012ebbd97f92340fdab25557f7a24504b30f` 创建独立 clean
  worktree；路径预算冻结为 runner/module/test + OpenSpec 四文件，最多七路径。
- [x] E2 先写 focused RED，覆盖 GET-only allowlist、tenant/Space/KB、SHA/
  attempt 漂移、跨 source 全局 fence、R1 descriptor、mixed-attempt chunks、
  manifest 重算、独立 secret ingress、结构缺失与 mapping-key 输出脱敏。
- [x] E3 实现 task-local `capture-existing`：只调用 `knowledge_get`、
  `revision_get`、`revision_chunks_get`，不调用 upload/reparse/delete/list。
- [x] E4 两 source 按固定顺序执行全局 PRE(K0/R0)→BODY(chunks/manifest)→
  POST(R1/K1)；全部 fence exact 相等后才构造输出，失败零 admitted bundle、
  零 revision/manifest 写。
- [x] E5 证据只记录 parser/profile、字段名/type/shape 与非敏感 digest；正文、
  credential、secret、绝对路径和未知 mapping key/digest 不进入报告；runtime
  scope 在 client 前 exact match，credential 仅来自 process environment。
- [x] E6 locator/metadata 只可分类为 `PRESENT_UNBOUND` 或
  `ABSENT_INSUFFICIENT`；两者均保持
  `W1_STRUCTURE_EVIDENCE_INSUFFICIENT`，不得猜测结构或授权 S0-Q。
- [x] E7 focused、Ruff、strict mypy、OpenSpec 047 strict、diff/scope/private/
  secret 最终门禁。
- [ ] E8 exact frozen candidate 的独立 Spec 与 Quality/Delivery 双审。

真实 credential/runtime/WeKnora capture、provider/model、PostgreSQL 和 full
均不属于 R1E 实现阶段，保持 `NOT RUN`。

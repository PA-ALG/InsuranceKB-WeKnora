# 051 · Validation report

## Candidate identity

- authoritative base：`0f231f9841ab31dde4bad15b958c4cd83c316086`
- base tree：`cd5c0d5b9db7b44808d4a1a7792d659de1b9736f`
- branch：`codex/051-enterprise-knowledge-compiler-architecture`
- state：`SPEC-ONLY / PARENT ARCHITECTURE / IMPLEMENTATION NOT STARTED`
- candidate tree：由最终只读 handoff 记录 exact Git tree；不在制品内自嵌，避免
  递归改变自身 identity

## Scope

051 只修改七个文档路径，不包含 Python/Go/TypeScript、migration、workflow、
provider 配置、Golden 数据或 WeKnora patch。父级合同不授予 B–G 开工；每个子
Mission 仍须独立占号、OpenSpec/Mission Card、RED→GREEN、路径预算和审查。

## Evidence reviewed

- Sole Serving Active Release Authority ADR 与 Authority Amendment 2；
- OpenSpec 033、当前 registry、MVP control board；
- JLX v3 与 `mvp_handoff_jlx.md`；
- 现有 W1/SourceRevision/FrozenW1Bundle、C0、TemplatePackage resolver/hash/
  approval 的设计事实；
- 047 的两 PDF evidence-capture 边界与 049 的 `596-1` 60-field frozen Golden；
- Dayu 借鉴决策、第一方 LLM-wiki-black 迁移边界与现有 Harness 设计。

## Frozen truth boundaries

- `pdfplumber → DeepSeek 一次 60 字段抽取` 只保留 baseline/simple fast path，
  不作为生产主链。
- C0 envelope/artifact hash 是唯一外层 custody/identity authority；领域 digest
  不能成为第二批准 authority。
- parser 与弱模型 winner 未选择；G 之前禁止模型实验。
- ParseQuality 仅冻结 required facts 与 reason-code families；数值阈值留 B 用
  `596-1` fixtures 校准。
- 产品族来自已批准 ProductVersion/MaterialProfile 显式映射，不由模型或文件名
  推断。
- 047 当前两 PDF 不满足条款/说明书/费率表三 PDF admission。
- 每个 MaterialProfile 只有一个 default parser 与至多一个 bounded upgrade；禁止
  第三次 parser attempt 或把候选族写成顺序 ladder。
- 子 Mission 顺序为 `A → C → B → {D,E} → F → G`；C 先提供 B 所消费的 exact
  MaterialProfile required capabilities，真实三 PDF admission 仍由 B 闭合。

## Gates

- OpenSpec 051 strict：`PASS`（OpenSpec 1.2.0）
- diff-check / exact seven-path scope / all `100644`：`PASS`
- UTF-8/LF / relative links / private / absolute path / secret：`PASS`
- internal Spec review：`C0 / I0 / M0 · Approved YES`
- internal Quality/Delivery/YAGNI review：`C0 / I0 / M0 · Approved YES`
- function/full/provider/model/PostgreSQL/WeKnora live/Golden：`NOT RUN / OUT OF SCOPE`

初次 diff-check 发现 architecture spec 标题元数据的 Markdown hard-break 尾随空格；
已改为独立引用行，fresh diff-check 通过。初次 absolute-path 高信号扫描还发现计划中
用于描述门禁的连续 `scope`、`private`、`secret` 字面串会形似绝对路径；已改为普通文字，
没有改动任何架构语义。

内部 Spec 逐条核对了材料权威、四级 fallback、ParseQuality reason families、
C0 唯一外层 hash authority、三 PDF 门和 A–G 准入；内部 Delivery/YAGNI 核对了
七路径、零功能实现、无 vendor winner、无通用 parser/Agent 平台和小 PR 停止条件。

## Final review corrective

两路 FINAL review 在前一冻结树确认两个 bounded docs-only blocker：解析路径允许超过
两次 parser attempt，以及 B 先于其 MaterialProfile 依赖 C。successor 已机械收窄
为一个 default parser + 至多一个 bounded upgrade，并改为
`A → C → B → {D,E} → F → G`。050 注册表状态同步为 PR #78 已合入。除此之外未
重开或新增架构要求；successor delta review：`NOT RUN / PENDING`。

本报告在 stable checkpoint 前只记录真实证据；不得把文档 PASS 写成功能完成、
parser/model admission、S0-Q PASS、Release ready 或生产完成。

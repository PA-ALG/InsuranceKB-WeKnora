# 053 · Parsed document contract implementation plan

> **For agentic workers:** 本 Mission 已获批准；在隔离 worktree 内按 strict TDD
> 顺序执行。禁止 commit/push/PR，直到稳定候选经总控授权。

**Goal:** 为 052 的 exact MaterialProfile 交付 vendor-neutral parsed artifact、完整
manifest 与 fail-closed quality decision 纯合同。

**Architecture:** 一个冻结 ParsedDocument 只包含身份、结构事实、locator 与摘要；
ParseManifest 从 document 确定性派生并绑定 C0 hash；ParseQuality 只消费 052
批准的 required capabilities 与 parser policy，不接受 caller flags。

**Tech Stack:** Python 3.12、Pydantic v2、C0 CanonicalEnvelopeV1、OpenSpec、pytest、
Ruff、strict mypy。

## Task 1: 规格和隔离身份

- [x] 从 remote `codex/052-material-profile-template-binding` exact head
  `46b7e6b16e2bf2afb7ce1e450d63cca81e849951` / tree
  `2fd7675233bd404248f974daa078e9c0c61ceb8a` 创建 clean worktree 与
  `codex/053-parsed-document-contract`。
- [x] 先在 registry 占用 053，再创建本目录。
- [x] 阅读 AGENTS、ADR、Amendment、HANDOFF 顶部、JLX M0/知识编译章节、051 与 052。
- [x] 冻结本 OpenSpec 七路径预算、stacked dependency、非目标与验收。
- [x] 保存七路径 WIP 后，将基线 exact fast-forward 到 052 successor
  `67483ab7d769fc4a2c01736d638c34bf9ee0e66f` / tree
  `1fe7692f1d8053a290b8e667799af54db8354dc4`，恢复 WIP 且不修改 052。

## Task 2: ParsedDocument / ParseManifest RED → GREEN

- [x] 先写 focused RED：模块缺失、identity/attempt/locator/order/count/hash 漂移、
  unknown vendor/body 字段、缺 required capability Evidence 均被拒绝。
- [x] 运行 focused tests，确认因能力缺失而失败，不因 typo/fixture 失败。
- [x] 实现最小 frozen/extra-forbid DTO、确定性 manifest builder 与 typed error。
- [x] 运行 focused tests至 GREEN；不得实现 parser 或读取 PDF/Markdown。

## Task 3: ParseQuality RED 与 052 successor 门

- [x] 先写 ADMIT/ESCALATE/BLOCK 的 RED，覆盖六个 KCA5 reason families。
- [x] 在 052 successor 未提供 exact parser policy 前，证明 ESCALATE fail closed；
  不接受 caller 自报/default 猜测。
- [x] successor identity 到达后仅消费其批准 policy，完成最多两次 attempt、第二次
  BLOCK+ReviewItem、隐私/输出策略与 threshold-version 绑定的最小 GREEN。

## Task 4: 回归与交付

- [x] 运行 052 focused、053 focused、相关 C0/W1 回归、Ruff、strict mypy、OpenSpec
  strict、diff/scope/private/secret 门禁。
- [x] 以 RED 证明 page/missing refs 不得冒充 `table_grid`，并由 bounded capability
  shape gate 转为 typed ESCALATE/BLOCK。
- [x] 以 RED 证明缺失或缩窄裸 receipt 不得 ADMIT；质量入口只接受 052 validated
  `MaterialProfileResolution`，exact 绑定 binding/catalog/profile/capabilities。
- [x] 冻结 exact seven-path temp-index candidate；real index 保持空。
- [x] 只报告真实 RED/GREEN 与 NOT RUN；不 commit/push/PR/Ready/merge。

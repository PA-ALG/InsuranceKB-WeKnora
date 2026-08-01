# 059 · Implementation Plan

> **For agentic workers:** Mission 已获批准。严格使用隔离 worktree 与 TDD；
> accepted 058 exact commit 到达前停在真实 RED，不 commit/push/PR。

## Task 1 · 身份、占号与父合同

- [x] 从 authoritative main `8f2f933c0c23e8f1dcc2d9073b463c62240ba54e`
  建立 clean worktree/branch，并确认 `.worktrees` 被忽略、项目 open PR 为 0。
- [x] 更新 registry，占用 059，并如实记录 058 独立 Owner 尚未合入。
- [x] 冻结 PR1 的 Candidate/human_batch 边界、严格七路径和 PR2 非目标。

## Task 2 · 058 dependency seam RED

- [x] 写 focused RED，明确因 accepted 058 exact public contract 缺失而阻断；
  不 xfail、不用本地 stub、不复制/猜测 058 DTO/hash/action logic。
- [x] Total Control 提供 accepted 058 commit 后，先 ff/rebase 到该 exact commit，
  fresh 核验公开 seam，再把依赖 RED 转为实际导入与行为 RED。
- [x] 若 058 缺少 proposal §“058 exact public seam”中的任一值，停止并报告
  dependency BLOCKER，不修改 058。

## Task 3 · Candidate RED→GREEN

- [x] 用 058 public DTO 与 057 public receipt DTO 写 RED：exact scope/source/
  schema/change-set/receipt binding；missing/ambiguous/cross-scope/drift fail closed。
- [x] 写 RED：相同语义输入顺序变化 hash 稳定；任一绑定 byte mutation 改变
  Candidate hash。
- [x] 在唯一 production module 中实现最小 frozen/extra-forbid DTO 与 C0
  canonical builder；不得定义第二套 ChangeSet 或 receipt authority。

## Task 4 · Human batch RED→GREEN

- [x] 写 RED：conflict/high-risk/repair-needed items 以 canonical 顺序进入
  human_batch，普通 item 不制造阻断；batch 绑定 exact Candidate hash。
- [x] 写 RED：conflict 保留全部 competing fact/Evidence；遗漏、歧义或跨 scope
  fail closed；无 review item 的 batch 仍不是 auto approval。
- [x] 实现最小 deterministic envelope，不实现 decision、Release 或 serving。

## Task 5 · 验证与冻结

- [x] 运行 focused test、057+058+059 bounded regression、Ruff、strict mypy、
  OpenSpec strict、diff/scope/private/secret/UTF-8-LF。
- [x] 冻结 exact seven-path temp-index tree，real index empty，并交独立
  Spec/Quality/Delivery 复审；Owner 不 commit/push/PR。

## Task 6 · Quality corrective

- [x] 用直接 DTO 构造与 `model_copy` RED 证明 HumanBatch membership 不能只由
  builder 保证；aggregate validator 重算 conflict/high-risk/repair-needed 的
  exact item、fact 与 Evidence custody。
- [x] 修复 focused test 的 strict mypy return annotation，重新运行 focused、
  bounded、Ruff、strict mypy、OpenSpec 与 custody 门禁后重冻 successor。
- [x] 用 exact 054 ReceiptChain 替换 caller 自报 schema authority；补
  foreign-Space/schema、repair-only source 与 repair unique-bijection RED，
  aggregate 重算全部 custody。
- [x] 以隔离进程拦截 filesystem/environment/network/DB/WeKnora 操作，证明
  057 传递加载未造成构造期 I/O；不为模块加载扩 facade。
- [x] 补 direct/model-copy RED：即使同步伪造 gap/review，也不能把 parent
  PASS result 改成 FAIL；逐字段保持 EEV5，并精确重算最终 gap/review。

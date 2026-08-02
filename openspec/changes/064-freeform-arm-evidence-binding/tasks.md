# 064 · Implementation Plan

> Mission 已获批准。唯一 Owner 在 exact main `f45b751b...` 的隔离 worktree 内
> 执行 RED→GREEN；稳定 checkpoint 前不 commit/push/PR。

## Task 1 · Contract and RED

- [x] 占用 OpenSpec064，冻结严格七路径、单一职责、非目标与失败边界。
- [x] 在既有 057 test 先写自由文本 output/receipt 的 wished-for API。
- [x] 观察缺少 DTO/binder/replay seam 的 focused RED。

## Task 2 · Exact identity and locator binding

- [x] 最小实现 exact document/manifest pairing、source/attempt/hash identity。
- [x] 校验 page/block/table/cell ref、kind、parent、content snapshot/hash 与 quote。
- [x] RED/GREEN 覆盖 wrong source/doc/attempt/manifest/page/ref/kind/content/quote。
- [x] Corrective RED/GREEN 覆盖 arm source/page/block/table/cell、row/column、
  header、row/column span 逐项 mutation，header 只由 exact header cell hash 重放。

## Task 3 · Multi-Evidence and receipt custody

- [x] 支持一字段多 Evidence/多 source；known field 缺/重/漏 source 或非 canonical
  顺序 fail closed；unknown 无 value/Evidence/document custody。
- [x] receipt hash 绑定 field/state/value、全部 Evidence 与每个 document/manifest
  hash；value/evidence mutation 改变 hash，exact replay 稳定。
- [x] 证明 057 不 import 061，不执行语义 judge；runner 仅需一对一 DTO 转换。

## Task 4 · Verification and freeze

- [x] focused 057+064、相关 053 回归、Ruff、strict mypy、OpenSpec strict、
  diff/scope/private/secret/UTF-8-LF。
- [x] 冻结 exact seven-path temp-index candidate；real index empty；不
  commit/push/PR。

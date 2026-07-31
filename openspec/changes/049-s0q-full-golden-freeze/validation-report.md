# 049 · Validation report

## Candidate identity

- base：`9867292e4e294b182494928489c56a96271dd197`
- ProductVersion：`596-1`
- model：`gpt-5.6-sol`
- current state：`S0_Q_FROZEN_FULL_GOLDEN_AVAILABLE / DRAFT DELIVERY PENDING`

## Evidence status

本报告只记录真实运行结果。两个隔离 blind pass 均由 `gpt-5.6-sol` 六批覆盖
exact 60 字段，各使用一次最终 Evidence retry，合计 parse retry 恰为 2。三 PDF
Evidence exact quote 回验为零 mismatch；两路 field-id 集合 diff 为 0。

- review hash：`babd9a9453afa1f5942dda168705926b6fe2b0a6467a586b2d71ee335754a3e5`
- recommendation package SHA256：
  `1942585c3893e877602c94833f2ba6214a2706711702d7fb81cf88ddce91c0c6`
- adjudication：59 项，`candidate=10`、`review=48`、`custom=1`
- external approval receipt SHA256：
  `2e8c16dbf064516ee0999c0fb079fcc6430ba0a10bc8881a380b6834db787692`
- release hash：`fca06f988bf0310d12a0f6f8d0703a9476c54a5405676fb1a9b3476f91ec21d0`
- artifact hash：`83032da028ef227071fddac0ed422cbb9d1c2cc31e195972f9878a67d95b44ca`
- approval subject：
  `6feb2acf4be1ab5ce075b662bc9c9a40024038ca2324b893d3f31b1384f7674b`

总控签发的外部 receipt 精确绑定上述三个 prospective hash、
`source_thread_id` / `conversation_id=019fa5ea-2507-73a2-acb8-d49030bad2f0`
和 `user-message:批准吧@2026-07-31`。任务脚本随后以 no-replace 临时目录构建并
原子发布唯一四件 artifact；没有脚本自填 approval 路径。

## Frozen artifact identity

目录：`dataset/goldenset/gs-s0q-596-v1/`

- `596.jsonl`：
  `562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb`
- `disputed.jsonl`：
  `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b`
- `review-and-approval.json`：
  `484fdb78bdc73109bccd4d771e41089574b26f28c1992b67b2114524a515c868`
- `manifest.json`：
  `d926cc3da4af4c531dffd05c12e5b8214fb8b79e50652ca5c30bd5db35f377c1`

manifest 记录三 PDF 的 exact repo path/size/SHA256，并记录前三个非 manifest
artifact 的实际文件字节 SHA256。结果为 60 条唯一 field-id、`disputed=0`；
`build_release` 重放字节一致，`validate_release` 五项通过且 self-eval
`P/R/F1=1.0, Evidence=1.0`。本产物只供 S0-Q，不是 production 或
`machine_auto` authority。

## Atomic no-replace corrective

Delivery review 复现了旧实现 `exists()` 后以 `os.replace()` 发布时可覆盖并发
创建的空目标目录。确定性 race test 在检查后创建空目录，旧实现 RED：
`DID NOT RAISE FileExistsError`。corrective 改为单次 OS no-replace 原语：
macOS `renamex_np(RENAME_EXCL)`、Linux `renameat2(RENAME_NOREPLACE)`；
原语或平台不支持时以 `ENOTSUP` fail closed。GREEN 同时证明并发目标目录
inode 和空内容保持不变、无部分 artifact；没有用锁或二次 `exists()` 冒充原子。
既有四 artifact 字节未改变。

## Independent corrective review

两路 final delta review 均绑定 pre-sync candidate tree
`1f31b24191b29b746c0c17ee30ea2f7cfc4949de`：

- Data / Spec / approval custody：`Approved YES`
- Quality / Delivery：`Approved YES`
- `BLOCKER=0`，没有要求重跑模型、改写 artifact 或扩大路径

本节只机械记录审查结果；corrective 后的原子 no-replace 逻辑、race test、四件
artifact 字节和前述 gate 证据均未在本次同步中修改。

## Gates

- focused：`7 passed in 17.66s`
- OpenSpec 049 strict：`PASS`
- Ruff：`PASS`
- strict mypy：`PASS`，2 files / 0 issues
- existing build / validate / no-replace：`PASS`
- diff-check / exact 11-path scope / private / secret：`PASS`
- full / provider / live / PostgreSQL / WeKnora：`NOT RUN`

# 049 · Tasks

## 合同与 TDD

- [x] T1 从 exact `origin/main=9867292e4e294b182494928489c56a96271dd197`
  创建隔离 worktree，并占用 049。
- [x] T2 冻结十一路径、单模型、双 blind pass、三 PDF、60 字段和人工批准边界。
- [x] T3 先写 focused RED，证明重复/缺失字段、错误 Evidence、两个 pass 合计
  retry 超二、forbidden input reference 和伪批准都 fail closed。
- [x] T4 实现单一任务脚本，不新增公共模块或修改通用 Golden 代码。

## 数据与人工闭环

- [x] T5 `gpt-5.6-sol` pass A：六批覆盖 60 字段，不读取旧答案。
- [x] T6 `gpt-5.6-sol` pass B：独立六批覆盖 60 字段，不读取 pass A/旧答案。
- [x] T7 回验三 PDF Evidence，计算差异、六个固定必审字段和固定三字段样本。
- [x] T8 approval 前只在内存或临时目录形成 review subject，并停机向总控请求
  具名逐字段 decision 与 exact release/artifact/subject hash 批准；不得创建
  release artifact 目录。
- [x] T9 exact 具名批准后，原子生成 `596.jsonl`、`manifest.json`、
  `disputed.jsonl` 和 `review-and-approval.json`；命令只消费总控提供、绑定
  conversation/user-approval provenance 的外部 receipt，不提供自填批准入口；
  任何失败保持零 artifact。

## 交付

- [x] T10 focused、OpenSpec 049 strict、Ruff、diff-check、scope/private/secret。
- [x] T11 corrective 后独立 Spec 与 Quality/Delivery delta review。
- [ ] T12 commit、push、创建 Draft PR；不得 Ready 或 merge。

## NOT RUN

full、provider/live、PostgreSQL、WeKnora 写入和第二模型不属于本 Mission。

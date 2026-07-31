# 049 · S0-Q full Golden freeze

## 状态

`S0_Q_FROZEN_FULL_GOLDEN_AVAILABLE / DRAFT DELIVERY PENDING`

## 为什么做

OpenSpec 047 已确认目标医疗产品的历史 WIP 覆盖当前 60 个可抽取字段，但覆盖
不等于独立复核、Evidence 闭合或人工批准。S0-Q 不能从未冻结的 WIP 投影四条
诊断记录，也不能另造一个四字段 Golden。

## 本 Change 做什么

- 只对 ProductVersion `596-1` 的三份当前材料执行一次完整 Golden Mission；
- 由 `gpt-5.6-sol` 在不读取旧 Golden/pred/draft 的两个隔离 blind pass 中分别
  覆盖全部 60 字段，预算为六批加六批，两个 pass 合计最多两次明确 parse
  retry；
- 将三份 PDF 的结果归并为唯一 60 行，并逐条回验 Evidence；
- 每个 pass 绑定独立 pass id、exact prompt SHA-256、input-manifest digest 与
  只含 Schema/596/596-1/三 PDF identity 的 allowlist；出现旧
  Golden/pred/keypoints/draft reference 时整次 pass 作废；
- 将两 pass 的差异、六个固定必审字段和固定三字段样本交给具名人工；
- 只有人工对 exact `release_hash`、C0 `artifact_hash` 和 approval subject 明确
  批准、且总控提供绑定该批准会话来源的外部 receipt 后，才生成状态为
  `FROZEN_FULL_GOLDEN` 的四件不可变制品。

## 不做什么

- 不重建 Golden 平台，不新增公共模块，也不修改既有 assemble/validate；
- 不创建四字段 Golden，不扩大到 71 个全字段，不运行第二模型；
- 不实现 P5a1、040、数据库、migration、CI、WeKnora 写入或生产准入；
- 本制品只供 S0-Q，绝不表示生产、`QUALITY_APPROVED` 或 `machine_auto`。

## 路径预算

总路径上限十一：README、OpenSpec 四文件、一个任务专用薄命令、一个 focused
test、四个 `gs-s0q-596-v1` artifact。需要第十二路径时必须停止并重新取授权。

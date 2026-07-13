# 008 规格（验收条款）

## W1 审核队列页

- W1.1 列表：pending ReviewItem 按 产品/风险等级/类型 筛选与排序（触发计数倒序默认）；分页；
- W1.2 详情：字段名/候选值/证据对照（引文+页码+来源文档+权威等级）/裁决历史/关联 ChangeSet 链接；
- W1.3 动作仅 approve / reject / defer / 批量 approve（仅 risk_level≠high 可批量）；全部经 007 服务层，写 operator 与时间；
- W1.4 动作后状态即时反映（HTMX 局部刷新），审计记录可查。

## W2 冲突与变更页

- W2.1 ChangeSet 列表（时间倒序，批次来源标注：文档批/结构化导入/回滚）；
- W2.2 明细按 add/enrich/supersede/conflict/retract 分色；conflict 展示双方值+证据+自动裁决依据（权威序比较过程）；
- W2.3 翻案入口：对已自动裁决项发起复议 → 生成新 ChangeSet 走审核（不直接改历史）；
- W2.4 人类可读时间线视图（G8）：按产品聚合的变更流（谁/何时/什么字段/旧值→新值/原因）。

## W3 完整度矩阵页

- W3.1 产品×字段热力矩阵，格子状态：present/absent/unknown/冲突中/待审（分色）；险种筛选；
- W3.2 点击格子下钻：Claim 详情+证据+版本历史；
- W3.3 缺口清单导出（CSV/JSONL），含 011 H1.6 同类对比缺口与 015 问答缺口（工单来源标注）。

## W4 发布与回滚页

- W4.1 快照列表：release_snapshots + 当前指针标注 + 相邻快照 diff 摘要（页面级增删改计数）；
- W4.2 回滚：先 dry-run 展示将变更的页面清单 → 二次确认 `--apply` 语义 → 007 回滚服务执行 → 结果展示。

## W5 工程

- W5.1 FastAPI + Jinja2 + HTMX，落点 workbench/；只调 knowledge/ 服务层函数，**测试断言无任何直接 SQL 写**；
- W5.2 鉴权：共享 token（配置）；无 token 访问 401；
- W5.3 TestClient 用例覆盖四页关键元素与四动作；复用 007 端到端夹具起真实数据形态；
- W5.4 零模型调用；门禁全绿。

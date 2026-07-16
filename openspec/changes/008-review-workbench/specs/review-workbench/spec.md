# 008 审核工作台验收规格

> 二版（2026-07-16）：正式 delta 格式。条款映射：W1~W3/W5 沿用；**W4（发布与回滚页）整页推迟到 PR #9（018）合入后**（一版"Phase A 即刻只读"与 W7.1"读取一律经 SnapshotReader"自相矛盾——main 上该读模型尚不存在）；W6 鉴权升级为 **token→Space 授权绑定**（一版共享 token 只证登录、不证可访问哪个 Space）。

## ADDED Requirements

### Requirement: W1 审核队列页

工作台 SHALL 提供审核队列页：pending ReviewItem 按产品/风险等级/类型筛选与排序（触发计数倒序默认，可选辅助排序信号=值信息量评分——仅排序参考、不作值替换判据）、分页；单条详情含字段名/候选值/证据对照（引文+页码+来源文档+权威等级）/裁决历史/关联 ChangeSet 链接；动作仅 approve / reject / defer / 批量 approve（仅 risk_level≠high 可批量），全部经 007/019 服务层、写 operator 与时间；动作幂等（重复提交同一决定不重复生效）、乐观并发（stale 版本拒绝并提示刷新）；动作后 HTMX 局部刷新即时反映。

#### Scenario: 三动作幂等与并发

- **WHEN** 同一 ReviewItem 被重复 approve，或基于过期版本提交决定
- **THEN** 重复提交不重复生效；过期提交被拒绝并返回最新状态

#### Scenario: 高风险不可批量

- **WHEN** 批量 approve 选择集中含 risk_level=high 的条目
- **THEN** 高风险条目被排除并显式提示，其余低风险条目正常生效

### Requirement: W2 冲突与变更页

工作台 SHALL 提供 ChangeSet 列表（时间倒序，批次来源标注：文档批/结构化导入/回滚）与明细（add/enrich/supersede/conflict/retract 分色）；conflict 展示双方值+证据+自动裁决依据（权威序比较过程）；翻案入口对已自动裁决项发起复议 → 生成新 ChangeSet 走审核（SHALL NOT 直接改历史）；并提供按产品聚合的人类可读变更时间线（G8：谁/何时/什么字段/旧值→新值/原因）。

#### Scenario: 翻案不改历史

- **WHEN** 对一条已自动裁决的 conflict 发起翻案并提交新值
- **THEN** 生成新 ChangeSet 进入审核流，原 ChangeSet 与裁决记录不可变

### Requirement: W3 完整度矩阵页

工作台 SHALL 提供产品×schema 字段热力矩阵（present/absent/unknown/冲突中/待审分色、险种筛选）、格子下钻（Claim 详情+证据+版本历史）、缺口清单导出（CSV/JSONL，含 011 H1.6 同类对比缺口与 015 问答缺口的工单来源标注——两者未交付前该列允许为空）。

#### Scenario: 矩阵与事实一致

- **WHEN** 以 007 端到端夹具起服并查看矩阵
- **THEN** 各格子状态与 claims 表聚合逐格一致，下钻可见证据

### Requirement: W4 发布与回滚页（整页依赖 018，PR #9 合入后交付）

发布与回滚页 SHALL 在 PR #9（018）合入后交付：快照列表/当前指针/相邻 diff 摘要一律经 018 SnapshotReader 与快照投影读取（SHALL NOT 直查 mutable Claim 表）；回滚动作调用 018 可恢复回滚（pointer-last，失败不移动指针），dry-run 预览基于 018 冻结 plan，二次确认后执行。018 合入前工作台 SHALL NOT 提供任何读取业务数据的发布页面（最多静态占位导航项，标注"待 018"）。

#### Scenario: 回滚全链

- **WHEN** 在 W4 页对上一快照发起回滚：dry-run → 二次确认 → 执行
- **THEN** dry-run 列出将变更页面清单（冻结 plan）；执行走 018 可恢复回滚；失败路径不移动当前指针

#### Scenario: 018 合入前无业务读取

- **WHEN** 018 未合入时访问发布页路由
- **THEN** 仅得到静态占位（无任何快照/Claim 数据查询发生）

### Requirement: W5 工程边界

实现 SHALL 为 FastAPI + Jinja2 + HTMX，落点 workbench/；只调 knowledge/ 服务层函数（测试断言无任何直接 SQL 写）；TestClient 覆盖各页关键元素与动作，复用 007 端到端夹具；零模型调用、门禁全绿。

#### Scenario: 无直接 SQL 写

- **WHEN** 静态检查 workbench/ 包
- **THEN** 不存在对业务表的直接 INSERT/UPDATE/DELETE（只经服务层函数）

### Requirement: W6 鉴权与 Space 授权绑定（016 对齐）

鉴权 SHALL 为 token→Space 授权绑定：部署配置将每个 token 映射到允许的 Space 集合（MVP 允许单 token→单 Space 的最简配置）；无 token 401；请求路径中的 space SHALL ∈ 该 token 的允许集，否则 403 且响应不泄露任何业务数据（fail-closed）；所有页面/查询只呈现该 space 数据，同业务键跨 space 互不可见；全部写动作审计含 space + operator + 时间。

#### Scenario: token 不能越 Space

- **WHEN** 绑定 Space A 的 token 请求 Space B 的任意页面或动作
- **THEN** 403 拒绝，响应体不含 B 空间任何业务数据

#### Scenario: 跨 space 数据不可见

- **WHEN** 两个 Space 存在同业务键的 ReviewItem/ChangeSet
- **THEN** 各自 token 只见本空间条目（复用 016 隔离语义夹具）

### Requirement: W7 质量闸门联动（019 对齐）

019 质量闸门产生的 ReviewItem SHALL 在 W1 队列正常展示并呈现 gate 原因（profile/baseline 标识文本）；工作台 SHALL NOT 提供任何绕过闸门的强制发布动作（无此按钮、无此端点，测试断言路由表）。

#### Scenario: 无绕过端点

- **WHEN** 枚举工作台全部路由与页面动作
- **THEN** 不存在任何跳过 QualityGate/审核的发布类动作

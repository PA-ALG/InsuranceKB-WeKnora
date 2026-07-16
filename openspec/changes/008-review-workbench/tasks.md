# 008 任务（TDD 顺序；测试名引用条款号）

> 二版（2026-07-16，按 PR #11 复审修订）：W4 **整页**推迟至 PR #9（018）合入后；鉴权升级为 token→Space 授权绑定。轨道 L2。执行者 C1，**Owner 复审=A**（workbench/ 属 A 域，17 §1）。
> **实施记录（2026-07-16，执行者=Claude 架构会话，worktree `ikb-008`）**：T1~T5、T7 逐任务红绿（21 RED→GREEN + 7 守卫钉）；全量 deterministic 见 validation-report；21 号 gauntlet 补钉 1 条对称路径（双空间 token 跨路径对象探测→404）。

- [x] T1 包骨架：FastAPI app 工厂 + token→(principal+Space 集合) 授权绑定——无 token/未知 token/零配置全 401（fail-closed 默认）；越 space 403 **常量体零泄露**；允许集内但未绑定 space 仍 403（016 语义）（W5/W6）
- [x] T2 只读查询模块：队列（risk 序+筛选+分页带 total）/ ChangeSet 列表（五类动作计数聚合）/ 完整度五态格（conflict_open>pending_review>三态）；**只读性质有专测钉住**（session.dirty/new/deleted 全空）（W1.1/W2.1/W3.1）
- [x] T3 审核队列页：三动作+批量（仅非 high，排除项显式提示）；approve 走 `publish_claim` 真实发布；同决定重复→幂等 200 且发布数不变；异决定撞已决→409；**动作路由签名不收 operator 字段**——审计 actor 只认 token principal（W1/W6.3）
- [x] T4 冲突与变更页：动作分色、conflict 双方值并排+decision_basis 逐键、翻案（理由必填→新 manual_edit ChangeSet，原决定与历史不改写）、G8 时间线（数据源=ClaimRevision 修订链：谁/何时/字段/旧→新/原因）（W2）
- [x] T5 完整度矩阵页：五态分色格+下钻（Claim 值/证据引文/版本历史）+CSV/JSONL 导出（含 ticket_source 空列，011/015 交付后回填）（W3）
- [ ] T6 发布与回滚页（**PR #9 合入后开工**）：SnapshotReader 读取 + 018 可恢复回滚 dry-run→确认→执行全链；合入前仅静态占位导航（W4）
- [x] T7 守卫钉：跨 space 同业务键互不可见；**路由白名单全等断言**（无 publish/force/rollback/release 端点，W7.3）；W5.1 静态零写扫描（源级禁 session.add/delete/insert/update）；gauntlet 补钉双空间 token 跨路径对象探测→404
- [x] T8 收尾（本波次）：validation-report（波次范围）→ HANDOFF 更新 → 14 号 Runbook 工作台段落；T6 完成后补 W4 部分

## 裁决记录（设计判断及依据）

1. **审计归属从签名层面不可伪造**：动作/批量路由的 Form 签名不含 operator——不是"过滤掉客户端值"而是结构上收不到（21 号"从不变量设计"）；专测塞 `operator=mallory` 断言落库 actor=principal。
2. **幂等语义分层**：路由层先读 item——已决+同决定→200 幂等提示（服务层 `resolve_review` 的"已决拒绝"保持原语义作第二层防线，不删冗余安全层）；已决+异决定→409 刷新。
3. **W1.1"触发计数倒序"**：主链无该字段——以 risk 序+更新时间倒序替代，不造假字段（T2 查询 docstring 同步注明）。
4. **零泄露三处一致**：403 常量体；跨 space 的 changeset/drill 返回 404（对象归属校验独立于 token 授权集，双空间 token 也探不到 A 对象经 B 路径）。
5. **G8 数据源**：直接投影 ClaimRevision 不可变链，不另建时间线表（一个事实一处存储）。
6. **导出 ticket_source 空列**：011 H1.6/015 未交付，列保留为空而非编造来源（诚实边界）。
7. **依赖引入**：fastapi/jinja2/python-multipart 进 pyproject（共享文件，PR 描述显式声明）；模板 PackageLoader+autoescape。
8. **Gauntlet 返工（2026-07-17，独立红队）**：抓到 3 项 HTTP 可达缺陷（详表见 validation-report §3.5），根因统一=**工作台边界未完整翻译服务层异常谱系**：`MergeError(RuntimeError)` 漏网→500（同字段双 approve / 无证据 / 批量整批回滚丢失已成功项，违 W1），`ScopeViolation(ValueError)` 被路由 `except ValueError` 吞成 400 泄露（overturn 越权，违 W6.1）。修法从异常谱系重设计：write 路由 `except ScopeViolation: raise`（→403 常量体）+ `except MergeError`（→409 常量体，不回显内含 id）+ 批量 savepoint 部分成功 + overturn 补 `get_review_item` 预检→404 对称。红队一处判断有误（overturn→403）由 live 复现纠正为 400——**规格自测的价值在找我没想到的失败模式，不是复述我想到的**。

约束：零模型调用；不改 compiler/goldenset/adapters；对 knowledge/ 只经服务层（W5.1 静态断言钉住）。
状态：**T1~T5/T7/T8(波次) 完成 + gauntlet 返工闭合，门禁全绿（deterministic 1301 passed 零破坏）；T6 候 PR #9**。依赖：007/016/019 已合入。

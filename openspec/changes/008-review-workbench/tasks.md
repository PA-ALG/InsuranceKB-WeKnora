# 008 任务（TDD 顺序；测试名引用条款号）

> 二版（2026-07-16，按 PR #11 复审修订）：W4 **整页**推迟至 PR #9（018）合入后；鉴权升级为 token→Space 授权绑定。轨道 L2。执行者 C1，**Owner 复审=A**（workbench/ 属 A 域，17 §1）。
> **实施记录（2026-07-16，执行者=Claude 架构会话，worktree `ikb-008`）**：T1~T5、T7 逐任务红绿（21 RED→GREEN + 7 守卫钉）；全量 deterministic 见 validation-report；21 号 gauntlet 补钉 1 条对称路径（双空间 token 跨路径对象探测→404）。

- [x] T1 包骨架：FastAPI app 工厂 + token→(principal+Space 集合) 授权绑定——无 token/未知 token/零配置全 401（fail-closed 默认）；越 space 403 **常量体零泄露**；允许集内但未绑定 space 仍 403（016 语义）（W5/W6）
- [x] T2 只读查询模块：队列（risk 序+筛选+分页带 total）/ ChangeSet 列表（五类动作计数聚合）/ 完整度五态格（conflict_open>pending_review>三态）；**只读性质有专测钉住**（session.dirty/new/deleted 全空）（W1.1/W2.1/W3.1）
- [x] T3 审核队列页：三动作+批量（仅非 high，排除项显式提示）；approve 走 `publish_claim` 真实发布；同决定重复→幂等 200 且发布数不变；异决定撞已决→409；**动作路由签名不收 operator 字段**——审计 actor 只认 token principal（W1/W6.3）
- [x] T4 冲突与变更页：动作分色、conflict 双方值并排+decision_basis 逐键、翻案（理由必填→新 manual_edit ChangeSet，原决定与历史不改写）、G8 时间线（数据源=ClaimRevision 修订链：谁/何时/字段/旧→新/原因）（W2）
- [x] T5 完整度矩阵页：五态分色格+下钻（Claim 值/证据引文/版本历史）+CSV/JSONL 导出（含 ticket_source 空列，011/015 交付后回填）（W3）
- [ ] T6 发布与回滚页（**018 已随 PR #9 合入 main，依赖已解锁（2026-07-18）**；按 codex R2 裁决**本 PR 不再扩大范围——T6/W4 以独立 follow-up PR 交付**，跟踪入口=本行 + HANDOFF B8）：SnapshotReader 读取 + 018 可恢复回滚 dry-run→确认→执行全链（W4）
- [x] T7 守卫钉：跨 space 同业务键互不可见；**路由白名单全等断言**（无 publish/force/rollback/release 端点，W7.3）；W5.1 静态零写扫描（源级禁 session.add/delete/insert/update）；gauntlet 补钉双空间 token 跨路径对象探测→404
- [x] T8 收尾（本波次）：validation-report（波次范围）→ HANDOFF 更新 → 14 号 Runbook 工作台段落；T6 完成后补 W4 部分

## 裁决记录（设计判断及依据）

1. **审计归属从签名层面不可伪造**：动作/批量路由的 Form 签名不含 operator——不是"过滤掉客户端值"而是结构上收不到（21 号"从不变量设计"）；专测塞 `operator=mallory` 断言落库 actor=principal。
2. **幂等语义分层**：路由层先读 item——已决+同决定→200 幂等提示（服务层 `resolve_review` 的"已决拒绝"保持原语义作第二层防线，不删冗余安全层）；已决+异决定→409 刷新。
3. ~~**W1.1"触发计数倒序"**：主链无该字段——以 risk 序+更新时间倒序替代~~ **（PR#15 codex 评审推翻，2026-07-17）**：实现报告不得单方面覆盖规格——`ensure_review_item` 现在在 `subject["trigger"]` 维护 `count/last_at`（再触发累计、状态不重置），队列默认按触发计数倒序、risk 序与更新时间为次序（spec 原文落地）。
4. **零泄露三处一致**：403 常量体；跨 space 的 changeset/drill 返回 404（对象归属校验独立于 token 授权集，双空间 token 也探不到 A 对象经 B 路径）。
5. **G8 数据源**：直接投影 ClaimRevision 不可变链，不另建时间线表（一个事实一处存储）。
6. **导出 ticket_source 空列**：011 H1.6/015 未交付，列保留为空而非编造来源（诚实边界）。
7. **依赖引入**：fastapi/jinja2/python-multipart 进 pyproject（共享文件，PR 描述显式声明）；模板 PackageLoader+autoescape。
8. **Gauntlet 返工（2026-07-17，独立红队）**：抓到 3 项 HTTP 可达缺陷（详表见 validation-report §3.5），根因统一=**工作台边界未完整翻译服务层异常谱系**：`MergeError(RuntimeError)` 漏网→500（同字段双 approve / 无证据 / 批量整批回滚丢失已成功项，违 W1），`ScopeViolation(ValueError)` 被路由 `except ValueError` 吞成 400 泄露（overturn 越权，违 W6.1）。修法从异常谱系重设计：write 路由 `except ScopeViolation: raise`（→403 常量体）+ `except MergeError`（→409 常量体，不回显内含 id）+ 批量 savepoint 部分成功 + overturn 补 `get_review_item` 预检→404 对称。红队一处判断有误（overturn→403）由 live 复现纠正为 400——**规格自测的价值在找我没想到的失败模式，不是复述我想到的**。
9. **PR#15 codex 评审全量返工（2026-07-17，7 项阻断逐一核实全部属实并修复）**：
   - **阻断1 数据合同**：工作台曾按扁平形态猜读 `ChangeItem.proposed`，测试种子复制了同一猜测（真实 MergeEngine 写 `{"claim": …}` 嵌套）——新增知识域只读投影 `knowledge/projection.py`（`project_change_item`/`load_review_aggregate` 按 action/mode 统一解析 add/fill_unknown/append_evidence/supersede/conflict/retract/overturn），工作台与导出**只**消费 DTO；测试改由 `MergeEngine.apply_batch` 真实造数（tests/wbhelpers）。
   - **阻断2 两阶段翻案**：原 `overturn_review` 即时改事实并覆写原 resolution，违 W2.3——重写为 `request_review_overturn`（登记 pending ChangeSet + `needs_review` reversal + open 翻案审核项 risk=high；原记录/当前事实零改动；`原key+原决定+目标动作` 派生幂等 key），批准翻案审核项时才执行 K3.5 反向/正向应用（007 spec 已加对齐注记）。
   - **阻断3 并发合同**：`resolve_review` 行锁（`SELECT…FOR UPDATE`，sqlite 无害忽略）+ `expected_version`（updated_at token）stale→`ReviewStale` 409 + 异决定→`ReviewDecisionConflict` + `request_id` 重放幂等；**defer 落审计事件**（`resolution.events` 整体重赋：actor/reason/at/request_id）并推进版本；批量逐项 `key@version` 在 savepoint 内锁定。真并发用 PostgreSQL 双会话测试证明（integration_postgres lane，本机一次性 PG16 容器实跑 1 passed）。`resolution.events` 为免迁移兼容方案，非防篡改账本；如需不可变合规审计另占 0010+ 建表。
   - **阻断4 浏览器闭环**：Bearer 只可自动化——新增 `/login` 登录桥（HttpOnly+SameSite=Strict 签名 cookie，仅存 token SHA-256 摘要+过期；配置轮换即时生效）+ CSRF 双提交 + `/logout`；vendored `htmx.min.js@1.9.12`（双 CDN 哈希一致核验，见 static/vendor/VENDOR.md）经 `/static` 服务并被页面加载；queue 页补齐筛选（状态/风险/类型/产品）/分页/候选值/双方证据（引文+页码+来源+权威级）/历史/ChangeSet 链接/按 `allowed_actions` 渲染三动作+理由/非高风险批量勾选（高风险显式禁用）/翻案入口；浏览器纵向测试全程不塞 Authorization 头。
   - **阻断5 矩阵语义**：`create_app` 注入 `SchemaRegistry`——每产品版本先铺险种全字段 `unknown` 底图（未收录≠不存在）再覆盖 published 三态/pending/conflict；险种筛选；HTML 与导出复用同一 cell 投影；下钻五态（pending/conflict 不再 404；unknown 展示 schema 来源）；**缺口导出只含 unknown/pending_review/conflict_open**，`ticket_source` 稳定写 `schema:<版本>`/`review:<key>`/`conflict:<id>`（011/015 后追加外部来源，不再空列冒充）。
   - **阻断6 gate 元数据**：`_gate_ok` 压 bool 丢原因——改为结构化 `GateDecision` 全程传递；仅"运营策略允许自动化但 gate 拒绝"标 `type=quality_gate`，reason+画像版本/内容哈希/artifact/baseline id/approval 哈希持久化进 subject 与 decision_basis 并在队列呈现；W7 测试改用**真实 QualityGate** 覆盖 missing/stale/threshold 三类拒绝 + 达标对照组，禁手造 gate 工单。
   - **阻断7 可启动性**：`uvicorn` 进声明依赖；新增零参生产工厂 `create_app_from_settings`（DB/token/schema 任一缺失启动即失败，engine 在 lifespan dispose）；Runbook §3.4 只留一条可工作命令（吞错 fallback 删除）；CI 新增 `wheel-smoke` job（uv build→空 venv 装 wheel→PackageLoader/静态资源/GET /login 冒烟，本地首跑 PASS）。
   - **测试同步纠偏**：扁平种子/串行"并发"/翻案即时改事实/导出含 present/badge 词断言全部替换为正确语义断言（非旁边补新测试）；仅并行摄入竞态保留 ORM 种子但强制真实嵌套形态（`seed_parallel_open_review`，字段与 Claim 行逐项一致）。连带更新：`test_knowledge_merge`（两阶段翻案）、`test_knowledge_review`（trigger 计数/异决定异常）、`test_scope_knowledge_016`（符号更名）、`test_ci_lanes_022`（PG lane 节点集+1）。

约束：零模型调用；不改 compiler/goldenset/adapters；工作台对 knowledge/ 只经服务层（W5.1 静态断言钉住；本次返工按 codex 处方在 knowledge/ 新增投影/翻案/并发服务层能力，属服务层自身演进——与 018（PR #9）的 knowledge/ 文件域重叠面为 merge.py，合并时需一次 rebase 对账）。
10. **codex R2 复审返工（2026-07-18，2 P1+1 P2 全部核实属实并闭合，rebase main@9c4a1226）**：
   - **P1 并发令牌强制**：expected_version/request_id 曾为可选（删掉隐藏字段即绕过 CAS）——`resolve_review` 对 open 项动作强制两令牌非空（缺失→`ReviewPreconditionRequired`，零写），HTTP 路由必填（缺失 422/服务层 428 双重强制），批量严格解析 `key@version`（裸 key/空版本按 malformed 显式拒绝不降级 None，request_id 必填）；已决同决定重放仍幂等、异决定仍 409，判定全留行锁内。全部调用方（含 007/016 测试）改为"取真实版本再提交"（tests/kbhelpers.resolve_with_version / wbhelpers.post_action），浏览器纵向测试的令牌**从页面 hidden 字段解析**。
   - **P1 分页成本模型**：曾全量取出 space 内 ReviewItem 再逐条投影（20 条实测 123 SQL）——`subject` 增写 `product_version_id` 稳定维度（无迁移；本仓库无生产存量故不做 backfill，无该键旧行不参与产品过滤），筛选/COUNT/trigger 计数倒序/LIMIT 全部下沉 SQL（JSON 表达式跨方言），新增 `load_review_aggregates` 批量投影（固定 5 条 IN 预取）；`change_set_detail` 关联审核项、`cell_drill` 待审/冲突定位同步 SQL 化。SQL 预算测试钉死：limit=20 在总量 20 与 200 时查询数**完全相等且 ≤10**。
   - **P2 投影边界**：`load_review_aggregate(s)`/`project_change_item` 曾不校验传入 ORM 对象归属——入口强制 `space_id`/经 ChangeSet 归属校验，跨 space 直接调用 → `ScopeViolation`（两条反例测试钉住）。
   - **对账**：rebase 取并集（`knowledge/__init__.py` 008+018 导出、`POSTGRES_NODES` 三节点 017/018/008、HANDOFF 以 main 已合入 018 为基线）；W4/T6 依赖措辞随 018 合入更新（不扩大本 PR，follow-up PR 交付）；报告措辞对齐"已验证事实"（不再在复审结论前写"全部闭合"）。

约束（同上）；状态：**T1~T5/T7/T8(波次) + R1 七项阻断 + R2 三项发现均已修复，rebase main 后门禁全绿（数字见 validation-report §1）；待 codex 终审；T6/W4 以 follow-up PR 交付（018 已解锁）**。依赖：007/016/018/019 已合入。

# 008 验收报告——T1~T5/T7 波次（2026-07-18，R1 七项阻断 + R2 三项发现返工后，rebase main@9c4a1226）

> 范围声明：本波次交付 W1/W2/W3/W5/W6/W7.3；**W4（发布与回滚页，T6）按 spec 候 PR #9（018）合入后交付**，届时补充本报告 W4 部分。零模型调用。
> 版本说明：2026-07-16 首版报告在 PR#15 codex 评审（7 项阻断全部核实属实）后**整体作废重写**——首版的"完成"结论建立在部分验证错误语义的测试上（扁平 proposed 种子/串行冒充并发/翻案即时改事实/缺口导出含 present），按"测试与文档同步纠偏"要求，本版全部证据来自返工后的正确语义测试。

## 1. 门禁（fresh，worktree `ikb-008` @ feat/008-review-workbench，R2 返工 + rebase main 后）

| 项 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy | Success，**209 files** |
| deterministic lane | **1562 passed / 8 deselected**（rebase 后基线含 018 全部用例；R2 净增 4 条验收测试） |
| PostgreSQL lane | **3 passed**（017 并发 + 018 release publisher + **008 双会话行锁**）——本机一次性 PG16 容器实跑；CI service lane 以 push 后为准 |
| wheel-smoke | 本地 PASS（uv build → 空 venv 装 wheel → PackageLoader/HTMX 静态/GET /login）；CI job 以 push 后为准 |
| 008 focused | **56 passed / 1 deselected(PG)**：`test_review_workbench_008.py` 44 + `test_redteam_008_findings.py` 9 + `test_workbench_concurrency_008.py` 3（另 1 条 PG lane 本机实跑 passed） |

连带更新声明（非 008 文件域）：`knowledge/merge.py`（两阶段翻案/行锁并发/gate 结构化决定）、`knowledge/review.py`（trigger 计数）、`knowledge/projection.py`（**新**，只读投影）、`knowledge/__init__.py`（导出）、007 spec K3.5 对齐注记、`test_knowledge_merge/review`、`test_scope_knowledge_016`（`overturn_review`→`request_review_overturn`）、`test_ci_lanes_022`（PG lane 节点集+1）、`config.py`（+3 工作台设置）、`pyproject.toml`（+uvicorn）、CI（+wheel-smoke job）。**与 PR #9（018）的重叠面 = knowledge/merge.py，后合者需 rebase 对账。**

## 2. 条款 → 证据（测试名；主正向用例全部经真实 MergeEngine 造数）

| 条款 | 证据 |
|---|---|
| W5.2 鉴权 | `test_w5_2_no_token_401` / `_unknown_token_401` / `_no_tokens_configured_denies_all_fail_closed`（零配置=拒绝一切） |
| W5 浏览器闭环 | `test_w5_browser_login_then_full_review_without_bearer`（login→cookie→点击队列→表单 approve **全程无 Authorization 头**、真实发布）/ `_logout_invalidates_browser_session` / `test_w5_htmx_vendored_and_loaded`（本地 vendor + 页面加载）/ `test_control_forged_session_cookie_rejected`（伪造签名→401） |
| W6.1 Space fail-closed | `test_w6_1_token_cannot_cross_space_403_zero_leak` / `_allowed_space_ok` / `_unbound_space_fail_closed_403`（016 语义）/ `test_w6_browser_cookie_cannot_cross_space`（cookie 通道同语义） |
| W6 CSRF | `test_w6_browser_session_csrf_required_on_writes`（cookie 写请求缺 CSRF→403 且零写；Bearer 豁免） |
| W6.2 跨空间不可见 | `test_w6_2_cross_space_same_business_key_invisible` + `test_w6_2_cross_space_object_id_probe_404_not_leak` |
| W6.3 审计归属 | `test_w6_3_audit_actor_is_token_principal_not_client_field` |
| W1.1 队列 | `test_w1_1_queue_shows_real_candidate_value_and_evidence`（**真实合并数据**：候选值/引文/权威级/产品/ChangeSet 链接）/ `_queue_filters_and_pagination` / `test_w1_1_trigger_count_desc_is_default_order`（**触发计数倒序默认**——spec 原文，压过 risk 序） |
| W1.3/W1.4 动作 | `test_w1_3_approve_publishes_and_resolves` / `test_w1_3_defer_keeps_open_but_audits`（defer 落 actor/时间/理由事件并**推进版本**）/ `test_w1_4_stale_version_rejected_409`（乐观并发：过期版本拒绝+带新版本成功）/ `_same_action_resubmit_idempotent` / `_request_id_replay_does_not_duplicate` / `_conflicting_action_on_resolved_409` / `test_w1_3_batch_approve_versioned_excludes_high`（逐项 `key@version`；高风险与 stale 项显式点名） |
| W1.4 真并发 | `test_w1_4_live_postgresql_two_sessions_single_apply`（**PostgreSQL 双会话**：s2 阻塞于 FOR UPDATE，s1 提交后 s2 幂等；publish revision 恰 1；第三方异决定→冲突）+ 服务层状态机 3 用例（`test_workbench_concurrency_008.py`） |
| W2.1/W2.2 | `test_w2_1_changes_page_lists_sets_with_counts` / `test_w2_2_detail_projects_real_merge_shapes`（真实 add/supersede/enrich-append 形态：predicate/提案值非 None、冲突双方值+证据+authority_cmp 依据并排） |
| W2.3 翻案（两阶段） | `test_w2_3_overturn_two_phase_via_http`：登记后**旧事实仍 published、原 resolution 未变、新 ChangeSet pending、翻案审核项 open(risk=high)**；重复请求幂等；**批准翻案审核项后**事实才变化且原记录仍不可变。服务层双向：`test_k3_5_overturn_creates_new_changeset`（approve→reject 反向）/ `test_k3_5_overturn_reject_of_request_keeps_facts`（拒绝复议→事实不变） |
| W2.4/G8 | `test_w2_4_timeline_human_readable_rows` |
| W3.1 | `test_w3_1_matrix_full_schema_baseline_zero_claim_product`（**零 Claim 产品仍有全字段底图**）/ `test_w3_1_matrix_five_states_from_real_merge`（conflict_open>pending_review>三态；unknown=未收录） |
| W3.2 | `test_w3_2_pending_and_conflict_drill_not_404`（待审/冲突格下钻可用：候选值/双方值）/ `test_w3_2_published_drill_and_unknown_drill`（published 值+引文+修订史；unknown 展示"未收录≠不存在"+schema 来源；非 schema 无数据→404） |
| W3.3 | `test_w3_3_gap_export_excludes_present_and_labels_sources`（**缺口导出不含 present/absent**；ticket_source=`schema:<版>`/`review:<key>`/`conflict:<id>`） |
| W5.1 只读/零直写 | `test_w5_1_queries_readonly_no_pending_writes` + `test_w5_1_static_no_direct_sql_writes_in_workbench` |
| W7 gate 联动 | `test_w7_real_gate_denials_create_quality_gate_reviews`（**真实 QualityGate** missing/stale/threshold 三类拒绝→type=quality_gate+原因/画像/基线标识持久化）/ `test_w7_gate_reason_rendered_in_queue`（队列呈现原因+baseline 标识）/ `test_w7_policy_off_denial_is_not_quality_gate_type`（策略关→low_confidence，不伪造 gate 元数据）/ `test_w7_passing_gate_with_policy_auto_publishes`（达标对照组） |
| W7.3 无绕过 | `test_w7_3_route_allowlist_no_bypass_endpoints`（含 login/logout/home 的白名单全等 + 关键词禁令） |

## 3. 21 号 gauntlet 结果

逐行过表：构造期约束在模型 ✓；判定单源（并发判定收口服务层行锁内，路由不再预读）✓；对称路径（跨路径对象探测 404；cookie/Bearer 双通道同 403 语义）✓；fail-open 无（五类异常处理器 + 零配置拒绝 + CSRF fail-closed + 生产工厂缺配置启动即死）✓；无后门（路由白名单全等）✓；文档不过度声称（本报告版本说明 + PG/CI 复证待 push 如实标注）✓。

## 3.5 Fresh-eyes 红队返工（2026-07-17，独立 agent + live 复现）

（保留首轮红队记录：3 项 HTTP 可达缺陷已修 + 回归钉见 `test_redteam_008_findings.py`。根因：路由只预期 `ValueError`，真实谱系 `{ScopeViolation(ValueError), MergeError(RuntimeError)}`。修法：`except ScopeViolation: raise`→403 常量体；`except MergeError`→409 常量体；批量 savepoint 部分成功；overturn 预检 404 对称。）

## 3.6 PR#15 codex 评审返工（2026-07-17，7 项阻断全部属实、全部闭合）

核实结论与修法逐项见 tasks.md 裁决记录 9；对应反例测试（codex 8 个失败反例的固化）：

| 阻断 | 反例测试（返工后 GREEN） |
|---|---|
| 1 数据合同 | `test_w1_1_queue_shows_real_candidate_value_and_evidence` / `test_w2_2_detail_projects_real_merge_shapes` / `test_w3_1_matrix_five_states_from_real_merge` |
| 2 两阶段翻案 | `test_w2_3_overturn_two_phase_via_http` / `test_k3_5_*` 双向 |
| 3 并发+defer 审计 | `test_w1_4_stale_version_rejected_409` / `test_w1_3_defer_keeps_open_but_audits` / PG 双会话用例 |
| 4 浏览器闭环 | `test_w5_browser_login_then_full_review_without_bearer` 等 5 条 |
| 5 矩阵语义 | `test_w3_1_matrix_full_schema_baseline_zero_claim_product` / `test_w3_2_pending_and_conflict_drill_not_404` / `test_w3_3_gap_export_excludes_present_and_labels_sources` |
| 6 gate 元数据 | `test_w7_real_gate_denials_create_quality_gate_reviews` 等 4 条 |
| 7 可启动性 | `scripts/wheel_smoke_workbench.py` 本地 PASS + CI `wheel-smoke` job（push 后复证） |

## 3.7 codex R2 复审返工（2026-07-18，2 P1 + 1 P2 全部属实、全部闭合）

核实结论与修法见 tasks.md 裁决记录 10；反例固化测试：

| 发现 | 反例测试（返工后 GREEN） |
|---|---|
| P1 并发令牌可选可绕过 | `test_w1_4_missing_tokens_rejected_zero_write`（缺/空令牌 422 零写）/ `test_w1_4_service_layer_precondition_required`（服务层 428 分支）/ 批量 malformed 断言并入 `test_w1_3_batch_approve_versioned_excludes_high`；全部正向 HTTP 测试改"取真实版本再提交"（浏览器纵向流从页面 hidden 字段解析令牌） |
| P1 分页库外执行 | `test_w1_1_queue_sql_budget_constant_wrt_total`：limit=20 在总量 20 与 200 时 SQL 数**完全相等且 ≤10**；产品过滤 total 语义保持正确 |
| P2 投影缺 scope 校验 | `test_w6_projection_rejects_foreign_orm_objects`：`load_review_aggregate(s)`/`project_change_item` 传入跨 space ORM 对象 → `ScopeViolation` |

## 4. 残留与交接

- **T6/W4**：018 已随 PR #9 合入 main（依赖解锁）；按 codex R2 裁决**本 PR 不扩大范围——T6/W4 以独立 follow-up PR 交付**（跟踪：tasks.md T6 + HANDOFF B8）；
- **rebase 已完成**（main@9c4a1226，018 并集对账：`knowledge/__init__.py` 双侧导出、`POSTGRES_NODES` 三节点、HANDOFF 以 main 事实为基线）；
- `resolution.events` 是免迁移的审计兼容方案（满足 W1 审计条款），**不是防篡改账本**——若合规要求不可变审计流水，按注册表占 0010+ 迁移号建 `review_action_events` 表，不在本 PR 私自抢号；
- `subject.product_version_id` 为本版新写维度：本仓库无生产存量故不做 backfill；若未来出现无该键的历史行，其不参与产品过滤（已在查询 docstring 声明）；
- CI 复证：PostgreSQL lane（三节点）与 wheel-smoke job 的绿色以 push 后 CI 为准（CI 绿才算绿）；本机等价实跑（一次性 PG16 容器 / 空 venv wheel）已通过；
- 当前状态 = **待 codex 终审，未合入 main**。

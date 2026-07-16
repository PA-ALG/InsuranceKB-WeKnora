# 008 验收报告——T1~T5/T7 波次（2026-07-16）

> 范围声明：本波次交付 W1/W2/W3/W5/W6/W7.3；**W4（发布与回滚页，T6）按 spec 候 PR #9（018）合入后交付**，届时补充本报告 W4 部分。零模型调用。

## 1. 门禁（fresh，worktree `ikb-008` @ feat/008-review-workbench）

| 项 | 结果 |
|---|---|
| ruff | All checks passed |
| mypy | Success，184 files |
| deterministic lane | **1301 passed / 5 deselected**（gauntlet 返工后：+8 红队回归钉，既有零破坏） |
| 008 focused | 28（W 条款）+ 8（红队回归 `test_redteam_008_findings.py`）passed |

## 2. 条款 → 证据（测试名）

| 条款 | 证据 |
|---|---|
| W5.2 鉴权 | `test_w5_2_no_token_401` / `_unknown_token_401` / `_no_tokens_configured_denies_all_fail_closed`（零配置=拒绝一切） |
| W6.1 Space fail-closed | `test_w6_1_token_cannot_cross_space_403_zero_leak`（403 常量体，不回显目标 space）/ `_allowed_space_ok` / `_unbound_space_fail_closed_403`（016 语义）/ CLI 级同套 |
| W6.2 跨空间不可见 | `test_w6_2_cross_space_same_business_key_invisible` + **gauntlet 补钉** `test_w6_2_cross_space_object_id_probe_404_not_leak`（双空间 token 用 A 对象 id 走 B 路径 → 404） |
| W6.3 审计归属 | `test_w6_3_audit_actor_is_token_principal_not_client_field`——路由签名不收 operator（结构性不可伪造），塞 mallory 落库仍 alice |
| W1.1 队列 | `test_w1_1_queue_query_filters_sorts_paginates`（risk 序/筛选/分页 total）+ `_queue_page_renders_items_with_badges` |
| W1.3/W1.4 动作 | `test_w1_3_approve_publishes_and_resolves`（**真实 publish_claim**，published 恰 1）/ `_reject_and_defer`（defer 保持 open 零 resolution）/ `test_w1_4_same_action_resubmit_idempotent`（发布数不变）/ `_conflicting_action_on_resolved_409` / `test_w1_3_batch_approve_excludes_high`（排除项显式点名） |
| W2.1/W2.2 | `test_w2_1_changes_page_lists_sets_with_counts` / `test_w2_2_detail_shows_conflict_both_sides_and_basis`（双方值并排 + decision_basis + action 分色） |
| W2.3 翻案 | `test_w2_3_overturn_creates_new_changeset_history_intact`：理由必填（缺→422）；新 manual_edit ChangeSet 恰 1；原 ChangeItem 决定不变；被采纳 Claim 转 retracted |
| W2.4/G8 | `test_w2_4_timeline_human_readable_rows`（ClaimRevision 投影：谁/何时/字段/旧→新/原因） |
| W3.1~W3.3 | `test_w3_1_matrix_page_renders_state_cells`（五态分色）/ `test_w3_2_cell_drilldown_shows_claim_evidence_history`（值+引文+修订史）/ `test_w3_3_export_csv_and_jsonl`（含 ticket_source 空列——011/015 前不编造来源） |
| W5.1 只读/零直写 | `test_w5_1_queries_readonly_no_pending_writes`（session 状态断言）+ `test_w5_1_static_no_direct_sql_writes_in_workbench`（源级扫描） |
| W7.3 无绕过 | `test_w7_3_route_allowlist_no_bypass_endpoints`（路由表**全等**断言 + publish/force/rollback/release 关键词禁令）；gate 类型工单展示见 `test_w1_1_..._badges` |

## 3. 21 号 gauntlet 结果

逐行过表：构造期约束在模型（Grant principal 非空白 validator、space_ids 非空）✓；判定单源（幂等判定读同一 DB 行，服务层"已决拒绝"保留为第二层）✓；对称路径——**补钉 1 条**（跨路径对象探测 404，见 W6.2 行）；fail-open 无（四类异常处理器 + 零配置拒绝）✓；无后门（路由白名单全等）✓；文档不过度声称（本报告范围声明与 ticket_source 空列）✓。

## 3.5 Fresh-eyes 红队返工（2026-07-17，独立 agent + live 复现）

逐行过表外补独立红队，抓到 3 项 HTTP 可达缺陷，均已修 + 8 条回归钉（`test_redteam_008_findings.py`）。根因统一：**路由只预期服务层抛 `ValueError`，而真实异常谱系为 `{ScopeViolation(ValueError), MergeError(RuntimeError)}`**——过窄（MergeError 漏网→500）且对 ScopeViolation 过宽（子类被 `except ValueError` 吞成 400 泄露）。

| # | 级别 | 缺陷 | 修复 |
|---|---|---|---|
| **A** | **高** | 同字段二次 approve →未处理 `MergeError`→**500**；批量撞冲突→**整批回滚**丢失已成功项（违 W1） | `except MergeError`→**409 常量体**（不回显内含的他项 claim id）；批量每条 `begin_nested` savepoint→部分成功 |
| A2 | 中 | 无证据候选 approve →同样 500 | 同 A（MergeError→409） |
| F1 | 中 | overturn 越权探测返回 `400 "scope mismatch"`（泄露原因，W6.1 违例） | 补 `get_review_item` 预检→404（与 action/读路径对称）+ `except ScopeViolation: raise` |

回归钉断言修复后正确行为：双 approve→409 常量体（`vid` 不泄露）、批量部分成功 published==1、overturn 外键→404 不泄露、以及对照组（畸形 id 无 500 / 空 Bearer 401 / operator 不可伪造 / 字符串 space_ids fail-closed）。**红队一处判断有误**（称 overturn 越权→403），由本地 live 复现纠正为实际 400——"逐条对源验证、送审前 live 复现"当场兑现。

## 4. 残留与交接

- T6/W4：候 PR #9——SnapshotReader 读取 + 018 可恢复回滚全链，届时按 spec Scenario 补两用例并更新路由白名单断言；
- 生产部署：`workbench_tokens_json` 配置见 config.py 注释与 14 号 Runbook §工作台；wheel 打包需确认 templates 随包（hatchling 默认含包内数据，CI 装包冒烟可在 T6 波次一并验证）；
- HTMX 静态资源：当前模板为服务端渲染骨架（属性已挂），htmx.js 本地引入随 T6 波次完成（不引 CDN——自包含纪律）。

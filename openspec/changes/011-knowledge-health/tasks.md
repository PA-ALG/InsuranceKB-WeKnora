# 011 任务（TDD 顺序；测试名引用条款号）

> 四版（2026-07-21，PR #22 fast-follow）：T3 改为远端/输入/工具链独立证据轴并覆盖多信号与不可归因退化；T6 对齐 024 durable attempt ledger。三版（2026-07-18，codex PR #12 复审收口）：T3 升级三方对账；新增 typed provider/持久基准/typed subject。轨道 L4 件。执行者 Owner=C（新包），**typed subject 接线（review 服务）+ 迁移 0010 属 Owner-A 复审**。

- [ ] T1 模块骨架 + Space 枚举/显式 space fail-closed + 报告双格式（markdown+JSON）骨架 + degraded 语义（H1/H1.8/H2）
- [ ] T2 过期/积压扫描器（**字段名对齐实际模型**：`claims.effective_to`、`ReviewItem(status=open)`）（H1.1/H1.2）
- [ ] T3 漂移三方对账：A=冻结页面 / B=WeKnora adapter 实读 / C=显式版本重编——页面关系、规范化 input_identity、toolchain_identity 独立取证；用真值表覆盖 A=C 时身份双变仍双报、A≠C+身份缺失时保留 local_render_drift/已知轴并 degraded、身份均相同却 A≠C 时 unclassified；B+C 与三轴同时变化零漏报（H1.3a）
- [ ] T4 退化扫描器 + 迁移 0010：completeness_snapshots + **health_runs/health_findings（不可变 run 基准：scanner/config 版本、provider watermark、分维度分数）**（H1.4/H2）
- [ ] T5 孤立（**009 未落地报 not-applicable**）+ 同类对比缺口（阈值可配）（H1.5/H1.6）
- [ ] T6 typed provider 合同：四源 ok|unavailable|stale + watermark；用不可变 020 registry snapshot 的 Space-scoped 全量已准入 run 集合，按 `(sequence,run_id)` 稳定消费 024 ledger+最终产物；watermark 冻结 namespace/revision/complete-through/snapshot hash，覆盖多 run 排列、旧失败保留、过期/回退/重复/缺工件或 digest 不符时整体 degraded；017 无 durable failure ledger 显式 unavailable，021 SourceEvent 不冒充解析失败账本（H1.7/H1.8）
- [ ] T7 工单集成：`health_finding_id` typed subject（复合 FK 闭 Space，**不走 ensure_review_item extra=ignore 旁路**；Owner-A）+ 稳定 ID 幂等/不复活 + `--open-tickets` dry-run 规范 + 总分/趋势从持久 run 重放（H2）
- [ ] T8 端到端：七类夹具全检出（含 provider 缺失 degraded、跨 Space subject 拒绝、趋势重放）+ 干净夹具（全 provider ok）零工单 + 收尾（validation-report → HANDOFF）（H3）

约束：零模型调用；只读主链表+冻结快照+adapter 只读回读；写仅 007 服务层开单 + 0010 自有表；不改 compiler/goldenset；迁移仅 0010。
状态：**已条款化，PR #12 主规格与 PR #22 fast-follow 修订均已写入本规格；011 本体可认领**。依赖：007/016/018 已合入；020 registry 未就绪时 H1.8 provider 按合同 degraded，不阻塞软件实现；H1.5 依赖 009（未落地报 not-applicable，不阻塞其余扫描器）。

# 013 MVP Core Profile（不代表完整 013 完成）

> 适用范围：2026-07-21 批准的 23-source MVP。029 提供批准快照 serving contract；032 提供独立人类阅读面。

## 本轮必须交付

1. `resolve_product(query, as_of_date?)`：exact/alias/candidates，不猜测；
2. `get_product_facts(product_id, as_of_date?, fields?)`：只读 `ApprovedSnapshotReader`，返回 `snapshot_id + manifest_hash + canonical facts`；
3. `get_claim_evidence(claim_id)`：只读冻结 Evidence，structured 分支无伪 page/chunk；
4. 稳定 response envelope、typed not-found、token→Space fail closed、零模型/零写；
5. 官方 Python MCP SDK 的本地 transport/service contract；若本轮未执行真实 WeKnora HTTP Streamable 挂载，validation report 必须标 `NOT RUN`。

## 本轮明确后置

- `compare_products`、完整历史矩阵和高级查询；
- SSE 兼容层、生产部署/限流/完整 SSO；
- 真实 WeKnora Agent 挂载（除非 030 live 环境确有可复验证据）。

## 状态口径

MVP 通过时只能报告“013 core PASS”；M1 四工具、M4 完整远程传输和 M5 全故事仍按实际证据标 PARTIAL/NOT RUN，不得把 SDK contract 冒充 WeKnora live。

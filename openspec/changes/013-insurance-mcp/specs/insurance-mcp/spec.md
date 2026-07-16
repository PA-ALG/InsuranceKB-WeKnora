# 013 insurance MCP server 验收规格

> 二版（2026-07-16）：正式 delta 格式。条款映射：旧 M1/M2 沿用；旧 M4（快照/Space）→ M3；**新增 M4 传输与集成**（修复一版事实错误：一版称 WeKnora"stdio+SSE 都吃"，实际 `internal/mcp/manager.go` 明确**禁用 stdio**、只收 SSE 或 HTTP Streamable）；旧 M3 验收 → M5。

## ADDED Requirements

### Requirement: M1 四个只读工具

server SHALL 提供四个只读、确定性工具：`resolve_product(query, as_of_date?)`（exact→alias→candidates 三级，绝不单选猜测；as_of_date 过滤版本生效区间，无适用版本返回 not_found(reason=no_version_at_date)）；`get_product_facts(product_id, as_of_date?, fields?)`（仅日期适用的已发布事实，每项含 value/tri_state/data_quality/confidence/evidence_summary/claim_id）；`get_claim_evidence(claim_id)`（全证据链：引文/页码/来源文档/权威等级/审核摘要/revision 列表；非 published 一律 not_found，不泄露存在性）；`compare_products(product_ids≤5, fields)`（产品×字段矩阵，缺值显式 unknown 并注明"未收录≠不存在"）。

#### Scenario: 产品解析绝不猜测

- **WHEN** 查询命中多个候选产品（如系列名"盛世金越"）
- **THEN** 返回 candidates 列表（含区分依据），不单选

#### Scenario: 按日期取当时事实

- **WHEN** 以历史日期（如 2023-06-01）查询某产品等待期
- **THEN** 返回该日期适用版本的已发布值与证据摘要，而非当前版本

#### Scenario: 证据链不泄露未发布内容

- **WHEN** 请求 draft/candidate Claim 的证据链
- **THEN** 返回 not_found（与"不存在"不可区分）

### Requirement: M2 响应信封与拒答语义

每个响应 SHALL 含：as_of_date（缺省=今天，回显）、schema_version、disclaimer（purpose 配置注入的"以条款原文为准"文案）、trace_id（Langfuse 关联）；拒答 SHALL 用统一 not_found 结构（reason 枚举：unknown_product/no_version_at_date/claim_not_published/coverage_gap 等），SHALL NOT 用空数组代替；整个包对 DB SHALL 只开只读事务（测试覆盖）。

#### Scenario: 拒答结构化

- **WHEN** 查询不存在的产品
- **THEN** 返回 not_found(reason=unknown_product) 结构，非空数组、非异常泄露

### Requirement: M3 快照读取与 Space 对齐（016/018）

一切事实读取 SHALL 经 018 SnapshotReader（published ReleaseSnapshot 投影），mutable Claim 表不出现在读路径；coverage gap 沿用 018 类型化 gap code 映射进拒答结构，不编造；每次调用 SHALL 在显式 KnowledgeSpace 内（token 绑定或参数显式），space 未知/未绑定 fail-closed，跨 space 产品一律 not_found（不泄露存在性）；curated-first：默认仅 curated 快照事实，RAW 回退遵循 018 fallback 配置（默认关闭），发生回退时响应 SHALL 显式标注 raw_fallback。实现基线 = PR #9 合入后的 main；测试夹具用 018 published snapshot fixture 构造，不 mock 读模型语义。

#### Scenario: 只读已发布快照

- **WHEN** 某 Claim 在快照发布后被 enrich/retract
- **THEN** 工具仍返回发布时的事实与证据（快照投影），mutable 表无读取

#### Scenario: 跨 space 不泄露存在性

- **WHEN** token 绑定 Space A 的连接查询 Space B 的产品
- **THEN** 返回 not_found（与不存在不可区分），无任何 B 空间数据泄露

### Requirement: M4 传输与 WeKnora 集成

主传输 SHALL 为 **HTTP Streamable**（WeKnora `MCPManager`/client 仅接受 SSE 或 HTTP Streamable，**stdio 被明确禁用**；MCP 现行规范亦以 Streamable HTTP 为远程主路径）；SSE SHALL 仅作兼容层；stdio 最多用于本地 SDK 单测，SHALL NOT 作为 WeKnora 集成验收形态。官方 Python `mcp` SDK 版本 SHALL 固定经验证的版本范围（锁定于 pyproject）；SHALL 提供最小集成合同测试：以 WeKnora MCP client 的传输形态（HTTP Streamable）连接并完成一次工具调用往返。服务默认 loopback 监听；连接级 token 鉴权（M3 的 space 绑定载体）。

#### Scenario: Streamable HTTP 往返合同

- **WHEN** 以 HTTP Streamable 传输连接 server 并调用 resolve_product
- **THEN** 完成一次符合 MCP 协议的完整往返（SDK 测试客户端断言）

#### Scenario: stdio 不作为集成验收

- **WHEN** 检查集成验收用例清单
- **THEN** 不存在以 stdio 传输断言 WeKnora 挂载能力的用例（stdio 仅限本地单测标注）

### Requirement: M5 端到端验收

在 007/018 夹具库上，SDK 测试客户端 SHALL 走通完整故事："2023-06-01 投保的产品等待期" → resolve(as_of_date) → get_facts 返回当时版本值与证据；停售产品返回历史版本+销售状态标注；多义名返回候选；draft/candidate 不可见；零模型调用、门禁全绿；真实 WeKnora Agent 挂载联调登记 L6/B10（须真实实例，不计入本 change 验收）。

#### Scenario: 版本敏感问答端到端

- **WHEN** 按历史投保日期询问某产品等待期（夹具含两个版本）
- **THEN** 返回投保时点适用版本的值、证据摘要与免责声明信封

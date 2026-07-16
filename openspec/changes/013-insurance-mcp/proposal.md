# 013 · insurance MCP server（版本敏感问答通道）

> 状态：**规格就绪（正式 delta 格式）**（2026-07-16 二版：新增 M3 快照/Space 对齐 + **M4 传输修正**——一版"stdio+SSE 都吃"与 WeKnora 事实不符，`internal/mcp/manager.go` 禁用 stdio、只收 SSE/HTTP Streamable，故主传输改 **HTTP Streamable**；业务方同日拍板从 M2 提前，轨道 L3，见 docs/insurance-kb/22）。**实现等 PR #9（018）合入后开工**——读路径走 SnapshotReader。
> 设计权威：02 §2 插件2、03（Claim/版本模型）、20（企业运行约束）、14 §4 L6、MCP transports 规范（Streamable HTTP 为远程主路径）。

## 为什么做

插件架构下"按保单时间过滤版本"不进 WeKnora 检索管线（ADR-001 的代价），补偿机制就是本组件：WeKnora Agent 原生支持挂 MCP 工具，历史版本、证据链、产品对齐类问题经这里回答。没有它，L6（Agent 端到端）只能答"当前有效"知识。

## 做什么（官方 python `mcp` SDK，落点 harness/src/insurance_harness/mcp/）

工具面（首批 4 个，全部只读、确定性）：

1. `resolve_product(query, as_of_date?)`：产品名/别名/planCode → 产品 + 适用版本（复用 003 别名索引；as_of_date 命中 version 生效区间）；多义返回候选列表不猜；
2. `get_product_facts(product_id, as_of_date?, fields?)`：按日期取当时 published 的 Claim 集（默认今天=当前有效）；每个值带 data_quality/confidence/证据摘要；
3. `get_claim_evidence(claim_id)`：完整证据链（原文引文、页码、来源文档、权威等级、审核记录、版本历史）；
4. `compare_products(product_ids, fields)`：同字段跨产品对照表（结构化返回，供 Agent 生成对比回答）。

横切要求：
- 每个响应带 `as_of_date`、schema_version、免责声明字段（"以条款原文为准"，purpose 配置注入）；
- 权限：MCP 连接鉴权（token）+ 租户隔离（只读该租户 Claim）；未发布/候选知识一律不可见；
- 拒答语义：查无产品/日期无适用版本时返回明确的 not_found 结构而非空猜（Agent 端统一拒答口径，master plan"统一 Agent 引用和拒答策略"）；
- 传输：**HTTP Streamable 主路径**（WeKnora `MCPManager` 禁用 stdio、只收 SSE/HTTP Streamable），SSE 仅兼容层，stdio 仅本地 SDK 单测（M4）。

## 验收

用 007 夹具库：Agent 侧模拟调用（mcp SDK 测试客户端）——"2023 年投保的 X 产品等待期" 经 resolve+get_facts(as_of_date) 返回当时版本的 Claim 与证据；停售产品返回历史版本 + 销售状态标注；多义名返回候选；候选/draft Claim 不可见。零模型调用；门禁全绿。在 WeKnora 真实实例挂载联调列 B10-L6。

## 不做什么

写操作（一切写走审核链路）、检索排序（WeKnora 职责）、规则引擎计算（master plan 规则可执行化是独立后续项）。

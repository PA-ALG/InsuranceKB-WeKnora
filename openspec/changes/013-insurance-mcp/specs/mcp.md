# 013 规格（验收条款）

> **2026-07-16 基础对齐修订**：本规格原写于 016/018 落地之前。新增 M4（快照读取与 Space 对齐）；M1/M2 原条款 ID 不变，其中"published Claim"的读取口径由 M4.1 收紧为 018 快照投影。

## M1 工具面

- M1.1 `resolve_product(query, as_of_date?)`：exact（planCode/备案文号/全名）→ alias → 多义返回 candidates[]（含区分依据），**绝不单选猜测**；as_of_date 过滤 version 生效区间，无适用版本返回 not_found(reason=no_version_at_date)；
- M1.2 `get_product_facts(product_id, as_of_date?, fields?)`：仅 published 且日期适用的 Claim；每项含 value/tri_state/data_quality/confidence/evidence_summary(页码+短引文)/claim_id；fields 过滤支持 field_id 与风险等级；
- M1.3 `get_claim_evidence(claim_id)`：全证据链（引文/页码/来源文档/权威等级/审核记录摘要/版本历史 revision 列表）；非 published Claim 返回 not_found（**不泄露存在性**）；
- M1.4 `compare_products(product_ids≤5, fields)`：矩阵结构返回（产品×字段），缺值格子显式 unknown 并注明"未收录≠不存在"。

## M2 横切

- M2.1 每个响应信封：as_of_date（缺省=今天，回显）、schema_version、disclaimer（purpose 配置注入的"以条款原文为准"文案）、trace_id（Langfuse 关联）；
- M2.2 鉴权：连接级 token；租户隔离（token 绑租户，跨租户产品 not_found）；
- M2.3 拒答语义统一：not_found 结构（reason 枚举：unknown_product/no_version_at_date/claim_not_published/…），禁止空数组代替；
- M2.4 stdio 与 SSE 两种传输同一实现（官方 mcp SDK server）；
- M2.5 只读断言：整个包对 DB 会话只开只读事务（测试覆盖）。

## M4 快照读取与 Space 对齐（016/018）

- M4.1 一切事实读取经 **018 SnapshotReader**（published ReleaseSnapshot 投影）；mutable Claim 表不出现在读路径；coverage gap 沿用 018 类型化 gap code，映射进 not_found.reason 或响应 gap 字段，**不编造**；
- M4.2 每次调用在显式 KnowledgeSpace 内（token 绑定或参数显式）；space 未知/未绑定 fail-closed；跨 space 产品一律 not_found（不泄露存在性，016 语义）；
- M4.3 curated-first：默认仅返回 curated 快照事实；RAW 回退遵循 018 fallback 配置（默认关闭），若发生回退，响应必须显式标注来源为 raw_fallback；
- M4.4 实现基线：PR #9（018）合入后的 main；测试夹具用 018 的 published snapshot fixture 构造，不 mock 读模型语义。

## M3 验收

- M3.1 夹具库上 SDK 测试客户端全流程："2023-06-01 投保的盛世金越等待期" → resolve(as_of_date) → get_facts 返回当时版本值与证据；
- M3.2 停售产品：返回历史版本 + 销售状态标注；多义名（盛世金越 系列）返回候选；draft/candidate Claim 不可见；
- M3.3 零模型调用；门禁全绿；真实 WeKnora Agent 挂载联调 = 14 §4 L6（B10）。

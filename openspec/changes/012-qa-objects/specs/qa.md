# 012 规格（验收条款）

## Q1 数据模型

- Q1.1 qa_items 表（Alembic 增量）：question、intent_fingerprint、answer、answer_claim_ids(JSON, 非空校验在服务层)、entity_refs（产品/概念）、qa_type(authoritative|derived)、status（复用 007 状态机）、effective 区间、source、external_record_id；
- Q1.2 **硬门禁：answer_claim_ids 为空或含非 published Claim 的 QA 不得发布**（服务层校验 + 测试覆盖绕过路径）。

## Q2 权威 QA 通道

- Q2.1 消费 010 的 qa_staging：答案中的值与候选 Claim 值做确定性匹配（归一化等价，复用 eval v2 要点匹配）→ 自动绑定；匹配不到 → ReviewItem(type=qa_unbound)，人工绑定或驳回；
- Q2.2 绑定后进审核门禁（低风险自动阈值默认关）→ published。

## Q3 派生 QA

- Q3.1 模板化生成器：高价值字段模板（YAML：field_id → 问题模板 + 答案模板），如 waiting_period → "「{产品}」的等待期是多久？"；只从 published Claim 生成，qa_type=derived 且页面展示标注"由条款字段自动生成"；
- Q3.2 **同步义务**：源 Claim supersede → 派生 QA 自动重编（新 ChangeSet 留痕）；retract → 自动下架；authoritative QA 的源 Claim 变更 → 标记复核（不自动改人工口径）；
- Q3.3 生成幂等：同 Claim 同模板重跑零新增。

## Q4 相似问合并

- Q4.1 intent_fingerprint = 归一化（去停用词/同义归一/字符排序 hash）；同指纹自动合并为一 QA 多问法（alias 问句表）；
- Q4.2 语义级合并 LLM 接口 stub（默认关）。

## Q5 发布与展示

- Q5.1 产品页/概念页聚合渲染 QA 区块（authoritative 在前，derived 标注），经 007 发布器；
- Q5.2 QA 页面变更纳入快照/回滚语义（与 Claim 页面一致）。

## Q6 端到端

- Q6.1 FAQ 夹具直入 → 绑定 → 发布；supersede 源 Claim → derived 重编 + authoritative 进复核；无 Claim 支撑发布被拒；三条相似问合一；
- Q6.2 零模型调用；门禁全绿。

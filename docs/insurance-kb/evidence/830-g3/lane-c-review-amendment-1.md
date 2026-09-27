# C 集中复核修订 1

本文件在修改实现前冻结，补充原 lane-c-batch-contract-draft.md（SHA 3fa650c5bcdf2e46e468f17ad6c44c5ad0bc3769a713e932202a83bdbc0a6d47），不改历史稿。对应 G3-R4/G3-R5；唯一 Owner 仍 g3_catalog_impl，生产/测试仍只限原两文件。修复前实现 f93b682e8fecd4a7b9db22a3cb84f74ce9a117b22b8375a951fe3c1637b13bcd，测试9ace729bbfb2382e16e67598e2740330ce30802517c53f5c1e84c9af41ee68f3。

独立复核7项BLOCKER已由总控对照代码和实际探针核实。当前C依赖执行暂停，真实批次、模型、DB、Candidate发布均NOT RUN。以下是一轮集中修复；先保存针对当前冻结实现的真实行为断言RED，再改实现。新RED不替代或回填原始RED日志缺口。

1. **既有身份竞争**：exact code检索之外，检查同scope不同code实体的规范化正式名、已批准别名、正式anchor(kind,normalized value)竞争。任一明确竞争进入NEEDS_CONFIRM/AMBIGUOUS_IDENTITY，不能CREATE或静默MATCH；不是模糊字符串相似度自动合并。
2. **真实MULTI**：来源完整性正常时，只有至少两个不同稳定实体key（space+normalized product_code），且各有独立name/code的有效Evidence，才计MULTI。相同key的名称/版本矛盾不能增加实体簇数量；排除自身IDENTITY_ANCHOR_CONFLICT/EVIDENCE_JOIN_FAILED/缺身份Evidence的簇。父决定与wire validator采用同一规则。
3. **先资格后聚合**：每row先计算来源、模型绑定、Evidence/trust、身份/分类阈值和pack解析资格，再聚合候选；禁止不合格row的Evidence加入合法Candidate。批次同key中经有效依据确认的不同版本、不同身份或不同primary pack竞争统一人工；同key/version不完整row与完整row竞争也确定性人工，不取排序第一的不完整row构造candidate。任何输入顺序都不得抛裸AssertionError。仅相同身份/版本/pack且合格的rows可聚合其合格身份Evidence；坏来源/伪Evidence/低置信row不能污染合格候选的内容或Evidence。逐row失败原因保留。
4. **模型用途绑定**：继续复用原PolicyReceipt且不把审计数据当传输授权。常量冻结为purpose=`g3-batch-resolution`、run_schema_version=`830-g3-v1`、identity.role=`classify`；receipt与permit_view都必须一致。错误用途/schema/role→MODEL_RECEIPT_INVALID，对应材料不计model_attempted；不添加第二Permit模型。
5. **有效期**：使用严格ISO日期`YYYY-MM-DD`，必须是真实Gregorian日期且解析/格式化往返完全相同；比较date值，不比较任意Text。可信Policy配置中的非null日期不合法时拒绝整个配置（INPUT_CONTRACT_INVALID）。Proposal保留原始Text以便记录模型错误；不合法日期、倒置区间、缺起始值或未被来源支持的非null日期均不能使interval rule自动通过，记TRUST_POLICY_UNRESOLVED。非null valid_from/valid_through需各自在同proposal、被identity_evidence_ids引用且purpose=version的exact Evidence quote中出现；该Evidence先通过原source/quote/trust范围校验。复用现purpose和字段，不另建时间解析平台；不从上传时间或模型自报日期推断有效期。
6. **真实材料唯一**：唯一来源key=`(tenant_id,space_id,raw_kb_id,wiki_kb_id,knowledge_id,weknora_parse_attempt,revision_source_id)`。相同source换material_id仍是重复；resolve_batch必须稳定抛DUPLICATE_MATERIAL，不增加任何分母。保留现material_id唯一约束。
7. **可重算wire语义**：BatchEntityResolutionV1新增必填`space_id: Text`，resolve填exact corpus.space_id并纳入batch hash。validate_batch单参API保持；对每CREATE重算 entity_key=`schema_wiki_sha256("entity-candidate-key.830.g3.v1", {space_id,product_code: normalized})`，再按原冻结version key公式重算version_candidate_key/candidate_id。candidate所有issuer/name/code/version/anchor与所属decision.anchors在normalized值及anchor.kind上一致；observed保留来源原文，不要求不同材料排版逐字相等。候选Evidence由resolve仅聚合同key/version/pack合格rows的身份Evidence；单参wire validator至少验证其属于本包对应合法自动决定的Evidence并集，不接受全包无关ID，不冒称仅凭ID可证明外部quote/purpose。自动MATCH/CREATE必须满足identity confidence>=identity threshold、primary label confidence>=classification threshold、分类pack/profile绑定完整且无阻断reason；不能只靠各层自hash自洽放行。validate_batch不声称单独证明外部SourceRevision真实性；外部真实性仍由resolve的exact输入及现有服务端来源复验提供。

## 修复验证

- 先新建/扩展当前测试中的最小反例，运行针对原冻结源码的断言RED并保存原日志：B1 name/alias/anchor竞争；B2同key冲突不计MULTI；B3坏row证据隔离/early incomplete/primary pack竞争；B4wrong purpose/schema/role；B5坏ISO日期/无时间依据；B6相同来源换material ID；B7任意key+层层rehash/不满足自动阈值+rehash。
- 保留旧18项及实际失败回执，修复后仅跑focused+ruff+strict mypy，给出新源码/test SHA和原始输出，再由同一独立reviewer集中复审。不要删除反例、降低阈值或修改真实预期样本来通过。
- A/B源码、Catalog字节与用户结构确认回执不变。模型用途常量是协议身份，不授予真实调用额度；具名queue/实际Policy/SourceRevision/Seed仍待完成。

# G3.5 原文身份抽取与已有实体匹配边界

2026-09-26；Owner root；基础 ac12fca1af0485b117715b79ada5a73e84197668。
用户已持续授权完成 G3.5；本修复属于正常上传纵向流程，不扩展提供方或材料范围。

真实任务 02424c86-520a-40d5-b0d1-d80c808eeb94 的 identity 调用正常返回，
但复制 existing_entities 内的代码及备案号，而所提供原文没有该证据。
离线重放 validate_identity_offered_response PASS，adapt_identity_response 报
identity asserted value lacks offered source evidence。原始响应保留，不修改或补造来源。

## ID-SOURCE-1：抽取只消费当前材料

build_identity_context 为唯一输入组装 Owner，移除已有实体参数及历史实体提示。
采用 product-identity-source-context.830.v2 明确当前材料抽取合同。
保留 Catalog、原文 locator、材料角色与分类约束，明确可选身份字段无证据返回 null。
不通过删除模型返回值、补假来源、产品名称特判或无限重试放宽校验。

## ID-SOURCE-2：匹配由既有 resolver 独立完成

pipeline 在调用抽取输入组装时不传已有实体；后续 resolve_batch 继续传入完整
existing_entities，保留名称、年份、已有别名及冲突处理。不新建第二套匹配算法。
源码改动只包含 identity.py、pipeline.py 的该参数行和相关测试；不包含现有 coverage WIP。

## ID-SOURCE-3：依赖变更不能复用旧错误响应

输入合同和内容哈希变更，既有回放输入身份校验必须拒绝旧调用。
失败任务保留审计，不原地修改。重新走正常上传，复用平台已解析同文件，
新身份调用及后续处理沿原持久 JobStore、审核和发布路径。
一次有限验证窗口：最多16次新模型调用、每次最多16384输出token、30分钟，
终态/不确定调用即停，不自动重试。失败后离线诊断属于后续新窗口，不能偷续旧窗口。

## 设计选择与执行

直接分离输入职责；仅追加提示词仍暴露无关事实，静默清空模型输出会掩盖错误，均不采用。
复用原生上传/解析及既有 identity adapter、resolver、checkpoint；无新依赖、数据库变更。
顺序：契约审查→防历史输入污染 RED→删除输入耦合→身份/匹配/回放回归→冻结独审→
仅构建/可回滚替换 Harness→正常上传→审核/发布/导航/来源回点。
代码及离线测试不能替代真实流程验收。质量与覆盖度专项继续后置。

## 2026-09-27 ID-PAGE-1—4：跨页身份来源视图

Owner root；基础 a587823fe；用户 G3.5 全项授权持续。真实 run cdefcda9 的两个跨页块
均以第1页起始，公司全称仅在实际第2页，旧身份输入漏掉该证据。修复输入，不改匹配门槛。

- **ID-PAGE-1**：局部不可变 IdentitySourcePageView 区分 source_page_number 与
  actual_page_number。从签名 mapping 选第1页片段；缺法律公司名时最多补一个实际第2—3页
  公司片段。优先保留既有独立块选择维持旧输入；缺独立块时按实际页/全局命中/块ID选跨页片段。
- **ID-PAGE-2**：原 SourceBlock、Corpus、Evidence 身份与坐标不变；不伪装G3v1投影。
  每个连续range及locator经既有project_evidence_locations验证恰好一物理页，原Evidence
  与投影piece一致。后页不能支持名称/分类/角色；跨材料、重复、未提供locator拒绝。
- **ID-PAGE-3**：共享“已解析语义+已验证Evidence→Proposal”由compiler单一模块所有；
  回调签名(material_id,locator)→Evidence，builder再次验证所属原corpus、start/end/quote/hash。
  原C入口保留G3v1契约、排序、结构ID及全部业务门禁。身份深模块公开prepare/assemble，
  封装选源、prompt、catalog；pipeline不再自行拼接三次推导。
- **ID-PAGE-4**：无跨页补充保持旧v2字节，有补充升v3和包含物理页/range的opaque ref，
  新input SHA不得复用旧响应。旧终态保留，走正常新上传并复用既有解析，不人工补issuer。

写域为identity局部模块、pipeline、compiler共享proposal/ref解析及相关测试。无新依赖、
DB迁移、Go/UI变更。先RED，定向兼容/恢复验证，冻结独审，再Harness-only可回滚交付和
一次有界正常长材料上传。待人审Candidate/自动审核拦截是下一独立切片，不能混记完成。

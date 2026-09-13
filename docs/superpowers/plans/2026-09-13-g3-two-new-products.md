# G3 两款新产品增量流程实施计划

> 执行采用 existing G3 独占 worktree、TDD 与有界独立复核；用户已明确要求挑两款新产品跑流程，此前合理 Gemini 调用、本机来源导入、签名/发布授权持续有效，不重复发起授权。Owner=root。

**Goal:** 在当前 epoch9 的 7 产品上增加福满分1820（年金82字段）与爱满分1818（两全79字段），保留旧结果与证据，实际执行新增材料的流程。

**Architecture:** 沿用唯一 WeKnora Release 与 Harness Candidate。首页正式名称复用 g3_title_routing 决定 Schema，身份/备案独立核验；C 的 native 页映射先选择首页，完整来源块保留给 D。旧 C 真实回执与新 C 真实回执组合重放，不重新调用旧材料模型。已有字段机械继承，仅新增字段调用分组抽取/审核；拒绝损坏旧字段/来源/跨实体混用。

**Tech Stack:** Python 3.12 Harness、现有 Go API、Gemini 网关；embedding保留原Qwen，rerank不变。DOCKER_ACTION=REUSE，只有影响APP的必要代码变更在定向验证通过后 BUILD_AFFECTED，不重建UI/数据库。

## 范围与已复现缺口

输入：/Users/houjing/Downloads/shouxian_product 下两款各条款、说明书、费率表共6PDF，exact清单在 /private/tmp/g3-two-products-20260913/source-selection.json。条款首页含1820/1818及平安人寿〔2025〕年金保险142号/两全保险140号。当前正式名称路由已覆盖两个名字，模型调用0可得到正确Schema。

已确认旧 PUBLISHED_G3 base 要求 existing==all，不能添加实体；C reuse只支持单源链；旧上传工具限定15材料且embedding仍指向旧一次性19030代理。这些是本次增量流程的真实阻断，不伪称现有入口可直接运行。

## Requirement / 写域 / 步骤

- G3-INC1：既有实体快照完整且可验证，允许新实体作为增量；旧entity/version/字段不得丢失或变更；普通来源核验、同版Catalog/Profile与Head CAS继续执行。
  - Owner子lane：harness/src/insurance_harness/knowledge_compiler/batch_concept_compile_830_g3.py、对应tests；internal/types/concept_free_wiki_830_g3.go及tests；如service父版比较确有必要，先报告root再列精确函数。
  - [ ] 在当前epoch9已发布快照加一个新实体构造RED；拒绝旧字段缺失/旧实体改版、新增实体混入existing。
  - [ ] 最小Python/Go镜像修复；验证旧342/493及增量场景；保留source authority与发布审核要求。
- G3-INC2：分类来源可组合、可追溯，旧C复用+新C执行；来源集合不得重叠冲突，当前策略重放和完整签名/ledger重开均保留。
  - Owner=root：g3_classification_reuse.py及定向tests，g3_bounded_model_execution.py和现有materializer的必要接线。
  - [ ] 先读/复用现有来源验证器；组合两份真实origin的RED；只扩数据组合而不重新造模型网关。
  - [ ] 数据按exact receipt/hash组合；原raw/model output不改写；模型仅处理新范围。
  - 2026-09-13 实证补充：ModelReceiptBinding.input_sha256 绑定原 C 的完整 corpus，不能直接用合并 corpus 校验。INC1 写域已冻结并验证；INC2 作者追加拥有 batch_entity_resolution_830_g3.py 的 receipt 验证与 Go concept_free_wiki_830_g3.go 对应镜像（独立新增 tests），按真实 PolicyReceipt 的 admission/run identity 分组重建每个原 corpus，再校验原 input hash。V3 的签名历史 verifier 必须证明这些分组确为对应成功 C；单源行为保留。不得改写原 ModelReceiptBinding 或放宽为任意 input hash。
- G3-INC3：可重复使用的本机来源/阶段执行由清单驱动，避免写死本次数字。
  - Owner=root：docs/insurance-kb/evidence/830-g3 本次runner/元数据；private evidence保存原始材料与回执；旧历史runner保持。
  - [ ] 新增6材料先本机native解析，再配置已授权embedding可用路由，upload→parse→revision/chunks→source/backfill逐件登记，不碰生产。
  - [ ] C只发所需首页，D按Schema字段分组并保存结果/证据/页码。确认调用输入、schema、模型及输出预算，调用失败保留且不盲重试。
- G3-INC4：实际新版与历史验证。
  - [ ] 只抽取161新增字段，旧493逐字保留；9产品/654字段的候选通过完整校验与实际发布。请求容量按实测检查，不用补造字段或删除历史满足大小。
  - [ ] 新产品页面、字段、source/PDF页码、检索及旧版读回独立复核，计时分别记录，不把软件测试替代真实效果。

## 非目标及停止边界

不进入G4/Q0/生产，不做1000文档压力测试，不更换embedding/rerank/模型，不重抽旧493字段，不覆盖第9版历史。不得以“全量重跑旧材料”掩盖增量缺口。若发现新的独立子系统/生产问题，仅报告事实，不扩大为本轮平台重构。

## 2026-09-13 实际D失败的有界恢复

第一次D compile000成功，compile001被既有校验拒绝：absent_explicitly同时value=null，证据只列一般保险责任，不能证明明确不保障。这是原响应的真实RED，保持校验和失败回执。Owner=root仅追加现有 g3_d_compile_v1.txt 的三态语义提示（present/absent均有非空value与直接证据，未提及必须unknown），不修改字段结果/投影校验；使用已存在字段级projection recovery验证并继承可用结果，新parent只调用失败/未执行字段。提示词为Harness输入，Go应用代码不变，继续消费已冻结49023120b的唯一APP构建；最终分别记录模型source与APPsource，不重复构建。

恢复请求的独立复核发现真实 Gemini 路径选择 g3_d_compile_references_v1.txt，a107 的补充只进入通用模板，18份已物化请求仍缺少三态约束，形成接线 RED。D2 仅 import/prepare，不执行 provider。Owner=root 将相同语义规则补入实际 references 模板，以新 source 和新签名重新物化18请求并检查真实 system body。只继承原成功的1个 ENTITY_SYNTHESIS，失败窗口不继承任何字段，161字段完整重做；不更改 projector，不重建 APP。

D3第一字段窗实际响应的age_segment_tags引用删除原文CRLF，触发既有offered-span校验RED。Owner=root仅在实际references模板明确优先短单行充分引用、多项事实使用多条独立证据，保留原始响应和严格校验；既有projection机制整体校验并复用其余9字段，不逐字段重复重渲染。下一物料组合多个已验证manifest（库已支持），仅调用剩余字段；APP构建和烟测已PASS，不重建。

## G3-INC5：重复原文的完整定位（D4实际RED后的有界修复）

D4已有4个字段窗口SUCCESS，第5窗因product_name引用“平安福满分（2026）养老年金保险”在同一已提供片段内精确出现两次，被唯一出现次数检查拒绝。原文没有改写、身份一致；选第一个位置会丢失出处，重复调用模型也不能解决定位器不支持重复原文的问题。

Owner=root，委托实现lane仅拥有g3_bounded_model_execution.py中_resolve_g3_d_evidence及3个调用点、一个新增定向测试文件。窗口模式给解析器传递已有offered spans，逐个保留其中所有精确、完整落在片段内的匹配，生成各自原始start/end/quote/hash并逐一verify_evidence；去重并稳定排序。禁止扩到未提供片段、跨来源、改写空白、模糊匹配或随意选一个位置。零匹配仍拒绝，无窗口的旧调用保持既有唯一匹配行为；输出Evidence DTO及APP均不改。

RED覆盖重复精确匹配、只保留offered范围内匹配、重叠片段去重、缺失/跨来源/空引用拒绝与旧无窗口兼容。实际D4失败response须保持FAILED原记录，利用已有recorded projection重新验证其可用字段并保留全部真实出处；既有3个origin的reuse manifests按新validator hash重新生成，不改原模型响应/终态。完成定向测试和独立复核后继续仅剩字段，不再为此重建APP，也不引入新模型协议。

Owner=root同步将实际references提示词的“必须唯一出现”改为“优先唯一且充分的原文”，明确相同精确引用保留已提供片段内全部位置；逐字、原始换行、来源范围和字段三态要求不变。

### 2026-09-13 D5 后续恢复执行配置（不改产品代码）

D5 原 SUCCESS 000 保留；001 为 INVALID_PROVIDER_RESPONSE，9 条字段缺 evidence，包含 present，不能补造证据或改写原响应。后续复用既有 g3-chain-failure-policy.830.v2：最多两个独立窗口同时执行，单窗失败保留原 FAILED 并允许其他独立窗口继续，失败仍禁止 D_REVIEW / Candidate；retry_limit 仍为 0。旧私有物料器沿用 v1 导致首错中止，本轮在新的私有配置物料器明确绑定已有 v2/worker_limit=2，并签入新 chain、parent、caps；原历次文件不变。不是新增恢复协议或新模型运行器。独立复核实际包 identity、配置一致性、69 已成功字段及 1 概述复用/剩余字段不重复后，才执行新调用；运行时实际验证仍必须 PASS，不以 helper 准备代替。所有原始失败/成功响应继续归档。

### G3-INC6 · 录制字段结果的有界格式适配和选定子集复用

D6 v2 已真实执行11个独立窗口，4 SUCCESS / 7 INVALID_PROVIDER_RESPONSE；来源原始 wire 明确出现 valid_time=null、单键 concept_ref 包装、fields 数组 literal null 噪声，另有精确引文错误。先冻结以下恢复边界，再实施 RED/实现/独立复核：原始响应字节、签名、FAILED 终态永不改写；仅在派生内存视图中适配无歧义机械表达（未提供时间 null→既有空串；单键 concept_ref 字符串包装展开；unknown 且 value=null/有效 unknown_reason 时遗漏 evidence 视为 []，present 不补证据）。fields 中 literal null 仅可忽略非成员噪声，剩余对象的 field_ref 必须唯一、精确覆盖原窗口全部目标；缺失/外来/重复成员继续失败。recorded subset 完整检查顶层 envelope 和原成员覆盖后，仅将 manifest 明选字段交给严格 DTO 与原 offered context 投影；未选坏字段不能污染有效子集，也不能进入结果。selected 字段证据仍须字节精确匹配原 offered spans，概念与实体归属仍按原 scope 检查；不做空白归一/模糊匹配/业务值修改，不把缺证据的 present 降成 unknown。所有机械适配可按新 validator identity 从同一原始响应确定重放，manifest 绑定该 identity 与实际输出哈希。

唯一实现写域：harness/src/insurance_harness/knowledge_compiler/g3_field_task_recovery.py 及其有界测试；若发现必须扩展写域，先回报根代理修订计划。软件验证需含原失败形式 RED→GREEN、present 缺证据拒绝、外来/重复/缺失 ref 拒绝、selected 坏引文拒绝、未选坏成员不进入投影、原字节不变与确定性重放。不改 Go/Evidence DTO/APP，不新增模型运行器。实际 D6 录制投影单独记账，不将原FAILED写成SUCCESS；后续仅为未闭合字段发新请求。

INC6 设计独立复核 0 BLOCKER 后收窄：上述机械适配只进入 project_g3_recorded_compile_subset 的 FIELDS 分支；共享 _parse_semantic、新调用与 synthesis 保持原校验。仅适配明选字段；已有错误 evidence 不修正、非单键 concept_ref 包装拒绝。派生视图仍须严格 DTO 及规范往返，再进入原 context projector。此收窄优先于上一段泛述。

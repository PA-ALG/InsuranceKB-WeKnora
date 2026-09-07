# 128 · G2 共享定义与开放知识准入

## Goal与触发依据

唯一Goal为29号文档G2，用户已明确授权实施，Owner为830-G2总控。
base=`e7f57b3628adf97929471de9b4add3ff75c29b8b`。
真实旧编译结果和无法接线的原因已先保存于
`docs/insurance-kb/evidence/830-g2/initial-gap.json`：G1产出76成员，free_wiki为空且不支持concept links。
126冻结空分组，009的五表/current revision方向已失效；不能放宽旧合同假装支持G2。

## 实现选择

在同一WeKnora preparation的Manifest/Members JSONB中承载新版本G2 bundle。
定义、实体字段、free_wiki、别名/义项、关系分别有稳定身份；聚合只读一个固定Release的成员集合。
Harness只编译和独立审核，不保存在线Head；沿现有Draft→human review→Release/CAS。
新候选有自己的candidate digest及审核输出，绝不复制G1旧candidate digest冒充新发现。
Content只能从同member的结构化payload确定性派生，供既有Search/Agent使用。
G1及815旧合同、历史payload、来源和Release不改。

## Owner matrix

总控独占 `HANDOFF.md`、`docs/insurance-kb/evidence/830-g2/**`、本OpenSpec、
`docs/superpowers/plans/2026-09-05-830-g2-concept-free-wiki.md` 与所有commit/D2/外部对象。
实施lane按切片签发，默认唯一非空产品写域；未派发前产品写域关闭。允许路径如下，不能自行加文件：

- Harness新增 `harness/src/insurance_harness/knowledge_compiler/concept_free_wiki_830_g2.py`、
  `harness/src/insurance_harness/knowledge_compiler/concept_compile_830_g2.py`；
  同名 `harness/tests/test_concept_free_wiki_830_g2.py`、`test_concept_compile_830_g2.py`，
  `harness/tests/fixtures/concept_free_wiki_830_g2_contract_vector.json`。
- Go新增 `internal/types/concept_free_wiki_830_g2.go`、`internal/application/service/concept_free_wiki_830_g2.go`、
  `internal/handler/concept_free_wiki_830_g2.go` 及各自 `_test.go`。
- 最小dispatch接线：`internal/handler/schema_wiki.go`、`internal/application/service/schema_wiki.go`、
  `internal/application/service/wiki_release.go`、`internal/router/routes_schema_wiki.go` 及各自 `_test.go`。
- 前端：新增 `frontend/src/api/schema-wiki/conceptFreeWiki830G2.ts`、对应 `.spec.ts`，
  `frontend/src/views/knowledge/schema-wiki/ConceptFreeWiki830G2.vue`、对应 `.spec.ts`；
  `frontend/src/router/index.ts`、`frontend/src/views/knowledge/KnowledgeBase.vue`、
  `frontend/src/views/knowledge/schema-wiki/EntityPageGraph830G1.vue`及现有对应tests。

当前列出跨栈接线预计触发YELLOW，分串行小切片评审；不据此授权大面积重构。
任何不在此清单的真实接缝需求先交总控复核写域；新表/新服务/第二authority直接STOP。

## 非目标与验证

不实现G3 Catalog/自动批量实体识别、G4完整增量/回滚、G5专家编辑流程、Q0语义指标。
协议允许EXPERT_REVISION_RECORD来源，但不能恢复“未另附文件就无来源”规则。
精确合同见spec.md，分步执行和命令见计划；首切片D0/D1，最终D2/D3。
调用、构建、数据/运行身份及STOP只以G2 execution记录和章程为准。

## 2026-09-06 人工准入补齐写域

总控负责Python两文件/测试、协议及计划；g2_sources负责Go types/service与测试。
本次新增机械dispatch允许域：`internal/application/service/concept_source_authority_830_g2.go`及其tests，
用于v2继承同一来源检查，不改存储协议。跨语言v2向量新增
`harness/tests/fixtures/concept_free_wiki_830_g2_human_contract_vector.json`。g2_bundle_review只读审核。
前端read协议不变，若实际发现UI缺口先登记精确路径；不预先扩UI范围。

## 2026-09-06 B 格式纠正输出容量修订

B 首次真实输出结束于 stop，消耗 31,238/32,768 output tokens，但遗漏 21 个 offset_unit、全部 136 条 audit，且两个既有 A 字段的证据数组顺序变化。独立逐对象复核确认无事实内容漂移；原始响应和失败账目保留。基于用户已批准的合理 G2 额度扩展，仅将预留的一次 format-correction 输出上限提高至 65,536；B 调用上限仍 3、全局仍 7、独立 reviewer 仍 8,192。官方文档公布最大输出 384K。

本次根控维护预算及规格，g2_sources 只准备独立私有 runner revision；g2_bundle_review 只读复核并出具冻结输入 review。先保存真实失败与负测，再冻结修订 runner/请求/预算 identity；只有独立 BLOCKER0 后根控发出纠正调用。只修复完整 wire、原证据顺序和全部 audit，禁止本地补 raw 冒充模型结果、禁止提分/质量重试。后续完整候选仍按已有正常/人工整包准入合同执行。

格式纠正输入允许附上既有冻结 proposal 的全部 136 条 audit projection；此前 catalogue 未包含该机械处置清单。该清单不增加来源文本、事实断言或分数，仅让模型能够返回可核验的完整 audit；测试必须逐对象核对与冻结 proposal 相等。原始失败回执和首次请求不修改。

## 2026-09-06 B 完整结构模板的单次恢复

第二次真实输出修好 21 个 offset_unit 与 136 条 audit，但漏写全部 134 个 valid_time 空串，且两 A 字段证据顺序仍变化。独立全树诊断确认其余内容及全部 audit 精确匹配，实质事实漂移为 0；第二次失败和已经耗尽的原纠偏槽均保持历史事实。

本次回到输入设计：在相同 request/catalog 上附既有冻结 proposal 的完整 wire_output_template，显式要求每个字段包含 valid_time 空串、两 A 数组按模板顺序，全量 raw 必须由模型重新返回；禁止本地修复或放松 raw 校验。先证明模板与既有 proposal 完全相同、不增加来源或事实，再冻结请求及独立复核。按用户合理 G2 扩展的已有授权，仅新增 1 次恢复调用：B 总上限 4，全局上限 8，恢复 output 65,536，末次独立 review 保留 1 次/8,192。新增恢复失败则 B compile 终止，不再自动追加。

根控独占预算、规格及真实调用；g2_sources 只准备 /private/tmp 的独立 revision runner 与负测；g2_bundle_review 只读复核实际冻结输入。源码 HEAD 99ec069 保持。平台两个候选版本均仍要求真实完整候选的具名整包批准，不将本次材料/额度授权写成候选批准。

## 2026-09-06 B 来源版本混用恢复（128-G2-SOURCE-RECOVERY）

真实 B Review 返回503，未激活。只读数据库证明两条 terms 引用使用已删除 attempt1 的分块编号，却绑定已封存 attempt3；原文完全相同。旧来源准备检查仅核对文档ID、分块数量及文件hash，漏掉 parse_attempt 和完整manifest重算。首包同一引用实际HTTP200，Active仍R4。

Owner总控：先负测旧导出必须被拒绝；再从当前封存版本只读快照重建来源目录，逐行核对 tenant/KB/knowledge/parse_attempt/deleted状态与完整manifest，仅替换两个编号及其派生hash。旧候选、模型raw、审核、人工批准和失败Draft全部保留。重新生成request/catalog/proposal；独立review确认新旧事实/引用原文/页码/偏移一致。不得修改服务校验、数据库分块或旧模型输出来过关。

依据用户已批准合理G2额度扩展，最多新增2次调用：一次完整wire编译(65536 output)及一次独立review(8192)，原8次保留，累计上限10、B累计6；无重试、无提分，任一步失败即停止该执行。根控执行provider；g2_bundle_review只写新私有runner和负测；g2_sources只读检查来源与冻结输入。源码HEAD99ec069保持。新candidate产生后展示完整修订及两处引用差异，按整包人工批准合同处理，旧批准不冒充新hash批准。随后仅在G2隔离发布，复验和既有一轮Agent授权继续。


## 128-G2-AGENT-DNS-RECOVERY（既有R6流程恢复）

真实finalAgent在模型连接前失败：容器DNS经宿主代理返回api.deepseek.com→198.18.0.6，SSRF安全检查正确拒绝；旧请求/创建会话/日志保留，不将其写为成功。两个独立HTTPS公共解析源当前均返回相同公网CloudFront地址，RED为实际受限IP错误。

拟在已有G2隔离app内临时恢复该单一域名的正确解析：执行前两个DoH结果一致且全为公网，原域名TLS认证通过；按原hosts SHA防漂移保存/只追加该主机映射；保持SSRF规则/白名单、模型配置、镜像、网络与生产不变；单轮结束恢复原hosts并校验。无整库/源码迁移、无重编译/发布。DNS变化不得通过禁用校验、放行198.18段或修改全局代理解决。若可信公网解析/TLS/原文件CAS不能成立，停止。

此为用户已批准核心G2与合理必要扩展范围内的网络环境恢复。原1次Agent请求发生在provider连接前，外发0；只允许一个独立记录的恢复请求，应用turn累计上限2（失败1+恢复1），全部实际模型请求总上限13不提高，禁止自动重复。恢复沿用用户明确批准的同一问题/定义/检索来源标识及DeepSeek目的地。新恢复执行器和输入重新冻结独立复核；旧state不改写或删除。


### R6 实际SSE生命周期回验纠偏

DNS恢复后的实际Agent已返回search/read成功、同R5 authority及完整答案/complete，但私有验证器把同tool_call_id的arguments=null开始事件与随后完整参数事件计为两次调用，错误tool_calls_not_exact_order。根因对应现有think.go流式工具预告与act.go实际参数事件两段生命周期。仅增加无provider本地sidecar，保持raw和旧失败回执不可变；严格按同ID/同工具名/null→一次完整参数→一次result合并逻辑调用，异常/重复/缺参数/错序/身份来源漂移继续拒绝，再复用原全部release/source/content/answer校验。先记录原raw在旧验证器失败RED及生命周期反例，sidecar独立复核后重验同一SSE；不再执行Agent，不增加模型请求或发布。

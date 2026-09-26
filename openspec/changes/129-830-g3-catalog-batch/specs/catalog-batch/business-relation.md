# G35-R4：产品到概念的正式关系首切片

2026-09-26；沿 G3.5 用户一次性授权及 FLOW 优先决定，root 唯一写者。
现有复用证据见 `docs/insurance-kb/evidence/830-g35/r4-capability-boundary-20260924.md`。
本增量冻结版本化 relation extension；不是通用图谱，也不是质量调优。

## 设计与边界

使用现有 FreeWikiPage/PageMember 作为一个关系断言的不可分割发布成员，新增显式
`business_relation`（`product-concept-relation.830.v1`）领域扩展。它不是自由 metadata：
Python/Go/前端均严格验证；既有 Candidate、review、manifest、incremental composition、
Release/read/source 合同统一负责生命周期。普通正文或 concept_ids 本身不构成关系。

主体类型 PRODUCT，由承载页的 space_id/entity_id/entity_version 唯一确定；
客体类型 CONCEPT，由扩展的 object_concept_id/object_definition_sha256 指向同一输出的
完整 ConceptDefinition。扩展包含 subject_type/object_type/predicate。首条 predicate
`benefit_reduced_by_advance_payment` 表示：该产品的约定利益会按所指险种的提前给付责任
及适用条件扣减；不是简单“相关”，也不表示一个未命名险种是具体附加产品。
条件、例外、有效期、正文和精确 Evidence 复用该原子成员的既有字段，只保存一份。
关系稳定键由 space/entity/predicate/object 唯一派生，不依赖模型命名；
主体版本和目标 revision 绑定承载页及扩展并参与 hash。同一语义边的正文/条件/证据
改变是显式 UPDATE，不能新建身份后让旧版关系被增量组合器保留。当前 G3 不支持
同主体版本迁移，关系遵守现有相同主体版本限制；稳定键不含版本不代表支持版本迁移。不同主体或义项才是新身份。不得把旧普通文章
静默升级为关系。

## Requirements

- **G35-R4-REL-1（身份与结构）**：扩展必须可省略，省略时旧 canonical 字节不变；仅 G3 batch 路径接受，G2 standalone 候选继续拒绝扩展；显式
  null、未知 contract/type/predicate、未知属性均拒绝。关系必须有非空主体版本、与唯一
  object 一致的 concept_ids、正确派生 stable_key。同名异义不合并；不同产品版本不得复用事实或审核；本切片同主体版本必须不变，跨版本迁移不支持。
- **G35-R4-REL-2（证据与依赖）**：关系正文、条件、例外及有效期均须 SOURCE_SUPPORTED；
  不接受无证据或 MODEL_GENERATED 的产品关系断言。复用逐段 evidence/provenance 与
  原文校验；目标必须同空间且 exact definition revision 匹配。引用和类型校验不是语义
  正确证明，独立审核仍需判断关系及条件是否被原文支持。
- **G35-R4-REL-3（同一治理链）**：完整 typed extension 进入 CompileOutput、member payload、
  canonical hash 与审核上下文。关系或条件修改使旧审核失效；失败 UPDATE 保留旧成员。
  Python→Go 实际 JSON 向量证明哈希/重放一致；Go 必须重验客体版本，不能仅相信签名或摘要。
- **G35-R4-REL-4（可见与可读）**：沿现有同 Release 页面读取和来源接口返回关系结构；
  页面明确展示主体、关系、客体、版本/条件和原文入口，可导航到对应概念。不新增 serving
  表、后台推理调用或不受审核的关系写接口；普通相关链接不能显示为正式关系。
- **G35-R4-REL-5（正常生成接线）**：只能通过显式新准入 wire/prompt capability 生成；
  旧 v1/v2/v3 请求身份及接受域不变。服务端绑定目标 revision、主体版本和稳定键，模型
  只提出语义，不创造身份/引文。未知实体继续 unresolved；概念与关系进入原依赖闭包。
  首切片完成真实正常任务、发布、关系读取和原文点击后才能记 R4 BUSINESS PASS。

## 实施顺序与唯一写域

1. 先 RED：typed 页准入、同名不同版本、空证据、目标漂移、旧字节及审核失效。
2. 在 `knowledge_compiler/product_concept_relation.py` 封装关系不变量；
   `concept_free_wiki_830_g2.py` 与 `batch_canonical_830_g3.py` 仅挂接既有校验/身份接口。
3. `internal/types/product_concept_relation.go` 负责同合同重放；原 G2/G3 DTO/decoder 挂接。
   通过 `harness/tests/test_product_concept_relation.py` 和同名 Go tests/共享 JSON 向量核验。
4. 前端 `api/schema-wiki/productConceptRelation.ts`、`batchConcept830G3.ts` 和
   `ConceptFreeWiki830G2.vue` 接入严格解析/展示，相关测试验证旧普通页不受影响。
5. 下一步冻结正常准入 wire 接线的 exact 写域与 RED 后接入，沿原 worker/审核/发布实测。
   未做生成接线/部署/真实关系发布时必须分别记 NOT RUN，不用纯 DTO 测试冒充 tracer 完成。

不改已后置 coverage/字段质量逻辑、不重传旧材料、不新增数据库迁移。软件阶段 Docker SKIP、
provider 0；交付前独审 exact diff，必要组件各构建一次并可回滚。任何旧协议回归或审核/证据
绕过是 BLOCKER；无法确定关系语义则保留 unresolved，不人为填实测答案。

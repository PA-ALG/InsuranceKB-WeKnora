# D 模型原始输出与机械保留记录修订4（实现前）

补充原D设计及修订1—3，冲突以本文为准。状态：INDEPENDENT_REVIEW_PENDING。仅闭合实际model raw与最终logical output不可共用一个ExecutionRecord的矛盾；原G2合同/record_output/执行回执不改。

## 两份结果各有身份

BatchConceptCandidateBundle830G3V1新增唯一必传顶层字段 `model_compile_result`，形状复用exact G2 CompileResult（output+execution），其output是模型对本次新增成员的原始提案，execution.raw_output是实际completion content逐字文本；最终compile_result仍为G2 CompileResult形状，但由固定机械组合器产生，不能标成上游原始模型输出。两者及review_result全部进入outer candidate_hash。

compiler_context_g3在原三个exact keys之外增加必传 `output_mode="NEW_MEMBERS_ONLY"`。model_compile_result.execution.context_hash使用原设计的batch-concept-compile-context.830.g3.v1域和该完整context；模型仍看到完整G3 request、base成员、Catalog、C绑定和来源。run_id/implementation保持真实执行identity，fixture必须明确fixture身份，不制造实际model receipt。原始provider HTTP请求/响应仍由受控执行器独立保存，completion raw不冒充整个HTTP body。

## 新增提案的边界

model_compile_result.output复用G2 CompileOutput的exact字段/原hash算法，request_hash必须等于base_request.request_hash，但在合并前不声称满足G2全字段coverage。G3 validator执行以下delta规则：

- field keys必须恰好等于每实体base_request.required_fields减该实体actual existing FieldAssertion keys；必须每项attempted且entity/version与request一致。不得输出任何旧field key，哪怕旧值相同，也不允许模型替代机械carry。
- 新definitions不能与任何existing concept_id重复；新pages不能与任何existing free_page_id重复。可以引用已有definition；source范围/Evidence验证均按最终完整request执行。
- delta audit必须精确覆盖delta objects；field为field_rule，新definition/page只允许new_page或符合原G2条件的sense；不允许夹带旧object audit或未对应对象的额外audit。具体原G2合法性在最终组合output的validate_output再次验证。
- raw必须无重复键并与delta output逐字段语义相等，raw_output_hash必须是原始UTF8字节SHA；只用G2原raw binding helper或语义等价公开包装，不把重序列化结果替换原completion。

## 唯一机械组合公式

`compose_batch_output(request, model_compile_result)`纯内存，无provider/DB。先验证上面delta边界，再按以下规则生成final CompileOutput：

- request_hash原base hash；transformation逐字沿delta值（不提升成EXTRACT或消除TRANSFORM）。
- definitions=exact existing definitions与delta新definitions并集，按concept_id排序；fields=exact existing fields与delta新fields并集，按(entity_id,field_key)排序；pages=exact existing pages与delta新pages并集，按free_page_id排序。任何identity碰撞均拒绝，不采用先到/后到覆盖。
- audit为delta audit加所有carry object的确定性audit，按key排序：旧definition/page disposition=alias_link、reason="BASE_CARRYOVER"；旧field disposition=field_rule、reason="BASE_CARRYOVER"。最终promoted对象与audit一一对应。delta audit的reason逐字保留。
- final必经原G2 validate_output(base_request, final)，再执行D全部base逐字保留、owner/source、legacy及Profile约束。所有FieldAssertion ID/hash、definition hash/free page ID仍用原G2公式。

`compile_result.output`必须逐字等于上述重新组合结果，服务端Go同样机械复算。`compile_result.execution.implementation`固定为 `base-carry-compiler.830.g3.v1`；其run_id为本次独立组合运行ID，必须与model compile及review两个run_id各不相同。final raw为按schema_wiki canonical JSON序列化的final output，必须恰是该canonical字符串且通过原G2 raw binding，明确是逻辑组合输出而非模型raw。

final execution.context_hash使用域 `batch-concept-carry-context.830.g3.v1`，payload exact keys：

```
request_sha256
model_compile_output_hash = model_compile_result.output.output_hash
model_compile_execution_sha256 = schema_wiki_sha256("batch-concept-model-execution.830.g3.v1", model_compile_result.execution)
```

每个hash均现场重算；通过request_sha完整绑定Catalog/C/base/source，execution hash完整绑定原raw、run/implementation/context。新G3 recorder直接构造原ExecutionRecord形状并重验，不能调用固定G2 execution-context域后伪称G3域，也不改旧G2 record_output。

review_result保持原设计：reviewer看到完整最终output及full G3 request，context域batch-concept-review-context.830.g3.v1，ReviewOutput绑定base hash和final output hash，raw逐字属于真实review completion；必须独立run ID。所有G3模型权限与外发预算仍由受控执行器的真实授权处理，这些审计hash不自动授予网络权限或Active能力。

## 必须RED及容量更新

新增向量：模型delta夹带旧field/definition/page，缺新增required field，伪造原raw或context，最终组合删/改旧对象，替换final raw冒充model raw，使用G2 context域，重复三类run ID，改delta transformation，carry audit缺失/重复均拒绝；真实不同raw与canonical logical raw各自完整且机械组合一致通过。

完整275与actual344字段容量向量必须包含新增model_compile_result、final compile_result、review_result、Catalog/C全部输入及manifest；不能只算final output。若超过现8MiB限制先回容量设计，不删原raw、来源或旧成员。原G2所有fixture及hash不变；本修订不新增模型调用次数，仍一次新增编译加一次独立审核的既有组合边界，真实额度尚待实际执行计划冻结。

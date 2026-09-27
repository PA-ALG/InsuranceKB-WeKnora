# G35-R2/R3/R7：按来源适用维度统一知识资格

2026-09-27，用户已要求模型补充可保留且显式标注、完整流程先行及统一维护质量；
正常长材料两窗流程到epoch24。root唯一写者；独立设计复核完成，采用现有G3请求、
审核、Candidate、Go重放及唯一Active，不新增审核平台。本文件冻结统一切片，
不修改任何旧模型raw，不将旧71分回执重新包装为新政策发布。

## 合同

- **QUAL-1**：G3请求可显式提供quality_policy=`provenance-applicable-score.830.v1`。
  缺省省略时严格保持旧序列化/hash与100分制；显式null、空串、未知版本拒绝。
  新政策必须进入request hash、独审context/prompt、StageCall及最终bundle校验身份。
  不借用base_request.policy_identity（它属于实体解析策略），G2独立合同保持不变。
- **QUAL-2**：单一纯资格模块接收可信政策、已验证最终member及原始六维分数，返回
  raw_total、applicable_max、band。纯MODEL_GENERATED必须正文完全分段、所有段为生成、
  无Evidence且证据分0，适用满分80；原文/混合/合法历史未分段内容满分100。
  用整数比较保持80%接受、60%待审阈值：生成64/48；其他80/60。分数原样保留，
  不生成虚假证据分，也不令模型灌满其他维度。生成证据分非0或来源合同错误拒绝。
- **QUAL-3**：评分资格不是发布授权。模型REJECT/NEEDS_HUMAN、处置失败、来源问题、
  产品事实无依据、实体/版本/权限错误仍优先。混合页不得冒充纯生成降低分母。
  仅对新/变更成员应用当前政策；未变更已发布知识按原复用边界保留。
- **QUAL-4**：Python初审、成功调用重放、组合proof、R6失败种子裁剪、G3 Candidate
  及Go最终重验必须一致。quality_policy应独立触发changed-member评分集合与pending
  列表重算，即使knowledge_update_policy缺省也不能跳过。旧review不能跨政策exact复用。
- **QUAL-5**：复用旧已审field_comparison资产，以现有compose_batch_output生成完整
  有效字段比较视图；保留正文、对象、条件、例外、unknown原因及修订，不把该视图
  当证据，不把字段归属当已覆盖，不用自由页替代失败字段。准入/独审/同代checkpoint
  必须绑定同一完整字段集合；当前两窗聚合下每domain亦须核对。新政策配置必须启用
  dependency_policy；直接独审入口缺selection或缺字段视图也拒绝，旧无政策行为保持。
  原深度coverage WIP
  不整包集成，不设尚未通过真实验收的深度审核为新前置。
- **QUAL-6**：使用共享边界向量验证Python/Go，真实正常worker和恢复各一条纵切；
  新政策需重新独审。仅在完成软件与独审后，集中构建受影响App/Harness并按原配置
  管理启用明确政策；UI复用既有模型生成标志。真实非空页面/关系/来源点击、质量与
  覆盖/成本分别记账，空结果或软件通过不冒充G3.5完成。

## RED与写域

RED覆盖：生成47/48/63/64/71及原文59/60/79/80；历史71仍待审；伪造纯生成、非0
证据分、缺少/多余评分、未知/空政策、模型拒绝、错误pending集合、无更新政策的最终
重验；跨政策raw复用与R6裁剪一致性；字段比较同代/跨页/多窗口篡改反例。

root写域：knowledge_compiler的G3请求/编译/资格新深模块；product_ingestion的
configuration、compilation、pipeline、checkpoint/rebase、native_admission/context/
preflight/stage、native_pipeline、discovery/review/composition/pruning及field_comparison；
internal/types的G3请求/资格新模块及对应测试/共享golden向量；现有计划、回执及本Spec。
范围限上述接口必需接线，旧超长文件仅增量接线，新模块不超过500行。先RED，最小实现，
定向检查，冻结独审，集中交付，真实验证；不新增Goal或要求用户重复授权。

# D 首切片既有pack兼容断言修订5

状态：INDEPENDENT_REVIEW_PENDING。补充修订3的禁止静默换pack条件；冲突以本文为准。常量直接读取已发布G2持久化bundle和已确认Catalog，不从字段数量猜分类。

## 唯一冻结兼容映射

```json
{
  "base_contract": "concept-candidate-bundle.830.g2.v1",
  "base_schema_identity": "medical-schema67.v1@fe3b390222108614d3ff07409fbd81d17e915e066eb9c25c03d3268bc49ef7ac",
  "base_profile_identity": "medical-schema67.presentation.v1@d83a3b38e3b72bd986823d373b86fe1077e0baa6333a27dc74a2545f58bfd3e9",
  "catalog_sha256": "b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd",
  "classification": "medical_insurance",
  "schema_pack_id": "schemapack_medical_insurance",
  "schema_version": "2026-08-12-v5",
  "schema_pack_sha256": "5a7938dcb86327f12dbff6e3056271e03c63842ba34904eefebb5bcdc8694079",
  "profile_id": "profile_medical_insurance",
  "profile_version": "1.0.0-candidate",
  "profile_sha256": "61595e9b2fec127dfca4c31ef95f161d55a9b0939211316b4508ccc4b7d21cf3"
}
```

本首切片服务端必须从actual base Head重开其原candidate request，核contract/schema_identity/profile_identity逐字等于上述旧值；每个base entity的D自动MATCH binding必须使用上述exact classification/pack三元组和Profile三元组，同时Catalog content hash匹配。Python从冻结base输入执行同一断言，Go不能仅信caller提供的base identity。

任一base MATCH本次被分成重疾、两全或其他pack，即使identity/version匹配、置信度高且旧字段全保留为legacy，也必须在delta编译/provider/Draft之前返回BASE_PACK_MIGRATION_REQUIRED。禁止将当前分类结果当作旧pack已迁移的授权。若base合同或schema/profile身份不在唯一映射中，返回BASE_PACK_AUTHORITY_UNSUPPORTED；不现场推断或添第二映射。

此兼容映射只对本首切片继承的G2医疗base适用。新CREATE可依其有效C分类选择其它已确认pack；字段名称差异仍按legacy保留规则处理，医疗Profile67及旧单数字段68并集不变。未来G3多pack base或真实pack迁移须明确每实体旧绑定authority，本次不新增registry/表/服务或另一路carry协议。

必须RED：合法自动MATCH entity/version不变但换为critical/endowment pack及其合法Profile均拒绝；旧base schema/profile/contract漂移拒绝；两个base MATCH保留exact医疗pack并集68字段、三新类别CREATE合法通过。跨语言fixtures和actual344容量向量必须包含这项检查。

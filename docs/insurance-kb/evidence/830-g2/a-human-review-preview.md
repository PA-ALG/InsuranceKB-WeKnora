# G2 A 整包候选确认预览

**状态：已装配，待平台草稿验证及用户整包确认；未发布。**

本候选用于隔离环境的流程验证，内容质量留待 Q0。模型原始评分保持66分，属于人工决定区间；本预览不表示用户已经批准。

本次新增一个共享定义，并让两条既有字段关联它；67个原有字段的事实内容和证据顺序保持不变。

## 新增定义

**被保险人**

被保险人就是受保险合同保障的人。

来源：596-1公开条款第1页。

## 关联字段

投保资格（条款第2页）与健康告知要求（条款第27页）关联“被保险人”。这些链接用于导航，不替代各字段的原有证据。

## 整包内容

共70个拟议成员：1个共享定义、67个字段、1个实体概览和1个开放知识分组。字段状态为2个有值、1个原文明确不提供、64个未知；未知不等于没有保障。本次没有新增开放知识内容页。

确认范围是下面绑定的完整候选；确认后仍需通过来源复验与原有发布授权，才会出现在隔离环境的在线页面中。生产环境不变。

## 全部字段

| 字段 | 状态 | 内容 |
|---|---|---|
| product_code | 未知 | FORMATION_MODE_DEFERRED |
| product_short_name | 未知 | FORMATION_MODE_DEFERRED |
| product_name | 未知 | FORMATION_MODE_DEFERRED |
| sales_start_date | 未知 | FORMATION_MODE_DEFERRED |
| sales_end_date | 未知 | FORMATION_MODE_DEFERRED |
| product_type | 未知 | FORMATION_MODE_DEFERRED |
| insurance_category | 未知 | FORMATION_MODE_DEFERRED |
| sales_channels | 未知 | FORMATION_MODE_DEFERRED |
| external_publication_status | 未知 | FORMATION_MODE_DEFERRED |
| sales_status | 未知 | FORMATION_MODE_DEFERRED |
| policy_role | 未知 | FORMATION_MODE_DEFERRED |
| product_summary | 未知 | FORMATION_MODE_DEFERRED |
| official_product_features | 未知 | FORMATION_MODE_DEFERRED |
| target_customer_profile | 未知 | FORMATION_MODE_DEFERRED |
| marketing_tagline | 未知 | SOURCE_NOT_AVAILABLE |
| product_overview | 未知 | FORMATION_MODE_DEFERRED |
| entry_age_range | 未知 | live_chunk_quote_not_unique |
| insured_eligibility | 有值 | 您可以同时为符合我们承保条件的家庭成员投保本产品，家庭成员仅指投保<br>人本人、投保时与投保人具有合法婚姻关系的配偶、投保人的父母以及投保<br>人的子女。 |
| health_declaration_requirements | 有值 | 订立本合同时，我们应当向您说明本合同的内容。对保险条款中免除我们责<br>任的条款，我们在订立合同时应当在投保单、保险单或者其他保险凭证上作<br>出足以引起您注意的提示，并对该条款的内容以书面或者口头形式向您作出<br>明确说明，未作提示或者明确说明的，该条款不成为合同的内容。<br>订立本合同时，我们就您和被保险人的有关情况提出询问，您应当如实告知。<br>如果您故意或者因重大过失未履行前款规定的如实告知义务，足以影响我们<br>决定是否同意承保或者提高保险费率的，我们有权解除本合同。<br>如果您故意不履行如实告知义务，对于本合同解除前发生的保险事故，我们<br>不承担保险责任，并不退还保险费。 |
| geographic_eligibility_requirements | 未知 | FORMATION_MODE_DEFERRED |
| social_insurance_requirement | 未知 | FORMATION_MODE_DEFERRED |
| eligible_occupation_classes | 未知 | live_chunk_quote_not_unique |
| underwriting_method | 未知 | FORMATION_MODE_DEFERRED |
| premium_payment_term | 未知 | SOURCE_LOCATION_UNRESOLVED |
| premium_payment_frequency | 未知 | SOURCE_LOCATION_UNRESOLVED |
| cooling_off_period | 未知 | live_chunk_quote_not_unique |
| waiting_period | 未知 | live_chunk_quote_not_unique |
| premium_grace_period | 未知 | SOURCE_NOT_AVAILABLE |
| coverage_period | 未知 | ANSWER_NOT_FOUND |
| coverage_term_category | 未知 | FORMATION_MODE_DEFERRED |
| surrender_and_cancellation_terms | 未知 | live_chunk_quote_not_unique |
| coverage_and_renewal_terms | 未知 | SOURCE_LOCATION_UNRESOLVED |
| guaranteed_renewal_status | 未知 | FORMATION_MODE_DEFERRED |
| guaranteed_renewal_period | 原文明示不提供 | 1.8 保险期间和不保<br>证续保<br>2.我们不保什么<br>1.8 保险期间与不保证<br>续保 |
| product_conversion_rules | 未知 | SOURCE_NOT_AVAILABLE |
| premium_adjustment_rules | 未知 | SOURCE_NOT_AVAILABLE |
| post_discontinuation_renewal_arrangement | 未知 | ANSWER_NOT_FOUND |
| covered_risk_categories | 未知 | FORMATION_MODE_DEFERRED |
| coverage_responsibilities | 未知 | ANSWER_NOT_FOUND |
| coverage_summary | 未知 | FORMATION_MODE_DEFERRED |
| cancer_medical_coverage | 未知 | FORMATION_MODE_DEFERRED |
| age_segment_tags | 未知 | FORMATION_MODE_DEFERRED |
| coverage_limit_category | 未知 | FORMATION_MODE_DEFERRED |
| special_coverage_and_exclusion_tags | 未知 | FORMATION_MODE_DEFERRED |
| exclusions | 未知 | SOURCE_LOCATION_UNRESOLVED |
| pre_existing_condition_rules | 未知 | SOURCE_LOCATION_UNRESOLVED |
| out_of_hospital_special_drug_coverage | 未知 | SOURCE_LOCATION_UNRESOLVED |
| indemnity_principle | 未知 | SOURCE_LOCATION_UNRESOLVED |
| zero_deductible_flag | 未知 | FORMATION_MODE_DEFERRED |
| deductible_rules | 未知 | SOURCE_LOCATION_UNRESOLVED |
| outpatient_inpatient_scope | 未知 | live_chunk_quote_not_unique |
| reimbursable_expense_scope | 未知 | live_chunk_quote_not_unique |
| reimbursement_rate_rules | 未知 | live_chunk_quote_not_unique |
| eligible_hospital_scope | 未知 | SOURCE_LOCATION_UNRESOLVED |
| premium_medical_facility_coverage | 未知 | FORMATION_MODE_DEFERRED |
| direct_billing_and_advance_payment_rules | 未知 | FORMATION_MODE_DEFERRED |
| claim_application_deadline_and_documents | 未知 | SOURCE_LOCATION_UNRESOLVED |
| policyholder_rights | 未知 | live_chunk_quote_not_unique |
| eligible_service_packages | 未知 | FORMATION_MODE_DEFERRED |
| medical_service_benefits | 未知 | FORMATION_MODE_DEFERRED |
| tax_qualified_status | 未知 | FORMATION_MODE_DEFERRED |
| tax_benefit_rules | 未知 | SOURCE_NOT_AVAILABLE |
| product_bundle_rules | 未知 | SOURCE_NOT_AVAILABLE |
| objection_handling_scripts | 未知 | SOURCE_NOT_AVAILABLE |
| product_faq | 未知 | SOURCE_NOT_AVAILABLE |
| four_step_sales_script | 未知 | SOURCE_NOT_AVAILABLE |
| sales_pitch_script | 未知 | SOURCE_NOT_AVAILABLE |

## 候选身份

- Candidate：`70cb4b6eb57cb50cf66c4dcb5efe357c34b54d7e3a4b74311cdbb7f7f7d363c5`
- 原文SHA256：`88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc`
- 编译：`g2-a-compile-003`；独立审核：`g2-a-review-002`。
- 原始审核字节SHA256：`36a9c25a558c420d3863c82da799ad659d8a07b63052081b7f555d030146836a`。
- 准入处置：`NEEDS_HUMAN`；待决页面1个。
- 当前步骤新增模型调用：0。

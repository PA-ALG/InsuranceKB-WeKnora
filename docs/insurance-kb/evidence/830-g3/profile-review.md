# G3 · 11类产品展示结构整包预览

状态：待具名产品负责人整包确认。这里确认分类、节点和字段归属；业务抽取质量由 Q0 收口。未形成确认记录，也未发布生产知识。

Catalog：`b4b8cd9c797442c3581c8721834abb3f6ec716057509dad4ac254f79fc0a97bd`。工作簿为 B0 持久 v5；每包完整11列元数据见 catalog/ 下相应 JSON。

| 产品 | 字段数 | 节点数 | 有序节点 |
|---|---:|---:|---|
| 医疗险 | 67 | 7 | 产品概览 → 投保与合同 → 续保与费率 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 |
| 意外医疗保险 | 70 | 7 | 产品概览 → 投保与合同 → 续保与费率 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 |
| 意外险 | 62 | 7 | 产品概览 → 投保与合同 → 续保与费率 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 |
| 重疾险 | 67 | 8 | 产品概览 → 投保与合同 → 续保与费率 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 → 保单价值与保全 |
| 定期寿险 | 66 | 7 | 产品概览 → 投保与合同 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 → 保单价值与保全 |
| 终身寿险 | 75 | 8 | 产品概览 → 投保与承保 → 合同与交费 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 → 保单价值与保全 |
| 两全保险 | 79 | 8 | 产品概览 → 投保与承保 → 合同与交费 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 → 保单价值与保全 |
| 年金险 | 82 | 8 | 产品概览 → 投保与承保 → 合同与交费 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 → 保单价值与保全 |
| 护理保险 | 74 | 7 | 产品概览 → 投保与合同 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 → 保单价值与保全 |
| 补充养老保险 | 83 | 8 | 产品概览 → 投保与承保 → 合同与交费 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 → 保单价值与保全 |
| 失能收入损失保险 | 76 | 7 | 产品概览 → 投保与合同 → 续保与费率 → 保障责任与除外 → 理赔与给付 → 服务与权益 → 销售支持 |

以下逐包列出全部主映射；每个字段恰好出现一次，既有医疗历史 Profile 未修改。

## 医疗险

Pack：`schemapack_medical_insurance@2026-08-12-v5`；Profile：`profile_medical_insurance@1.0.0-candidate`。

Profile hash：`61595e9b2fec127dfca4c31ef95f161d55a9b0939211316b4508ccc4b7d21cf3`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与合同（15字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 社保要求 | social_insurance_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 续保与费率（6字段）

| 字段 | 稳定字段 key |
|---|---|
| 保险期间和续保 | coverage_and_renewal_terms |
| 保证续保 | guaranteed_renewal_status |
| 保证续保期 | guaranteed_renewal_period |
| 险种转换 | product_conversion_rules |
| 费率可调 | premium_adjustment_rules |
| 停售后续保安排 | post_discontinuation_renewal_arrangement |

### 保障责任与除外（11字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 癌症医疗 | cancer_medical_coverage |
| 额度类型 | coverage_limit_category |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |
| 既往症定义与处理 | pre_existing_condition_rules |
| 外购药/特药责任 | out_of_hospital_special_drug_coverage |
| 补偿原则 | indemnity_principle |

### 理赔与给付（9字段）

| 字段 | 稳定字段 key |
|---|---|
| 0免赔 | zero_deductible_flag |
| 免赔额 | deductible_rules |
| 报销门诊/住院范围 | outpatient_inpatient_scope |
| 报销范围 | reimbursable_expense_scope |
| 报销比例 | reimbursement_rate_rules |
| 医院范围 | eligible_hospital_scope |
| 高端医疗 | premium_medical_facility_coverage |
| 直付或垫付规则 | direct_billing_and_advance_payment_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

## 意外医疗保险

Pack：`schemapack_accident_medical_insurance@2026-08-12-v5`；Profile：`profile_accident_medical_insurance@1.0.0-candidate`。

Profile hash：`99c40175fffee344081b8090237b9a434b93045bb791900075343a0089bf8c77`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与合同（15字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 社保要求 | social_insurance_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 续保与费率（6字段）

| 字段 | 稳定字段 key |
|---|---|
| 保险期间和续保 | coverage_and_renewal_terms |
| 保证续保 | guaranteed_renewal_status |
| 保证续保期 | guaranteed_renewal_period |
| 险种转换 | product_conversion_rules |
| 费率可调 | premium_adjustment_rules |
| 停售后续保安排 | post_discontinuation_renewal_arrangement |

### 保障责任与除外（13字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 额度类型 | coverage_limit_category |
| 意外伤害定义与认定标准 | accident_definition_and_criteria |
| 意外场景覆盖范围 | covered_accident_scenarios |
| 事故后医疗时限 | accident_medical_treatment_window |
| 保障地域 | coverage_geography |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |
| 既往症定义与处理 | pre_existing_condition_rules |
| 补偿原则 | indemnity_principle |

### 理赔与给付（9字段）

| 字段 | 稳定字段 key |
|---|---|
| 0免赔 | zero_deductible_flag |
| 免赔额 | deductible_rules |
| 报销门诊/住院范围 | outpatient_inpatient_scope |
| 报销范围 | reimbursable_expense_scope |
| 报销比例 | reimbursement_rate_rules |
| 医院范围 | eligible_hospital_scope |
| 高端医疗 | premium_medical_facility_coverage |
| 直付或垫付规则 | direct_billing_and_advance_payment_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |

### 服务与权益（6字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 意外救援服务 | accident_assistance_services |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

## 意外险

Pack：`schemapack_accident_insurance@2026-08-12-v5`；Profile：`profile_accident_insurance@1.0.0-candidate`。

Profile hash：`12ca8ca665464a76608943f7e0df57b60c8a50cddebb534fc072534331eebf49`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与合同（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |
| 保障生效时间 | coverage_effective_time |

### 续保与费率（1字段）

| 字段 | 稳定字段 key |
|---|---|
| 保险期间和续保 | coverage_and_renewal_terms |

### 保障责任与除外（12字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 意外伤害定义与认定标准 | accident_definition_and_criteria |
| 意外场景覆盖范围 | covered_accident_scenarios |
| 意外伤残 | accidental_disability_coverage_flag |
| 满期生存金 | maturity_benefit_flag |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |
| 保障地域 | coverage_geography |

### 理赔与给付（6字段）

| 字段 | 稳定字段 key |
|---|---|
| 意外身故给付规则 | accidental_death_benefit_rules |
| 伤残给付规则 | disability_benefit_rules |
| 满期给付规则 | maturity_benefit_rules |
| 额外/加倍给付规则 | additional_benefit_rules |
| 伤残定义与认定标准 | disability_definition_and_assessment_criteria |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |

### 服务与权益（6字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 意外救援服务 | accident_assistance_services |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

## 重疾险

Pack：`schemapack_critical_illness_insurance@2026-08-12-v5`；Profile：`profile_critical_illness_insurance@1.0.0-candidate`。

Profile hash：`1c41afee407096b18999a5d8797be138c5279edbef7d45b2e859fddc04d76ca9`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与合同（15字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 续保与费率（1字段）

| 字段 | 稳定字段 key |
|---|---|
| 保险期间和续保 | coverage_and_renewal_terms |

### 保障责任与除外（17字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 疾病分组 | disease_grouping_rules |
| 保费豁免规则 | premium_waiver_rules |
| 满期生存金 | maturity_benefit_flag |
| 轻中重症疾病数量 | disease_count_by_severity |
| 轻症特定疾病 | covered_mild_specified_diseases |
| 中症特定疾病 | covered_moderate_specified_diseases |
| 重症特定疾病 | covered_critical_specified_diseases |
| 特定疾病清单 | covered_specified_diseases |
| 疾病定义与认定标准 | disease_definitions_and_criteria |
| 运动达标涨保障 | activity_based_coverage_increase_rules |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（6字段）

| 字段 | 稳定字段 key |
|---|---|
| 疾病给付规则 | disease_benefit_rules |
| 满期给付规则 | maturity_benefit_rules |
| 额外/加倍给付规则 | additional_benefit_rules |
| 多次赔付规则 | multiple_benefit_payment_rules |
| 责任间给付关系 | benefit_interaction_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

### 保单价值与保全（2字段）

| 字段 | 稳定字段 key |
|---|---|
| 现金价值规则 | cash_value_rules |
| 保单贷款规则 | policy_loan_rules |

## 定期寿险

Pack：`schemapack_term_life_insurance@2026-08-12-v5`；Profile：`profile_term_life_insurance@1.0.0-candidate`。

Profile hash：`1b4f646248291001020446b79d5d030d703c6785592312479e8e6761904df0f4`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与合同（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 契约调查要求 | underwriting_investigation_requirements |
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 保障责任与除外（11字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 全残保障 | total_disability_coverage_flag |
| 意外身故 | accidental_death_coverage_flag |
| 疾病身故 | disease_death_coverage_flag |
| 满期生存金 | maturity_benefit_flag |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 满期给付规则 | maturity_benefit_rules |
| 身故给付规则 | death_benefit_rules |
| 伤残给付规则 | disability_benefit_rules |
| 额外/加倍给付规则 | additional_benefit_rules |
| 伤残定义与认定标准 | disability_definition_and_assessment_criteria |
| 责任间给付关系 | benefit_interaction_rules |
| 受益人规则 | beneficiary_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

### 保单价值与保全（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 分红规则 | dividend_rules |
| 现金价值规则 | cash_value_rules |
| 加保规则 | coverage_increase_rules |
| 保单贷款规则 | policy_loan_rules |
| 双被保人/联合被保人规则 | multiple_insured_rules |

## 终身寿险

Pack：`schemapack_whole_life_insurance@2026-08-12-v5`；Profile：`profile_whole_life_insurance@1.0.0-candidate`。

Profile hash：`b0b226886448e7717ed698d6ff33f6e4fa98484d74bd5569513177fc22a4cb6a`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与承保（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 契约调查要求 | underwriting_investigation_requirements |

### 合同与交费（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 保障责任与除外（13字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 保额形态 | sum_assured_pattern |
| 保额增长规则 | sum_assured_growth_rules |
| 产品利率 | sum_assured_growth_rate |
| 全残保障 | total_disability_coverage_flag |
| 意外身故 | accidental_death_coverage_flag |
| 疾病身故 | disease_death_coverage_flag |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（7字段）

| 字段 | 稳定字段 key |
|---|---|
| 身故给付规则 | death_benefit_rules |
| 伤残给付规则 | disability_benefit_rules |
| 额外/加倍给付规则 | additional_benefit_rules |
| 伤残定义与认定标准 | disability_definition_and_assessment_criteria |
| 责任间给付关系 | benefit_interaction_rules |
| 受益人规则 | beneficiary_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

### 保单价值与保全（13字段）

| 字段 | 稳定字段 key |
|---|---|
| 加保规则 | coverage_increase_rules |
| 现金价值规则 | cash_value_rules |
| 减保规则 | sum_assured_reduction_rules |
| 部分领取规则 | partial_withdrawal_rules |
| 保单贷款规则 | policy_loan_rules |
| 万能账户最低保证利率 | universal_account_guaranteed_interest_rate |
| 万能账户结算规则 | universal_account_settlement_rules |
| 初始费用规则 | initial_charge_rules |
| 领取手续费规则 | withdrawal_charge_rules |
| 分红规则 | dividend_rules |
| 非保证利益规则 | non_guaranteed_benefit_rules |
| 投资账户规则 | investment_account_rules |
| 双被保人/联合被保人规则 | multiple_insured_rules |

## 两全保险

Pack：`schemapack_endowment_insurance@2026-08-12-v5`；Profile：`profile_endowment_insurance@1.0.0-candidate`。

Profile hash：`78fe6eb7eb595836e97540ea0324749ca11ad5b9493bb67026b30fd5dfa16f08`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与承保（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 契约调查要求 | underwriting_investigation_requirements |

### 合同与交费（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 保障责任与除外（15字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 保额形态 | sum_assured_pattern |
| 保额增长规则 | sum_assured_growth_rules |
| 产品利率 | sum_assured_growth_rate |
| 保费豁免规则 | premium_waiver_rules |
| 全残保障 | total_disability_coverage_flag |
| 意外身故 | accidental_death_coverage_flag |
| 疾病身故 | disease_death_coverage_flag |
| 满期生存金 | maturity_benefit_flag |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（9字段）

| 字段 | 稳定字段 key |
|---|---|
| 身故给付规则 | death_benefit_rules |
| 伤残给付规则 | disability_benefit_rules |
| 伤残定义与认定标准 | disability_definition_and_assessment_criteria |
| 额外/加倍给付规则 | additional_benefit_rules |
| 满期给付规则 | maturity_benefit_rules |
| 生存保险金给付规则 | survival_benefit_rules |
| 责任间给付关系 | benefit_interaction_rules |
| 受益人规则 | beneficiary_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

### 保单价值与保全（13字段）

| 字段 | 稳定字段 key |
|---|---|
| 加保规则 | coverage_increase_rules |
| 现金价值规则 | cash_value_rules |
| 减保规则 | sum_assured_reduction_rules |
| 部分领取规则 | partial_withdrawal_rules |
| 保单贷款规则 | policy_loan_rules |
| 万能账户最低保证利率 | universal_account_guaranteed_interest_rate |
| 万能账户结算规则 | universal_account_settlement_rules |
| 初始费用规则 | initial_charge_rules |
| 领取手续费规则 | withdrawal_charge_rules |
| 分红规则 | dividend_rules |
| 非保证利益规则 | non_guaranteed_benefit_rules |
| 投资账户规则 | investment_account_rules |
| 双被保人/联合被保人规则 | multiple_insured_rules |

## 年金险

Pack：`schemapack_annuity_insurance@2026-08-12-v5`；Profile：`profile_annuity_insurance@1.0.0-candidate`。

Profile hash：`dc8cb313afbc93f55090f0c7d3aefe3d27a1566c987ca46a7760396781c35c72`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与承保（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 契约调查要求 | underwriting_investigation_requirements |

### 合同与交费（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 保障责任与除外（11字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 保额形态 | sum_assured_pattern |
| 保额增长规则 | sum_assured_growth_rules |
| 产品利率 | sum_assured_growth_rate |
| 满期生存金 | maturity_benefit_flag |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（15字段）

| 字段 | 稳定字段 key |
|---|---|
| 身故给付规则 | death_benefit_rules |
| 满期给付规则 | maturity_benefit_rules |
| 受益人规则 | beneficiary_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |
| 领取型保险金类别 | annuity_benefit_types |
| 年金开始领取时间 | annuity_start_time |
| 起领年龄 | annuity_start_age |
| 领取频率 | annuity_payment_frequency |
| 领取期间 | annuity_payment_period |
| 年金给付金额/计算规则 | annuity_payment_amount_rules |
| 保证领取状态 | guaranteed_payment_status |
| 保证领取规则 | guaranteed_payment_rules |
| 保证领取期间 | guaranteed_payment_period |
| 未领取年金/保证领取余额处理规则 | unpaid_guaranteed_benefit_rules |
| 养老年金责任 | pension_annuity_coverage_flag |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

### 保单价值与保全（14字段）

| 字段 | 稳定字段 key |
|---|---|
| 现金价值规则 | cash_value_rules |
| 减保规则 | sum_assured_reduction_rules |
| 部分领取规则 | partial_withdrawal_rules |
| 保单贷款规则 | policy_loan_rules |
| 万能账户关联规则 | universal_account_linkage_rules |
| 年金转入万能账户规则 | annuity_transfer_to_universal_account_rules |
| 万能账户最低保证利率 | universal_account_guaranteed_interest_rate |
| 万能账户结算规则 | universal_account_settlement_rules |
| 初始费用规则 | initial_charge_rules |
| 领取手续费规则 | withdrawal_charge_rules |
| 分红规则 | dividend_rules |
| 非保证利益规则 | non_guaranteed_benefit_rules |
| 投资账户规则 | investment_account_rules |
| 双被保人/联合被保人规则 | multiple_insured_rules |

## 护理保险

Pack：`schemapack_nursing_care_insurance@2026-08-12-v5`；Profile：`profile_nursing_care_insurance@1.0.0-candidate`。

Profile hash：`5517a230a791bcba8a653e40638eda8e30471f772444b34ba13f8b62a71a1239`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与合同（15字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 保障责任与除外（17字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 保额形态 | sum_assured_pattern |
| 保额增长规则 | sum_assured_growth_rules |
| 产品利率 | sum_assured_growth_rate |
| 保费豁免规则 | premium_waiver_rules |
| 满期生存金 | maturity_benefit_flag |
| 特定疾病清单 | covered_specified_diseases |
| 轻症特定疾病 | covered_mild_specified_diseases |
| 中症特定疾病 | covered_moderate_specified_diseases |
| 重症特定疾病 | covered_critical_specified_diseases |
| 疾病定义与认定标准 | disease_definitions_and_criteria |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（13字段）

| 字段 | 稳定字段 key |
|---|---|
| 身故给付规则 | death_benefit_rules |
| 满期给付规则 | maturity_benefit_rules |
| 责任间给付关系 | benefit_interaction_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |
| 护理状态定义与认定标准 | care_state_definition_and_criteria |
| 日常生活活动能力（ADL）评定规则 | activities_of_daily_living_assessment_rules |
| 护理状态持续时间要求 | care_state_duration_requirement |
| 护理保险金给付条件 | care_benefit_eligibility_conditions |
| 护理保险金给付方式与金额规则 | care_benefit_payment_rules |
| 护理保险金给付期限 | care_benefit_payment_period |
| 特定疾病关爱金给付条件 | specified_disease_care_benefit_conditions |
| 特定疾病关爱金给付方式与金额规则 | specified_disease_care_benefit_payment_rules |
| 特定疾病关爱金给付期限 | specified_disease_care_benefit_payment_period |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

### 保单价值与保全（3字段）

| 字段 | 稳定字段 key |
|---|---|
| 现金价值规则 | cash_value_rules |
| 减保规则 | sum_assured_reduction_rules |
| 保单贷款规则 | policy_loan_rules |

## 补充养老保险

Pack：`schemapack_supplementary_pension_insurance@2026-08-12-v5`；Profile：`profile_supplementary_pension_insurance@1.0.0-candidate`。

Profile hash：`096e8257c1f66cb3aefebe7caa516ecd15cdb85ef5848cdbb3830adb06328c8b`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与承保（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 契约调查要求 | underwriting_investigation_requirements |

### 合同与交费（8字段）

| 字段 | 稳定字段 key |
|---|---|
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 保障责任与除外（11字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 保额形态 | sum_assured_pattern |
| 保额增长规则 | sum_assured_growth_rules |
| 产品利率 | sum_assured_growth_rate |
| 满期生存金 | maturity_benefit_flag |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 身故给付规则 | death_benefit_rules |
| 满期给付规则 | maturity_benefit_rules |
| 受益人规则 | beneficiary_rules |
| 责任间给付关系 | benefit_interaction_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |
| 领取型保险金类别 | annuity_benefit_types |
| 年金开始领取时间 | annuity_start_time |
| 起领年龄 | annuity_start_age |
| 养老年金领取条件 | pension_annuity_eligibility_rules |
| 领取频率 | annuity_payment_frequency |
| 领取期间 | annuity_payment_period |
| 年金给付金额/计算规则 | annuity_payment_amount_rules |
| 保证领取状态 | guaranteed_payment_status |
| 保证领取规则 | guaranteed_payment_rules |
| 保证领取期间 | guaranteed_payment_period |
| 未领取年金/保证领取余额处理规则 | unpaid_guaranteed_benefit_rules |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

### 保单价值与保全（14字段）

| 字段 | 稳定字段 key |
|---|---|
| 现金价值规则 | cash_value_rules |
| 减保规则 | sum_assured_reduction_rules |
| 部分领取规则 | partial_withdrawal_rules |
| 保单贷款规则 | policy_loan_rules |
| 万能账户关联规则 | universal_account_linkage_rules |
| 年金转入万能账户规则 | annuity_transfer_to_universal_account_rules |
| 万能账户最低保证利率 | universal_account_guaranteed_interest_rate |
| 万能账户结算规则 | universal_account_settlement_rules |
| 初始费用规则 | initial_charge_rules |
| 领取手续费规则 | withdrawal_charge_rules |
| 分红规则 | dividend_rules |
| 非保证利益规则 | non_guaranteed_benefit_rules |
| 投资账户规则 | investment_account_rules |
| 双被保人/联合被保人规则 | multiple_insured_rules |

## 失能收入损失保险

Pack：`schemapack_disability_income_insurance@2026-08-12-v5`；Profile：`profile_disability_income_insurance@1.0.0-candidate`。

Profile hash：`bba94b5f95ed657d512044aa19569294cdde3a72b80637066e524952258483c0`。

### 产品概览（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 险种代码 | product_code |
| 险种简称 | product_short_name |
| 险种名称 | product_name |
| 开始使用时间 | sales_start_date |
| 结束使用时间 | sales_end_date |
| 产品类型 | product_type |
| 产品类别 | insurance_category |
| 销售渠道 | sales_channels |
| 发布外网 | external_publication_status |
| 销售状态 | sales_status |
| 主附加险 | policy_role |
| 产品简介 | product_summary |
| 产品特色 | official_product_features |
| 适用人群 | target_customer_profile |
| 产品宣传语 | marketing_tagline |
| 产品概览 | product_overview |

### 投保与合同（16字段）

| 字段 | 稳定字段 key |
|---|---|
| 投保年龄 | entry_age_range |
| 投保范围 | insured_eligibility |
| 健康告知要求 | health_declaration_requirements |
| 投保地区或常住地限制 | geographic_eligibility_requirements |
| 可投保职业 | eligible_occupation_classes |
| 核保方式 | underwriting_method |
| 购买限制 | purchase_limitations |
| 收入/职业资格要求 | income_and_employment_eligibility_requirements |
| 缴费期限 | premium_payment_term |
| 缴费方式 | premium_payment_frequency |
| 犹豫期 | cooling_off_period |
| 等待期 | waiting_period |
| 宽限期 | premium_grace_period |
| 保障期间 | coverage_period |
| 保障期间分类 | coverage_term_category |
| 犹豫期及合同解除（退保） | surrender_and_cancellation_terms |

### 续保与费率（1字段）

| 字段 | 稳定字段 key |
|---|---|
| 保险期间和续保 | coverage_and_renewal_terms |

### 保障责任与除外（18字段）

| 字段 | 稳定字段 key |
|---|---|
| 可覆盖风险 | covered_risk_categories |
| 保险责任 | coverage_responsibilities |
| 保什么 | coverage_summary |
| 保障人群 | age_segment_tags |
| 基本保险金额/保额范围 | sum_assured_range |
| 保额形态 | sum_assured_pattern |
| 保额增长规则 | sum_assured_growth_rules |
| 产品利率 | sum_assured_growth_rate |
| 保费豁免规则 | premium_waiver_rules |
| 保费豁免重大疾病清单 | premium_waiver_critical_illnesses |
| 满期生存金 | maturity_benefit_flag |
| 特定疾病清单 | covered_specified_diseases |
| 轻症特定疾病 | covered_mild_specified_diseases |
| 中症特定疾病 | covered_moderate_specified_diseases |
| 重症特定疾病 | covered_critical_specified_diseases |
| 疾病定义与认定标准 | disease_definitions_and_criteria |
| 特殊承保与除外标签 | special_coverage_and_exclusion_tags |
| 责任免除 | exclusions |

### 理赔与给付（15字段）

| 字段 | 稳定字段 key |
|---|---|
| 满期给付规则 | maturity_benefit_rules |
| 责任间给付关系 | benefit_interaction_rules |
| 理赔申请时效与申请材料 | claim_application_deadline_and_documents |
| 失能状态定义与认定标准 | disability_state_definition_and_criteria |
| 失能状态持续时间要求 | disability_state_duration_requirement |
| 失能状态核验与复评规则 | disability_status_verification_and_reassessment_rules |
| 失能恢复与给付终止规则 | disability_recovery_and_benefit_termination_rules |
| 收入损失保险金给付条件 | income_loss_benefit_eligibility_conditions |
| 收入损失保险金给付方式与金额规则 | income_loss_benefit_payment_rules |
| 收入损失保险金给付期限 | income_loss_benefit_payment_period |
| 收入损失关爱金给付条件 | income_loss_care_benefit_conditions |
| 收入损失关爱金给付方式与金额规则 | income_loss_care_benefit_payment_rules |
| 收入损失关爱金给付期限 | income_loss_care_benefit_payment_period |
| 收入损失认定与证明规则 | income_loss_verification_rules |
| 收入损失给付上限规则 | income_loss_benefit_limit_rules |

### 服务与权益（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 保单权益 | policyholder_rights |
| 可享服务 | eligible_service_packages |
| 增值服务 | medical_service_benefits |
| 可享税优 | tax_qualified_status |
| 税优规则 | tax_benefit_rules |

### 销售支持（5字段）

| 字段 | 稳定字段 key |
|---|---|
| 产品搭配规则 | product_bundle_rules |
| 产品异议话术 | objection_handling_scripts |
| 产品Q&A | product_faq |
| 四步法讲解话术 | four_step_sales_script |
| Pitch话术 | sales_pitch_script |

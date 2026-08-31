export interface SchemaWikiMvpRuntimeConfig {
  readonly SCHEMA_WIKI_MVP_ENTRY_KB_ID?: string
  readonly SCHEMA_WIKI_MVP_SERVING_KB_ID?: string
  readonly SCHEMA_WIKI_MVP_LABEL?: string
}

export interface SchemaWikiMvpExperience {
  readonly entryKnowledgeBaseId: string
  readonly servingKnowledgeBaseId: string
  readonly active: boolean
  readonly label: string | null
}

const ID_SEGMENT = /^[A-Za-z0-9._:-]+$/
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/
const DEFAULT_MVP_LABEL = '当前 MVP · 只读'

export const MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS = Object.freeze([
  ['product_code', '险种代码'],
  ['product_short_name', '险种简称'],
  ['product_name', '险种名称'],
  ['sales_start_date', '开始使用时间'],
  ['sales_end_date', '结束使用时间'],
  ['product_type', '产品类型'],
  ['insurance_category', '产品类别'],
  ['sales_channels', '销售渠道'],
  ['external_publication_status', '发布外网'],
  ['sales_status', '销售状态'],
  ['policy_role', '主附加险'],
  ['product_summary', '产品简介'],
  ['official_product_features', '产品特色'],
  ['target_customer_profile', '适用人群'],
  ['marketing_tagline', '产品宣传语'],
  ['product_overview', '产品概览'],
  ['entry_age_range', '投保年龄'],
  ['insured_eligibility', '投保范围'],
  ['health_declaration_requirements', '健康告知要求'],
  ['geographic_eligibility_requirements', '投保地区或常住地限制'],
  ['social_insurance_requirement', '不限社保'],
  ['eligible_occupation_classes', '可投保职业'],
  ['underwriting_method', '核保方式'],
  ['premium_payment_term', '缴费期限'],
  ['premium_payment_frequency', '缴费方式'],
  ['cooling_off_period', '犹豫期'],
  ['waiting_period', '等待期'],
  ['premium_grace_period', '宽限期'],
  ['coverage_period', '保障期间'],
  ['coverage_term_category', '保障期间分类'],
  ['surrender_and_cancellation_terms', '犹豫期及合同解除（退保）'],
  ['coverage_and_renewal_terms', '保险期间和续保'],
  ['guaranteed_renewal_status', '保证续保'],
  ['guaranteed_renewal_period', '保证续保期'],
  ['product_conversion_rules', '险种转换'],
  ['premium_adjustment_rules', '费率可调'],
  ['post_discontinuation_renewal_arrangement', '停售后续保安排'],
  ['covered_risk_categories', '可覆盖风险'],
  ['coverage_responsibilities', '保险责任'],
  ['coverage_summary', '保什么'],
  ['cancer_medical_coverage', '癌症医疗'],
  ['age_segment_tags', '保障人群'],
  ['coverage_limit_category', '额度类型'],
  ['special_coverage_and_exclusion_tags', '特殊承保与除外标签'],
  ['exclusions', '责任免除'],
  ['pre_existing_condition_rules', '既往症定义与处理'],
  ['out_of_hospital_special_drug_coverage', '外购药/特药责任'],
  ['indemnity_principle', '补偿原则'],
  ['zero_deductible_flag', '0免赔'],
  ['deductible_rules', '免赔额'],
  ['outpatient_inpatient_scope', '报销门诊/住院范围'],
  ['reimbursable_expense_scope', '报销范围'],
  ['reimbursement_rate_rules', '报销比例'],
  ['eligible_hospital_scope', '医院范围'],
  ['premium_medical_facility_coverage', '高端医疗'],
  ['direct_billing_and_advance_payment_rules', '直付或垫付规则'],
  ['claim_application_deadline_and_documents', '理赔申请时效与申请材料'],
  ['policyholder_rights', '保单权益'],
  ['eligible_service_packages', '可享服务'],
  ['medical_service_benefits', '增值服务'],
  ['tax_qualified_status', '可享税优'],
  ['tax_benefit_rules', '税优规则'],
  ['product_bundle_rules', '产品搭配规则'],
  ['objection_handling_scripts', '产品异议话术'],
  ['product_faq', '产品Q&A'],
  ['four_step_sales_script', '四步法讲解话术'],
  ['sales_pitch_script', 'Pitch话术'],
] as const)

function canonicalLabel(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.trim() === value
    && value.normalize('NFC') === value
    && !CONTROL_CHARACTER.test(value)
}

export function resolveSchemaWikiMvpExperience(
  currentKnowledgeBaseId: string,
  config: SchemaWikiMvpRuntimeConfig = {},
): SchemaWikiMvpExperience {
  const identity = Object.freeze({
    entryKnowledgeBaseId: currentKnowledgeBaseId,
    servingKnowledgeBaseId: currentKnowledgeBaseId,
    active: false,
    label: null,
  })
  if (!ID_SEGMENT.test(currentKnowledgeBaseId)) return identity

  const entry = config.SCHEMA_WIKI_MVP_ENTRY_KB_ID
  const serving = config.SCHEMA_WIKI_MVP_SERVING_KB_ID
  if (
    typeof entry !== 'string' || !ID_SEGMENT.test(entry)
    || typeof serving !== 'string' || !ID_SEGMENT.test(serving)
    || currentKnowledgeBaseId !== entry
  ) return identity

  const configuredLabel = config.SCHEMA_WIKI_MVP_LABEL
  return Object.freeze({
    entryKnowledgeBaseId: currentKnowledgeBaseId,
    servingKnowledgeBaseId: serving,
    active: true,
    label: canonicalLabel(configuredLabel) ? configuredLabel : DEFAULT_MVP_LABEL,
  })
}

export function assertMedicalSchema67Presentation(
  orderedFieldIds: ReadonlyArray<string>,
): ReadonlyMap<string, string> {
  if (
    orderedFieldIds.length !== MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS.length
    || new Set(orderedFieldIds).size !== orderedFieldIds.length
    || orderedFieldIds.some((fieldId, index) => (
      fieldId !== MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS[index][0]
    ))
  ) {
    throw new Error('SCHEMA_WIKI_MVP_PRESENTATION_TOPOLOGY_INVALID')
  }
  return new Map(MEDICAL_SCHEMA67_FIELD_PRESENTATION_ROWS)
}

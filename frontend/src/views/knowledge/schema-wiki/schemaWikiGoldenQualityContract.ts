import {
  citationPreviewHighlightStyle,
  parseCitationBBoxV1,
  parseLiveRevisionSourceReceiptV1,
  type CitationBBoxV1,
  type LiveRevisionSourceReceiptV1,
} from '../../../components/schema-wiki/schemaCitationTarget.ts'

export type GoldenQualityStatus = 'PASS' | 'FAIL' | 'FIXTURE_ONLY' | 'INCONCLUSIVE'
export type Schema67State = 'present' | 'absent_explicitly' | 'unknown'

export interface Schema67GoldenMetricV1 {
  readonly metric_id: string
  readonly numerator: number | null
  readonly denominator: number | null
  readonly value_ppm: number | null
  readonly supports: ReadonlyArray<number>
  readonly evaluability: 'EVALUABLE' | 'NOT_EVALUABLE'
  readonly sample_size: 'SMALL_SAMPLE' | 'ADEQUATE' | 'NOT_EVALUABLE'
  readonly wilson_low_ppm: number | null
  readonly wilson_high_ppm: number | null
  readonly admission_status: 'PASS' | 'FAIL'
  readonly metric_sha256: string
}

export interface Schema67GoldenFieldDecisionV1 {
  readonly field_id: string
  readonly golden_field_sha256: string
  readonly candidate_state: Schema67State
  readonly golden_state: Schema67State
  readonly state_correct: boolean
  readonly value_correct: boolean
  readonly atom_true_positive: number
  readonly atom_false_positive: number
  readonly atom_false_negative: number
  readonly atom_f1_ppm: number
  readonly evidence_fragments: number
  readonly evidence_fragments_matched: number
  readonly bbox_required: number
  readonly bbox_passed: number
  readonly bbox_iou_ppm_values: ReadonlyArray<number>
  readonly high_risk_pass: boolean
  readonly conflict_resolved: boolean
  readonly decision_sha256: string
}

export interface Schema67GoldenPublicAggregateV1 {
  readonly contract: 'schema67-golden-public-aggregate.v1'
  readonly product_version_id: '596-1'
  readonly candidate_sha256: string
  readonly golden_set_sha256: string
  readonly evaluator_identity_sha256: string
  readonly metrics: ReadonlyArray<Schema67GoldenMetricV1>
  readonly status: 'PASS'
  readonly reason_codes: ReadonlyArray<string>
  readonly aggregate_sha256: string
}

export interface Schema67GoldenPrivateDossierV1 {
  readonly contract: 'schema67-golden-private-dossier.v1'
  readonly candidate_sha256: string
  readonly candidate_evidence_authority_sha256: string
  readonly golden_set_sha256: string
  readonly field_decisions: ReadonlyArray<Schema67GoldenFieldDecisionV1>
  readonly metrics: ReadonlyArray<Schema67GoldenMetricV1>
  readonly status: 'PASS'
  readonly reason_codes: ReadonlyArray<string>
  readonly dossier_sha256: string
}

export interface SchemaWikiGoldenQualitySummaryV1 {
  readonly version: 'schema-wiki-golden-quality-summary.v1'
  readonly preparation_id: string
  readonly evaluation_id: string
  readonly quality_gate_receipt_sha256: string
  readonly public_aggregate: Schema67GoldenPublicAggregateV1
  readonly evaluation_bundle_sha256: string
  readonly wiki_admission_allowed: false
  readonly serving_effect: 'NONE'
}

export interface SchemaWikiGoldenQualityDossierV1 {
  readonly version: 'schema-wiki-golden-quality-dossier.v1'
  readonly preparation_id: string
  readonly evaluation_id: string
  readonly quality_gate_receipt_sha256: string
  readonly private_dossier: Schema67GoldenPrivateDossierV1
  readonly evaluation_bundle_sha256: string
  readonly serving_effect: 'NONE'
}

export interface SchemaWikiGoldenEvidencePreviewRequestV1 {
  readonly preparation_id: string
  readonly evaluation_id: string
  readonly field_id: string
  readonly evidence_id: string
}

export interface SchemaWikiGoldenEvidencePreviewAuthorityV1 {
  readonly contract: 'schema-wiki-golden-evidence-preview-authority.v1'
  readonly token_key_id: string
  readonly preparation_id: string
  readonly evaluation_id: string
  readonly candidate_sha256: string
  readonly field_id: string
  readonly evidence_id: string
  readonly revision_source: LiveRevisionSourceReceiptV1
  readonly citation_sha256: string
  readonly binding_sha256: string
  readonly evidence_receipt_sha256: string
  readonly page_number: number
  readonly bbox: CitationBBoxV1
  readonly quote_sha256: string
  readonly content_snapshot_sha256: string
  readonly coordinate_space_version: 'normalized_0_1e6'
  readonly page_width: 1_000_000
  readonly page_height: 1_000_000
  readonly rotation_degrees: 0 | 90 | 180 | 270
  readonly retention_state: 'pinned'
  readonly expires_at_unix: number
  readonly authority_sha256: string
  readonly opaque_token: string
}

const SUMMARY_KEYS = [
  'version', 'preparation_id', 'evaluation_id', 'quality_gate_receipt_sha256',
  'public_aggregate', 'evaluation_bundle_sha256', 'wiki_admission_allowed', 'serving_effect',
] as const
const DOSSIER_KEYS = [
  'version', 'preparation_id', 'evaluation_id', 'quality_gate_receipt_sha256',
  'private_dossier', 'evaluation_bundle_sha256', 'serving_effect',
] as const
const PUBLIC_KEYS = [
  'contract', 'product_version_id', 'candidate_sha256', 'golden_set_sha256',
  'evaluator_identity_sha256', 'metrics', 'status', 'reason_codes', 'aggregate_sha256',
] as const
const PRIVATE_KEYS = [
  'contract', 'candidate_sha256', 'candidate_evidence_authority_sha256', 'golden_set_sha256',
  'field_decisions', 'metrics', 'status', 'reason_codes', 'dossier_sha256',
] as const
const FIELD_KEYS = [
  'field_id', 'golden_field_sha256', 'candidate_state', 'golden_state', 'state_correct',
  'value_correct', 'atom_true_positive', 'atom_false_positive', 'atom_false_negative',
  'atom_f1_ppm', 'evidence_fragments', 'evidence_fragments_matched', 'bbox_required',
  'bbox_passed', 'bbox_iou_ppm_values', 'high_risk_pass', 'conflict_resolved',
  'decision_sha256',
] as const
const METRIC_KEYS = [
  'metric_id', 'numerator', 'denominator', 'value_ppm', 'supports', 'evaluability',
  'sample_size', 'wilson_low_ppm', 'wilson_high_ppm', 'admission_status', 'metric_sha256',
] as const
const PREVIEW_KEYS = [
  'contract', 'token_key_id', 'preparation_id', 'evaluation_id', 'candidate_sha256',
  'field_id', 'evidence_id', 'revision_source', 'citation_sha256', 'binding_sha256',
  'evidence_receipt_sha256', 'page_number', 'bbox', 'quote_sha256',
  'content_snapshot_sha256', 'coordinate_space_version', 'page_width', 'page_height',
  'rotation_degrees', 'retention_state', 'expires_at_unix', 'authority_sha256', 'opaque_token',
] as const

const METRIC_IDS = Object.freeze([
  'sgq.state.micro_accuracy.v1',
  'sgq.state.macro_recall.v1',
  'sgq.value.present.micro_precision.v1',
  'sgq.value.present.micro_recall.v1',
  'sgq.value.present.macro_f1.v1',
  'sgq.state.absent_to_unknown.v1',
  'sgq.state.unknown_to_absent.v1',
  'sgq.value.wrong_fill_rate.v1',
  'sgq.value.hallucinated_fill_rate.v1',
  'sgq.evidence.document_revision_page_precision.v1',
  'sgq.evidence.field_support_recall.v1',
  'sgq.evidence.bbox_iou.v1',
  'sgq.evidence.highlight_accuracy.v1',
  'sgq.human.high_risk_pass.v1',
  'sgq.human.conflict_resolution_pass.v1',
])
export const SCHEMA67_GOLDEN_ORDERED_FIELD_IDS = Object.freeze([
  'product_code', 'product_short_name', 'product_name', 'sales_start_date', 'sales_end_date',
  'product_type', 'insurance_category', 'sales_channels', 'external_publication_status',
  'sales_status', 'policy_role', 'product_summary', 'official_product_features',
  'target_customer_profile', 'marketing_tagline', 'product_overview', 'entry_age_range',
  'insured_eligibility', 'health_declaration_requirements', 'geographic_eligibility_requirements',
  'social_insurance_requirement', 'eligible_occupation_classes', 'underwriting_method',
  'premium_payment_term', 'premium_payment_frequency', 'cooling_off_period', 'waiting_period',
  'premium_grace_period', 'coverage_period', 'coverage_term_category',
  'surrender_and_cancellation_terms', 'coverage_and_renewal_terms', 'guaranteed_renewal_status',
  'guaranteed_renewal_period', 'product_conversion_rules', 'premium_adjustment_rules',
  'post_discontinuation_renewal_arrangement', 'covered_risk_categories',
  'coverage_responsibilities', 'coverage_summary', 'cancer_medical_coverage', 'age_segment_tags',
  'coverage_limit_category', 'special_coverage_and_exclusion_tags', 'exclusions',
  'pre_existing_condition_rules', 'out_of_hospital_special_drug_coverage', 'indemnity_principle',
  'zero_deductible_flag', 'deductible_rules', 'outpatient_inpatient_scope',
  'reimbursable_expense_scope', 'reimbursement_rate_rules', 'eligible_hospital_scope',
  'premium_medical_facility_coverage', 'direct_billing_and_advance_payment_rules',
  'claim_application_deadline_and_documents', 'policyholder_rights', 'eligible_service_packages',
  'medical_service_benefits', 'tax_qualified_status', 'tax_benefit_rules', 'product_bundle_rules',
  'objection_handling_scripts', 'product_faq', 'four_step_sales_script', 'sales_pitch_script',
])
const SHA256 = /^[0-9a-f]{64}$/
const OPAQUE_TOKEN = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/
const TEXT = /^[^\u0000-\u001f\u007f]+$/

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function canonicalText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value
    && value.normalize('NFC') === value && TEXT.test(value)
}

function hash(value: unknown): value is string {
  return typeof value === 'string' && SHA256.test(value)
}

function integer(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max
}

function nullableInteger(value: unknown, min = 0, max = Number.MAX_SAFE_INTEGER): value is number | null {
  return value === null || integer(value, min, max)
}

function parseMetric(value: unknown, expectedId: string): Schema67GoldenMetricV1 {
  if (!record(value) || !exactKeys(value, METRIC_KEYS)) throw new Error('GOLDEN_QUALITY_METRIC_INVALID')
  if (
    value.metric_id !== expectedId || !hash(value.metric_sha256)
    || !['EVALUABLE', 'NOT_EVALUABLE'].includes(value.evaluability as string)
    || !['SMALL_SAMPLE', 'ADEQUATE', 'NOT_EVALUABLE'].includes(value.sample_size as string)
    || !['PASS', 'FAIL'].includes(value.admission_status as string)
    || !nullableInteger(value.numerator) || !nullableInteger(value.denominator, 1)
    || !nullableInteger(value.value_ppm, 0, 1_000_000)
    || !nullableInteger(value.wilson_low_ppm, 0, 1_000_000)
    || !nullableInteger(value.wilson_high_ppm, 0, 1_000_000)
    || !Array.isArray(value.supports) || value.supports.some(item => !integer(item))
  ) throw new Error('GOLDEN_QUALITY_METRIC_INVALID')
  if (value.evaluability === 'EVALUABLE') {
    if (value.numerator === null || value.denominator === null || value.value_ppm === null
      || value.numerator > value.denominator || value.sample_size === 'NOT_EVALUABLE') {
      throw new Error('GOLDEN_QUALITY_METRIC_INVALID')
    }
  } else if (value.numerator !== null || value.denominator !== null || value.value_ppm !== null
    || value.wilson_low_ppm !== null || value.wilson_high_ppm !== null
    || value.sample_size !== 'NOT_EVALUABLE') {
    throw new Error('GOLDEN_QUALITY_METRIC_INVALID')
  }
  return Object.freeze({
    metric_id: value.metric_id as string,
    numerator: value.numerator as number | null,
    denominator: value.denominator as number | null,
    value_ppm: value.value_ppm as number | null,
    supports: Object.freeze([...(value.supports as number[])]),
    evaluability: value.evaluability as Schema67GoldenMetricV1['evaluability'],
    sample_size: value.sample_size as Schema67GoldenMetricV1['sample_size'],
    wilson_low_ppm: value.wilson_low_ppm as number | null,
    wilson_high_ppm: value.wilson_high_ppm as number | null,
    admission_status: value.admission_status as Schema67GoldenMetricV1['admission_status'],
    metric_sha256: value.metric_sha256 as string,
  })
}

function parseMetrics(value: unknown): ReadonlyArray<Schema67GoldenMetricV1> {
  if (!Array.isArray(value) || value.length !== METRIC_IDS.length) {
    throw new Error('GOLDEN_QUALITY_METRIC_INVALID')
  }
  return Object.freeze(value.map((metric, index) => parseMetric(metric, METRIC_IDS[index])))
}

function parseFieldDecision(value: unknown): Schema67GoldenFieldDecisionV1 {
  if (!record(value) || !exactKeys(value, FIELD_KEYS)) throw new Error('GOLDEN_QUALITY_FIELD_INVALID')
  const counts = [
    value.atom_true_positive, value.atom_false_positive, value.atom_false_negative,
    value.evidence_fragments, value.evidence_fragments_matched, value.bbox_required, value.bbox_passed,
  ]
  if (
    !canonicalText(value.field_id) || !hash(value.golden_field_sha256) || !hash(value.decision_sha256)
    || !['present', 'absent_explicitly', 'unknown'].includes(value.candidate_state as string)
    || !['present', 'absent_explicitly', 'unknown'].includes(value.golden_state as string)
    || typeof value.state_correct !== 'boolean' || typeof value.value_correct !== 'boolean'
    || typeof value.high_risk_pass !== 'boolean' || typeof value.conflict_resolved !== 'boolean'
    || counts.some(item => !integer(item)) || !integer(value.atom_f1_ppm, 0, 1_000_000)
    || (value.evidence_fragments_matched as number) > (value.evidence_fragments as number)
    || (value.bbox_passed as number) > (value.bbox_required as number)
    || !Array.isArray(value.bbox_iou_ppm_values)
    || value.bbox_iou_ppm_values.length !== value.bbox_required
    || value.bbox_iou_ppm_values.some(item => !integer(item, 0, 1_000_000))
  ) throw new Error('GOLDEN_QUALITY_FIELD_INVALID')
  return Object.freeze({
    ...(value as unknown as Schema67GoldenFieldDecisionV1),
    bbox_iou_ppm_values: Object.freeze([...(value.bbox_iou_ppm_values as number[])]),
  })
}

function parsePublicAggregate(value: unknown): Schema67GoldenPublicAggregateV1 {
  if (!record(value) || !exactKeys(value, PUBLIC_KEYS)) throw new Error('GOLDEN_QUALITY_SUMMARY_INVALID')
  if (
    value.contract !== 'schema67-golden-public-aggregate.v1' || value.product_version_id !== '596-1'
    || value.status !== 'PASS' || !Array.isArray(value.reason_codes) || value.reason_codes.length !== 0
    || !hash(value.candidate_sha256) || !hash(value.golden_set_sha256)
    || !hash(value.evaluator_identity_sha256) || !hash(value.aggregate_sha256)
  ) throw new Error('GOLDEN_QUALITY_SUMMARY_INVALID')
  return Object.freeze({
    ...(value as unknown as Schema67GoldenPublicAggregateV1),
    metrics: parseMetrics(value.metrics),
    reason_codes: Object.freeze([]),
  })
}

function parsePrivateDossier(value: unknown): Schema67GoldenPrivateDossierV1 {
  if (!record(value) || !exactKeys(value, PRIVATE_KEYS)) throw new Error('GOLDEN_QUALITY_DOSSIER_INVALID')
  if (
    value.contract !== 'schema67-golden-private-dossier.v1' || value.status !== 'PASS'
    || !Array.isArray(value.reason_codes) || value.reason_codes.length !== 0
    || !hash(value.candidate_sha256) || !hash(value.candidate_evidence_authority_sha256)
    || !hash(value.golden_set_sha256) || !hash(value.dossier_sha256)
    || !Array.isArray(value.field_decisions) || value.field_decisions.length !== 67
  ) throw new Error('GOLDEN_QUALITY_DOSSIER_INVALID')
  let fields: ReadonlyArray<Schema67GoldenFieldDecisionV1>
  let metrics: ReadonlyArray<Schema67GoldenMetricV1>
  try {
    fields = Object.freeze(value.field_decisions.map(parseFieldDecision))
    metrics = parseMetrics(value.metrics)
  } catch {
    throw new Error('GOLDEN_QUALITY_DOSSIER_INVALID')
  }
  if (new Set(fields.map(field => field.field_id)).size !== fields.length
    || fields.some((field, index) => field.field_id !== SCHEMA67_GOLDEN_ORDERED_FIELD_IDS[index])) {
    throw new Error('GOLDEN_QUALITY_DOSSIER_INVALID')
  }
  return Object.freeze({
    ...(value as unknown as Schema67GoldenPrivateDossierV1),
    field_decisions: fields,
    metrics,
    reason_codes: Object.freeze([]),
  })
}

export function goldenQualityStatusPresentation(value: unknown): {
  readonly status: GoldenQualityStatus
  readonly readable: boolean
  readonly label: string
} {
  const labels: Record<GoldenQualityStatus, string> = {
    PASS: 'Quality gate passed',
    FAIL: 'Quality gate failed',
    FIXTURE_ONLY: 'Fixture only — not a real evaluation',
    INCONCLUSIVE: 'Quality evaluation inconclusive',
  }
  if (!canonicalText(value) || !(value in labels)) throw new Error('GOLDEN_QUALITY_STATUS_INVALID')
  const status = value as GoldenQualityStatus
  return Object.freeze({ status, readable: status === 'PASS', label: labels[status] })
}

export function parseSchemaWikiGoldenQualitySummary(
  value: unknown,
  expected: { readonly preparationId: string; readonly evaluationId: string },
): SchemaWikiGoldenQualitySummaryV1 {
  if (!record(value) || !exactKeys(value, SUMMARY_KEYS)) throw new Error('GOLDEN_QUALITY_SUMMARY_INVALID')
  const aggregate = parsePublicAggregate(value.public_aggregate)
  if (
    value.version !== 'schema-wiki-golden-quality-summary.v1'
    || value.preparation_id !== expected.preparationId || value.evaluation_id !== expected.evaluationId
    || !hash(value.quality_gate_receipt_sha256) || !hash(value.evaluation_bundle_sha256)
    || value.wiki_admission_allowed !== false || value.serving_effect !== 'NONE'
  ) throw new Error('GOLDEN_QUALITY_SUMMARY_INVALID')
  return Object.freeze({
    version: value.version,
    preparation_id: value.preparation_id,
    evaluation_id: value.evaluation_id,
    quality_gate_receipt_sha256: value.quality_gate_receipt_sha256,
    public_aggregate: aggregate,
    evaluation_bundle_sha256: value.evaluation_bundle_sha256,
    wiki_admission_allowed: false,
    serving_effect: 'NONE',
  })
}

export function parseSchemaWikiGoldenQualityDossier(
  value: unknown,
  expected: { readonly preparationId: string; readonly evaluationId: string },
): SchemaWikiGoldenQualityDossierV1 {
  if (!record(value) || !exactKeys(value, DOSSIER_KEYS)) throw new Error('GOLDEN_QUALITY_DOSSIER_INVALID')
  const privateDossier = parsePrivateDossier(value.private_dossier)
  if (
    value.version !== 'schema-wiki-golden-quality-dossier.v1'
    || value.preparation_id !== expected.preparationId || value.evaluation_id !== expected.evaluationId
    || !hash(value.quality_gate_receipt_sha256) || !hash(value.evaluation_bundle_sha256)
    || value.serving_effect !== 'NONE'
  ) throw new Error('GOLDEN_QUALITY_DOSSIER_INVALID')
  return Object.freeze({
    version: value.version,
    preparation_id: value.preparation_id,
    evaluation_id: value.evaluation_id,
    quality_gate_receipt_sha256: value.quality_gate_receipt_sha256,
    private_dossier: privateDossier,
    evaluation_bundle_sha256: value.evaluation_bundle_sha256,
    serving_effect: 'NONE',
  })
}

export function assertGoldenSummaryDossierJoin(
  summary: SchemaWikiGoldenQualitySummaryV1,
  dossier: SchemaWikiGoldenQualityDossierV1,
): void {
  if (
    summary.preparation_id !== dossier.preparation_id || summary.evaluation_id !== dossier.evaluation_id
    || summary.quality_gate_receipt_sha256 !== dossier.quality_gate_receipt_sha256
    || summary.evaluation_bundle_sha256 !== dossier.evaluation_bundle_sha256
    || summary.public_aggregate.candidate_sha256 !== dossier.private_dossier.candidate_sha256
    || summary.public_aggregate.golden_set_sha256 !== dossier.private_dossier.golden_set_sha256
    || JSON.stringify(summary.public_aggregate.metrics) !== JSON.stringify(dossier.private_dossier.metrics)
  ) throw new Error('GOLDEN_QUALITY_IDENTITY_MISMATCH')
}

export function parseSchemaWikiGoldenEvidencePreviewAuthority(
  value: unknown,
  expected: SchemaWikiGoldenEvidencePreviewRequestV1 & { readonly candidateSha256: string },
): SchemaWikiGoldenEvidencePreviewAuthorityV1 {
  if (!record(value) || !exactKeys(value, PREVIEW_KEYS)) throw new Error('GOLDEN_EVIDENCE_UNAVAILABLE')
  if (
    value.contract !== 'schema-wiki-golden-evidence-preview-authority.v1'
    || value.preparation_id !== expected.preparation_id || value.evaluation_id !== expected.evaluation_id
    || value.field_id !== expected.field_id || value.evidence_id !== expected.evidence_id
    || value.candidate_sha256 !== expected.candidateSha256
    || !hash(value.evaluation_id) || !hash(value.evidence_id) || !hash(value.candidate_sha256)
    || !hash(value.citation_sha256) || !hash(value.binding_sha256)
    || !hash(value.evidence_receipt_sha256) || !hash(value.quote_sha256)
    || !hash(value.content_snapshot_sha256) || !hash(value.authority_sha256)
    || !canonicalText(value.token_key_id) || !canonicalText(value.preparation_id)
    || !canonicalText(value.field_id) || value.retention_state !== 'pinned'
    || value.coordinate_space_version !== 'normalized_0_1e6'
    || value.page_width !== 1_000_000 || value.page_height !== 1_000_000
    || ![0, 90, 180, 270].includes(value.rotation_degrees as number)
    || !integer(value.expires_at_unix, 1) || typeof value.opaque_token !== 'string'
    || !OPAQUE_TOKEN.test(value.opaque_token)
  ) throw new Error('GOLDEN_EVIDENCE_UNAVAILABLE')
  const revisionSource = parseLiveRevisionSourceReceiptV1(value.revision_source)
  if (!integer(value.page_number, 1) || value.page_number > revisionSource.page_count) {
    throw new Error('PAGE_UNAVAILABLE')
  }
  const bbox = parseCitationBBoxV1(value.bbox)
  if (
    bbox.coordinate_system !== value.coordinate_space_version
    || bbox.page_width !== value.page_width || bbox.page_height !== value.page_height
  ) throw new Error('BBOX_UNAVAILABLE')
  return Object.freeze({
    ...(value as unknown as SchemaWikiGoldenEvidencePreviewAuthorityV1),
    revision_source: revisionSource,
    bbox,
  })
}

export function goldenEvidenceHighlightStyle(
  authority: SchemaWikiGoldenEvidencePreviewAuthorityV1,
  viewport: { readonly width: number; readonly height: number },
): { readonly left: number; readonly top: number; readonly width: number; readonly height: number } {
  return citationPreviewHighlightStyle(authority, viewport)
}

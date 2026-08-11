import type { GoldenReviewerPresentation } from './schemaWikiGoldenReviewerPresentation.ts'

export interface SchemaWikiGoldenSuccessorStatusV1 {
  readonly version: 'schema-wiki-golden-successor-status.v1'
  readonly contract: 'schema-wiki-golden-successor-status.v1'
  readonly tenant_id: 10003
  readonly space_id: string
  readonly raw_kb_id: string
  readonly wiki_kb_id: string
  readonly product_version_id: '596-1'
  readonly schema_pack_id: 'medical-schema67.v1'
  readonly golden_set_sha256: string
  readonly mapping_sha256: string
  readonly successor_file_sha256: string
  readonly attestation_sha256: string
  readonly source_review_status: 'COMPLETED'
  readonly reviewed_by: 'linyao'
  readonly annotator_model_id: 'claude-fable-5'
  readonly reviewed_at: null
  readonly attestor_id: 'workspace-owner-houjing'
  readonly attested_at: string
  readonly schema67_mapping_status: 'COMPLETE_67'
  readonly closed_count: number
  readonly residual_count: number
  readonly residual_field_ids: ReadonlyArray<string>
  readonly golden_admission_status: 'BLOCKED_RECEIPT_UNVERIFIED'
  readonly receipt_status: 'UNVERIFIED'
  readonly ready_to_sign_status: 'READY_TO_SIGN'
  readonly status_sha256: string
}

export interface GoldenSuccessorStatusExpectedScope {
  readonly spaceId: string
  readonly rawKbId: string
  readonly wikiKbId: string
}

const CONTRACT = 'schema-wiki-golden-successor-status.v1'
const STATUS_KEYS = Object.freeze([
  'annotator_model_id', 'attestation_sha256', 'attested_at', 'attestor_id',
  'closed_count', 'contract', 'golden_admission_status', 'golden_set_sha256',
  'mapping_sha256', 'product_version_id', 'raw_kb_id', 'ready_to_sign_status',
  'receipt_status', 'residual_count', 'residual_field_ids', 'reviewed_at',
  'reviewed_by', 'schema67_mapping_status', 'schema_pack_id', 'source_review_status',
  'space_id', 'status_sha256', 'successor_file_sha256', 'tenant_id', 'version', 'wiki_kb_id',
])
const AUTHORITY = Object.freeze({
  goldenSetSHA256: '6ce87e0d1352b9f3435baa232c01f0dfdb6fd968b959b2462038849da40c8ad0',
  mappingSHA256: '85646d263932d33a2dbb02fbbc93425252618d162c3c1e012b2fede5addf2f43',
  successorFileSHA256: '8ff7e476b41f737427a72dd08a86a28a0057b4b5d085b7e23399bc5d38671e71',
  attestationSHA256: '7fdbfde1b57de76a59c79b5e0535a48766c896e6ee7615bc055bb9bec73b0d5d',
  statusSHA256: '4a219fc1b48474df4473a1f44215c872d7eb944990e847fe3101e55ae65ef594',
})
const HASH = /^[0-9a-f]{64}$/
const TEXT = /^[^\u0000-\u001f\u007f]+$/
const ADMISSION_BLOCKING_REASON_CODES = Object.freeze([
  'GOLDEN_APPROVAL_RECEIPT_UNVERIFIED',
])

function invalid(): never {
  throw new Error('GOLDEN_SUCCESSOR_STATUS_INVALID')
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exactKeys(value: Record<string, unknown>): boolean {
  const keys = Object.keys(value).sort()
  return keys.length === STATUS_KEYS.length && keys.every((key, index) => key === STATUS_KEYS[index])
}

function canonicalText(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
    && value.normalize('NFC') === value && TEXT.test(value)
}

function hash(value: unknown): value is string {
  return typeof value === 'string' && HASH.test(value)
}

function canonicalJSON(value: unknown): string {
  if (value === null || typeof value === 'boolean' || typeof value === 'number') {
    return JSON.stringify(value)
  }
  if (typeof value === 'string') {
    if (!canonicalText(value)) invalid()
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`
  if (record(value)) {
    return `{${Object.keys(value).sort().map(key => {
      if (!canonicalText(key)) invalid()
      return `${JSON.stringify(key)}:${canonicalJSON(value[key])}`
    }).join(',')}}`
  }
  return invalid()
}

async function statusSHA256(value: Record<string, unknown>): Promise<string> {
  const payload = { ...value }
  delete payload.status_sha256
  const preimage = new TextEncoder().encode(
    `schema-wiki-canonical.v1\u0000${CONTRACT}\u0000${canonicalJSON(payload)}`,
  )
  const digest = await globalThis.crypto.subtle.digest('SHA-256', preimage)
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
}

export async function parseSchemaWikiGoldenSuccessorStatus(
  value: unknown,
  expected: GoldenSuccessorStatusExpectedScope,
): Promise<SchemaWikiGoldenSuccessorStatusV1> {
  if (!record(value) || !exactKeys(value) || !record(expected)) invalid()
  if (
    value.version !== CONTRACT || value.contract !== CONTRACT || value.tenant_id !== 10003
    || value.space_id !== expected.spaceId || value.raw_kb_id !== expected.rawKbId
    || value.wiki_kb_id !== expected.wikiKbId || value.product_version_id !== '596-1'
    || value.schema_pack_id !== 'medical-schema67.v1'
    || value.golden_set_sha256 !== AUTHORITY.goldenSetSHA256
    || value.mapping_sha256 !== AUTHORITY.mappingSHA256
    || value.successor_file_sha256 !== AUTHORITY.successorFileSHA256
    || value.attestation_sha256 !== AUTHORITY.attestationSHA256
    || value.status_sha256 !== AUTHORITY.statusSHA256
    || value.source_review_status !== 'COMPLETED' || value.reviewed_by !== 'linyao'
    || value.annotator_model_id !== 'claude-fable-5' || value.reviewed_at !== null
    || value.attestor_id !== 'workspace-owner-houjing' || !canonicalText(value.attested_at)
    || value.schema67_mapping_status !== 'COMPLETE_67'
    || !Number.isSafeInteger(value.closed_count) || !Number.isSafeInteger(value.residual_count)
    || value.closed_count !== 67 || value.residual_count !== 0
    || !Array.isArray(value.residual_field_ids)
    || value.residual_field_ids.length !== 0
    || value.golden_admission_status !== 'BLOCKED_RECEIPT_UNVERIFIED'
    || value.receipt_status !== 'UNVERIFIED'
    || value.ready_to_sign_status !== 'READY_TO_SIGN'
    || !hash(value.golden_set_sha256) || !hash(value.mapping_sha256)
    || !hash(value.successor_file_sha256) || !hash(value.attestation_sha256)
    || !hash(value.status_sha256)
  ) invalid()
  const residualIDs = (value.residual_field_ids as unknown[]).map(fieldID => {
    if (!canonicalText(fieldID)) invalid()
    return fieldID
  })
  if (
    residualIDs.length !== 0
    || await statusSHA256(value) !== value.status_sha256
  ) invalid()
  return Object.freeze({
    ...(value as unknown as SchemaWikiGoldenSuccessorStatusV1),
    residual_field_ids: Object.freeze([...residualIDs]),
  })
}

export function goldenSuccessorStatusPresentation(
  status: SchemaWikiGoldenSuccessorStatusV1,
): GoldenReviewerPresentation {
  return Object.freeze({
    sourceReview: Object.freeze({
      status: status.source_review_status,
      reviewedBy: status.reviewed_by,
      reviewedAtLabel: 'UNKNOWN',
      annotatorModelId: status.annotator_model_id,
      attestedBy: status.attestor_id,
    }),
    mapping: Object.freeze({
      status: status.schema67_mapping_status,
      closedCount: status.closed_count,
      residualCount: status.residual_count,
      orderedResidualFieldIds: Object.freeze([...status.residual_field_ids]),
    }),
    admission: Object.freeze({
      status: status.golden_admission_status,
      readyToSignStatus: status.ready_to_sign_status,
      receiptStatus: status.receipt_status,
      blockingReasonCodes: ADMISSION_BLOCKING_REASON_CODES,
    }),
  })
}

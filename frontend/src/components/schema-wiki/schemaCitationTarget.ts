export type CitationCoordinateSystem = 'pdf_points' | 'normalized_0_1e6'

export interface CitationBBoxV1 {
  readonly coordinate_system: CitationCoordinateSystem
  readonly page_width: number
  readonly page_height: number
  readonly x0: number
  readonly y0: number
  readonly x1: number
  readonly y1: number
}

export interface CitationTargetV1 {
  readonly contract: 'citation-target.v1'
  readonly citation_id: string
  readonly source_role: string
  readonly space_id: string
  readonly entity_version_id: string
  readonly knowledge_id: string
  readonly chunk_id: string
  readonly source_revision_id: string
  readonly parse_attempt_id: string
  readonly parsed_document_sha256: string
  readonly parse_manifest_sha256: string
  readonly page_number: number
  readonly locator_ref: string
  readonly bbox: CitationBBoxV1
  readonly quote_snapshot: string
  readonly quote_sha256: string
  readonly content_snapshot_sha256: string
  readonly logical_member_ref: string
  readonly citation_sha256: string
}

export interface CitationPinV1 {
  readonly release_id: string
  readonly field_id: string
  readonly logical_member_ref: string
  readonly member_digest: string
  readonly citation_binding: {
    readonly contract: 'citation-member-binding.v1'
    readonly citation_sha256: string
    readonly logical_member_ref: string
    readonly member_digest: string
    readonly binding_sha256: string
  }
  readonly space_id: string
  readonly entity_version_id: string
  readonly knowledge_id: string
  readonly chunk_id: string
  readonly source_revision_id: string
  readonly parse_attempt_id: string
  readonly parsed_document_sha256: string
  readonly parse_manifest_sha256: string
  readonly page_number: number
  readonly locator_ref: string
  readonly quote_snapshot: string
  readonly content_snapshot_sha256: string
}

const TARGET_KEYS = [
  'contract',
  'citation_id',
  'source_role',
  'space_id',
  'entity_version_id',
  'knowledge_id',
  'chunk_id',
  'source_revision_id',
  'parse_attempt_id',
  'parsed_document_sha256',
  'parse_manifest_sha256',
  'page_number',
  'locator_ref',
  'bbox',
  'quote_snapshot',
  'quote_sha256',
  'content_snapshot_sha256',
  'logical_member_ref',
  'citation_sha256',
] as const
const BBOX_KEYS = [
  'coordinate_system', 'page_width', 'page_height', 'x0', 'y0', 'x1', 'y1',
] as const
const HEX_64 = /^[0-9a-f]{64}$/
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function isCanonicalText(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.trim() === value
    && value.normalize('NFC') === value
    && !CONTROL_CHARACTER.test(value)
}

function isHash(value: unknown): value is string {
  return typeof value === 'string' && HEX_64.test(value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

export function parseCitationBBoxV1(value: unknown): CitationBBoxV1 {
  if (!isRecord(value) || !hasExactKeys(value, BBOX_KEYS)) {
    throw new Error('BBOX_UNAVAILABLE')
  }
  const coordinates = [value.page_width, value.page_height, value.x0, value.y0, value.x1, value.y1]
  if (
    !['pdf_points', 'normalized_0_1e6'].includes(value.coordinate_system as string)
    || coordinates.some(item => typeof item !== 'number' || !Number.isInteger(item))
    || !isPositiveInteger(value.page_width) || !isPositiveInteger(value.page_height)
    || (value.x0 as number) < 0 || (value.y0 as number) < 0
    || (value.x0 as number) >= (value.x1 as number)
    || (value.y0 as number) >= (value.y1 as number)
    || (value.x1 as number) > value.page_width || (value.y1 as number) > value.page_height
    || (
      value.x0 === 0 && value.y0 === 0
      && value.x1 === value.page_width && value.y1 === value.page_height
    )
  ) {
    throw new Error('BBOX_UNAVAILABLE')
  }
  return Object.freeze({
    coordinate_system: value.coordinate_system as CitationCoordinateSystem,
    page_width: value.page_width,
    page_height: value.page_height,
    x0: value.x0 as number,
    y0: value.y0 as number,
    x1: value.x1 as number,
    y1: value.y1 as number,
  })
}

export function parseCitationTarget(value: unknown): CitationTargetV1 {
  if (!isRecord(value)) {
    throw new Error('CITATION_TARGET_INCOMPLETE')
  }
  if (!hasExactKeys(value, TARGET_KEYS)) {
    const keysWithoutPage = TARGET_KEYS.filter(key => key !== 'page_number')
    if (!Object.hasOwn(value, 'page_number') && hasExactKeys(value, keysWithoutPage)) {
      throw new Error('PAGE_UNAVAILABLE')
    }
    throw new Error('CITATION_TARGET_INCOMPLETE')
  }
  if (!isPositiveInteger(value.page_number)) {
    throw new Error('PAGE_UNAVAILABLE')
  }
  if (
    !isCanonicalText(value.source_revision_id)
    || value.source_revision_id.toLowerCase() === 'current'
    || value.source_revision_id.toLowerCase() === 'latest'
  ) {
    throw new Error('CITATION_REVISION_NOT_PINNED')
  }
  const textFields = [
    value.citation_id,
    value.source_role,
    value.space_id,
    value.entity_version_id,
    value.knowledge_id,
    value.chunk_id,
    value.parse_attempt_id,
    value.locator_ref,
    value.quote_snapshot,
    value.logical_member_ref,
  ]
  const hashFields = [
    value.parsed_document_sha256,
    value.parse_manifest_sha256,
    value.quote_sha256,
    value.content_snapshot_sha256,
    value.citation_sha256,
  ]
  if (
    value.contract !== 'citation-target.v1'
    || textFields.some(item => !isCanonicalText(item))
    || hashFields.some(item => !isHash(item))
  ) {
    throw new Error('CITATION_TARGET_INCOMPLETE')
  }
  return Object.freeze({
    contract: value.contract,
    citation_id: value.citation_id as string,
    source_role: value.source_role as string,
    space_id: value.space_id as string,
    entity_version_id: value.entity_version_id as string,
    knowledge_id: value.knowledge_id as string,
    chunk_id: value.chunk_id as string,
    source_revision_id: value.source_revision_id,
    parse_attempt_id: value.parse_attempt_id as string,
    parsed_document_sha256: value.parsed_document_sha256 as string,
    parse_manifest_sha256: value.parse_manifest_sha256 as string,
    page_number: value.page_number,
    locator_ref: value.locator_ref as string,
    bbox: parseCitationBBoxV1(value.bbox),
    quote_snapshot: value.quote_snapshot as string,
    quote_sha256: value.quote_sha256 as string,
    content_snapshot_sha256: value.content_snapshot_sha256 as string,
    logical_member_ref: value.logical_member_ref as string,
    citation_sha256: value.citation_sha256 as string,
  })
}

export function assertPinnedCitation(target: CitationTargetV1, pin: CitationPinV1): void {
  if (
    pin.citation_binding.contract !== 'citation-member-binding.v1'
    || !isHash(pin.citation_binding.binding_sha256)
    || !isHash(pin.member_digest)
    || target.logical_member_ref !== `field:${pin.field_id}`
    || target.logical_member_ref !== pin.logical_member_ref
    || target.citation_sha256 !== pin.citation_binding.citation_sha256
    || target.logical_member_ref !== pin.citation_binding.logical_member_ref
    || pin.member_digest !== pin.citation_binding.member_digest
  ) {
    throw new Error('CITATION_MEMBER_BINDING_MISMATCH')
  }
  const actual = [
    target.space_id,
    target.entity_version_id,
    target.knowledge_id,
    target.chunk_id,
    target.source_revision_id,
    target.parse_attempt_id,
    target.parsed_document_sha256,
    target.parse_manifest_sha256,
    target.page_number,
    target.locator_ref,
    target.quote_snapshot,
    target.content_snapshot_sha256,
  ]
  const expected = [
    pin.space_id,
    pin.entity_version_id,
    pin.knowledge_id,
    pin.chunk_id,
    pin.source_revision_id,
    pin.parse_attempt_id,
    pin.parsed_document_sha256,
    pin.parse_manifest_sha256,
    pin.page_number,
    pin.locator_ref,
    pin.quote_snapshot,
    pin.content_snapshot_sha256,
  ]
  if (actual.some((item, index) => item !== expected[index])) {
    throw new Error('CITATION_REPLAY_IDENTITY_MISMATCH')
  }
}

export function citationHighlightStyle(
  target: CitationTargetV1,
  viewport: { width: number; height: number },
): { left: number; top: number; width: number; height: number } {
  if (
    !Number.isFinite(viewport.width) || viewport.width <= 0
    || !Number.isFinite(viewport.height) || viewport.height <= 0
  ) {
    throw new Error('BBOX_UNAVAILABLE')
  }
  const scaleX = viewport.width / target.bbox.page_width
  const scaleY = viewport.height / target.bbox.page_height
  return {
    left: target.bbox.x0 * scaleX,
    top: target.bbox.y0 * scaleY,
    width: (target.bbox.x1 - target.bbox.x0) * scaleX,
    height: (target.bbox.y1 - target.bbox.y0) * scaleY,
  }
}

export interface SchemaWikiCitationPreviewRequestV1 {
  readonly release_id: string
  readonly activation_epoch: number
  readonly field_id: string
  readonly citation_id: string
}

export interface LiveRevisionSourceReceiptV1 {
  readonly contract: 'live-revision-source-receipt.v1'
  readonly revision_source_id: string
  readonly tenant_id: number
  readonly space_id: string
  readonly raw_kb_id: string
  readonly wiki_kb_id: string
  readonly knowledge_id: string
  readonly evidence_parse_attempt_id: string
  readonly weknora_parse_attempt: number
  readonly resource_id: string
  readonly file_sha256: string
  readonly size: number
  readonly mime_type: 'application/pdf'
  readonly page_count: number
  readonly parsed_document_sha256: string
  readonly parse_manifest_sha256: string
  readonly weknora_manifest_algorithm: 'weknora.chunk_manifest.v1'
  readonly weknora_manifest_digest: string
  readonly weknora_chunk_count: number
  readonly source_receipt_sha256: string
}

export interface SchemaWikiCitationContentAuthorityV1 {
  readonly contract: 'schema-wiki-citation-content-authority.v1'
  readonly token_key_id: string
  readonly release_id: string
  readonly activation_epoch: number
  readonly candidate_sha256: string
  readonly field_id: string
  readonly citation_id: string
  readonly revision_source: LiveRevisionSourceReceiptV1
  readonly citation_sha256: string
  readonly binding_sha256: string
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

const PREVIEW_REQUEST_KEYS = [
  'release_id', 'activation_epoch', 'field_id', 'citation_id',
] as const
const REVISION_SOURCE_KEYS = [
  'contract', 'revision_source_id', 'tenant_id', 'space_id', 'raw_kb_id', 'wiki_kb_id',
  'knowledge_id', 'evidence_parse_attempt_id', 'weknora_parse_attempt', 'resource_id',
  'file_sha256', 'size', 'mime_type', 'page_count', 'parsed_document_sha256',
  'parse_manifest_sha256', 'weknora_manifest_algorithm', 'weknora_manifest_digest',
  'weknora_chunk_count', 'source_receipt_sha256',
] as const
const CITATION_CONTENT_AUTHORITY_KEYS = [
  'contract', 'token_key_id', 'release_id', 'activation_epoch', 'candidate_sha256',
  'field_id', 'citation_id', 'revision_source', 'citation_sha256', 'binding_sha256',
  'page_number', 'bbox', 'quote_sha256', 'content_snapshot_sha256',
  'coordinate_space_version', 'page_width', 'page_height', 'rotation_degrees',
  'retention_state', 'expires_at_unix', 'authority_sha256', 'opaque_token',
] as const
const OPAQUE_TOKEN = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/

export function parseLiveRevisionSourceReceiptV1(value: unknown): LiveRevisionSourceReceiptV1 {
  if (!isRecord(value) || !hasExactKeys(value, REVISION_SOURCE_KEYS)) {
    throw new Error('CITATION_PREVIEW_AUTHORITY_INVALID')
  }
  const text = [
    value.space_id,
    value.raw_kb_id,
    value.wiki_kb_id,
    value.knowledge_id,
    value.evidence_parse_attempt_id,
    value.resource_id,
  ]
  const hashes = [
    value.revision_source_id,
    value.file_sha256,
    value.parsed_document_sha256,
    value.parse_manifest_sha256,
    value.weknora_manifest_digest,
    value.source_receipt_sha256,
  ]
  if (
    value.contract !== 'live-revision-source-receipt.v1'
    || value.mime_type !== 'application/pdf'
    || value.weknora_manifest_algorithm !== 'weknora.chunk_manifest.v1'
    || text.some(item => !isCanonicalText(item))
    || hashes.some(item => !isHash(item))
    || !isPositiveInteger(value.tenant_id)
    || !isPositiveInteger(value.weknora_parse_attempt)
    || !isPositiveInteger(value.size)
    || !isPositiveInteger(value.page_count)
    || !isPositiveInteger(value.weknora_chunk_count)
  ) {
    throw new Error('CITATION_PREVIEW_AUTHORITY_INVALID')
  }
  return Object.freeze({
    contract: value.contract,
    revision_source_id: value.revision_source_id as string,
    tenant_id: value.tenant_id,
    space_id: value.space_id as string,
    raw_kb_id: value.raw_kb_id as string,
    wiki_kb_id: value.wiki_kb_id as string,
    knowledge_id: value.knowledge_id as string,
    evidence_parse_attempt_id: value.evidence_parse_attempt_id as string,
    weknora_parse_attempt: value.weknora_parse_attempt,
    resource_id: value.resource_id as string,
    file_sha256: value.file_sha256 as string,
    size: value.size,
    mime_type: value.mime_type,
    page_count: value.page_count,
    parsed_document_sha256: value.parsed_document_sha256 as string,
    parse_manifest_sha256: value.parse_manifest_sha256 as string,
    weknora_manifest_algorithm: value.weknora_manifest_algorithm,
    weknora_manifest_digest: value.weknora_manifest_digest as string,
    weknora_chunk_count: value.weknora_chunk_count,
    source_receipt_sha256: value.source_receipt_sha256 as string,
  })
}

function validatePreviewRequest(value: unknown): SchemaWikiCitationPreviewRequestV1 {
  if (!isRecord(value) || !hasExactKeys(value, PREVIEW_REQUEST_KEYS)) {
    throw new Error('CITATION_PREVIEW_REQUEST_INVALID')
  }
  if (
    !isCanonicalText(value.release_id)
    || !isPositiveInteger(value.activation_epoch)
    || !isCanonicalText(value.field_id)
    || !isCanonicalText(value.citation_id)
  ) {
    throw new Error('CITATION_PREVIEW_REQUEST_INVALID')
  }
  return Object.freeze({
    release_id: value.release_id,
    activation_epoch: value.activation_epoch,
    field_id: value.field_id,
    citation_id: value.citation_id,
  })
}

export function parseSchemaWikiCitationContentAuthorityV1(
  value: unknown,
  expected: SchemaWikiCitationPreviewRequestV1,
): SchemaWikiCitationContentAuthorityV1 {
  const request = validatePreviewRequest(expected)
  if (!isRecord(value) || !hasExactKeys(value, CITATION_CONTENT_AUTHORITY_KEYS)) {
    throw new Error('CITATION_PREVIEW_AUTHORITY_INVALID')
  }
  if (
    value.release_id !== request.release_id
    || value.activation_epoch !== request.activation_epoch
    || value.field_id !== request.field_id
    || value.citation_id !== request.citation_id
  ) {
    throw new Error('CITATION_REPLAY_IDENTITY_MISMATCH')
  }
  const revisionSource = parseLiveRevisionSourceReceiptV1(value.revision_source)
  if (!isPositiveInteger(value.page_number) || value.page_number > revisionSource.page_count) {
    throw new Error('PAGE_UNAVAILABLE')
  }
  let bbox: CitationBBoxV1
  try {
    bbox = parseCitationBBoxV1(value.bbox)
  } catch {
    throw new Error('BBOX_UNAVAILABLE')
  }
  if (
    value.coordinate_space_version !== 'normalized_0_1e6'
    || value.page_width !== 1_000_000
    || value.page_height !== 1_000_000
    || bbox.coordinate_system !== value.coordinate_space_version
    || bbox.page_width !== value.page_width
    || bbox.page_height !== value.page_height
    || ![0, 90, 180, 270].includes(value.rotation_degrees as number)
  ) {
    throw new Error('BBOX_UNAVAILABLE')
  }
  const text = [value.token_key_id, value.release_id, value.field_id, value.citation_id]
  const hashes = [
    value.candidate_sha256,
    value.citation_sha256,
    value.binding_sha256,
    value.quote_sha256,
    value.content_snapshot_sha256,
    value.authority_sha256,
  ]
  if (
    value.contract !== 'schema-wiki-citation-content-authority.v1'
    || value.retention_state !== 'pinned'
    || !isPositiveInteger(value.expires_at_unix)
    || text.some(item => !isCanonicalText(item))
    || hashes.some(item => !isHash(item))
    || typeof value.opaque_token !== 'string'
    || !OPAQUE_TOKEN.test(value.opaque_token)
  ) {
    throw new Error('CITATION_PREVIEW_AUTHORITY_INVALID')
  }
  return Object.freeze({
    contract: value.contract,
    token_key_id: value.token_key_id as string,
    release_id: value.release_id as string,
    activation_epoch: value.activation_epoch as number,
    candidate_sha256: value.candidate_sha256 as string,
    field_id: value.field_id as string,
    citation_id: value.citation_id as string,
    revision_source: revisionSource,
    citation_sha256: value.citation_sha256 as string,
    binding_sha256: value.binding_sha256 as string,
    page_number: value.page_number,
    bbox,
    quote_sha256: value.quote_sha256 as string,
    content_snapshot_sha256: value.content_snapshot_sha256 as string,
    coordinate_space_version: value.coordinate_space_version,
    page_width: value.page_width,
    page_height: value.page_height,
    rotation_degrees: value.rotation_degrees as 0 | 90 | 180 | 270,
    retention_state: value.retention_state,
    expires_at_unix: value.expires_at_unix,
    authority_sha256: value.authority_sha256 as string,
    opaque_token: value.opaque_token,
  })
}

export function citationPreviewHighlightStyle(
  authority: Pick<
    SchemaWikiCitationContentAuthorityV1,
    'bbox' | 'page_width' | 'page_height' | 'rotation_degrees'
  >,
  viewport: { width: number; height: number },
): { left: number; top: number; width: number; height: number } {
  if (
    !Number.isFinite(viewport.width) || viewport.width <= 0
    || !Number.isFinite(viewport.height) || viewport.height <= 0
  ) {
    throw new Error('BBOX_UNAVAILABLE')
  }
  const { x0, y0, x1, y1 } = authority.bbox
  const sourceWidth = authority.page_width
  const sourceHeight = authority.page_height
  const rotated = authority.rotation_degrees === 90
    ? { x0: sourceHeight - y1, y0: x0, x1: sourceHeight - y0, y1: x1, width: sourceHeight, height: sourceWidth }
    : authority.rotation_degrees === 180
      ? { x0: sourceWidth - x1, y0: sourceHeight - y1, x1: sourceWidth - x0, y1: sourceHeight - y0, width: sourceWidth, height: sourceHeight }
      : authority.rotation_degrees === 270
        ? { x0: y0, y0: sourceWidth - x1, x1: y1, y1: sourceWidth - x0, width: sourceHeight, height: sourceWidth }
        : { x0, y0, x1, y1, width: sourceWidth, height: sourceHeight }
  const scaleX = viewport.width / rotated.width
  const scaleY = viewport.height / rotated.height
  return {
    left: rotated.x0 * scaleX,
    top: rotated.y0 * scaleY,
    width: (rotated.x1 - rotated.x0) * scaleX,
    height: (rotated.y1 - rotated.y0) * scaleY,
  }
}

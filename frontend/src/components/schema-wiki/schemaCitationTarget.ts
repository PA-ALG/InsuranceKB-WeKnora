export type CitationCoordinateSpace = 'normalized_0_1000'

export interface CitationBBoxV1 {
  x0: number
  y0: number
  x1: number
  y1: number
  coordinate_space: CitationCoordinateSpace
}

export interface CitationTargetV1 {
  version: 'citation-target.v1'
  citation_id: string
  citation_sha256: string
  logical_member_ref: string
  knowledge_id: string
  source_revision_id: string
  parse_attempt: number
  document_sha256: string
  manifest_sha256: string
  chunk_id: string
  page_number: number
  locator_kind: string
  locator_id: string
  bbox: CitationBBoxV1
  quote_sha256: string
  content_sha256: string
}

export interface CitationPinV1 {
  release_id: string
  field_id: string
  logical_member_ref: string
  member_digest: string
  citation_binding: {
    citation_sha256: string
    member_digest: string
  }
  source_revision_id: string
  parse_attempt: number
  document_sha256: string
  manifest_sha256: string
}

const TARGET_KEYS = [
  'version',
  'citation_id',
  'citation_sha256',
  'logical_member_ref',
  'knowledge_id',
  'source_revision_id',
  'parse_attempt',
  'document_sha256',
  'manifest_sha256',
  'chunk_id',
  'page_number',
  'locator_kind',
  'locator_id',
  'bbox',
  'quote_sha256',
  'content_sha256',
] as const

const BBOX_KEYS = ['x0', 'y0', 'x1', 'y1', 'coordinate_space'] as const
const HEX_64 = /^[0-9a-f]{64}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim() === value && value.length > 0
}

function isHash(value: unknown): value is string {
  return typeof value === 'string' && HEX_64.test(value)
}

function parseBBox(value: unknown): CitationBBoxV1 {
  if (!isRecord(value) || !hasExactKeys(value, BBOX_KEYS)) {
    throw new Error('BBOX_UNAVAILABLE')
  }
  const { x0, y0, x1, y1, coordinate_space: coordinateSpace } = value
  if (
    typeof x0 !== 'number' || !Number.isFinite(x0)
    || typeof y0 !== 'number' || !Number.isFinite(y0)
    || typeof x1 !== 'number' || !Number.isFinite(x1)
    || typeof y1 !== 'number' || !Number.isFinite(y1)
    || coordinateSpace !== 'normalized_0_1000'
    || x0 < 0 || y0 < 0 || x1 > 1000 || y1 > 1000
    || x0 >= x1 || y0 >= y1
    || (x0 === 0 && y0 === 0 && x1 === 1000 && y1 === 1000)
  ) {
    throw new Error('BBOX_UNAVAILABLE')
  }
  return Object.freeze({ x0, y0, x1, y1, coordinate_space: coordinateSpace })
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
  if (!Number.isInteger(value.page_number) || (value.page_number as number) <= 0) {
    throw new Error('PAGE_UNAVAILABLE')
  }
  if (
    !isNonEmptyString(value.source_revision_id)
    || value.source_revision_id === 'current'
    || value.source_revision_id === 'latest'
  ) {
    throw new Error('CITATION_REVISION_NOT_PINNED')
  }
  if (
    value.version !== 'citation-target.v1'
    || !isNonEmptyString(value.citation_id)
    || !isHash(value.citation_sha256)
    || !isNonEmptyString(value.logical_member_ref)
    || !isNonEmptyString(value.knowledge_id)
    || !Number.isInteger(value.parse_attempt) || (value.parse_attempt as number) <= 0
    || !isHash(value.document_sha256)
    || !isHash(value.manifest_sha256)
    || !isNonEmptyString(value.chunk_id)
    || !isNonEmptyString(value.locator_kind)
    || !isNonEmptyString(value.locator_id)
    || !isHash(value.quote_sha256)
    || !isHash(value.content_sha256)
  ) {
    throw new Error('CITATION_TARGET_INCOMPLETE')
  }
  const bbox = parseBBox(value.bbox)
  return Object.freeze({
    version: value.version,
    citation_id: value.citation_id,
    citation_sha256: value.citation_sha256,
    logical_member_ref: value.logical_member_ref,
    knowledge_id: value.knowledge_id,
    source_revision_id: value.source_revision_id,
    parse_attempt: value.parse_attempt as number,
    document_sha256: value.document_sha256,
    manifest_sha256: value.manifest_sha256,
    chunk_id: value.chunk_id,
    page_number: value.page_number as number,
    locator_kind: value.locator_kind,
    locator_id: value.locator_id,
    bbox,
    quote_sha256: value.quote_sha256,
    content_sha256: value.content_sha256,
  })
}

export function assertPinnedCitation(target: CitationTargetV1, pin: CitationPinV1): void {
  if (
    target.logical_member_ref !== pin.logical_member_ref
    || target.citation_sha256 !== pin.citation_binding.citation_sha256
    || pin.member_digest !== pin.citation_binding.member_digest
  ) {
    throw new Error('CITATION_MEMBER_BINDING_MISMATCH')
  }
  if (
    target.source_revision_id !== pin.source_revision_id
    || target.parse_attempt !== pin.parse_attempt
    || target.document_sha256 !== pin.document_sha256
    || target.manifest_sha256 !== pin.manifest_sha256
  ) {
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
  const scaleX = viewport.width / 1000
  const scaleY = viewport.height / 1000
  return {
    left: target.bbox.x0 * scaleX,
    top: target.bbox.y0 * scaleY,
    width: (target.bbox.x1 - target.bbox.x0) * scaleX,
    height: (target.bbox.y1 - target.bbox.y0) * scaleY,
  }
}

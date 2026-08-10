import {
  assertPinnedCitation,
  parseCitationTarget,
  type CitationPinV1,
  type CitationTargetV1,
} from '../../../components/schema-wiki/schemaCitationTarget.ts'

const HEX_64 = /^[0-9a-f]{64}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function isId(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value.trim() === value
}

function isHash(value: unknown): value is string {
  return typeof value === 'string' && HEX_64.test(value)
}

export interface SchemaWikiScopeV1 {
  readonly version: 'schema-wiki-scope.v1'
  readonly space_id: string
  readonly raw_kb_id: string
  readonly wiki_kb_id: string
  readonly scope_sha256: string
}

export function parseSchemaWikiScope(value: unknown): SchemaWikiScopeV1 {
  const keys = ['version', 'space_id', 'raw_kb_id', 'wiki_kb_id', 'scope_sha256']
  if (
    !isRecord(value) || !hasExactKeys(value, keys)
    || value.version !== 'schema-wiki-scope.v1'
    || !isId(value.space_id) || !isId(value.raw_kb_id) || !isId(value.wiki_kb_id)
    || !isHash(value.scope_sha256)
  ) {
    throw new Error('SCHEMA_WIKI_SCOPE_INVALID')
  }
  return Object.freeze({
    version: value.version,
    space_id: value.space_id,
    raw_kb_id: value.raw_kb_id,
    wiki_kb_id: value.wiki_kb_id,
    scope_sha256: value.scope_sha256,
  })
}

export interface SchemaPackV1 {
  readonly version: 'schema-pack.v1'
  readonly domain_id: string
  readonly schema_pack_id: string
  readonly schema_pack_sha256: string
  readonly fields: ReadonlyArray<{ readonly field_id: string; readonly ordinal: number }>
  readonly sections: ReadonlyArray<{
    readonly section_id: string
    readonly ordinal: number
    readonly field_ids: ReadonlyArray<string>
  }>
}

export function parseSchemaPack(value: unknown): SchemaPackV1 {
  const keys = ['version', 'domain_id', 'schema_pack_id', 'schema_pack_sha256', 'fields', 'sections']
  if (
    !isRecord(value) || !hasExactKeys(value, keys)
    || value.version !== 'schema-pack.v1'
    || !isId(value.domain_id) || !isId(value.schema_pack_id) || !isHash(value.schema_pack_sha256)
    || !Array.isArray(value.fields) || !Array.isArray(value.sections)
  ) {
    throw new Error('SCHEMA_PACK_INVALID')
  }
  const fields = value.fields.map((field, index) => {
    if (
      !isRecord(field) || !hasExactKeys(field, ['field_id', 'ordinal'])
      || !isId(field.field_id) || field.ordinal !== index
    ) {
      throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
    }
    return Object.freeze({ field_id: field.field_id, ordinal: index })
  })
  const expectedFieldIds = fields.map(field => field.field_id)
  if (new Set(expectedFieldIds).size !== expectedFieldIds.length) {
    throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
  }
  const sections = value.sections.map((section, index) => {
    if (
      !isRecord(section) || !hasExactKeys(section, ['section_id', 'ordinal', 'field_ids'])
      || !isId(section.section_id) || section.ordinal !== index || !Array.isArray(section.field_ids)
      || section.field_ids.some(fieldId => !isId(fieldId))
    ) {
      throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
    }
    return Object.freeze({
      section_id: section.section_id,
      ordinal: index,
      field_ids: Object.freeze([...(section.field_ids as string[])]),
    })
  })
  const sectionFieldIds = sections.flatMap(section => section.field_ids)
  if (
    new Set(sections.map(section => section.section_id)).size !== sections.length
    || new Set(sectionFieldIds).size !== sectionFieldIds.length
    || sectionFieldIds.length !== expectedFieldIds.length
    || sectionFieldIds.some((fieldId, index) => fieldId !== expectedFieldIds[index])
  ) {
    throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
  }
  return Object.freeze({
    version: value.version,
    domain_id: value.domain_id,
    schema_pack_id: value.schema_pack_id,
    schema_pack_sha256: value.schema_pack_sha256,
    fields: Object.freeze(fields),
    sections: Object.freeze(sections),
  })
}

export type SchemaFieldState = 'present' | 'absent_explicitly' | 'unknown'

export interface SchemaFieldMemberV1 {
  readonly version: 'schema-field-member.v1'
  readonly release_id: string
  readonly member_digest: string
  readonly logical_slug: string
  readonly section_id: string
  readonly field_id: string
  readonly state: SchemaFieldState
  readonly value: unknown
  readonly citations: ReadonlyArray<CitationTargetV1>
  readonly citation_bindings: ReadonlyArray<{ citation_sha256: string; member_digest: string }>
  readonly review_items: ReadonlyArray<Record<string, unknown>>
}

export function parseSchemaFieldMember(
  value: unknown,
  expected: { releaseId: string; memberDigest: string },
): SchemaFieldMemberV1 {
  const keys = [
    'version', 'release_id', 'member_digest', 'logical_slug', 'section_id', 'field_id',
    'state', 'value', 'citations', 'citation_bindings', 'review_items',
  ]
  if (!isRecord(value) || !hasExactKeys(value, keys) || value.version !== 'schema-field-member.v1') {
    throw new Error('SCHEMA_FIELD_MEMBER_INVALID')
  }
  if (value.release_id !== expected.releaseId) {
    throw new Error('SCHEMA_FIELD_RELEASE_PIN_MISMATCH')
  }
  if (value.member_digest !== expected.memberDigest) {
    throw new Error('SCHEMA_FIELD_MEMBER_PIN_MISMATCH')
  }
  if (
    !isId(value.logical_slug) || !isId(value.section_id) || !isId(value.field_id)
    || !isHash(value.member_digest)
    || !Array.isArray(value.citations) || !Array.isArray(value.citation_bindings)
    || !Array.isArray(value.review_items)
    || !['present', 'absent_explicitly', 'unknown'].includes(value.state as string)
  ) {
    throw new Error('SCHEMA_FIELD_MEMBER_INVALID')
  }
  if (value.state === 'unknown' && (value.value !== null || value.citations.length > 0 || value.citation_bindings.length > 0)) {
    throw new Error('UNKNOWN_FIELD_HAS_AUTHORITY')
  }
  if (value.state === 'unknown' && value.review_items.length === 0) {
    throw new Error('SCHEMA_FIELD_MEMBER_INVALID')
  }
  if (value.state === 'absent_explicitly' && (
    typeof value.value !== 'string' || value.value.length === 0
    || value.citations.length === 0 || value.citation_bindings.length === 0
  )) {
    throw new Error('EXPLICIT_ABSENCE_EVIDENCE_REQUIRED')
  }
  if (value.state === 'present' && (
    value.value === null || value.value === undefined
    || value.citations.length === 0 || value.citation_bindings.length === 0
  )) {
    throw new Error('SCHEMA_FIELD_MEMBER_INVALID')
  }
  const citations = value.citations.map(parseCitationTarget)
  const bindings = value.citation_bindings.map(binding => {
    if (
      !isRecord(binding) || !hasExactKeys(binding, ['citation_sha256', 'member_digest'])
      || !isHash(binding.citation_sha256) || !isHash(binding.member_digest)
    ) {
      throw new Error('SCHEMA_FIELD_MEMBER_INVALID')
    }
    return Object.freeze({ citation_sha256: binding.citation_sha256, member_digest: binding.member_digest })
  })
  if (citations.length !== bindings.length) {
    throw new Error('SCHEMA_FIELD_MEMBER_INVALID')
  }
  citations.forEach((citation, index) => {
    const binding = bindings[index]
    const pin: CitationPinV1 = {
      release_id: value.release_id as string,
      field_id: value.field_id as string,
      logical_member_ref: value.logical_slug as string,
      member_digest: value.member_digest as string,
      citation_binding: binding,
      source_revision_id: citation.source_revision_id,
      parse_attempt: citation.parse_attempt,
      document_sha256: citation.document_sha256,
      manifest_sha256: citation.manifest_sha256,
    }
    assertPinnedCitation(citation, pin)
  })
  return Object.freeze({
    version: value.version,
    release_id: value.release_id as string,
    member_digest: value.member_digest as string,
    logical_slug: value.logical_slug,
    section_id: value.section_id,
    field_id: value.field_id,
    state: value.state as SchemaFieldState,
    value: value.value,
    citations: Object.freeze(citations),
    citation_bindings: Object.freeze(bindings),
    review_items: Object.freeze(value.review_items.map(item => {
      if (!isRecord(item)) throw new Error('SCHEMA_FIELD_MEMBER_INVALID')
      return Object.freeze({ ...item })
    })),
  })
}

export function assertSchemaReadSurface(
  value: { surface: string; preparation_id?: string },
  expected: 'current' | 'search' | 'preparation',
): void {
  if (value.surface === 'preparation' && expected === 'current') {
    throw new Error('SCHEMA_DRAFT_NOT_ACTIVE')
  }
  if (value.surface === 'preparation' && expected === 'search') {
    throw new Error('SCHEMA_DRAFT_NOT_SEARCHABLE')
  }
  if (value.surface !== expected) {
    throw new Error('SCHEMA_READ_SURFACE_MISMATCH')
  }
}

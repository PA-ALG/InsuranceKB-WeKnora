export type EntityPageKind830G1 = 'overview' | 'section' | 'field' | 'free_wiki'
export type EntityFieldState830G1 = 'present' | 'absent_explicitly' | 'unknown'

export interface EntityPageTarget830G1 {
  readonly entityId: string
  readonly pageKind: EntityPageKind830G1
  readonly stableKey: string
}

export interface EntityPageProfileField830G1 {
  readonly field_key: string
  readonly short_title: string
}

export interface EntityPageProfileSection830G1 {
  readonly section_key: string
  readonly display_name: string
  readonly fields: ReadonlyArray<EntityPageProfileField830G1>
}

export interface EntityPageProfile830G1 {
  readonly contract: 'presentation-profile.v1'
  readonly profile_id: string
  readonly profile_version: string
  readonly schema_pack_id: string
  readonly schema_version: string
  readonly schema_pack_sha256: string
  readonly sections: ReadonlyArray<EntityPageProfileSection830G1>
  readonly profile_sha256: string
}

export interface EntityPageCitation830G1 {
  readonly citation_id: string
  readonly join_receipt_sha256: string
  readonly page_number: number
  readonly bbox: EntityPageCitationBBox830G1
  readonly quote_snapshot: string
  readonly citation_sha256: string
  readonly [key: string]: unknown
}

export interface EntityPageCitationBBox830G1 {
  readonly coordinate_system: 'normalized_0_1e6'
  readonly page_width: 1_000_000
  readonly page_height: 1_000_000
  readonly x0: number
  readonly y0: number
  readonly x1: number
  readonly y1: number
}

export interface EntityPageFieldPayload830G1 {
  readonly contract: 'field-assertion-page.830.g1.v1'
  readonly field_key: string
  readonly reference: Record<string, unknown>
  readonly state: EntityFieldState830G1
  readonly value_snapshot: string | null
  readonly display_value: string | null
  readonly unknown_reason: string | null
  readonly source_typed_reason: string | null
  readonly citations: ReadonlyArray<EntityPageCitation830G1>
}

export interface EntityPageOverviewPayload830G1 {
  readonly contract: 'entity-overview-page.830.g1.v1'
  readonly entity_id: string
  readonly entity_version_id: string
  readonly ordered_section_page_ids: ReadonlyArray<string>
  readonly field_assertions: ReadonlyArray<Record<string, unknown>>
}

export interface EntityPageSectionPayload830G1 {
  readonly contract: 'entity-section-page.830.g1.v1'
  readonly section_key: string
  readonly field_assertions: ReadonlyArray<Record<string, unknown>>
}

export interface EntityPageFreeWikiPayload830G1 {
  readonly contract: 'empty-free-wiki-page.830.g1.v1'
  readonly items: readonly []
}

export type EntityPagePayload830G1 = EntityPageOverviewPayload830G1
  | EntityPageSectionPayload830G1
  | EntityPageFieldPayload830G1
  | EntityPageFreeWikiPayload830G1

export interface EntityPageMember830G1 {
  readonly contract: 'entity-page-member.830.g1.v1'
  readonly page_id: string
  readonly namespace: string
  readonly route: string
  readonly page_kind: EntityPageKind830G1
  readonly stable_key: string
  readonly short_title: string
  readonly space_id: string
  readonly wiki_kb_id: string
  readonly entity_id: string
  readonly release_id: string
  readonly candidate_sha256: string
  readonly claim_set_sha256: string
  readonly evidence_authority_sha256: string
  readonly schema_pack_sha256: string
  readonly profile_sha256: string
  readonly payload: EntityPagePayload830G1
  readonly payload_sha256: string
  readonly member_digest: string
}

export interface EntityPageGraphRead830G1 {
  readonly contract: 'entity-page-read.830.g1.v1'
  readonly read_mode: 'current' | 'pinned' | 'preparation'
  readonly release_id: string
  readonly preparation_id?: string
  readonly activation_epoch: number
  readonly manifest_sha256: string
  readonly entity_id: string
  readonly entity_version_id: string
  readonly display_name: string
  readonly classification_display_name: string
  readonly profile: EntityPageProfile830G1
  readonly member: EntityPageMember830G1
}

const HEX64 = /^[0-9a-f]{64}$/
const SEGMENT = /^[A-Za-z0-9._:@-]+$/
const CONTROL = /[\u0000-\u001f\u007f]/

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function exact(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
}

function text(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && value === value.trim()
    && value.normalize('NFC') === value && !CONTROL.test(value)
}

function hash(value: unknown): value is string {
  return typeof value === 'string' && HEX64.test(value)
}

function hashList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every(hash) && new Set(value).size === value.length
}

function parseProfile(value: unknown): EntityPageProfile830G1 {
  if (!record(value) || !exact(value, [
    'contract', 'profile_id', 'profile_version', 'schema_pack_id', 'schema_version',
    'schema_pack_sha256', 'sections', 'profile_sha256',
  ]) || value.contract !== 'presentation-profile.v1' || !text(value.profile_id)
    || !text(value.profile_version) || !text(value.schema_pack_id) || !text(value.schema_version)
    || !hash(value.schema_pack_sha256) || !hash(value.profile_sha256) || !Array.isArray(value.sections)
    || value.sections.length === 0) throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  const sectionKeys = new Set<string>()
  const fieldKeys = new Set<string>()
  const sections = value.sections.map(section => {
    if (!record(section) || !exact(section, ['section_key', 'display_name', 'fields'])
      || !text(section.section_key) || !text(section.display_name)
      || !Array.isArray(section.fields) || section.fields.length === 0
      || sectionKeys.has(section.section_key)) throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
    sectionKeys.add(section.section_key)
    const fields = section.fields.map(field => {
      if (!record(field) || !exact(field, ['field_key', 'short_title'])
        || !text(field.field_key) || !text(field.short_title) || fieldKeys.has(field.field_key)) {
        throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
      }
      fieldKeys.add(field.field_key)
      return Object.freeze({ field_key: field.field_key, short_title: field.short_title })
    })
    return Object.freeze({
      section_key: section.section_key,
      display_name: section.display_name,
      fields: Object.freeze(fields),
    })
  })
  return Object.freeze({ ...value, sections: Object.freeze(sections) }) as unknown as EntityPageProfile830G1
}

const REFERENCE_KEYS = [
  'field_key', 'page_id', 'source_release_id', 'source_candidate_sha256',
  'product_version_id', 'claim_sha256', 'evidence_receipt_sha256s', 'citation_sha256s',
] as const

function validReference(value: unknown, fieldKey?: string): value is Record<string, unknown> {
  return record(value) && exact(value, REFERENCE_KEYS) && text(value.field_key)
    && (!fieldKey || value.field_key === fieldKey) && text(value.page_id)
    && text(value.source_release_id) && hash(value.source_candidate_sha256)
    && text(value.product_version_id) && hash(value.claim_sha256)
    && hashList(value.evidence_receipt_sha256s) && hashList(value.citation_sha256s)
}

function validReferences(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.every(item => validReference(item))
}

const CITATION_KEYS = [
  'contract', 'citation_id', 'join_receipt_sha256', 'evidence_receipt_sha256', 'source_role',
  'source_sha256', 'source_revision_id', 'knowledge_id', 'chunk_id', 'parse_attempt_id',
  'parsed_document_sha256', 'parse_manifest_sha256', 'page_number', 'locator_kind', 'locator_ref',
  'locator_content_sha256', 'bbox', 'quote_snapshot', 'quote_sha256', 'citation_sha256',
] as const

const CITATION_BBOX_KEYS = [
  'coordinate_system', 'page_width', 'page_height', 'x0', 'y0', 'x1', 'y1',
] as const

function integer(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value)
}

function validCitationBBox(value: unknown): value is EntityPageCitationBBox830G1 {
  if (!record(value) || !exact(value, CITATION_BBOX_KEYS)
    || value.coordinate_system !== 'normalized_0_1e6'
    || value.page_width !== 1_000_000 || value.page_height !== 1_000_000
    || !integer(value.x0) || !integer(value.y0) || !integer(value.x1) || !integer(value.y1)) {
    return false
  }
  return value.x0 >= 0 && value.y0 >= 0
    && value.x0 < value.x1 && value.y0 < value.y1
    && value.x1 <= value.page_width && value.y1 <= value.page_height
}

function validCitation(value: unknown): value is EntityPageCitation830G1 {
  if (!record(value) || !exact(value, CITATION_KEYS)
    || value.contract !== 'entity-page-exact-citation.830.g1.v1'
    || !text(value.citation_id) || !text(value.source_role) || !text(value.source_revision_id)
    || !text(value.knowledge_id) || !text(value.chunk_id) || !text(value.parse_attempt_id)
    || !text(value.locator_kind) || !text(value.locator_ref) || !text(value.quote_snapshot)
    || !integer(value.page_number) || value.page_number <= 0
    || !validCitationBBox(value.bbox)) return false
  return [
    value.join_receipt_sha256, value.evidence_receipt_sha256, value.source_sha256,
    value.parsed_document_sha256, value.parse_manifest_sha256, value.locator_content_sha256,
    value.quote_sha256, value.citation_sha256,
  ].every(hash)
}

function parsePayload(value: unknown, target: EntityPageTarget830G1): EntityPagePayload830G1 {
  if (!record(value)) throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  if (target.pageKind === 'overview') {
    if (!exact(value, ['contract', 'entity_id', 'entity_version_id', 'ordered_section_page_ids', 'field_assertions'])
      || value.contract !== 'entity-overview-page.830.g1.v1' || value.entity_id !== target.entityId
      || !text(value.entity_version_id) || !Array.isArray(value.ordered_section_page_ids)
      || !value.ordered_section_page_ids.every(text) || !validReferences(value.field_assertions)) {
      throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
    }
  } else if (target.pageKind === 'section') {
    if (!exact(value, ['contract', 'section_key', 'field_assertions'])
      || value.contract !== 'entity-section-page.830.g1.v1' || value.section_key !== target.stableKey
      || !validReferences(value.field_assertions)) throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  } else if (target.pageKind === 'free_wiki') {
    if (!exact(value, ['contract', 'items']) || value.contract !== 'empty-free-wiki-page.830.g1.v1'
      || !Array.isArray(value.items) || value.items.length !== 0) throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  } else {
    if (!exact(value, [
      'contract', 'field_key', 'reference', 'state', 'value_snapshot', 'display_value',
      'unknown_reason', 'source_typed_reason', 'citations',
    ]) || value.contract !== 'field-assertion-page.830.g1.v1' || value.field_key !== target.stableKey
      || !validReference(value.reference, target.stableKey) || !Array.isArray(value.citations)
      || !value.citations.every(validCitation)) throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
    if (value.state === 'unknown') {
      if (value.value_snapshot !== null || value.display_value !== null || !text(value.unknown_reason)
        || !text(value.source_typed_reason) || value.citations.length !== 0) {
        throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
      }
    } else if ((value.state !== 'present' && value.state !== 'absent_explicitly')
      || !text(value.value_snapshot) || value.value_snapshot !== value.display_value
      || value.unknown_reason !== null || value.source_typed_reason !== null || value.citations.length === 0) {
      throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
    }
  }
  return Object.freeze(value) as unknown as EntityPagePayload830G1
}

function expectedTitle(profile: EntityPageProfile830G1, target: EntityPageTarget830G1, displayName: string): string | null {
  if (target.pageKind === 'overview') return displayName
  if (target.pageKind === 'free_wiki') return '自由知识'
  const section = profile.sections.find(item => item.section_key === target.stableKey)
  if (target.pageKind === 'section') return section?.display_name ?? null
  for (const item of profile.sections) {
    const field = item.fields.find(entry => entry.field_key === target.stableKey)
    if (field) return field.short_title
  }
  return null
}

function expectedMemberRoute(wikiKBID: string, target: EntityPageTarget830G1): string {
  const base = `/platform/knowledge-bases/${wikiKBID}/schema-wiki/entities/${target.entityId}`
  if (target.pageKind === 'overview') return `${base}/overview`
  if (target.pageKind === 'section') return `${base}/sections/${target.stableKey}`
  if (target.pageKind === 'field') return `${base}/fields/${target.stableKey}`
  return `${base}/free-wiki`
}

function sameStrings(left: unknown, right: readonly string[]): boolean {
  return Array.isArray(left) && left.length === right.length
    && left.every((item, index) => item === right[index])
}

export function parseEntityPageGraphRead830G1(
  value: unknown,
  target: EntityPageTarget830G1,
): EntityPageGraphRead830G1 {
  try {
    if (!record(value) || !exact(value, ['success', 'data']) || value.success !== true || !record(value.data)) {
      throw new Error()
    }
    const data = value.data
    const readKeys = [
      'contract', 'read_mode', 'release_id', 'activation_epoch', 'manifest_sha256', 'entity_id',
      'entity_version_id', 'display_name', 'classification_display_name', 'profile', 'member',
    ]
    if (data.read_mode === 'preparation') readKeys.push('preparation_id')
    if (!exact(data, readKeys) || data.contract !== 'entity-page-read.830.g1.v1'
      || (data.read_mode !== 'current' && data.read_mode !== 'pinned' && data.read_mode !== 'preparation')
      || (data.read_mode === 'preparation'
        ? !text(data.preparation_id) || ['current', 'latest'].includes(data.preparation_id.toLowerCase())
        : 'preparation_id' in data)
      || !text(data.release_id)
      || ['current', 'latest'].includes(data.release_id.toLowerCase())
      || !Number.isSafeInteger(data.activation_epoch) || (data.activation_epoch as number) <= 0
      || !hash(data.manifest_sha256) || data.entity_id !== target.entityId || !text(data.entity_version_id)
      || !text(data.display_name) || !text(data.classification_display_name) || !record(data.member)) throw new Error()
    const profile = parseProfile(data.profile)
    const member = data.member
    if (!exact(member, [
      'contract', 'page_id', 'namespace', 'route', 'page_kind', 'stable_key', 'short_title',
      'space_id', 'wiki_kb_id', 'entity_id', 'release_id', 'candidate_sha256', 'claim_set_sha256',
      'evidence_authority_sha256', 'schema_pack_sha256', 'profile_sha256', 'payload',
      'payload_sha256', 'member_digest',
    ]) || member.contract !== 'entity-page-member.830.g1.v1' || member.page_kind !== target.pageKind
      || member.stable_key !== target.stableKey || member.entity_id !== target.entityId
      || !text(member.release_id)
      || (data.read_mode === 'preparation'
        ? member.release_id !== data.release_id
        : member.release_id === data.release_id)
      || member.profile_sha256 !== profile.profile_sha256
      || member.schema_pack_sha256 !== profile.schema_pack_sha256 || !text(member.page_id)
      || !text(member.namespace) || !text(member.route) || !text(member.short_title)
      || !text(member.space_id) || !text(member.wiki_kb_id)
      || ![member.candidate_sha256, member.claim_set_sha256, member.evidence_authority_sha256,
        member.payload_sha256, member.member_digest].every(hash)
      || expectedTitle(profile, target, data.display_name) !== member.short_title) throw new Error()
    const payload = parsePayload(member.payload, target)
    const namespaceKind = target.pageKind === 'free_wiki' ? 'free-wiki' : target.pageKind
    if (member.namespace !== `urn:jlx:wiki:${member.space_id}:entity:${target.entityId}:${namespaceKind}:${target.stableKey}`
      || member.route !== expectedMemberRoute(member.wiki_kb_id as string, target)) throw new Error()
    if (payload.contract === 'entity-overview-page.830.g1.v1'
      && (payload.entity_id !== data.entity_id || payload.entity_version_id !== data.entity_version_id)) throw new Error()
    if (payload.contract === 'field-assertion-page.830.g1.v1') {
      const reference = payload.reference
      const citationHashes = payload.citations.map(citation => citation.citation_sha256)
      const receiptHashes = [...new Set(payload.citations.map(citation => citation.evidence_receipt_sha256 as string))]
      if (reference.page_id !== member.page_id || reference.source_release_id !== member.release_id
        || reference.source_candidate_sha256 !== member.candidate_sha256
        || !sameStrings(reference.citation_sha256s, citationHashes)
        || !sameStrings(reference.evidence_receipt_sha256s, receiptHashes)) throw new Error()
    }
    return Object.freeze({
      ...data,
      profile,
      member: Object.freeze({ ...member, payload }),
    }) as unknown as EntityPageGraphRead830G1
  } catch {
    throw new Error('ENTITY_PAGE_GRAPH_RESPONSE_INVALID')
  }
}

export function assertEntityPageTarget830G1(target: EntityPageTarget830G1): void {
  if (!target || !SEGMENT.test(target.entityId) || !SEGMENT.test(target.stableKey)
    || !['overview', 'section', 'field', 'free_wiki'].includes(target.pageKind)
    || (target.pageKind === 'overview' && target.stableKey !== 'overview')
    || (target.pageKind === 'free_wiki' && target.stableKey !== 'free-wiki')) {
    throw new Error('ENTITY_PAGE_GRAPH_TARGET_INVALID')
  }
}

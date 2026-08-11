import {
  parseCitationTarget,
  type CitationTargetV1,
} from '../../../components/schema-wiki/schemaCitationTarget.ts'

const HEX_64 = /^[0-9a-f]{64}$/
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/
const validatedScopes = new WeakSet<object>()
const validatedCurrentEntityVersions = new WeakSet<object>()

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
    || !isCanonicalText(value.space_id)
    || !isCanonicalText(value.raw_kb_id)
    || !isCanonicalText(value.wiki_kb_id)
    || !isHash(value.scope_sha256)
  ) {
    throw new Error('SCHEMA_WIKI_SCOPE_INVALID')
  }
  const scope = Object.freeze({
    version: value.version,
    space_id: value.space_id,
    raw_kb_id: value.raw_kb_id,
    wiki_kb_id: value.wiki_kb_id,
    scope_sha256: value.scope_sha256,
  })
  validatedScopes.add(scope)
  return scope
}

export function assertValidatedSchemaWikiScope(value: SchemaWikiScopeV1): void {
  if (!validatedScopes.has(value)) {
    throw new Error('SCHEMA_WIKI_SCOPE_INVALID')
  }
}

export interface SchemaRootPageV1 {
  readonly contract: 'schema-root-page.v1'
  readonly domain_id: string
  readonly domain_sha256: string
  readonly schema_pack_id: string
  readonly schema_version: string
  readonly schema_pack_sha256: string
  readonly entity_id: string
  readonly entity_version_id: string
  readonly product_version_id: string
  readonly taxonomy_version: string
  readonly taxonomy_sha256: string
  readonly product_display_name: string
  readonly ordered_section_ids: ReadonlyArray<string>
  readonly root_page_sha256: string
}

export interface SchemaWikiCurrentEntityVersionV1 {
  readonly version: 'schema-wiki-current-entity-version.v1'
  readonly entity_id: string
  readonly entity_version_id: string
  readonly active_release_id: string
  readonly activation_epoch: number
  readonly root: SchemaRootPageV1
}

function parseSchemaRootPage(
  value: unknown,
  expected: { entityId: string; entityVersionId: string },
): SchemaRootPageV1 {
  const keys = [
    'contract', 'domain_id', 'domain_sha256', 'schema_pack_id', 'schema_version',
    'schema_pack_sha256', 'entity_id', 'entity_version_id', 'product_version_id',
    'taxonomy_version', 'taxonomy_sha256', 'product_display_name',
    'ordered_section_ids', 'root_page_sha256',
  ]
  if (
    !isRecord(value) || !hasExactKeys(value, keys)
    || value.contract !== 'schema-root-page.v1'
    || !isCanonicalText(value.domain_id)
    || !isHash(value.domain_sha256)
    || !isCanonicalText(value.schema_pack_id)
    || !isCanonicalText(value.schema_version)
    || !isHash(value.schema_pack_sha256)
    || !isCanonicalText(value.entity_id)
    || !isCanonicalText(value.entity_version_id)
    || !isCanonicalText(value.product_version_id)
    || !isCanonicalText(value.taxonomy_version)
    || !isHash(value.taxonomy_sha256)
    || !isCanonicalText(value.product_display_name)
    || !Array.isArray(value.ordered_section_ids)
    || !isHash(value.root_page_sha256)
    || value.entity_id !== expected.entityId
    || value.entity_version_id !== expected.entityVersionId
  ) {
    throw new Error('SCHEMA_ROOT_PAGE_INVALID')
  }
  const orderedSectionIds = value.ordered_section_ids.map(sectionId => {
    if (!isCanonicalText(sectionId)) throw new Error('SCHEMA_ROOT_PAGE_INVALID')
    return sectionId
  })
  if (
    orderedSectionIds.length === 0
    || new Set(orderedSectionIds).size !== orderedSectionIds.length
  ) {
    throw new Error('SCHEMA_ROOT_PAGE_INVALID')
  }
  return Object.freeze({
    contract: value.contract,
    domain_id: value.domain_id,
    domain_sha256: value.domain_sha256,
    schema_pack_id: value.schema_pack_id,
    schema_version: value.schema_version,
    schema_pack_sha256: value.schema_pack_sha256,
    entity_id: value.entity_id,
    entity_version_id: value.entity_version_id,
    product_version_id: value.product_version_id,
    taxonomy_version: value.taxonomy_version,
    taxonomy_sha256: value.taxonomy_sha256,
    product_display_name: value.product_display_name,
    ordered_section_ids: Object.freeze(orderedSectionIds),
    root_page_sha256: value.root_page_sha256,
  })
}

export function parseSchemaWikiCurrentEntityVersion(
  value: unknown,
  expected: { entityId: string; entityVersionId: string },
): SchemaWikiCurrentEntityVersionV1 {
  const keys = [
    'version', 'entity_id', 'entity_version_id', 'active_release_id',
    'activation_epoch', 'root',
  ]
  if (
    !isRecord(value) || !hasExactKeys(value, keys)
    || value.version !== 'schema-wiki-current-entity-version.v1'
    || !isCanonicalText(expected.entityId)
    || !isCanonicalText(expected.entityVersionId)
    || !isCanonicalText(value.entity_id)
    || !isCanonicalText(value.entity_version_id)
    || value.entity_id !== expected.entityId
    || value.entity_version_id !== expected.entityVersionId
    || !isCanonicalText(value.active_release_id)
    || ['current', 'latest'].includes(value.active_release_id.toLowerCase())
    || !Number.isSafeInteger(value.activation_epoch)
    || (value.activation_epoch as number) <= 0
  ) {
    throw new Error('SCHEMA_WIKI_CURRENT_ENTITY_VERSION_INVALID')
  }
  let root: SchemaRootPageV1
  try {
    root = parseSchemaRootPage(value.root, expected)
  } catch {
    throw new Error('SCHEMA_WIKI_CURRENT_ENTITY_VERSION_INVALID')
  }
  const current = Object.freeze({
    version: value.version,
    entity_id: value.entity_id,
    entity_version_id: value.entity_version_id,
    active_release_id: value.active_release_id,
    activation_epoch: value.activation_epoch as number,
    root,
  })
  validatedCurrentEntityVersions.add(current)
  return current
}

export function assertValidatedSchemaWikiCurrentEntityVersion(
  value: SchemaWikiCurrentEntityVersionV1,
): void {
  if (!validatedCurrentEntityVersions.has(value)) {
    throw new Error('SCHEMA_WIKI_CURRENT_ENTITY_VERSION_INVALID')
  }
}

export interface SchemaSectionV1 {
  readonly section_id: string
  readonly display_name: string
  readonly ordered_field_ids: ReadonlyArray<string>
}

export interface SchemaPackV1 {
  readonly contract: 'schema-pack.v1'
  readonly schema_pack_id: string
  readonly schema_version: string
  readonly domain_id: string
  readonly ordered_field_ids: ReadonlyArray<string>
  readonly sections: ReadonlyArray<SchemaSectionV1>
  readonly schema_pack_sha256: string
}

export function parseSchemaPack(value: unknown): SchemaPackV1 {
  const keys = [
    'contract', 'schema_pack_id', 'schema_version', 'domain_id',
    'ordered_field_ids', 'sections', 'schema_pack_sha256',
  ]
  if (
    !isRecord(value) || !hasExactKeys(value, keys)
    || value.contract !== 'schema-pack.v1'
    || !isCanonicalText(value.schema_pack_id)
    || !isCanonicalText(value.schema_version)
    || !isCanonicalText(value.domain_id)
    || !isHash(value.schema_pack_sha256)
    || !Array.isArray(value.ordered_field_ids)
    || !Array.isArray(value.sections)
  ) {
    throw new Error('SCHEMA_PACK_INVALID')
  }
  const orderedFieldIds = value.ordered_field_ids.map(fieldId => {
    if (!isCanonicalText(fieldId)) throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
    return fieldId
  })
  if (orderedFieldIds.length === 0 || new Set(orderedFieldIds).size !== orderedFieldIds.length) {
    throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
  }
  const sections = value.sections.map(section => {
    if (
      !isRecord(section)
      || !hasExactKeys(section, ['section_id', 'display_name', 'ordered_field_ids'])
      || !isCanonicalText(section.section_id)
      || !isCanonicalText(section.display_name)
      || !Array.isArray(section.ordered_field_ids)
    ) {
      throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
    }
    const fieldIds = section.ordered_field_ids.map(fieldId => {
      if (!isCanonicalText(fieldId)) throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
      return fieldId
    })
    if (fieldIds.length === 0 || new Set(fieldIds).size !== fieldIds.length) {
      throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
    }
    return Object.freeze({
      section_id: section.section_id,
      display_name: section.display_name,
      ordered_field_ids: Object.freeze(fieldIds),
    })
  })
  const flattened = sections.flatMap(section => section.ordered_field_ids)
  if (
    sections.length === 0
    || new Set(sections.map(section => section.section_id)).size !== sections.length
    || flattened.length !== orderedFieldIds.length
    || flattened.some((fieldId, index) => fieldId !== orderedFieldIds[index])
  ) {
    throw new Error('SCHEMA_PACK_TOPOLOGY_INVALID')
  }
  return Object.freeze({
    contract: value.contract,
    schema_pack_id: value.schema_pack_id,
    schema_version: value.schema_version,
    domain_id: value.domain_id,
    ordered_field_ids: Object.freeze(orderedFieldIds),
    sections: Object.freeze(sections),
    schema_pack_sha256: value.schema_pack_sha256,
  })
}

export type SchemaFieldState = 'present' | 'absent_explicitly' | 'unknown'
export type SchemaFieldUnknownReason = 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS'

export function schemaFieldUnknownReasonI18nKey(
  reason: SchemaFieldUnknownReason | null,
): 'knowledgeEditor.wikiBrowser.schemaUnknown' {
  if (reason !== 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS') {
    throw new Error('SCHEMA_FIELD_UNKNOWN_REASON_INVALID')
  }
  return 'knowledgeEditor.wikiBrowser.schemaUnknown'
}

export interface SchemaFieldPageV1 {
  readonly contract: 'schema-field-page.v1'
  readonly field_id: string
  readonly state: SchemaFieldState
  readonly value_snapshot: string | null
  readonly citations: ReadonlyArray<CitationTargetV1>
  readonly evidence_receipt_sha256s: ReadonlyArray<string>
  readonly review_item_reason: string | null
  readonly unknown_reason: SchemaFieldUnknownReason | null
  readonly field_page_sha256: string
}

export function parseSchemaFieldPage(
  value: unknown,
  expected: { fieldId: string; fieldPageSha256: string },
): SchemaFieldPageV1 {
  const keys = [
    'contract', 'field_id', 'state', 'value_snapshot', 'citations',
    'evidence_receipt_sha256s', 'review_item_reason', 'unknown_reason',
    'field_page_sha256',
  ]
  if (
    !isRecord(value) || !hasExactKeys(value, keys)
    || value.contract !== 'schema-field-page.v1'
    || !isCanonicalText(value.field_id)
    || !['present', 'absent_explicitly', 'unknown'].includes(value.state as string)
    || !Array.isArray(value.citations)
    || !Array.isArray(value.evidence_receipt_sha256s)
    || !isHash(value.field_page_sha256)
  ) {
    throw new Error('SCHEMA_FIELD_PAGE_INVALID')
  }
  if (value.field_id !== expected.fieldId || value.field_page_sha256 !== expected.fieldPageSha256) {
    throw new Error('SCHEMA_FIELD_PAGE_PIN_MISMATCH')
  }
  const citations = value.citations.map(parseCitationTarget)
  const citationHashes = citations.map(citation => citation.citation_sha256)
  const evidenceReceipts = value.evidence_receipt_sha256s.map(receipt => {
    if (!isHash(receipt)) throw new Error('SCHEMA_FIELD_PAGE_INVALID')
    return receipt
  })
  if (
    new Set(citationHashes).size !== citationHashes.length
    || new Set(evidenceReceipts).size !== evidenceReceipts.length
  ) {
    throw new Error('SCHEMA_FIELD_PAGE_INVALID')
  }
  if (value.state === 'unknown') {
    if (
      value.value_snapshot !== null || citations.length > 0 || evidenceReceipts.length > 0
      || value.review_item_reason !== 'FIELD_UNKNOWN'
      || value.unknown_reason !== 'NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS'
    ) {
      throw new Error('UNKNOWN_FIELD_HAS_AUTHORITY')
    }
  } else {
    const validKnown = isCanonicalText(value.value_snapshot)
      && citations.length > 0
      && evidenceReceipts.length > 0
      && value.review_item_reason === null
      && value.unknown_reason === null
    if (!validKnown) {
      throw new Error(
        value.state === 'absent_explicitly'
          ? 'EXPLICIT_ABSENCE_EVIDENCE_REQUIRED'
          : 'SCHEMA_FIELD_PAGE_INVALID',
      )
    }
  }
  return Object.freeze({
    contract: value.contract,
    field_id: value.field_id,
    state: value.state as SchemaFieldState,
    value_snapshot: value.value_snapshot as string | null,
    citations: Object.freeze(citations),
    evidence_receipt_sha256s: Object.freeze(evidenceReceipts),
    review_item_reason: value.review_item_reason as string | null,
    unknown_reason: value.unknown_reason as SchemaFieldUnknownReason | null,
    field_page_sha256: value.field_page_sha256,
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

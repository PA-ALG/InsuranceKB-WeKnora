import {
  buildSchemaWikiScopeBootstrapPath,
  type SchemaWikiReadTransport,
} from './index'
import { parseConceptCatalog830G2 } from './conceptDirectory830G2'
import {
  CATALOG_ID_830_G3,
  CATALOG_VERSION_830_G3,
  parseSchemaPackCatalog830G3,
  type SchemaPackCatalog830G3,
} from './schemaPackCatalog830G3'
import {
  parseSchemaWikiScope,
  type SchemaWikiScopeV1,
} from '../../views/knowledge/schema-wiki/schemaWikiContract'
import { buildScopedSchemaWikiPath } from '../../views/knowledge/schema-wiki/schemaWikiNavigation'

const PREPARATION_CONTRACT = 'batch-concept-preparation-read.830.g3.v1'
const MANIFEST_CONTRACT = 'batch-concept-page-manifest.830.g3.v1'
const OVERVIEW_CONTRACT = 'entity-directory-entry.830.g3.v1'
const PAGE_CONTRACT = 'concept-page-read.830.g2.v1'
const MEMBER_HASH_CONTRACT = 'batch-concept-member.830.g3.v1'
const MEMBERS_HASH_CONTRACT = 'batch-concept-page-members.830.g3.v1'
const HASH = /^[0-9a-f]{64}$/
const PATH_ID = /^[A-Za-z0-9._:@-]+$/
const STRUCTURED_CONTROL = /[\u0000-\u001f\u007f]/
const BODY_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/
const EDGE_SPACE = /^\p{White_Space}|\p{White_Space}$/u
const encoder = new TextEncoder()
type R = Record<string, unknown>

export interface BatchConceptEvidence830G3 {
  readonly tenant_id: number
  readonly space_id: string
  readonly raw_kb_id: string
  readonly knowledge_id: string
  readonly parse_attempt: number
  readonly revision_id: string
  readonly source_hash: string
  readonly parse_hash: string
  readonly parser_identity: string
  readonly source_type: 'DOCUMENT' | 'EXPERT_REVISION_RECORD'
  readonly block_id: string
  readonly page_number: number
  readonly offset_unit: 'UNICODE_CODE_POINT'
  readonly start: number
  readonly end: number
  readonly quote: string
  readonly quote_hash: string
}

export interface BatchConceptMember830G3 {
  readonly kind: 'concept' | 'field_assertion' | 'entity_overview' | 'free_wiki' | 'free_wiki_item'
  readonly member_id: string
  readonly owner_id: string
  readonly title: string
  readonly content: string
  readonly payload: R
}

export interface BatchConceptEntity830G3 {
  readonly entityID: string
  readonly entityVersion: string
  readonly displayName: string
  readonly issuer: string
  readonly productCode: string
  readonly primaryClassification: string
  readonly navigationPrimaryLabel?: string
  readonly navigationLabels?: readonly string[]
  readonly schemaPackID: string
  readonly schemaVersion: string
  readonly schemaPackSHA256: string
  readonly schemaPackDisplayName: string
  readonly profileID: string
  readonly profileVersion: string
  readonly profileSHA256: string
  readonly qualityStatus: 'REGISTERED_NOT_QUALITY_ADMITTED'
  readonly releaseLane: 'ISOLATED_NOT_FOR_PRODUCTION'
  readonly overview: BatchConceptMember830G3
  readonly freeWiki: BatchConceptMember830G3
  readonly sections: readonly {
    readonly sectionKey: string
    readonly displayName: string
    readonly fields: readonly {
      readonly fieldKey: string
      readonly shortTitle: string
      readonly memberID: string
    }[]
  }[]
  readonly fieldCount: number
  readonly freeItemCount: number
}

export interface BatchConceptAlignment830G3 {
  readonly entityID: string
  readonly entityVersion: string
  readonly oldFieldKey: 'social_insurance_requirement'
  readonly newFieldKey: 'social_insurance_requirements'
  readonly oldMemberID: string
  readonly newMemberID: string
  readonly oldReleaseID: string
}

interface BatchConceptBase830G3 {
  readonly scope: SchemaWikiScopeV1
  readonly catalog: SchemaPackCatalog830G3
  readonly candidateHash: string
  readonly members: readonly BatchConceptMember830G3[]
  readonly entities: readonly BatchConceptEntity830G3[]
  readonly alignments: readonly BatchConceptAlignment830G3[]
}

export interface BatchConceptPreparation830G3 extends BatchConceptBase830G3 {
  readonly mode: 'g3-preparation'
  readonly preparationID: string
  readonly status: 'DRAFT' | 'READY'
  readonly statusLabel: '待审核' | '已审核但未发布'
  readonly expectedBaseReleaseID: string
  readonly expectedBaseActivationEpoch: number
}

export interface BatchConceptActive830G3 extends BatchConceptBase830G3 {
  readonly mode: 'g3-active'
  readonly releaseID: string
  readonly activationEpoch: number
}

export type BatchConceptDirectory830G3 = BatchConceptPreparation830G3 | BatchConceptActive830G3

export interface BatchConceptPage830G3 {
  readonly readMode: 'preparation' | 'active'
  readonly directory: BatchConceptDirectory830G3
  readonly member: BatchConceptMember830G3
  readonly relatedMembers: readonly BatchConceptMember830G3[]
  readonly citations: readonly { readonly citation_id: string, readonly page_number: number, readonly quote: string }[]
  readonly session?: {
    readonly scope: SchemaWikiScopeV1
    readonly read: {
      readonly contract: 'concept-page-read.830.g2.v1'
      readonly read_mode: 'pinned'
      readonly release_id: string
      readonly activation_epoch: number
      readonly candidate_hash: string
      readonly space_id: string
      readonly raw_kb_id: string
      readonly wiki_kb_id: string
      readonly member: BatchConceptMember830G3
      readonly related_members: readonly BatchConceptMember830G3[]
      readonly citations: readonly { readonly citation_id: string, readonly page_number: number, readonly quote: string }[]
      readonly definition_hash: string
      readonly aggregate_hash: string
    }
  }
}

function invalid(code = 'BATCH_CONCEPT_830_G3_INVALID'): never { throw new Error(code) }
function record(value: unknown): value is R { return typeof value === 'object' && value !== null && !Array.isArray(value) }
function exact(value: unknown, keys: readonly string[]): R {
  if (!record(value)) return invalid()
  const actual = Object.keys(value).sort(); const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) return invalid()
  return value
}
function bodyText(value: unknown, allowEmpty = false): string {
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0)
    || value.normalize('NFC') !== value || BODY_CONTROL.test(value)) return invalid()
  return value
}
function structuredText(value: unknown, allowEmpty = false): string {
  if (typeof value !== 'string' || (!allowEmpty && value.length === 0)
    || value.normalize('NFC') !== value || STRUCTURED_CONTROL.test(value)) return invalid()
  return value
}
function identity(value: unknown): string {
  const result = structuredText(value)
  if (encoder.encode(result).length > 512 || EDGE_SPACE.test(result)) return invalid()
  return result
}
function pathID(value: unknown): string {
  const result = identity(value)
  if (!PATH_ID.test(result) || ['current', 'latest'].includes(result.toLowerCase())) return invalid()
  return result
}
function entityVersion(value: unknown, ownerID: string): string {
  const result = identity(value)
  if (!result.startsWith(`${ownerID}@`) || result.length === ownerID.length + 1) return invalid()
  return result
}
function hash(value: unknown): string { if (typeof value !== 'string' || !HASH.test(value)) return invalid(); return value }
function positive(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) <= 0) return invalid()
  return Number(value)
}
function integer(value: unknown): number {
  if (!Number.isSafeInteger(value)) return invalid()
  return Number(value)
}
function strings(value: unknown, unique = false): string[] {
  if (!Array.isArray(value)) return invalid()
  const result = value.map(item => identity(item))
  if (unique && new Set(result).size !== result.length) return invalid()
  return result
}
function bodyStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return invalid()
  return value.map(item => bodyText(item))
}
function same(a: unknown, b: unknown): boolean {
  if (a === null || typeof a !== 'object') return Object.is(a, b)
  if (Array.isArray(a)) return Array.isArray(b) && a.length === b.length && a.every((item, index) => same(item, b[index]))
  if (!record(b)) return false
  const keys = Object.keys(a).sort(); const other = Object.keys(b).sort()
  return keys.length === other.length && keys.every((key, index) => key === other[index] && same((a as R)[key], b[key]))
}
function canonicalJSON(value: unknown): string {
  if (value === null || typeof value === 'boolean') return JSON.stringify(value)
  if (typeof value === 'string') return JSON.stringify(bodyText(value, true))
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) return invalid()
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`
  if (!record(value)) return invalid()
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(structuredText(key, true))}:${canonicalJSON(value[key])}`).join(',')}}`
}
async function sha256(value: string): Promise<string> {
  const digest = await globalThis.crypto.subtle.digest('SHA-256', encoder.encode(value))
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}
async function schemaWikiHash(contract: string, payload: unknown): Promise<string> {
  return sha256(`schema-wiki-canonical.v1\u0000${contract}\u0000${canonicalJSON(payload)}`)
}
function without(value: R, key: string): R {
  return Object.fromEntries(Object.entries(value).filter(([name]) => name !== key))
}
function codePointOrder(left: string, right: string): number {
  const a = [...left]; const b = [...right]
  for (let i = 0; i < Math.min(a.length, b.length); i++) {
    const difference = a[i]!.codePointAt(0)! - b[i]!.codePointAt(0)!
    if (difference) return difference
  }
  return a.length - b.length
}
function unwrap(value: unknown): unknown {
  const response = exact(value, ['success', 'data'])
  if (response.success !== true) return invalid()
  return response.data
}
function deepFreeze<T>(value: T): T {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value)
    for (const nested of Object.values(value as R)) deepFreeze(nested)
  }
  return value
}

const EVIDENCE_KEYS = ['tenant_id', 'space_id', 'raw_kb_id', 'knowledge_id', 'parse_attempt', 'revision_id',
  'source_hash', 'parse_hash', 'parser_identity', 'source_type', 'block_id', 'page_number', 'offset_unit',
  'start', 'end', 'quote', 'quote_hash']
async function evidence(value: unknown, scope: SchemaWikiScopeV1, tenantID?: number): Promise<BatchConceptEvidence830G3[]> {
  if (!Array.isArray(value)) return invalid()
  return Promise.all(value.map(async raw => {
    const item = exact(raw, EVIDENCE_KEYS)
    const tenant = positive(item.tenant_id); const start = integer(item.start); const end = integer(item.end)
    const quote = bodyText(item.quote, true)
    if (tenantID !== undefined && tenant !== tenantID) return invalid()
    if (identity(item.space_id) !== scope.space_id || identity(item.raw_kb_id) !== scope.raw_kb_id
      || !['DOCUMENT', 'EXPERT_REVISION_RECORD'].includes(String(item.source_type))
      || item.offset_unit !== 'UNICODE_CODE_POINT' || positive(item.parse_attempt) < 1
      || positive(item.page_number) < 1 || start < 0 || end <= start || Array.from(quote).length !== end - start
      || ![item.revision_id, item.source_hash, item.parse_hash, item.parser_identity, item.block_id]
        .every(value => typeof value === 'string' && value.length > 0)
      || !hash(item.source_hash) || !hash(item.parse_hash) || await sha256(quote) !== hash(item.quote_hash)) return invalid()
    identity(item.knowledge_id); identity(item.revision_id); identity(item.parser_identity); identity(item.block_id)
    return item as unknown as BatchConceptEvidence830G3
  }))
}

async function pageMember(value: unknown, scope: SchemaWikiScopeV1, tenantID?: number): Promise<BatchConceptMember830G3> {
  const member = exact(value, ['kind', 'member_id', 'owner_id', 'title', 'content', 'payload'])
  const kind = member.kind
  if (!['concept', 'field_assertion', 'entity_overview', 'free_wiki', 'free_wiki_item'].includes(String(kind))) return invalid()
  const memberID = pathID(member.member_id); const ownerID = identity(member.owner_id)
  const title = bodyText(member.title, true); const content = bodyText(member.content, true)
  if (!record(member.payload)) return invalid()
  const payload = member.payload
  if (kind === 'field_assertion') {
    const p = exact(payload, ['space_id', 'entity_id', 'field_key', 'state', 'value', 'attempted', 'unknown_reason',
      'evidence', 'concept_ids', 'conditions', 'exceptions', 'entity_version', 'valid_time'])
    const state = p.state; const proofs = await evidence(p.evidence, scope, tenantID)
    const conditions = bodyStrings(p.conditions); const exceptions = bodyStrings(p.exceptions); strings(p.concept_ids, true)
    const validTime = bodyText(p.valid_time, true); const fieldKey = identity(p.field_key)
    if (!memberID.startsWith('assertion_') || p.space_id !== scope.space_id || identity(p.entity_id) !== ownerID
      || !entityVersion(p.entity_version, ownerID) || p.attempted !== true || structuredText(title).length === 0) return invalid()
    let first: string
    if (state === 'unknown') {
      if (p.value !== null || proofs.length !== 0 || typeof p.unknown_reason !== 'string' || !p.unknown_reason) return invalid()
      first = `未知：${bodyText(p.unknown_reason)}`
    } else if (state === 'present' || state === 'absent_explicitly') {
      if (typeof p.value !== 'string' || p.value.length === 0 || p.unknown_reason !== null || proofs.length === 0) return invalid()
      first = `${state === 'present' ? '值' : '明确不提供'}：${bodyText(p.value)}`
    } else return invalid()
    const expected = [first, ...conditions.map(item => `条件：${item}`), ...exceptions.map(item => `例外：${item}`),
      ...(validTime === '' ? [] : [`有效期：${validTime}`])].join('\n')
    if (identity(fieldKey) !== p.field_key || content !== expected) return invalid()
  } else if (kind === 'concept') {
    const p = exact(payload, ['space_id', 'canonical_key', 'sense_key', 'title', 'body', 'evidence', 'aliases', 'origin'])
    if (!memberID.startsWith('concept_') || ownerID !== scope.space_id || p.space_id !== scope.space_id
      || bodyText(p.title) !== title || bodyText(p.body) !== content || strings(p.aliases).length < 0
      || (await evidence(p.evidence, scope, tenantID)).length === 0
      || !['SCHEMA_DEFINITION', 'MODEL_COMPILE', 'EXPERT_REVISION_RECORD'].includes(String(p.origin))) return invalid()
    identity(p.canonical_key); identity(p.sense_key)
  } else if (kind === 'free_wiki_item') {
    const p = exact(payload, ['space_id', 'entity_id', 'stable_key', 'title', 'body', 'evidence', 'concept_ids',
      'conditions', 'exceptions', 'entity_version', 'valid_time'])
    const pageBody = bodyText(p.body); const conditions = bodyStrings(p.conditions); const exceptions = bodyStrings(p.exceptions)
    const validTime = bodyText(p.valid_time, true)
    const expected = [pageBody, ...conditions.map(item => `条件：${item}`), ...exceptions.map(item => `例外：${item}`),
      ...(validTime === '' ? [] : [`有效期：${validTime}`])].join('\n')
    if (!memberID.startsWith('free_') || p.space_id !== scope.space_id || identity(p.entity_id) !== ownerID
      || !entityVersion(p.entity_version, ownerID) || bodyText(p.title) !== title || expected !== content
      || (await evidence(p.evidence, scope, tenantID)).length === 0) return invalid()
    identity(p.stable_key); strings(p.concept_ids, true)
  } else if (kind === 'free_wiki') {
    const p = exact(payload, ['member_ids'])
    const refs = strings(p.member_ids, true).map(pathID)
    if (!memberID.startsWith('free_wiki_') || title !== '开放知识' || content !== ''
      || refs.some((ref, index) => ref !== [...refs].sort()[index])) return invalid()
  } else {
    await overviewPayload(payload, scope, ownerID)
    if (!memberID.startsWith('entity_overview_') || content.length === 0 || title !== payload.display_name) return invalid()
  }
  return member as unknown as BatchConceptMember830G3
}

async function overviewPayload(value: unknown, scope: SchemaWikiScopeV1, ownerID: string): Promise<R> {
  const p = exact(value, ['contract', 'entity_id', 'entity_version', 'display_name', 'issuer', 'product_code',
    'primary_classification', 'schema_pack_id', 'schema_version', 'schema_pack_sha256', 'schema_pack_display_name',
    'profile_id', 'profile_version', 'profile_sha256', 'quality_status', 'release_lane', 'sections',
    ...(record(value) && Object.hasOwn(value, 'navigation_assignment') ? ['navigation_assignment'] : [])])
  if (p.contract !== OVERVIEW_CONTRACT || identity(p.entity_id) !== ownerID
    || !entityVersion(p.entity_version, ownerID) || !Array.isArray(p.sections)
    || p.quality_status !== 'REGISTERED_NOT_QUALITY_ADMITTED' || p.release_lane !== 'ISOLATED_NOT_FOR_PRODUCTION') return invalid()
  for (const name of ['display_name', 'issuer', 'product_code', 'primary_classification', 'schema_pack_id',
    'schema_version', 'schema_pack_display_name', 'profile_id', 'profile_version']) identity(p[name])
  hash(p.schema_pack_sha256); hash(p.profile_sha256)
  if (Object.hasOwn(p, 'navigation_assignment')) {
    const nav = exact(p.navigation_assignment, ['contract', 'entity_id', 'entity_version', 'assignment_version',
      'labels', 'primary_label', 'previous_assignment_sha256', 'assignment_sha256'])
    if (nav.contract !== 'g3-navigation-assignment.830.v1' || nav.entity_id !== ownerID
      || nav.entity_version !== p.entity_version || !Number.isSafeInteger(nav.assignment_version)
      || Number(nav.assignment_version) < 1 || !Array.isArray(nav.labels)
      || nav.labels.length < 1 || nav.labels.length > 16) return invalid()
    const labels = nav.labels.map(label => {
      const text = identity(label)
      if ([...text].length > 80) return invalid()
      return text
    })
    if (new Set(labels).size !== labels.length || labels.some((label, i) => label !== [...labels].sort(codePointOrder)[i])
      || !labels.includes(identity(nav.primary_label))) return invalid()
    hash(nav.previous_assignment_sha256)
    if (await schemaWikiHash(String(nav.contract), without(nav, 'assignment_sha256'))
      !== hash(nav.assignment_sha256)) return invalid()
  }
  const sectionKeys = new Set<string>(); const fieldKeys = new Set<string>(); const memberIDs = new Set<string>()
  for (const rawSection of p.sections) {
    const section = exact(rawSection, ['section_key', 'display_name', 'fields'])
    const sectionKey = identity(section.section_key)
    if (sectionKeys.has(sectionKey) || !Array.isArray(section.fields) || section.fields.length === 0) return invalid()
    sectionKeys.add(sectionKey); identity(section.display_name)
    for (const rawField of section.fields) {
      const field = exact(rawField, ['field_key', 'short_title', 'member_id'])
      const fieldKey = identity(field.field_key); const memberID = pathID(field.member_id)
      if (fieldKeys.has(fieldKey) || memberIDs.has(memberID)) return invalid()
      fieldKeys.add(fieldKey); memberIDs.add(memberID); identity(field.short_title)
    }
  }
  void scope
  return p
}

async function expectedGroupID(scope: SchemaWikiScopeV1, ownerID: string, kind: 'entity_overview' | 'free_wiki') {
  return `${kind}_` + await schemaWikiHash('entity-group.830.g2.v1', [scope.space_id, ownerID, kind])
}

async function validateMembers(rawMembers: unknown, scope: SchemaWikiScopeV1,
  catalog: SchemaPackCatalog830G3, tenantID?: number): Promise<{
    members: BatchConceptMember830G3[], entities: BatchConceptEntity830G3[]
  }> {
  if (!Array.isArray(rawMembers) || rawMembers.length === 0) return invalid()
  const members = await Promise.all(rawMembers.map(item => pageMember(item, scope, tenantID)))
  const identities = members.map(item => `${item.kind}\u0000${item.member_id}`)
  if (new Set(members.map(item => item.member_id)).size !== members.length
    || identities.some((value, index) => value !== [...identities].sort()[index])) return invalid()
  const byID = new Map(members.map(item => [item.member_id, item]))
  const overviews = members.filter(item => item.kind === 'entity_overview')
  const freeRoots = members.filter(item => item.kind === 'free_wiki')
  if (overviews.length === 0 || new Set(overviews.map(item => item.owner_id)).size !== overviews.length
    || freeRoots.length !== overviews.length) return invalid()
  const referencedFields = new Set<string>()
  const referencedFreeItems = new Set<string>()
  const entities: BatchConceptEntity830G3[] = []
  for (const overview of overviews) {
    const p = overview.payload; const owner = overview.owner_id
    if (overview.member_id !== await expectedGroupID(scope, owner, 'entity_overview')) return invalid()
    const entry = catalog.entries.find(item => item.pack.schema_pack_id === p.schema_pack_id
      && item.pack.schema_version === p.schema_version && item.pack.schema_pack_sha256 === p.schema_pack_sha256
      && item.profile.profile_id === p.profile_id && item.profile.profile_version === p.profile_version
      && item.profile.profile_sha256 === p.profile_sha256)
    if (!entry || entry.pack.display_name !== p.schema_pack_display_name
      || entry.pack.applicable_classifications[0] !== p.primary_classification) return invalid()
    const sections = p.sections as R[]
    if (sections.length !== entry.profile.sections.length) return invalid()
    let fieldCount = 0
    const projected = sections.map((rawSection, sectionIndex) => {
      const section = rawSection as R; const expected = entry.profile.sections[sectionIndex]
      const rawFields = section.fields as R[]
      if (section.section_key !== expected.section_key || section.display_name !== expected.display_name
        || rawFields.length !== expected.fields.length) return invalid()
      const fields = rawFields.map((rawField, fieldIndex) => {
        const expectedField = expected.fields[fieldIndex]
        const memberID = String(rawField.member_id); const member = byID.get(memberID)
        if (rawField.field_key !== expectedField.field_key || rawField.short_title !== expectedField.short_title
          || !member || member.kind !== 'field_assertion' || member.owner_id !== owner
          || member.payload.entity_version !== p.entity_version || member.payload.field_key !== rawField.field_key
          || member.title !== rawField.short_title
          || referencedFields.has(memberID)) return invalid()
        referencedFields.add(memberID); fieldCount++
        return { fieldKey: String(rawField.field_key), shortTitle: String(rawField.short_title), memberID }
      })
      return { sectionKey: String(section.section_key), displayName: String(section.display_name), fields }
    })
    const freeWiki = freeRoots.find(item => item.owner_id === owner)
    if (!freeWiki || freeWiki.member_id !== await expectedGroupID(scope, owner, 'free_wiki')) return invalid()
    const freeIDs = (freeWiki.payload.member_ids as string[])
    if (freeIDs.some(id => byID.get(id)?.kind !== 'free_wiki_item' || byID.get(id)?.owner_id !== owner
      || byID.get(id)?.payload.entity_version !== p.entity_version || referencedFreeItems.has(id))) return invalid()
    freeIDs.forEach(id => referencedFreeItems.add(id))
    entities.push({ entityID: owner, entityVersion: String(p.entity_version), displayName: String(p.display_name),
      issuer: String(p.issuer), productCode: String(p.product_code), primaryClassification: String(p.primary_classification),
      navigationPrimaryLabel: p.navigation_assignment
        ? String((p.navigation_assignment as R).primary_label) : String(p.primary_classification),
      navigationLabels: p.navigation_assignment
        ? (p.navigation_assignment as R).labels as string[] : [String(p.primary_classification)],
      schemaPackID: String(p.schema_pack_id), schemaVersion: String(p.schema_version),
      schemaPackSHA256: String(p.schema_pack_sha256), schemaPackDisplayName: String(p.schema_pack_display_name),
      profileID: String(p.profile_id), profileVersion: String(p.profile_version), profileSHA256: String(p.profile_sha256),
      qualityStatus: 'REGISTERED_NOT_QUALITY_ADMITTED', releaseLane: 'ISOLATED_NOT_FOR_PRODUCTION', overview,
      freeWiki, sections: projected, fieldCount, freeItemCount: freeIDs.length })
  }
  const allFields = members.filter(item => item.kind === 'field_assertion')
  const allFreeItems = members.filter(item => item.kind === 'free_wiki_item')
  if (referencedFields.size !== allFields.length || referencedFreeItems.size !== allFreeItems.length
    || allFreeItems.some(item => !referencedFreeItems.has(item.member_id))) return invalid()
  const conceptIDs = new Set(members.filter(item => item.kind === 'concept').map(item => item.member_id))
  for (const member of [...allFields, ...allFreeItems]) {
    if ((member.payload.concept_ids as string[]).some(id => !conceptIDs.has(id))) return invalid()
  }
  return { members, entities }
}

function assertAudit(value: unknown, members: readonly BatchConceptMember830G3[]): void {
  if (!Array.isArray(value)) return invalid()
  const allowed = new Set(['new_page', 'update', 'sense', 'field_rule', 'alias_link', 'pending', 'reject', 'mention', 'duplicate'])
  const eligible = new Set(members.filter(item => !['entity_overview', 'free_wiki'].includes(item.kind)).map(item => item.member_id))
  const keys: string[] = []
  for (const raw of value) {
    const item = exact(raw, ['disposition', 'key', 'reason']); const key = pathID(item.key)
    if (!allowed.has(String(item.disposition)) || bodyText(item.reason).length === 0 || !eligible.has(key)) return invalid()
    keys.push(key)
  }
  if (keys.length !== eligible.size || new Set(keys).size !== keys.length
    || keys.some((key, index) => key !== [...keys].sort()[index])) return invalid()
}

async function parseManifest(value: unknown, scope: SchemaWikiScopeV1,
  catalog: SchemaPackCatalog830G3, tenantID?: number) {
  const manifest = exact(value, ['contract', 'members', 'members_sha256', 'audit'])
  if (manifest.contract !== MANIFEST_CONTRACT || !Array.isArray(manifest.members)
    || await schemaWikiHash(MEMBERS_HASH_CONTRACT, { members: manifest.members }) !== hash(manifest.members_sha256)) return invalid()
  const parsed = await validateMembers(manifest.members, scope, catalog, tenantID)
  assertAudit(manifest.audit, parsed.members)
  return parsed
}

export async function parseBatchConceptPreparation830G3(value: unknown, scope: SchemaWikiScopeV1,
  catalog: SchemaPackCatalog830G3, expectedPreparationID: string): Promise<BatchConceptPreparation830G3> {
  parseSchemaWikiScope(scope); pathID(expectedPreparationID)
  const read = exact(value, ['contract', 'read_mode', 'tenant_id', 'space_id', 'raw_kb_id', 'wiki_kb_id',
    'preparation_id', 'status', 'candidate_sha256', 'expected_base_release_id', 'expected_base_activation_epoch',
    'page_manifest', 'read_sha256'])
  const tenantID = positive(read.tenant_id)
  if (read.contract !== PREPARATION_CONTRACT || read.read_mode !== 'preparation'
    || read.space_id !== scope.space_id || read.raw_kb_id !== scope.raw_kb_id || read.wiki_kb_id !== scope.wiki_kb_id
    || pathID(read.preparation_id) !== expectedPreparationID || !['DRAFT', 'READY'].includes(String(read.status))
    || await schemaWikiHash(PREPARATION_CONTRACT, without(read, 'read_sha256')) !== hash(read.read_sha256)) return invalid()
  const parsed = await parseManifest(read.page_manifest, scope, catalog, tenantID)
  const status = read.status as 'DRAFT' | 'READY'
  return deepFreeze({ mode: 'g3-preparation', scope, catalog, preparationID: expectedPreparationID, status,
    statusLabel: status === 'DRAFT' ? '待审核' : '已审核但未发布', candidateHash: hash(read.candidate_sha256),
    expectedBaseReleaseID: pathID(read.expected_base_release_id),
    expectedBaseActivationEpoch: positive(read.expected_base_activation_epoch), members: parsed.members,
    entities: parsed.entities, alignments: [] })
}

export async function parseBatchConceptActive830G3(value: unknown, scope: SchemaWikiScopeV1,
  catalog: SchemaPackCatalog830G3, current: { release_id: string, activation_epoch: number }): Promise<BatchConceptActive830G3> {
  parseSchemaWikiScope(scope); const releaseID = pathID(current.release_id); const epoch = positive(current.activation_epoch)
  if (!Array.isArray(value) || value.length === 0) return invalid()
  const rows = value.map(raw => exact(raw, ['kind', 'logical_slug', 'revision_id', 'member_digest', 'title', 'content', 'payload']))
  const revisions = new Set(rows.map(row => hash(row.revision_id)))
  if (revisions.size !== 1) return invalid()
  const candidateHash = [...revisions][0]
  const owners = new Map<string, string>()
  for (const row of rows) {
    if (!record(row.payload)) return invalid()
    if (row.kind === 'concept') owners.set(String(row.logical_slug), scope.space_id)
    else if (row.kind === 'field_assertion' || row.kind === 'free_wiki_item' || row.kind === 'entity_overview') {
      owners.set(String(row.logical_slug), identity(row.payload.entity_id))
    }
  }
  const overviewOwners = [...owners.entries()].filter(([id]) => id.startsWith('entity_overview_')).map(([, owner]) => owner)
  for (const row of rows.filter(row => row.kind === 'free_wiki')) {
    const matches = await Promise.all(overviewOwners.map(async owner => ({ owner,
      id: await expectedGroupID(scope, owner, 'free_wiki') })))
    const match = matches.find(item => item.id === row.logical_slug)
    if (!match) return invalid(); owners.set(String(row.logical_slug), match.owner)
  }
  const members: BatchConceptMember830G3[] = []
  for (const row of rows) {
    const member = { kind: row.kind, member_id: row.logical_slug, owner_id: owners.get(String(row.logical_slug)),
      title: row.title, content: row.content, payload: row.payload }
    const parsed = await pageMember(member, scope)
    if (await schemaWikiHash(MEMBER_HASH_CONTRACT, member) !== hash(row.member_digest)) return invalid()
    members.push(parsed)
  }
  // Published search rows use slug order; validate the reconstructed member set in canonical order.
  members.sort((left, right) => {
    const a = `${left.kind}\0${left.member_id}`
    const b = `${right.kind}\0${right.member_id}`
    return a < b ? -1 : a > b ? 1 : 0
  })
  const parsed = await validateMembers(members, scope, catalog)
  return deepFreeze({ mode: 'g3-active', scope, catalog, releaseID, activationEpoch: epoch,
    candidateHash, members: parsed.members, entities: parsed.entities, alignments: [] })
}

function genericPath(scope: SchemaWikiScopeV1, suffix: string): string {
  parseSchemaWikiScope(scope)
  if (!/^\/(?:current|releases\/[A-Za-z0-9._:@-]+\/search)$/.test(suffix)) return invalid()
  return `/api/v1/knowledgebase/${encodeURIComponent(scope.wiki_kb_id)}`
    + `/wiki/release-scopes/${encodeURIComponent(scope.space_id)}`
    + `/raw/${encodeURIComponent(scope.raw_kb_id)}${suffix}`
}
function preparationScopePath(wikiKBID: string, preparationID: string): string {
  return `/api/v1/knowledgebase/${encodeURIComponent(pathID(wikiKBID))}`
    + `/wiki/preparations/${encodeURIComponent(pathID(preparationID))}/schema-scope`
}
async function loadCatalog(scope: SchemaWikiScopeV1, transport: SchemaWikiReadTransport) {
  const path = buildScopedSchemaWikiPath(scope,
    `/catalogs/${CATALOG_ID_830_G3}/versions/${CATALOG_VERSION_830_G3}`, { expectedScope: scope })
  return parseSchemaPackCatalog830G3(unwrap(await transport.get(path)))
}

function emptyUnknown(member: { payload: R }): boolean {
  const p = member.payload
  return p.attempted === true && p.state === 'unknown' && p.value === null && typeof p.unknown_reason === 'string'
    && Array.isArray(p.evidence) && p.evidence.length === 0 && Array.isArray(p.conditions) && p.conditions.length === 0
    && Array.isArray(p.exceptions) && p.exceptions.length === 0 && Array.isArray(p.concept_ids) && p.concept_ids.length === 0
    && p.valid_time === ''
}
async function alignments(prepared: BatchConceptPreparation830G3, rows: unknown): Promise<BatchConceptAlignment830G3[]> {
  let old
  try {
    old = await parseConceptCatalog830G2(rows, prepared.scope, {
      release_id: prepared.expectedBaseReleaseID, activation_epoch: prepared.expectedBaseActivationEpoch,
    })
  } catch { return invalid('BATCH_CONCEPT_830_G3_ALIGNMENT_INVALID') }
  if (old.mode !== 'g2') return invalid('BATCH_CONCEPT_830_G3_ALIGNMENT_INVALID')
  const medical = prepared.entities.filter(entity => entity.schemaPackID === 'schemapack_medical_insurance')
  if (medical.length !== 2 || old.entities.length !== 2) return invalid('BATCH_CONCEPT_830_G3_ALIGNMENT_INVALID')
  const result: BatchConceptAlignment830G3[] = []
  for (const entity of medical) {
    const oldEntity = old.entities.find(item => item.entityID === entity.entityID && item.entityVersion === entity.entityVersion)
    const newRefs = entity.sections.flatMap(section => section.fields).filter(item => item.fieldKey === 'social_insurance_requirements')
    const oldFields = old.members.filter(item => item.kind === 'field_assertion' && item.owner_id === entity.entityID
      && item.payload.field_key === 'social_insurance_requirement')
    if (!oldEntity || newRefs.length !== 1 || oldFields.length !== 1) return invalid('BATCH_CONCEPT_830_G3_ALIGNMENT_INVALID')
    const next = prepared.members.find(item => item.member_id === newRefs[0].memberID)!
    const previous = oldFields[0]
    if (!emptyUnknown(next) || !emptyUnknown(previous) || next.payload.unknown_reason !== previous.payload.unknown_reason
      || next.payload.entity_id !== previous.payload.entity_id || next.payload.entity_version !== previous.payload.entity_version) {
      return invalid('BATCH_CONCEPT_830_G3_ALIGNMENT_INVALID')
    }
    result.push({ entityID: entity.entityID, entityVersion: entity.entityVersion,
      oldFieldKey: 'social_insurance_requirement', newFieldKey: 'social_insurance_requirements',
      oldMemberID: previous.member_id, newMemberID: next.member_id, oldReleaseID: prepared.expectedBaseReleaseID })
  }
  return result.sort((a, b) => a.entityID.localeCompare(b.entityID))
}

export async function loadBatchConceptPreparation830G3(wikiKBID: string, preparationID: string,
  transport: SchemaWikiReadTransport): Promise<BatchConceptPreparation830G3> {
  const scope = parseSchemaWikiScope(unwrap(await transport.get(preparationScopePath(wikiKBID, preparationID))))
  if (scope.wiki_kb_id !== wikiKBID) return invalid()
  const catalog = await loadCatalog(scope, transport)
  const path = buildScopedSchemaWikiPath(scope, `/preparations/${pathID(preparationID)}/batch-concept`, { expectedScope: scope })
  const prepared = await parseBatchConceptPreparation830G3(unwrap(await transport.get(path)), scope, catalog, preparationID)
  const oldRows = unwrap(await transport.get(genericPath(scope,
    `/releases/${prepared.expectedBaseReleaseID}/search`) + '?q='))
  const mapped = await alignments(prepared, oldRows)
  return deepFreeze({ ...prepared, alignments: mapped })
}

export async function loadBatchConceptActive830G3(wikiKBID: string,
  transport: SchemaWikiReadTransport): Promise<BatchConceptActive830G3 | null> {
  pathID(wikiKBID)
  const scope = parseSchemaWikiScope(unwrap(await transport.get(buildSchemaWikiScopeBootstrapPath(wikiKBID))))
  if (scope.wiki_kb_id !== wikiKBID) return invalid()
  const current = exact(unwrap(await transport.get(genericPath(scope, '/current'))), ['release_id', 'activation_epoch'])
  const pin = { release_id: pathID(current.release_id), activation_epoch: positive(current.activation_epoch) }
  const rows = unwrap(await transport.get(genericPath(scope, `/releases/${pin.release_id}/search`) + '?q='))
  if (!Array.isArray(rows)) return invalid()
  const markers = rows.filter(row => record(row) && record(row.payload) && row.payload.contract === OVERVIEW_CONTRACT)
  if (markers.length === 0) return null
  const catalog = await loadCatalog(scope, transport)
  return parseBatchConceptActive830G3(rows, scope, catalog, pin)
}

// Read the requested immutable release, including its server-issued activation epoch.
// The pinned page is parsed again against the complete verified snapshot without a second GET.
export async function readPinnedBatchConceptPage830G3(wikiKBID: string, memberID: string,
  releaseID: string, transport: SchemaWikiReadTransport): Promise<BatchConceptPage830G3 | null> {
  pathID(wikiKBID); const target = pathID(memberID); const release = pathID(releaseID)
  const scope = parseSchemaWikiScope(unwrap(await transport.get(buildSchemaWikiScopeBootstrapPath(wikiKBID))))
  if (scope.wiki_kb_id !== wikiKBID) return invalid()
  const rows = unwrap(await transport.get(genericPath(scope, `/releases/${release}/search`) + '?q='))
  if (!Array.isArray(rows)) return invalid()
  if (!rows.some(row => record(row) && record(row.payload) && row.payload.contract === OVERVIEW_CONTRACT)) return null
  const path = buildScopedSchemaWikiPath(scope, `/concept-pages/${encodeURIComponent(target)}`,
    { expectedScope: scope }) + `?release_id=${encodeURIComponent(release)}`
  const raw = unwrap(await transport.get(path))
  if (!record(raw) || raw.contract !== PAGE_CONTRACT || raw.read_mode !== 'pinned'
    || raw.release_id !== release || raw.space_id !== scope.space_id
    || raw.raw_kb_id !== scope.raw_kb_id || raw.wiki_kb_id !== scope.wiki_kb_id) return invalid()
  const epoch = positive(raw.activation_epoch)
  const catalog = await loadCatalog(scope, transport)
  const directory = await parseBatchConceptActive830G3(rows, scope, catalog, {
    release_id: release, activation_epoch: epoch,
  })
  return parseBatchConceptPage(directory, target, raw)
}

function localRelated(directory: BatchConceptDirectory830G3, member: BatchConceptMember830G3) {
  let refs: string[] = []
  if (member.kind === 'entity_overview') refs = (member.payload.sections as R[]).flatMap(section =>
    (section.fields as R[]).map(field => String(field.member_id)))
  else if (member.kind === 'free_wiki') refs = member.payload.member_ids as string[]
  else if (member.kind === 'concept') refs = directory.members.filter(item =>
    item.kind === 'field_assertion' && (item.payload.concept_ids as string[]).includes(member.member_id)).map(item => item.member_id)
  else refs = member.payload.concept_ids as string[]
  const wanted = new Set(refs)
  const related = directory.members.filter(item => wanted.has(item.member_id))
  if (related.length !== refs.length) return invalid()
  return related
}

export async function readBatchConceptPage830G3(directory: BatchConceptDirectory830G3, memberID: string,
  transport: SchemaWikiReadTransport): Promise<BatchConceptPage830G3> {
  const target = pathID(memberID); const expected = directory.members.find(item => item.member_id === target)
  if (!expected) return invalid()
  if (directory.mode === 'g3-preparation') {
    return deepFreeze({ readMode: 'preparation', directory, member: expected,
      relatedMembers: localRelated(directory, expected), citations: [] })
  }
  const path = buildScopedSchemaWikiPath(directory.scope, `/concept-pages/${encodeURIComponent(target)}`,
    { expectedScope: directory.scope }) + `?release_id=${encodeURIComponent(directory.releaseID)}`
  return parseBatchConceptPage(directory, target, unwrap(await transport.get(path)))
}

async function parseBatchConceptPage(directory: BatchConceptActive830G3, target: string,
  value: unknown): Promise<BatchConceptPage830G3> {
  const expected = directory.members.find(item => item.member_id === target)
  if (!expected) return invalid()
  const raw = exact(value, ['contract', 'read_mode', 'release_id', 'activation_epoch',
    'candidate_hash', 'space_id', 'raw_kb_id', 'wiki_kb_id', 'member', 'related_members', 'citations',
    'definition_hash', 'aggregate_hash'])
  if (raw.contract !== PAGE_CONTRACT || raw.read_mode !== 'pinned' || raw.release_id !== directory.releaseID
    || raw.activation_epoch !== directory.activationEpoch || raw.candidate_hash !== directory.candidateHash
    || raw.space_id !== directory.scope.space_id || raw.raw_kb_id !== directory.scope.raw_kb_id
    || raw.wiki_kb_id !== directory.scope.wiki_kb_id || !Array.isArray(raw.related_members)
    || !Array.isArray(raw.citations) || ![raw.definition_hash, raw.aggregate_hash]
      .every(item => item === '' || HASH.test(String(item)))) return invalid()
  const selected = await pageMember(raw.member, directory.scope)
  const related = await Promise.all(raw.related_members.map(item => pageMember(item, directory.scope)))
  const frozen = new Map(directory.members.map(item => [item.member_id, item]))
  if (!same(selected, expected) || related.some(item => !same(item, frozen.get(item.member_id)))) return invalid()
  const expectedRelated = localRelated(directory, expected)
  if (related.length !== expectedRelated.length || related.some((item, index) => item.member_id !== expectedRelated[index].member_id)) return invalid()
  const citations = raw.citations.map(item => {
    const citation = exact(item, ['citation_id', 'page_number', 'quote'])
    if (!/^citation-[a-f0-9]{24}$/.test(String(citation.citation_id)) || positive(citation.page_number) < 1
      || bodyText(citation.quote).length === 0) return invalid()
    return citation as unknown as { citation_id: string, page_number: number, quote: string }
  })
  const read = { ...raw, member: selected, related_members: related, citations } as BatchConceptPage830G3['session'] extends { read: infer T } ? T : never
  return deepFreeze({ readMode: 'active', directory, member: selected, relatedMembers: related, citations,
    session: { scope: directory.scope, read } })
}

import { buildSchemaWikiScopeBootstrapPath, type SchemaWikiReadTransport } from './index'
import { parseSchemaWikiScope, type SchemaWikiScopeV1 } from '../../views/knowledge/schema-wiki/schemaWikiContract'
import { buildScopedSchemaWikiPath } from '../../views/knowledge/schema-wiki/schemaWikiNavigation'

const HASH = /^[a-f0-9]{64}$/
const ID = /^[A-Za-z0-9._:@-]+$/
const INVALID_CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/
const IDENTITY_CONTROL = /[\u0000-\u001f\u007f]/
const EDGE_UNICODE_SPACE = /^\p{White_Space}|\p{White_Space}$/u
const SNAPSHOT_KEYS = ['kind', 'logical_slug', 'revision_id', 'member_digest', 'title', 'content', 'payload']
const G2_EXCLUSIVE = new Set(['concept', 'field_assertion', 'entity_overview', 'free_wiki_item'])
const G2_KINDS = new Set([...G2_EXCLUSIVE, 'free_wiki'])
const G1_CONTRACTS: Record<string, string> = {
  overview: 'entity-overview-page.830.g1.v1', section: 'entity-section-page.830.g1.v1',
  field: 'field-assertion-page.830.g1.v1', free_wiki: 'empty-free-wiki-page.830.g1.v1',
}
const SCHEMA_CONTRACTS: Record<string, string> = {
  root: 'schema-root-page.v1', section: 'schema-section-page.v1', field: 'schema-field-page.v1',
}
type R = Record<string, unknown>

export interface ConceptDirectoryMember830G2 {
  readonly kind: 'concept' | 'field_assertion' | 'entity_overview' | 'free_wiki' | 'free_wiki_item'
  readonly member_id: string
  readonly revision_id: string
  readonly member_digest: string
  readonly owner_id: string
  readonly title: string
  readonly content: string
  readonly payload: R
}
interface ParsedG2 {
  readonly mode: 'g2'
  readonly scope: SchemaWikiScopeV1
  readonly releaseID: string
  readonly activationEpoch: number
  readonly candidateHash: string
  readonly members: readonly ConceptDirectoryMember830G2[]
  readonly concepts: readonly ConceptDirectoryMember830G2[]
  readonly entities: readonly { entityID: string, entityVersion: string,
    overview: ConceptDirectoryMember830G2 }[]
  readonly freeWikiRoots: readonly ConceptDirectoryMember830G2[]
}
export interface ConceptDirectoryEntity830G2 {
  readonly entityID: string
  readonly entityVersion: string
  readonly overview: ConceptDirectoryMember830G2
  readonly freeWiki: ConceptDirectoryMember830G2
  readonly fieldCount: number
  readonly freeItemCount: number
}
export type ConceptCatalogResult830G2 =
  | (Omit<ParsedG2, 'entities' | 'freeWikiRoots'> & { readonly entities: readonly ConceptDirectoryEntity830G2[] })
  | { readonly mode: 'entity-g1', readonly scope: SchemaWikiScopeV1, readonly releaseID: string,
      readonly activationEpoch: number, readonly entityID: string }
  | { readonly mode: 'schema-legacy', readonly scope: SchemaWikiScopeV1,
      readonly releaseID: string, readonly activationEpoch: number }
export type ParsedConceptCatalog830G2 = ParsedG2 | Exclude<ConceptCatalogResult830G2, { mode: 'g2' }>

function fail(message = 'G2_DIRECTORY_INVALID'): never { throw new Error(message) }
function record(value: unknown): value is R { return typeof value === 'object' && value !== null && !Array.isArray(value) }
function exact(value: unknown, keys: readonly string[]): R {
  if (!record(value)) return fail()
  const actual = Object.keys(value).sort(); const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, i) => key !== expected[i])) return fail()
  return value
}
function text(value: unknown, nonempty = false): string {
  if (typeof value !== 'string' || (nonempty && value.length === 0)
    || value.normalize('NFC') !== value || INVALID_CONTROL.test(value)) return fail()
  return value
}
function pathIdentity(value: unknown): string {
  const result = text(value, true)
  if (!ID.test(result) || ['current', 'latest'].includes(result.toLowerCase())) return fail()
  return result
}
function conceptIdentity(value: unknown): string {
  if (typeof value !== 'string' || value.length === 0 || new TextEncoder().encode(value).length > 512
    || value.normalize('NFC') !== value || IDENTITY_CONTROL.test(value)
    || EDGE_UNICODE_SPACE.test(value)) return fail()
  return value
}
function hash(value: unknown): string { if (typeof value !== 'string' || !HASH.test(value)) return fail(); return value }
function positive(value: unknown): number { if (!Number.isSafeInteger(value) || Number(value) <= 0) return fail(); return Number(value) }
function integer(value: unknown): number { if (!Number.isSafeInteger(value)) return fail(); return Number(value) }
function list(value: unknown, parse: (item: unknown) => string = item => text(item), unique = false): string[] {
  if (!Array.isArray(value)) return fail()
  const result = value.map(parse)
  if (unique && new Set(result).size !== result.length) return fail()
  return result
}
function equalList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((value, i) => value === b[i])
}
function unwrap(value: unknown): unknown {
  const response = exact(value, ['success', 'data'])
  if (response.success !== true) return fail('G2_DIRECTORY_RESPONSE_INVALID')
  return response.data
}
function sameJSON(a: unknown, b: unknown): boolean {
  if (a === null || typeof a !== 'object') return Object.is(a, b)
  if (Array.isArray(a)) return Array.isArray(b) && a.length === b.length && a.every((v, i) => sameJSON(v, b[i]))
  if (!record(b)) return false
  const keys = Object.keys(a).sort(); const other = Object.keys(b).sort()
  return equalList(keys, other) && keys.every(key => sameJSON((a as R)[key], b[key]))
}
function buildGenericReleasePath(scope: SchemaWikiScopeV1, suffix: string): string {
  parseSchemaWikiScope(scope)
  if (!/^\/(?:current|releases\/[A-Za-z0-9._:@-]+\/search)$/.test(suffix)) return fail()
  return `/api/v1/knowledgebase/${encodeURIComponent(scope.wiki_kb_id)}`
    + `/wiki/release-scopes/${encodeURIComponent(scope.space_id)}`
    + `/raw/${encodeURIComponent(scope.raw_kb_id)}${suffix}`
}

const EVIDENCE_KEYS = ['tenant_id', 'space_id', 'raw_kb_id', 'knowledge_id', 'parse_attempt', 'revision_id',
  'source_hash', 'parse_hash', 'parser_identity', 'source_type', 'block_id', 'page_number', 'offset_unit',
  'start', 'end', 'quote', 'quote_hash']
function evidence(value: unknown, scope: SchemaWikiScopeV1): readonly R[] {
  if (!Array.isArray(value)) return fail()
  return value.map(item => {
    const e = exact(item, EVIDENCE_KEYS)
    positive(e.tenant_id); positive(e.parse_attempt); positive(e.page_number)
    conceptIdentity(e.space_id); conceptIdentity(e.raw_kb_id); conceptIdentity(e.knowledge_id); conceptIdentity(e.revision_id)
    conceptIdentity(e.parser_identity); conceptIdentity(e.block_id); hash(e.source_hash); hash(e.parse_hash); hash(e.quote_hash)
    const start = integer(e.start); const end = integer(e.end); const quote = text(e.quote, true)
    if (e.space_id !== scope.space_id || e.raw_kb_id !== scope.raw_kb_id
      || !['DOCUMENT', 'EXPERT_REVISION_RECORD'].includes(String(e.source_type))
      || e.offset_unit !== 'UNICODE_CODE_POINT' || start < 0 || end <= start
      || Array.from(quote).length !== end - start) return fail()
    return e
  })
}
function snapshot(value: unknown): R {
  const row = exact(value, SNAPSHOT_KEYS)
  pathIdentity(row.logical_slug); hash(row.revision_id); hash(row.member_digest)
  text(row.title); text(row.content)
  if (!record(row.payload)) return fail()
  return row
}
function looksG2(rows: readonly R[]): boolean {
  return rows.some(row => G2_EXCLUSIVE.has(String(row.kind))
    || row.kind === 'free_wiki' && record(row.payload) && Array.isArray((row.payload as R).member_ids)
    || record(row.payload) && 'space_id' in row.payload
      && ['canonical_key', 'field_key', 'stable_key'].some(key => key in (row.payload as R)))
}

function parseG2(rows: readonly R[], scope: SchemaWikiScopeV1,
  current: { release_id: string, activation_epoch: number }): ParsedG2 {
  if (rows.length === 0 || rows.some(row => !G2_KINDS.has(String(row.kind)))) return fail()
  const revisions = new Set(rows.map(row => hash(row.revision_id)))
  const slugs = rows.map(row => pathIdentity(row.logical_slug))
  if (revisions.size !== 1 || new Set(slugs).size !== slugs.length) return fail()
  const members: ConceptDirectoryMember830G2[] = []
  const conceptIDs = new Set<string>()
  const versions = new Map<string, string>()
  for (const row of rows) {
    const kind = row.kind as ConceptDirectoryMember830G2['kind']; const memberID = String(row.logical_slug)
    let ownerID = ''
    if (kind === 'concept') {
      if (!/^concept_[a-f0-9]{64}$/.test(memberID)) return fail()
      const p = exact(row.payload, ['space_id', 'canonical_key', 'sense_key', 'title', 'body', 'evidence', 'aliases', 'origin'])
      conceptIdentity(p.space_id); conceptIdentity(p.canonical_key); conceptIdentity(p.sense_key)
      list(p.aliases, conceptIdentity)
      if (p.space_id !== scope.space_id || p.title !== row.title || p.body !== row.content
        || evidence(p.evidence, scope).length === 0
        || !['SCHEMA_DEFINITION', 'MODEL_COMPILE', 'EXPERT_REVISION_RECORD'].includes(String(p.origin))) return fail()
      ownerID = scope.space_id; conceptIDs.add(memberID)
    } else if (kind === 'field_assertion') {
      if (!/^assertion_[a-f0-9]{64}$/.test(memberID)) return fail()
      const p = exact(row.payload, ['space_id', 'entity_id', 'field_key', 'state', 'value', 'attempted',
        'unknown_reason', 'evidence', 'concept_ids', 'conditions', 'exceptions', 'entity_version', 'valid_time'])
      ownerID = conceptIdentity(p.entity_id); const version = conceptIdentity(p.entity_version)
      if (p.space_id !== scope.space_id || p.field_key !== row.title || p.attempted !== true) return fail()
      const proofs = evidence(p.evidence, scope); list(p.concept_ids, pathIdentity, true)
      list(p.conditions); list(p.exceptions); text(p.valid_time)
      if (p.state === 'unknown') {
        if (p.value !== null || proofs.length || typeof p.unknown_reason !== 'string' || !p.unknown_reason
          || row.content !== `未知：${p.unknown_reason}`) return fail()
      } else if (p.state === 'present' || p.state === 'absent_explicitly') {
        if (typeof p.value !== 'string' || !p.value || p.unknown_reason !== null || !proofs.length || row.content !== p.value) return fail()
      } else return fail()
      if (versions.has(ownerID) && versions.get(ownerID) !== version) return fail(); versions.set(ownerID, version)
    } else if (kind === 'free_wiki_item') {
      if (!/^free_[a-f0-9]{64}$/.test(memberID)) return fail()
      const p = exact(row.payload, ['space_id', 'entity_id', 'stable_key', 'title', 'body', 'evidence',
        'concept_ids', 'conditions', 'exceptions', 'entity_version', 'valid_time'])
      ownerID = conceptIdentity(p.entity_id); const version = conceptIdentity(p.entity_version); conceptIdentity(p.stable_key)
      list(p.concept_ids, pathIdentity, true); list(p.conditions); list(p.exceptions); text(p.valid_time)
      if (p.space_id !== scope.space_id || p.title !== row.title || p.body !== row.content || !evidence(p.evidence, scope).length) return fail()
      if (versions.has(ownerID) && versions.get(ownerID) !== version) return fail(); versions.set(ownerID, version)
    } else {
      const prefix = kind === 'entity_overview' ? 'entity_overview_' : 'free_wiki_'
      if (!new RegExp(`^${prefix}[a-f0-9]{64}$`).test(memberID) || row.content !== '') return fail()
      const p = exact(row.payload, ['member_ids']); const refs = list(p.member_ids, pathIdentity, true)
      if (!equalList(refs, [...refs].sort())) return fail()
      if (kind === 'entity_overview') { ownerID = conceptIdentity(row.title) } else if (row.title !== '开放知识') return fail()
    }
    members.push({ kind, member_id: memberID, revision_id: String(row.revision_id), member_digest: String(row.member_digest),
      owner_id: ownerID, title: String(row.title), content: String(row.content), payload: row.payload as R })
  }
  const concepts = members.filter(member => member.kind === 'concept')
  const entityMembers = members.filter(member => ['field_assertion', 'free_wiki_item'].includes(member.kind))
  const entityIDs = [...new Set(entityMembers.map(member => member.owner_id))].sort()
  const overviews = members.filter(member => member.kind === 'entity_overview')
  const freeRoots = members.filter(member => member.kind === 'free_wiki')
  if (overviews.length !== entityIDs.length || freeRoots.length !== entityIDs.length) return fail()
  const entities = entityIDs.map(entityID => {
    const roots = overviews.filter(member => member.owner_id === entityID)
    if (roots.length !== 1) return fail()
    const expected = entityMembers.filter(member => member.owner_id === entityID).map(member => member.member_id).sort()
    if (!equalList(list(roots[0].payload.member_ids, pathIdentity, true), expected)) return fail()
    return { entityID, entityVersion: versions.get(entityID)!, overview: roots[0] }
  })
  const allIDs = new Set(members.map(member => member.member_id))
  for (const member of entityMembers) {
    for (const conceptID of list(member.payload.concept_ids, pathIdentity, true)) if (!conceptIDs.has(conceptID)) return fail()
  }
  for (const root of [...overviews, ...freeRoots]) for (const ref of list(root.payload.member_ids, pathIdentity, true)) if (!allIDs.has(ref)) return fail()
  return { mode: 'g2', scope, releaseID: current.release_id, activationEpoch: current.activation_epoch,
    candidateHash: [...revisions][0], members, concepts, entities, freeWikiRoots: freeRoots }
}

const G1_REFERENCE_KEYS = ['field_key', 'page_id', 'source_release_id', 'source_candidate_sha256',
  'product_version_id', 'claim_sha256', 'evidence_receipt_sha256s', 'citation_sha256s']
const G1_CITATION_KEYS = ['contract', 'citation_id', 'join_receipt_sha256', 'evidence_receipt_sha256',
  'source_role', 'source_sha256', 'source_revision_id', 'knowledge_id', 'chunk_id', 'parse_attempt_id',
  'parsed_document_sha256', 'parse_manifest_sha256', 'page_number', 'locator_kind', 'locator_ref',
  'locator_content_sha256', 'bbox', 'quote_snapshot', 'quote_sha256', 'citation_sha256']

function g1HashList(value: unknown): string[] {
  if (!Array.isArray(value)) return fail()
  const values = value.map(hash)
  if (new Set(values).size !== values.length) return fail()
  return values
}
function g1Reference(value: unknown): R {
  const ref = exact(value, G1_REFERENCE_KEYS)
  pathIdentity(ref.field_key); pathIdentity(ref.page_id); pathIdentity(ref.source_release_id)
  pathIdentity(ref.product_version_id); hash(ref.source_candidate_sha256); hash(ref.claim_sha256)
  g1HashList(ref.evidence_receipt_sha256s); g1HashList(ref.citation_sha256s)
  return ref
}
function g1References(value: unknown): R[] {
  if (!Array.isArray(value)) return fail()
  const refs = value.map(g1Reference)
  if (new Set(refs.map(ref => String(ref.page_id))).size !== refs.length) return fail()
  return refs
}
function g1Citation(value: unknown): void {
  const citation = exact(value, G1_CITATION_KEYS)
  if (citation.contract !== 'entity-page-exact-citation.830.g1.v1') return fail()
  ;['citation_id', 'source_role', 'source_revision_id', 'knowledge_id', 'chunk_id', 'parse_attempt_id',
    'locator_kind', 'locator_ref'].forEach(key => pathIdentity(citation[key]))
  text(citation.quote_snapshot, true)
  ;['join_receipt_sha256', 'evidence_receipt_sha256', 'source_sha256', 'parsed_document_sha256',
    'parse_manifest_sha256', 'locator_content_sha256', 'quote_sha256', 'citation_sha256'].forEach(key => hash(citation[key]))
  positive(citation.page_number)
  const bbox = exact(citation.bbox, ['coordinate_system', 'page_width', 'page_height', 'x0', 'y0', 'x1', 'y1'])
  if (bbox.coordinate_system !== 'normalized_0_1e6' || bbox.page_width !== 1_000_000
    || bbox.page_height !== 1_000_000) return fail()
  const x0 = integer(bbox.x0); const y0 = integer(bbox.y0); const x1 = integer(bbox.x1); const y1 = integer(bbox.y1)
  if (x0 < 0 || y0 < 0 || x1 <= x0 || y1 <= y0 || x1 > 1_000_000 || y1 > 1_000_000) return fail()
}

function parseG1(rows: readonly R[], scope: SchemaWikiScopeV1,
  current: { release_id: string, activation_epoch: number }): ParsedConceptCatalog830G2 {
  const overviewRows = rows.filter(row => row.kind === 'overview')
  const sections = rows.filter(row => row.kind === 'section')
  const fields = rows.filter(row => row.kind === 'field')
  const freeWiki = rows.filter(row => row.kind === 'free_wiki')
  if (overviewRows.length !== 1 || sections.length === 0 || fields.length === 0 || freeWiki.length !== 1
    || rows.length !== 2 + sections.length + fields.length) return fail()
  const overview = exact(overviewRows[0].payload,
    ['contract', 'entity_id', 'entity_version_id', 'ordered_section_page_ids', 'field_assertions'])
  const entityID = pathIdentity(overview.entity_id); const entityVersion = pathIdentity(overview.entity_version_id)
  if (overview.contract !== G1_CONTRACTS.overview) return fail()
  const sectionIDs = list(overview.ordered_section_page_ids, pathIdentity, true)
  if (!equalList([...sectionIDs].sort(), sections.map(row => String(row.logical_slug)).sort())) return fail()
  const overviewRefs = g1References(overview.field_assertions)
  const allSectionRefs: R[] = []
  const sectionKeys = new Set<string>()
  for (const row of sections) {
    const payload = exact(row.payload, ['contract', 'section_key', 'field_assertions'])
    const key = pathIdentity(payload.section_key)
    if (payload.contract !== G1_CONTRACTS.section || sectionKeys.has(key)) return fail()
    sectionKeys.add(key); allSectionRefs.push(...g1References(payload.field_assertions))
  }
  if (allSectionRefs.length !== fields.length
    || new Set(allSectionRefs.map(ref => String(ref.page_id))).size !== allSectionRefs.length) return fail()
  const fieldRefs = new Map<string, R>()
  let productVersion = ''; let sourceRelease = ''; let sourceCandidate = ''
  for (const row of fields) {
    const payload = exact(row.payload, ['contract', 'field_key', 'reference', 'state', 'value_snapshot',
      'display_value', 'unknown_reason', 'source_typed_reason', 'citations'])
    const fieldKey = pathIdentity(payload.field_key); const ref = g1Reference(payload.reference)
    if (payload.contract !== G1_CONTRACTS.field || ref.field_key !== fieldKey || ref.page_id !== row.logical_slug
      || fieldRefs.has(fieldKey) || !Array.isArray(payload.citations)) return fail()
    payload.citations.forEach(g1Citation)
    if (payload.state === 'unknown') {
      if (payload.value_snapshot !== null || payload.display_value !== null
        || typeof payload.unknown_reason !== 'string' || typeof payload.source_typed_reason !== 'string'
        || payload.citations.length !== 0) return fail()
    } else if (!['present', 'absent_explicitly'].includes(String(payload.state))
      || typeof payload.value_snapshot !== 'string' || payload.value_snapshot.length === 0
      || payload.display_value !== payload.value_snapshot || payload.unknown_reason !== null
      || payload.source_typed_reason !== null || payload.citations.length === 0) return fail()
    fieldRefs.set(fieldKey, ref)
    const values = [String(ref.product_version_id), String(ref.source_release_id), String(ref.source_candidate_sha256)]
    if (!productVersion) [productVersion, sourceRelease, sourceCandidate] = values
    else if (!equalList(values, [productVersion, sourceRelease, sourceCandidate])) return fail()
  }
  const expectedRefs = [...fieldRefs.values()]
  if (overviewRefs.length !== expectedRefs.length || allSectionRefs.length !== expectedRefs.length
    || expectedRefs.some(ref => !overviewRefs.some(item => sameJSON(item, ref))
      || !allSectionRefs.some(item => sameJSON(item, ref)))) return fail()
  const freePayload = exact(freeWiki[0].payload, ['contract', 'items'])
  if (freePayload.contract !== G1_CONTRACTS.free_wiki || !Array.isArray(freePayload.items)
    || freePayload.items.length !== 0 || entityVersion !== `${entityID}@${productVersion}`) return fail()
  return { mode: 'entity-g1', scope, releaseID: current.release_id,
    activationEpoch: current.activation_epoch, entityID }
}

function parseLegacy(rows: readonly R[], scope: SchemaWikiScopeV1,
  current: { release_id: string, activation_epoch: number }): ParsedConceptCatalog830G2 {
  if (!rows.length || new Set(rows.map(row => String(row.logical_slug))).size !== rows.length) return fail()
  const overviews = rows.filter(row => row.kind === 'overview')
  if (overviews.length) {
    return parseG1(rows, scope, current)
  }
  const c6Contract = 'schema-wiki-isolated-r1-member.815.v1'
  const hasC6 = rows.some(row => (row.payload as R).contract === c6Contract)
  if (hasC6) {
    const counts = { root: 0, section: 0, field: 0 }
    const fieldOrders = new Set<number>()
    let candidate = ''; let manifest = ''; let preview = ''
    const c6Keys = ['contract', 'candidate_sha256', 'c5_manifest_sha256', 'c5_preview_sha256',
      'quality_status', 'mvp_status', 'production_status', 'publishing', 'member_kind', 'body']
    if (rows.length !== 75) return fail()
    for (const row of rows) {
      const kind = String(row.kind)
      if (!(kind in counts)) return fail()
      counts[kind as keyof typeof counts]++
      const p = exact(row.payload, c6Keys); const body = record(p.body) ? p.body : fail()
      const nextCandidate = hash(p.candidate_sha256); const nextManifest = hash(p.c5_manifest_sha256)
      const nextPreview = hash(p.c5_preview_sha256)
      if (!candidate) { candidate = nextCandidate; manifest = nextManifest; preview = nextPreview }
      if (p.contract !== c6Contract || p.member_kind !== kind || nextCandidate !== candidate
        || nextManifest !== manifest || nextPreview !== preview || row.revision_id !== manifest
        || p.quality_status !== 'NOT_EVALUATED' || p.mvp_status !== 'NOT_ACCEPTED'
        || p.production_status !== 'NOT_FOR_PRODUCTION' || p.publishing !== false) return fail()
      let bodyID: string
      if (kind === 'root') bodyID = pathIdentity(body.entity_version_id)
      else if (kind === 'section') bodyID = pathIdentity(body.section_id)
      else {
        bodyID = pathIdentity(body.field_id)
        const order = positive(body.schema_order)
        if (order > 67 || fieldOrders.has(order)) return fail()
        fieldOrders.add(order)
      }
      if (row.logical_slug !== `${kind}:${bodyID}`) return fail()
      try { if (!sameJSON(JSON.parse(String(row.content)), p)) return fail() } catch { return fail() }
    }
    if (counts.root !== 1 || counts.section !== 7 || counts.field !== 67 || fieldOrders.size !== 67) return fail()
  } else if (rows.filter(row => row.kind === 'root').length !== 1
    || rows.some(row => !(String(row.kind) in SCHEMA_CONTRACTS)
      || (row.payload as R).contract !== SCHEMA_CONTRACTS[String(row.kind)])) return fail()
  return { mode: 'schema-legacy', scope, releaseID: current.release_id, activationEpoch: current.activation_epoch }
}

export async function parseConceptCatalog830G2(value: unknown, scope: SchemaWikiScopeV1,
  current: { release_id: string, activation_epoch: number }): Promise<ParsedConceptCatalog830G2> {
  if (!Array.isArray(value)) return fail()
  pathIdentity(current.release_id); positive(current.activation_epoch)
  const rows = value.map(snapshot)
  return looksG2(rows) ? parseG2(rows, scope, current) : parseLegacy(rows, scope, current)
}

function rootMember(value: unknown, scope: SchemaWikiScopeV1): ConceptDirectoryMember830G2 {
  const member = exact(value, ['kind', 'member_id', 'owner_id', 'title', 'content', 'payload'])
  if (!G2_KINDS.has(String(member.kind)) || !record(member.payload)
    || ('space_id' in member.payload && member.payload.space_id !== scope.space_id)) return fail()
  return { kind: member.kind as ConceptDirectoryMember830G2['kind'], member_id: pathIdentity(member.member_id),
    revision_id: '', member_digest: '', owner_id: conceptIdentity(member.owner_id), title: text(member.title),
    content: text(member.content), payload: member.payload }
}

async function readRootDetail(parsed: ParsedG2, expected: ConceptDirectoryMember830G2,
  transport: SchemaWikiReadTransport): Promise<{ ownerID: string }> {
  const path = buildScopedSchemaWikiPath(parsed.scope,
    `/concept-pages/${encodeURIComponent(expected.member_id)}`, { expectedScope: parsed.scope })
    + `?release_id=${encodeURIComponent(parsed.releaseID)}`
  const read = exact(unwrap(await transport.get(path)), ['contract', 'read_mode', 'release_id', 'activation_epoch',
    'candidate_hash', 'space_id', 'raw_kb_id', 'wiki_kb_id', 'member', 'related_members', 'citations',
    'definition_hash', 'aggregate_hash'])
  if (read.contract !== 'concept-page-read.830.g2.v1' || read.read_mode !== 'pinned'
    || read.release_id !== parsed.releaseID || read.activation_epoch !== parsed.activationEpoch
    || read.candidate_hash !== parsed.candidateHash || read.space_id !== parsed.scope.space_id
    || read.raw_kb_id !== parsed.scope.raw_kb_id || read.wiki_kb_id !== parsed.scope.wiki_kb_id
    || !Array.isArray(read.related_members) || !Array.isArray(read.citations) || read.citations.length !== 0
    || ![read.definition_hash, read.aggregate_hash].every(value => value === '' || HASH.test(String(value)))) return fail()
  const selected = rootMember(read.member, parsed.scope)
  const related = read.related_members.map(member => rootMember(member, parsed.scope))
  if (selected.member_id !== expected.member_id || selected.kind !== expected.kind
    || selected.title !== expected.title || selected.content !== expected.content
    || !sameJSON(selected.payload, expected.payload)) return fail()
  const refs = list(expected.payload.member_ids, pathIdentity, true)
  if (!equalList(related.map(member => member.member_id).sort(), [...refs].sort())) return fail()
  const snapshots = new Map(parsed.members.map(member => [member.member_id, member]))
  for (const item of related) {
    const frozen = snapshots.get(item.member_id)
    if (!frozen || item.kind !== frozen.kind || item.title !== frozen.title
      || item.content !== frozen.content || !sameJSON(item.payload, frozen.payload)
      || item.owner_id !== frozen.owner_id) return fail()
  }
  return { ownerID: selected.owner_id }
}

export async function loadConceptDirectory830G2(wikiKB: string,
  transport: SchemaWikiReadTransport): Promise<ConceptCatalogResult830G2> {
  pathIdentity(wikiKB)
  const scope = parseSchemaWikiScope(unwrap(await transport.get(buildSchemaWikiScopeBootstrapPath(wikiKB))))
  if (scope.wiki_kb_id !== wikiKB) return fail()
  const scoped = (suffix: string) => buildGenericReleasePath(scope, suffix)
  const rawCurrent = exact(unwrap(await transport.get(scoped('/current'))), ['release_id', 'activation_epoch'])
  const current = { release_id: pathIdentity(rawCurrent.release_id), activation_epoch: positive(rawCurrent.activation_epoch) }
  const rows = unwrap(await transport.get(scoped(`/releases/${encodeURIComponent(current.release_id)}/search`) + '?q='))
  const parsed = await parseConceptCatalog830G2(rows, scope, current)
  if (parsed.mode !== 'g2') return parsed
  const roots = [...parsed.entities.map(entity => entity.overview), ...parsed.freeWikiRoots]
  const rootReads = await Promise.all(roots.map(root => readRootDetail(parsed, root, transport)))
  const rootByID = new Map<string, ConceptDirectoryMember830G2>()
  roots.forEach((root, i) => rootByID.set(root.member_id,
    { ...root, owner_id: rootReads[i].ownerID }))
  const freeByEntity = new Map<string, ConceptDirectoryMember830G2>()
  for (let i = parsed.entities.length; i < roots.length; i++) {
    const owner = rootReads[i].ownerID
    if (!parsed.entities.some(entity => entity.entityID === owner) || freeByEntity.has(owner)) return fail()
    freeByEntity.set(owner, rootByID.get(roots[i].member_id)!)
  }
  const entities = parsed.entities.map(entity => {
    const freeWiki = freeByEntity.get(entity.entityID)
    if (!freeWiki || rootReads[parsed.entities.indexOf(entity)].ownerID !== entity.entityID) return fail()
    const owned = parsed.members.filter(member => member.owner_id === entity.entityID)
    return { ...entity, overview: rootByID.get(entity.overview.member_id)!, freeWiki,
      fieldCount: owned.filter(member => member.kind === 'field_assertion').length,
      freeItemCount: owned.filter(member => member.kind === 'free_wiki_item').length }
  })
  return { mode: 'g2', scope, releaseID: parsed.releaseID, activationEpoch: parsed.activationEpoch,
    candidateHash: parsed.candidateHash, members: parsed.members, concepts: parsed.concepts, entities }
}

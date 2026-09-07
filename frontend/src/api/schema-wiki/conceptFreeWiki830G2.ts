import { buildSchemaWikiScopeBootstrapPath, createSchemaWikiCitationPreviewTransport,
  type SchemaWikiReadTransport, type SchemaWikiPreviewTransport,
  type SchemaWikiCitationPreviewTransport } from './index'
import { parseSchemaWikiScope, type SchemaWikiScopeV1 } from '../../views/knowledge/schema-wiki/schemaWikiContract'
import { buildScopedSchemaWikiPath } from '../../views/knowledge/schema-wiki/schemaWikiNavigation'

export interface ConceptMember830G2 {
  kind: 'concept' | 'field_assertion' | 'entity_overview' | 'free_wiki' | 'free_wiki_item'
  member_id: string
  owner_id: string
  title: string
  content: string
  payload: Record<string, unknown>
}
export interface ConceptRead830G2 {
  contract: 'concept-page-read.830.g2.v1'
  read_mode: 'current' | 'pinned'
  release_id: string
  activation_epoch: number
  candidate_hash: string
  space_id: string
  raw_kb_id: string
  wiki_kb_id: string
  member: ConceptMember830G2
  related_members: ConceptMember830G2[]
  citations: { citation_id: string, page_number: number, quote: string }[]
  definition_hash: string
  aggregate_hash: string
}
export interface ConceptSession830G2 { scope: SchemaWikiScopeV1, read: ConceptRead830G2 }

const hash = /^[a-f0-9]{64}$/
const kinds = new Set(['concept', 'field_assertion', 'entity_overview', 'free_wiki', 'free_wiki_item'])
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}
function id(value: unknown): string {
  if (typeof value !== 'string' || !/^[A-Za-z0-9._:@-]+$/.test(value)
    || ['current', 'latest'].includes(value.toLowerCase())) throw new Error('G2_IDENTITY_INVALID')
  return encodeURIComponent(value)
}
function unwrap(value: unknown): unknown {
  if (!record(value) || value.success !== true || Object.keys(value).length !== 2) {
    throw new Error('G2_RESPONSE_INVALID')
  }
  return value.data
}
function member(value: unknown, scope: SchemaWikiScopeV1): ConceptMember830G2 {
  if (!record(value) || !kinds.has(String(value.kind)) || !record(value.payload)
    || typeof value.title !== 'string' || typeof value.content !== 'string') {
    throw new Error('G2_MEMBER_INVALID')
  }
  id(value.member_id); id(value.owner_id)
  const domainMember = ['concept', 'field_assertion', 'free_wiki_item'].includes(String(value.kind))
  if ((domainMember || value.payload.space_id !== undefined) && value.payload.space_id !== scope.space_id) {
    throw new Error('G2_SCOPE_DRIFT')
  }
  if (value.kind === 'concept' ? value.owner_id !== scope.space_id
    : domainMember && value.owner_id !== value.payload.entity_id) throw new Error('G2_OWNER_DRIFT')
  if (domainMember) {
    if (!Array.isArray(value.payload.evidence)
      || (value.kind !== 'field_assertion' && value.payload.evidence.length === 0)) throw new Error('G2_EVIDENCE_INVALID')
    for (const evidence of value.payload.evidence) {
      if (!record(evidence) || evidence.space_id !== scope.space_id || evidence.raw_kb_id !== scope.raw_kb_id) {
        throw new Error('G2_EVIDENCE_SCOPE_DRIFT')
      }
    }
  }
  if (value.kind === 'field_assertion') {
    const p = value.payload
    if (!['present', 'absent_explicitly', 'unknown'].includes(String(p.state))
      || p.attempted !== true || typeof p.entity_version !== 'string' || p.entity_version === ''
      || !Array.isArray(p.evidence) || (p.state === 'unknown'
        ? p.value !== null || p.evidence.length !== 0 || typeof p.unknown_reason !== 'string'
        : typeof p.value !== 'string' || p.value.length === 0 || p.evidence.length === 0)) {
      throw new Error('G2_FIELD_INVALID')
    }
  }
  return value as unknown as ConceptMember830G2
}

export async function readConceptPage830G2(wikiKB: string, memberID: string,
  releaseID: string | undefined, transport: SchemaWikiReadTransport): Promise<ConceptSession830G2> {
  id(wikiKB); const target = id(memberID)
  const query = releaseID === undefined ? '' : `?release_id=${id(releaseID)}`
  const scope = parseSchemaWikiScope(unwrap(await transport.get(buildSchemaWikiScopeBootstrapPath(wikiKB))))
  if (scope.wiki_kb_id !== wikiKB) throw new Error('G2_SCOPE_DRIFT')
  const raw = unwrap(await transport.get(buildScopedSchemaWikiPath(scope,
    `/concept-pages/${target}`, { expectedScope: scope }) + query))
  if (!record(raw) || raw.contract !== 'concept-page-read.830.g2.v1'
    || raw.read_mode !== (releaseID === undefined ? 'current' : 'pinned')
    || (releaseID !== undefined && raw.release_id !== releaseID)
    || raw.space_id !== scope.space_id || raw.raw_kb_id !== scope.raw_kb_id
    || raw.wiki_kb_id !== scope.wiki_kb_id || !Number.isSafeInteger(raw.activation_epoch)
    || Number(raw.activation_epoch) <= 0 || !hash.test(String(raw.candidate_hash))
    || !Array.isArray(raw.related_members) || !Array.isArray(raw.citations)
    || ![raw.definition_hash, raw.aggregate_hash].every(v => v === '' || hash.test(String(v)))) {
    throw new Error('G2_RESPONSE_INVALID')
  }
  id(raw.release_id)
  const selected = member(raw.member, scope)
  if (selected.member_id !== memberID) throw new Error('G2_MEMBER_DRIFT')
  const related = raw.related_members.map(m => member(m, scope))
  if (selected.kind === 'concept' && related.some(m => m.kind !== 'field_assertion'
    || !Array.isArray(m.payload.concept_ids) || !m.payload.concept_ids.includes(selected.member_id))) {
    throw new Error('G2_CONCEPT_RELATION_DRIFT')
  }
  if (selected.kind !== 'concept') {
    const group = ['entity_overview', 'free_wiki'].includes(selected.kind)
    const links = group ? selected.payload.member_ids : selected.payload.concept_ids
    if (!Array.isArray(links) || !links.every(v => typeof v === 'string')
      || new Set(links).size !== links.length || links.length !== related.length
      || related.some(m => !links.includes(m.member_id) || (group
        ? m.owner_id !== selected.owner_id || !(selected.kind === 'free_wiki'
          ? m.kind === 'free_wiki_item' : ['field_assertion', 'free_wiki_item'].includes(m.kind))
        : m.kind !== 'concept'))) throw new Error('G2_NAVIGATION_DRIFT')
  }
  if (new Set(related.map(m => m.member_id)).size !== related.length) throw new Error('G2_DUPLICATE_MEMBER')
  for (const citation of raw.citations) {
    if (!record(citation) || !/^citation-[a-f0-9]{24}$/.test(String(citation.citation_id))
      || !Number.isSafeInteger(citation.page_number) || Number(citation.page_number) <= 0
      || typeof citation.quote !== 'string' || citation.quote === '') throw new Error('G2_CITATION_INVALID')
  }
  return { scope, read: { ...raw, member: selected, related_members: related } as unknown as ConceptRead830G2 }
}

export function conceptCitationTransport830G2(session: ConceptSession830G2,
  io: SchemaWikiReadTransport & SchemaWikiPreviewTransport): SchemaWikiCitationPreviewTransport {
  const { scope, read } = session
  const existing = createSchemaWikiCitationPreviewTransport(scope, io)
  return {
    async getAuthority(request) {
      if (request.release_id !== read.release_id || request.activation_epoch !== read.activation_epoch
        || request.field_id !== read.member.member_id
        || !read.citations.some(c => c.citation_id === request.citation_id)) {
        throw new Error('G2_CITATION_BINDING_MISMATCH')
      }
      return unwrap(await io.get(buildScopedSchemaWikiPath(scope,
        `/concept-pages/${id(read.member.member_id)}/citations/${id(request.citation_id)}/preview`,
        { expectedScope: scope }) + `?release_id=${id(read.release_id)}`))
    },
    getBytesByToken: token => existing.getBytesByToken(token),
  }
}

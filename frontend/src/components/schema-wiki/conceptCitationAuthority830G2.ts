import type { ConceptSession830G2 } from '@/api/schema-wiki/conceptFreeWiki830G2'

const CONTRACT = 'concept-citation-content-authority.830.g2.v1'
const BLOCK_CONTRACT = 'concept-citation-content-authority.830.g3.v1'
const SOURCE_KEYS = ['tenant_id', 'space_id', 'raw_kb_id', 'knowledge_id', 'parse_attempt',
  'revision_id', 'source_hash', 'parse_hash', 'parser_identity']
const HASH = /^[a-f0-9]{64}$/
const fail = (): never => { throw new Error('G2_CITATION_AUTHORITY_INVALID') }
function object(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v)
}
function closed(v: unknown, keys: string[]): Record<string, unknown> {
  if (!object(v) || Object.keys(v).sort().join('|') !== [...keys].sort().join('|')) return fail()
  return v
}
function positive(v: unknown): v is number { return Number.isSafeInteger(v) && Number(v) > 0 }
function nonnegative(v: unknown): v is number { return Number.isSafeInteger(v) && Number(v) >= 0 }
function canonical(v: unknown): string {
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']'
  if (object(v)) return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}'
  return JSON.stringify(v)
}
export async function conceptSHA256830G2(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', Uint8Array.from(bytes).buffer)
  return Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')
}
const textSHA = (s: string) => conceptSHA256830G2(new TextEncoder().encode(s))
export interface ConceptCitationAuthority830G2 {
  readonly opaque_token: string
  readonly page_number: number
  readonly block_id: string
  readonly source: Readonly<Record<string, string | number>>
  readonly revision_source: { readonly binding_digest: string; readonly file_sha256: string; readonly page_count: number }
  readonly bbox: { readonly x0: number; readonly y0: number; readonly x1: number; readonly y1: number }
  readonly source_locator?: {
    readonly contract: 'concept-source-block-locator.830.g3.v1'
    readonly source_block_sha256: string
    readonly source_page_number: number
    readonly start: number
    readonly end: number
    readonly block_global_start: number
    readonly global_start: number
    readonly global_end: number
    readonly actual_page_number: number
  }
}
export async function parseConceptCitationAuthority830G2(value: unknown, session: ConceptSession830G2,
  citationID: string): Promise<ConceptCitationAuthority830G2> {
  const blockLocated = object(value) && value.contract === BLOCK_CONTRACT
  const a = closed(value, ['contract', 'token_key_id', 'release_id', 'activation_epoch', 'candidate_hash',
    'member_id', 'citation_id', 'scope', 'source', 'revision_source', 'block_id', 'page_number', 'quote_hash',
    'bbox', 'expires_at_unix', 'authority_digest', 'opaque_token', ...(blockLocated ? ['source_locator'] : [])])
  const scope = closed(a.scope, ['tenant_id', 'space_id', 'raw_kb_id', 'wiki_kb_id'])
  const source = closed(a.source, SOURCE_KEYS)
  const revision = closed(a.revision_source, ['binding_digest', 'file_sha256', 'page_count'])
  const bbox = closed(a.bbox, ['coordinate_space', 'x0', 'y0', 'x1', 'y1'])
  const locator = blockLocated ? closed(a.source_locator, ['contract', 'source_block_sha256',
    'source_page_number', 'start', 'end', 'block_global_start', 'global_start', 'global_end',
    'actual_page_number']) : undefined
  const { read } = session
  const citation = read.citations.find(c => c.citation_id === citationID)
  if ((!blockLocated && a.contract !== CONTRACT) || a.release_id !== read.release_id || a.activation_epoch !== read.activation_epoch
    || a.candidate_hash !== read.candidate_hash || a.member_id !== read.member.member_id
    || a.citation_id !== citationID || !citation || a.page_number !== citation.page_number
    || !positive(scope.tenant_id) || !positive(source.parse_attempt)
    || source.tenant_id !== scope.tenant_id || source.space_id !== scope.space_id || source.raw_kb_id !== scope.raw_kb_id
    || scope.space_id !== session.scope.space_id || scope.raw_kb_id !== session.scope.raw_kb_id
    || scope.wiki_kb_id !== session.scope.wiki_kb_id || !positive(a.page_number) || !positive(revision.page_count)
    || a.page_number > revision.page_count || revision.file_sha256 !== source.source_hash
    || ![source.revision_id, source.source_hash, source.parse_hash, source.parser_identity,
      revision.binding_digest, a.quote_hash, a.authority_digest].every(v => typeof v === 'string' && HASH.test(v))
    || typeof a.token_key_id !== 'string' || a.token_key_id.length === 0
    || typeof a.opaque_token !== 'string' || !/^[A-Za-z0-9_.-]+$/.test(a.opaque_token)
    || !positive(a.expires_at_unix) || a.expires_at_unix <= Date.now() / 1000
    || a.expires_at_unix > Date.now() / 1000 + 330
    || bbox.coordinate_space !== 'normalized_0_1e6_top_left'
    || ![bbox.x0, bbox.y0, bbox.x1, bbox.y1].every(v => Number.isSafeInteger(v) && Number(v) >= 0 && Number(v) <= 1_000_000)
    || Number(bbox.x0) >= Number(bbox.x1) || Number(bbox.y0) >= Number(bbox.y1)) return fail()
  if (locator && (locator.contract !== 'concept-source-block-locator.830.g3.v1'
    || typeof locator.source_block_sha256 !== 'string' || !HASH.test(locator.source_block_sha256)
    || locator.source_page_number !== a.page_number || !positive(locator.actual_page_number)
    || locator.actual_page_number > Number(revision.page_count)
    || !nonnegative(locator.start) || !positive(locator.end) || locator.end <= locator.start
    || !nonnegative(locator.block_global_start) || !nonnegative(locator.global_start)
    || !positive(locator.global_end)
    || locator.global_start !== locator.block_global_start + locator.start
    || locator.global_end !== locator.block_global_start + locator.end
    || locator.end - locator.start !== Array.from(citation.quote).length)) return fail()
  if (a.quote_hash !== await textSHA(citation.quote)) return fail()
  const evidence = read.member.payload.evidence
  if (!Array.isArray(evidence)) return fail()
  let matching = 0
  for (const e of evidence) {
    if (!object(e) || e.quote !== citation.quote || e.page_number !== a.page_number || e.block_id !== a.block_id
      || e.quote_hash !== a.quote_hash || !SOURCE_KEYS.every(k => e[k] === source[k])) continue
    if (locator && (e.offset_unit !== 'UNICODE_CODE_POINT'
      || e.start !== locator.start || e.end !== locator.end)) continue
    const derived = 'citation-' + (await textSHA(JSON.stringify([read.candidate_hash, read.member.member_id,
      e.revision_id, e.block_id, e.page_number, e.start, e.end, e.quote_hash]))).slice(0, 24)
    if (derived === citationID) matching++
  }
  if (matching !== 1) return fail()
  const { authority_digest, opaque_token: _token, ...unsigned } = a
  if (authority_digest !== await textSHA(String(a.contract) + '\n' + canonical(unsigned))) return fail()
  return structuredClone(a) as unknown as ConceptCitationAuthority830G2
}

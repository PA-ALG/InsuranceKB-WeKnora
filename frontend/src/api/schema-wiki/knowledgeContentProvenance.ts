import { conceptCitationID, conceptSHA256830G2 } from './conceptCitationIdentity'
export interface KnowledgeContentSegment {
  text: string
  origin: 'SOURCE_SUPPORTED' | 'MODEL_GENERATED'
  evidence_indexes: number[]
}
export interface KnowledgeCitation {
  citation_id: string
  page_number: number
  quote: string
  evidence_index?: number
}
type Member = { kind: string, member_id: string, content: string, payload: Record<string, unknown> }
const invalid = (): never => { throw new Error('KNOWLEDGE_CONTENT_PROVENANCE_INVALID') }
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
function exact(value: unknown, keys: string[]): Record<string, unknown> {
  if (!record(value) || Object.keys(value).sort().join('|') !== keys.sort().join('|')) return invalid()
  return value
}
export function knowledgeContentSegments(member: Member): KnowledgeContentSegment[] | undefined {
  const p = member.payload
  if (!Object.hasOwn(p, 'content_provenance')) return undefined
  if (!['concept', 'free_wiki_item'].includes(member.kind)) return invalid()
  const provenance = exact(p.content_provenance, ['contract', 'segments'])
  if (provenance.contract !== 'knowledge-content-provenance.830.v1' || !Array.isArray(provenance.segments)
    || provenance.segments.length === 0 || !Array.isArray(p.evidence)) return invalid()
  if (typeof p.body !== 'string' || p.body.length === 0) return invalid()
  let expectedContent = p.body
  if (member.kind === 'free_wiki_item') {
    if (!Array.isArray(p.conditions) || !Array.isArray(p.exceptions)
      || ![...p.conditions, ...p.exceptions].every(v => typeof v === 'string') || typeof p.valid_time !== 'string') return invalid()
    expectedContent = [p.body, ...p.conditions.map(v => `条件：${v}`), ...p.exceptions.map(v => `例外：${v}`),
      ...(p.valid_time ? [`有效期：${p.valid_time}`] : [])].join('\n')
  }
  if (member.content !== expectedContent) return invalid()
  const evidence = p.evidence
  const identities = evidence.map(e => {
    if (!record(e) || !['revision_id', 'block_id', 'quote', 'quote_hash'].every(k => typeof e[k] === 'string' && e[k] !== '')
      || ![e.page_number, e.start, e.end].every(Number.isSafeInteger)
      || Number(e.page_number) <= 0 || Number(e.start) < 0 || Number(e.end) <= Number(e.start)
      || e.offset_unit !== 'UNICODE_CODE_POINT' || Array.from(String(e.quote)).length !== Number(e.end) - Number(e.start)
      || !/^[a-f0-9]{64}$/.test(String(e.quote_hash))) return invalid()
    return JSON.stringify([e.revision_id, e.block_id, e.page_number, e.start, e.end, e.quote_hash])
  })
  if (new Set(identities).size !== evidence.length) return invalid()
  const used = new Set<number>()
  const segments = provenance.segments.map(raw => {
    const row = exact(raw, ['text', 'origin', 'evidence_indexes'])
    if (typeof row.text !== 'string' || row.text.length === 0 || !Array.isArray(row.evidence_indexes)
      || !['SOURCE_SUPPORTED', 'MODEL_GENERATED'].includes(String(row.origin))) return invalid()
    const indexes = row.evidence_indexes
    if ((row.origin === 'SOURCE_SUPPORTED') !== (indexes.length > 0)
      || indexes.some((index, i) => !Number.isSafeInteger(index) || index < 0 || index >= evidence.length
        || (i > 0 && index <= indexes[i - 1]))) return invalid()
    indexes.forEach(index => used.add(index))
    if (member.kind === 'concept' && row.origin === 'MODEL_GENERATED' && p.origin !== 'MODEL_COMPILE') return invalid()
    return row as unknown as KnowledgeContentSegment
  })
  if (segments.map(s => s.text).join('') !== member.content || used.size !== evidence.length) return invalid()
  return segments
}
export async function validateKnowledgeCitations(member: Member, candidate: string, citations: KnowledgeCitation[]): Promise<void> {
  if (!knowledgeContentSegments(member)) {
    if (citations.some(c => Object.hasOwn(c, 'evidence_index'))) return invalid()
    return
  }
  const evidence = member.payload.evidence as Record<string, unknown>[]
  if (citations.length !== evidence.length || new Set(citations.map(c => c.evidence_index)).size !== evidence.length) return invalid()
  await Promise.all(citations.map(async citation => {
    const index = citation.evidence_index
    if (index === undefined || !Number.isSafeInteger(index) || index < 0 || index >= evidence.length) return invalid()
    const proof = evidence[index]!
    if (citation.page_number !== proof.page_number || citation.quote !== proof.quote
      || proof.quote_hash !== await conceptSHA256830G2(new TextEncoder().encode(citation.quote))
      || citation.citation_id !== await conceptCitationID(candidate, member.member_id, proof)) return invalid()
  }))
}

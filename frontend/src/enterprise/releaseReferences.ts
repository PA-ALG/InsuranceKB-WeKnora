import type { KnowledgeReferenceLike } from '../utils/referenceSources'

export const publishedKnowledgeTools = [
  'knowledge_find_entity', 'knowledge_get_fields', 'knowledge_search_fields', 'knowledge_get_concept',
] as const
export const isPublishedKnowledgeTool = (name: unknown): boolean =>
  typeof name === 'string' && publishedKnowledgeTools.some(tool => tool === name)

type Reference = {
  id?: string; chunkId?: string; chunk_ids?: string[]; chunkIds?: string[]
  knowledge_title?: string; title?: string; content?: string
  metadata?: Record<string, unknown> | null
}
export type ReleaseCitationTarget = { spaceId: string; releaseId: string; member: string; evidence: number }
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : ''
const identity = (reference: Reference) => reference.id || reference.chunkId || ''

/** Detection only blocks fallback; the complete platform tuple still needs validation. */
export function isReleaseReference(reference: Reference): boolean {
  return reference.metadata?.source_tier === 'release' || identity(reference).startsWith('release:')
}

export function releaseCitationTarget(reference: Reference): ReleaseCitationTarget | null {
  const metadata = reference.metadata
  if (metadata?.source_tier !== 'release') return null
  const spaceId = text(metadata.space_id), releaseId = text(metadata.release_id), member = text(metadata.logical_slug)
  const raw = metadata.evidence_index
  const evidence = typeof raw === 'number' ? raw : typeof raw === 'string' && /^(0|[1-9]\d*)$/.test(raw) ? Number(raw) : NaN
  if (!spaceId || !releaseId || releaseId.toLowerCase() === 'active' || !member
    || !Number.isSafeInteger(evidence) || evidence < 0
    || identity(reference) !== `release:${releaseId}:${member}`) return null
  return { spaceId, releaseId, member, evidence }
}

export function releaseCitationPreview(chunkId: string, references: readonly Reference[] | null | undefined, failure: string) {
  const matches = (references || []).filter(reference => identity(reference) === chunkId
    || reference.chunk_ids?.includes(chunkId) || reference.chunkIds?.includes(chunkId))
  if (!chunkId.startsWith('release:') && !matches.some(isReleaseReference)) return null
  const targets = matches.map(releaseCitationTarget)
  if (!matches.length || targets.some(target => !target)
    || new Set(targets.map(target => JSON.stringify(target))).size !== 1) {
    return { title: '', content: '', error: failure }
  }
  return { title: matches[0]!.knowledge_title || matches[0]!.title || '', content: matches[0]!.content || '' }
}

/** Tool events carry durable metadata; model text is never an identity source. */
export function publishedKnowledgeReferences(data: unknown): KnowledgeReferenceLike[] {
  if (!data || typeof data !== 'object') return []
  const rows = (data as { results?: unknown }).results
  if (!Array.isArray(rows)) return []
  return rows.flatMap(row => {
    if (!row || typeof row !== 'object') return []
    const reference: KnowledgeReferenceLike = {
      id: text(row.chunk_id), knowledge_title: text(row.knowledge_title), content: text(row.content), metadata: row.metadata,
    }
    return releaseCitationTarget(reference) ? [reference] : []
  })
}

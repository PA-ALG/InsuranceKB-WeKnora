export type SourceTier = 'raw_text' | 'release' | 'wiki_page' | 'method' | 'sale_status'

function referenceMetadata(reference: unknown): Record<string, unknown> | null {
  if (!reference || typeof reference !== 'object') return null
  const metadata = (reference as { metadata?: unknown }).metadata
  return metadata && typeof metadata === 'object' && !Array.isArray(metadata)
    ? metadata as Record<string, unknown>
    : null
}

/** Only the platform's reference metadata can identify a reviewed source. */
export function sourceTier(reference: unknown): SourceTier | null {
  const metadata = referenceMetadata(reference)
  const tier = metadata?.source_tier
  // SK-3: a release reference of method knowledge is training material, not a reviewed fact.
  if (tier === 'release' && metadata?.knowledge_class === 'method') return 'method'
  // PV-5: a sale status is computed from the product's registered sale period, not quoted from a material.
  if (tier === 'release' && metadata?.knowledge_class === 'sale_status') return 'sale_status'
  return tier === 'raw_text' || tier === 'release' || tier === 'wiki_page' ? tier : null
}

export function sourceTierLabel(tier: SourceTier | null | undefined, t: (key: string) => string): string {
  if (tier === 'raw_text') return t('chat.sourceTierRawText')
  if (tier === 'release') return t('chat.sourceTierRelease')
  if (tier === 'wiki_page') return t('chat.sourceTierWikiPage')
  if (tier === 'method') return t('chat.sourceTierMethod')
  if (tier === 'sale_status') return t('chat.sourceTierSaleStatus')
  return ''
}

/** Keep ordinary keys stable while separating provenance, including future tiers. */
export function referenceSourceKey(reference: unknown): string {
  const metadata = referenceMetadata(reference)
  const tier = typeof metadata?.source_tier === 'string' ? metadata.source_tier : ''
  const release = typeof metadata?.release_id === 'string' ? metadata.release_id : ''
  const provenance = tier === 'release' || tier === 'wiki_page'
    ? [tier, release, metadata?.space_id, metadata?.logical_slug, metadata?.evidence_index]
    : [tier, release]
  return tier || release ? `:source:${JSON.stringify(provenance)}` : ''
}

type SourceReference = {
  id?: string
  chunk_ids?: string[]
  chunk_type?: string
  metadata?: unknown
}

/** Ambiguous chunk identities cannot establish which source the model cited. */
export function sourceTierForChunk(chunkId: string, references?: readonly SourceReference[] | null): SourceTier | null {
  const matches = (references || []).filter(reference => reference && reference.chunk_type !== 'web_search'
    && (reference.id === chunkId || reference.chunk_ids?.includes(chunkId)))
  if (!matches.length || new Set(matches.map(referenceSourceKey)).size !== 1) return null
  return sourceTier(matches[0])
}

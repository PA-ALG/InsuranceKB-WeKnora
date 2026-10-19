export type SourceTier = 'raw_text' | 'release'

function referenceMetadata(reference: unknown): Record<string, unknown> | null {
  if (!reference || typeof reference !== 'object') return null
  const metadata = (reference as { metadata?: unknown }).metadata
  return metadata && typeof metadata === 'object' && !Array.isArray(metadata)
    ? metadata as Record<string, unknown>
    : null
}

/** Only the platform's reference metadata can identify a reviewed source. */
export function sourceTier(reference: unknown): SourceTier | null {
  const tier = referenceMetadata(reference)?.source_tier
  return tier === 'raw_text' || tier === 'release' ? tier : null
}

export function sourceTierLabel(tier: SourceTier | null | undefined, t: (key: string) => string): string {
  if (tier === 'raw_text') return t('chat.sourceTierRawText')
  if (tier === 'release') return t('chat.sourceTierRelease')
  return ''
}

/** Keep ordinary keys stable while separating provenance, including future tiers. */
export function referenceSourceKey(reference: unknown): string {
  const metadata = referenceMetadata(reference)
  const tier = typeof metadata?.source_tier === 'string' ? metadata.source_tier : ''
  const release = typeof metadata?.release_id === 'string' ? metadata.release_id : ''
  return tier || release ? `:source:${JSON.stringify([tier, release])}` : ''
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

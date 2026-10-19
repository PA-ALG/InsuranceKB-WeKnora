import type { KnowledgeReferenceLike } from '@/utils/referenceSources'

/** Offline fixtures for the real reference list, drawer and citation popover. */
export const chatSourceReferences = (): KnowledgeReferenceLike[] => [
  { id: 'raw-a', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'raw first', metadata: { source_tier: 'raw_text', release_id: 'r1' } },
  { id: 'raw-b', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'raw second', metadata: { source_tier: 'raw_text', release_id: 'r1' } },
  { id: 'raw-old', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'old raw', metadata: { source_tier: 'raw_text', release_id: 'r0' } },
  { id: 'published', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'reviewed', metadata: { source_tier: 'release', release_id: 'r1' } },
  { id: 'ordinary', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'ordinary' },
  { id: 'web', chunk_type: 'web_search', knowledge_title: 'Web', content: 'web', metadata: { url: 'https://example.com' } },
]

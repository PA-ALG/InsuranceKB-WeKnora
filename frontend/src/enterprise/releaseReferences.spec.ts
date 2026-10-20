import { describe, expect, it } from 'vitest'
import { resolveCitationChunkId } from '@/utils/citationMarkdown'
import { buildReferenceList, resolveReferenceHighlightKey } from '@/utils/referenceSources'
import { releaseCitationTarget, releaseCitationPreview, publishedKnowledgeReferences } from './releaseReferences'

const reference = (space = 'space-a', release = 'old-release', slug = 'item/field') => ({
  id: `release:${release}:${slug}`, knowledge_title: 'Product · Field', content: '20 days',
  metadata: { source_tier: 'release', space_id: space, release_id: release, logical_slug: slug, evidence_index: '0' },
})

describe('published knowledge references', () => {
  it('uses the exact server tuple and never invents an evidence index', () => {
    expect(releaseCitationTarget(reference())).toEqual({ spaceId: 'space-a', releaseId: 'old-release', member: 'item/field', evidence: 0 })
    for (const evidence_index of [undefined, '', '-1', '1.5', '0x1', '0junk', NaN]) {
      expect(releaseCitationTarget({ ...reference(), metadata: { ...reference().metadata, evidence_index } })).toBeNull()
    }
    expect(releaseCitationTarget({ ...reference(), id: 'release:other:item/field' })).toBeNull()
    expect(releaseCitationTarget(reference('space-a', 'active'))).toBeNull()
  })
  it('keeps same-named claims in different spaces, releases and slugs separate', () => {
    expect(buildReferenceList([reference(), reference('space-b'), reference('space-a', 'new-release'), reference('space-a', 'old-release', 'item/other')])).toHaveLength(4)
    expect(releaseCitationPreview(reference().id, [reference(), reference('space-b')], 'missing')?.error).toBe('missing')
    expect(resolveReferenceHighlightKey([reference(), reference('space-b')], { chunkId: reference().id })).toBeNull()
  })
  it('previews only trusted exact references and blocks release-shaped missing references', () => {
    expect(releaseCitationPreview(reference().id, [reference()], 'missing')).toMatchObject({ title: 'Product · Field', content: '20 days' })
    expect(releaseCitationPreview(reference().id, [], 'missing')?.error).toBe('missing')
    expect(releaseCitationPreview('ordinary', [], 'missing')).toBeNull()
    expect(resolveCitationChunkId('release:missing:item/field', { doc: 'Product · Field' }, [reference()])).toBe('release:missing:item/field')
    expect(resolveCitationChunkId('1', { doc: 'Product · Field' }, [reference()])).toBe('1')
  })
  it('reconstructs persisted tool data without accepting unproven rows', () => {
    const r = reference()
    expect(publishedKnowledgeReferences({ results: [{ chunk_id: r.id, knowledge_title: r.knowledge_title, content: r.content, metadata: r.metadata }] })).toEqual([r])
    expect(publishedKnowledgeReferences({ results: [{ chunk_id: 'ordinary', content: 'no metadata' }] })).toEqual([])
  })
})

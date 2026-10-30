// S6e acceptance (protected, written by Claude): a native Wiki page cited in chat is a third,
// model-written source, pinned like published fields; a tier that disagrees with its member is
// refused (Spec docs/design/slices/S6e-问答读取延伸阅读页面.md §3).
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import { isPublishedKnowledgeTool, isReleaseReference, publishedKnowledgeReferences, releaseCitationTarget } from './releaseReferences'
import { referenceSourceKey, sourceTier, sourceTierLabel } from './sourceTier'

const { t } = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } }).global

function row(tier: string, member: string, evidence = '0') {
  return {
    id: `release:rel-9:${member}`, knowledge_title: '甲医疗 · 等待期', content: '模型整理（未逐条审核）：等待期',
    metadata: { source_tier: tier, space_id: 'demo', release_id: 'rel-9', logical_slug: member, evidence_index: evidence },
  }
}

describe('native Wiki pages as a chat source', () => {
  it('is its own tier with its own label', () => {
    expect(sourceTier(row('wiki_page', 'wiki/M1/concept/deng-dai-qi'))).toBe('wiki_page')
    expect(sourceTierLabel('wiki_page', t)).toBe('模型整理（未逐条审核）')
    expect(sourceTierLabel('release', t)).toBe('已发布知识（审核过）')
  })

  it('opens the pinned page member, and refuses a tier that disagrees with the member', () => {
    expect(releaseCitationTarget(row('wiki_page', 'wiki/M1/concept/deng-dai-qi', '2')))
      .toEqual({ spaceId: 'demo', releaseId: 'rel-9', member: 'wiki/M1/concept/deng-dai-qi', evidence: 2 })
    expect(releaseCitationTarget(row('wiki_page', 'M1/waiting_period'))).toBeNull()
    expect(releaseCitationTarget(row('release', 'wiki/M1/concept/deng-dai-qi'))).toBeNull()
    expect(releaseCitationTarget(row('release', 'M1/waiting_period'))).not.toBeNull()
    expect(isReleaseReference(row('wiki_page', 'wiki/M1/concept/deng-dai-qi'))).toBe(true)
  })

  it('keeps page and field citations apart and reads page rows from the tool', () => {
    expect(referenceSourceKey(row('wiki_page', 'wiki/M1/concept/deng-dai-qi')))
      .not.toBe(referenceSourceKey(row('release', 'wiki/M1/concept/deng-dai-qi')))
    expect(referenceSourceKey(row('wiki_page', 'wiki/M1/concept/deng-dai-qi', '0')))
      .not.toBe(referenceSourceKey(row('wiki_page', 'wiki/M1/concept/deng-dai-qi', '1')))
    const page = row('wiki_page', 'wiki/M1/concept/deng-dai-qi')
    const refs = publishedKnowledgeReferences({ results: [
      { chunk_id: page.id, knowledge_title: page.knowledge_title, content: page.content, metadata: page.metadata },
      { chunk_id: 'release:rel-9:M1/waiting_period', metadata: { ...page.metadata, logical_slug: 'M1/waiting_period' } },
    ] })
    expect(refs.map(ref => ref.id)).toEqual(['release:rel-9:wiki/M1/concept/deng-dai-qi'])
    expect(isPublishedKnowledgeTool('knowledge_search_pages')).toBe(true)
  })
})

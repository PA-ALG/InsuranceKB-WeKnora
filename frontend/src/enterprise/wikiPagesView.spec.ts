// S6d acceptance (protected, written by Claude): a product's native Wiki pages in one release
// (Spec docs/design/slices/S6d-延伸阅读页面.md §2). Synthetic data only.
import { describe, expect, it } from 'vitest'
import { wikiRelease } from './__tests__/wikiFixtures'
import { wikiPages, wikiPageView } from './wikiPagesView'

describe('wiki pages of one product', () => {
  it('lists only this product\'s Space-visible pages, concepts first, each by title', () => {
    expect(wikiPages(wikiRelease(), 'M1')).toEqual([
      { key: 'concept/deng-dai-qi', pageType: 'concept', title: '等待期', slug: 'wiki/M1/concept/deng-dai-qi' },
      { key: 'concept/kuan-xian-qi', pageType: 'concept', title: '宽限期', slug: 'wiki/M1/concept/kuan-xian-qi' },
      { key: 'entity/jia-yi-liao', pageType: 'entity', title: '甲医疗', slug: 'wiki/M1/entity/jia-yi-liao' },
    ]) // titles by localeCompare('zh'): 等(deng) before 宽(kuan)
    expect(wikiPages(wikiRelease(), 'C1')).toEqual([])
  })

  it('reads one page with its evidence numbered in order', () => {
    const page = wikiPageView(wikiRelease(), 'M1', 'concept/deng-dai-qi')!
    expect(page.title).toBe('等待期')
    expect(page.pageType).toBe('concept')
    expect(page.summary).toBe('等待期的说明。')
    expect(page.slug).toBe('wiki/M1/concept/deng-dai-qi')
    expect(page.content).toContain('[[wiki/M1/concept/kuan-xian-qi|宽限期规则]]')
    expect(page.evidence).toEqual([
      { index: 0, quote: '等待期为90日。', page: 3 },
      { index: 1, quote: '意外无等待期。', page: 5 },
    ])
  })

  it('has no page outside the product, the release or the Space scope', () => {
    expect(wikiPageView(wikiRelease(), 'M1', 'concept/missing')).toBeNull()
    expect(wikiPageView(wikiRelease(), 'M1', 'concept/hidden')).toBeNull()
    expect(wikiPageView(wikiRelease(), 'M1', 'concept/qi-ta')).toBeNull()
  })
})

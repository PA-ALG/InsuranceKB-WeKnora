// @vitest-environment happy-dom
// S6d-2 acceptance (protected, written by Claude): on a further-reading page the navigation opens
// that product's "延伸阅读" group and marks the current page; elsewhere the group stays collapsed
// (Spec docs/design/slices/S6d-2-延伸阅读与知识库选择体验.md §1).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseNavigation from './EnterpriseNavigation.vue'
import EnterpriseWikiPage from './EnterpriseWikiPage.vue'
import { readRelease } from './enterpriseApi'
import { wikiRelease } from './__tests__/wikiFixtures'

async function nav(props: Record<string, string>) {
  const view = mount(EnterpriseNavigation, {
    props: { release: wikiRelease(), spaceId: 'demo', ...props },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub } },
  })
  await flushPromises()
  return view
}

function current(view: Awaited<ReturnType<typeof nav>>) {
  return view.get('[data-nav-wiki]').findAll('a').filter(link => link.attributes('aria-current') === 'page').map(link => link.text())
}

describe('further reading in the navigation on a page of it', () => {
  it('opens the group and marks the page being read', async () => {
    const view = await nav({ entityId: 'M1', wikiPageKey: 'concept/kuan-xian-qi' })
    expect(view.get('[data-nav-wiki]').attributes('open')).toBeDefined()
    expect(current(view)).toEqual(['宽限期'])
  })

  it('stays collapsed with nothing marked on the product page', async () => {
    const view = await nav({ entityId: 'M1' })
    expect(view.get('[data-nav-wiki]').attributes('open')).toBeUndefined()
    expect(current(view)).toEqual([])
  })
})

describe('a further-reading page', () => {
  it('tells the navigation which page is being read', async () => {
    vi.mocked(readRelease).mockResolvedValue(wikiRelease())
    const blank = { template: '<div />' }
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/', component: blank },
      { name: 'enterpriseWikiPage', path: '/spaces/:spaceId/wiki/:entityId/:pageType/:pageSlug', component: blank },
      { name: 'enterpriseEntity', path: '/spaces/:spaceId/entities/:entityId', component: blank },
      { name: 'enterpriseSpace', path: '/spaces/:spaceId', component: blank },
    ] })
    await router.push('/')
    const view = mount(EnterpriseWikiPage, {
      props: { spaceId: 'demo', entityId: 'M1', pageType: 'concept', pageSlug: 'deng-dai-qi', releaseId: 'rel-9' },
      global: {
        plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
        stubs: { RouterLink: RouterLinkStub, CitationPanel: true, EnterpriseNavigation: true },
      },
    })
    await flushPromises()
    expect(view.getComponent(EnterpriseNavigation).props()).toMatchObject({ entityId: 'M1', wikiPageKey: 'concept/deng-dai-qi' })
  })
})

// @vitest-environment happy-dom
// S6d acceptance (protected, written by Claude): a native Wiki page read from one release, labelled
// model-compiled, with sanitized content, in-release page links and pinned sources
// (Spec docs/design/slices/S6d-延伸阅读页面.md §1, §3).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import EnterpriseWikiPage from './EnterpriseWikiPage.vue'
import { EnterpriseError, readRelease } from './enterpriseApi'
import { wikiRelease } from './__tests__/wikiFixtures'

const blank = { template: '<div />' }

async function page(props: Record<string, string> = { pageType: 'concept', pageSlug: 'deng-dai-qi' }) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { name: 'enterpriseWikiPage', path: '/spaces/:spaceId/wiki/:entityId/:pageType/:pageSlug', component: blank },
    { name: 'enterpriseEntity', path: '/spaces/:spaceId/entities/:entityId', component: blank },
    { name: 'enterpriseSpace', path: '/spaces/:spaceId', component: blank },
  ] })
  await router.push('/spaces/demo')
  await router.isReady()
  const view = mount(EnterpriseWikiPage, {
    props: { spaceId: 'demo', entityId: 'M1', releaseId: 'rel-9', ...props },
    attachTo: document.body,
    global: {
      plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub, CitationPanel: true },
    },
  })
  await flushPromises()
  return { view, router }
}

afterEach(() => { vi.resetAllMocks(); delete (window as unknown as { hacked?: boolean }).hacked })

describe('native Wiki page', () => {
  it('reads the pinned release and shows the page, labelled model-compiled', async () => {
    vi.mocked(readRelease).mockResolvedValue(wikiRelease())
    const { view } = await page()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9']])
    const root = view.get('[data-wiki-page]')
    expect(root.text()).toContain('等待期')
    expect(root.text()).toContain('等待期的说明。')
    expect(view.get('[data-wiki-generated]').text()).toContain('模型整理，未逐条审核')
    view.unmount()
  })

  it('renders in-release page links and strips scripts', async () => {
    vi.mocked(readRelease).mockResolvedValue(wikiRelease())
    const { view, router } = await page()
    const link = view.get('a[data-wiki-link="wiki/M1/concept/kuan-xian-qi"]')
    expect(link.text()).toBe('宽限期规则')
    expect(view.text()).toContain('别处') // a link outside the export keeps only its text
    expect(view.find('a[data-wiki-link="concept/elsewhere"]').exists()).toBe(false)
    expect(view.html()).not.toContain('<script')
    expect(view.html()).not.toContain('onerror')
    expect((window as unknown as { hacked?: boolean }).hacked).toBeUndefined()
    await link.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('enterpriseWikiPage')
    expect(router.currentRoute.value.params).toEqual({ spaceId: 'demo', entityId: 'M1', pageType: 'concept', pageSlug: 'kuan-xian-qi' })
    expect(router.currentRoute.value.query).toEqual({ release: 'rel-9' })
    view.unmount()
  })

  it('opens each source pinned to the release and the page member', async () => {
    vi.mocked(readRelease).mockResolvedValue(wikiRelease())
    const { view } = await page()
    const sources = view.findAll('[data-wiki-source]')
    expect(sources).toHaveLength(2)
    expect(sources[1]!.text()).toContain('出处 2')
    await sources[1]!.trigger('click')
    await flushPromises()
    const panel = view.getComponent(CitationPanel)
    expect([panel.props('spaceId'), panel.props('releaseId'), panel.props('member'), panel.props('evidence')])
      .toEqual(['demo', 'rel-9', 'wiki/M1/concept/deng-dai-qi', 1])
    view.unmount()
  })

  it('says when the release has no such page, and retries a failed read', async () => {
    vi.mocked(readRelease).mockResolvedValue(wikiRelease())
    const missing = await page({ pageType: 'concept', pageSlug: 'missing' })
    expect(missing.view.text()).toContain('该版本中没有这个页面')
    missing.view.unmount()

    vi.mocked(readRelease).mockReset()
    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
      .mockResolvedValueOnce(wikiRelease())
    const failing = await page()
    await failing.view.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(failing.view.find('[data-wiki-page]').exists()).toBe(true)
    failing.view.unmount()
  })
})

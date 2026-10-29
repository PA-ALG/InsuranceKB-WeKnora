// @vitest-environment happy-dom
// Implementation regressions: actual page lifetimes, explicit choices versus automatic expansion.
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseWikiPage from './EnterpriseWikiPage.vue'
import { readRelease } from './enterpriseApi'
import { wikiRelease } from './__tests__/wikiFixtures'

vi.mock('./enterpriseApi', async original => ({
  ...(await original<typeof import('./enterpriseApi')>()), readRelease: vi.fn(),
}))
const mounted: ReturnType<typeof mount>[] = []
afterEach(() => { mounted.splice(0).forEach(view => view.unmount()); vi.resetAllMocks() })

async function app(start: string) {
  vi.mocked(readRelease).mockImplementation(async (_space, id) => ({ ...wikiRelease(), id: id ?? 'rel-9' }))
  const blank = { template: '<div />' }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: blank },
    { name: 'enterpriseSpace', path: '/enterprise/:spaceId', component: blank },
    { name: 'enterpriseConcept', path: '/enterprise/:spaceId/concepts/:conceptKey', component: blank },
    { name: 'enterpriseEntity', path: '/enterprise/:spaceId/entities/:entityId', component: EnterpriseEntity,
      props: route => ({ ...route.params, releaseId: route.query.release ?? undefined }) },
    { name: 'enterpriseWikiPage', path: '/enterprise/:spaceId/wiki/:entityId/:pageType/:pageSlug', component: EnterpriseWikiPage,
      props: route => ({ ...route.params, releaseId: route.query.release ?? undefined }) },
  ] })
  await router.push(start)
  const view = mount(defineComponent({ render: () => h(RouterView) }), {
    global: { plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { CitationPanel: true, Drawer: true, 't-drawer': true } },
  })
  mounted.push(view)
  await flushPromises()
  const group = (name: 'schema' | 'wiki') => view.get<HTMLDetailsElement>(`[data-nav-${name}]`).element
  return { view, router, group,
    async go(address: string) { await router.push(address); await flushPromises() },
    async choose(name: 'schema' | 'wiki', open: boolean) {
      group(name).open = open
      group(name).dispatchEvent(new Event('toggle'))
      await flushPromises()
    },
  }
}
const product = '/enterprise/one/entities/M1'
const wiki = '/enterprise/one/wiki/M1/concept/kuan-xian-qi'

it.each([product, wiki])('pins the loaded release without a request or replacing navigation: %s', async address => {
  const page = await app(address)
  const before = page.group('schema')
  expect(readRelease).toHaveBeenCalledTimes(1)
  await page.go(`${address}?release=rel-9`)
  expect(page.group('schema')).toBe(before)
  expect(readRelease).toHaveBeenCalledTimes(1)
  expect(page.view.find('[role="status"]').exists()).toBe(false)
  // Same id in another Space is a new read; a different id is a new version.
  await page.go(`${address.replace('/one/', '/two/')}?release=rel-9`)
  expect(readRelease).toHaveBeenLastCalledWith('two', 'rel-9')
  expect(readRelease).toHaveBeenCalledTimes(2)
  await page.go(`${address.replace('/one/', '/two/')}?release=rel-next`)
  expect(readRelease).toHaveBeenLastCalledWith('two', 'rel-next')
  expect(readRelease).toHaveBeenCalledTimes(3)
  // Returning to Active needs to resolve the head again; this is not a business-data cache.
  await page.go(address.replace('/one/', '/two/'))
  expect(readRelease).toHaveBeenCalledTimes(4)
})

it('does not save programmatic wiki expansion as a manual choice across page lifetimes', async () => {
  const page = await app(`${product}?release=rel-9`)
  expect(page.group('wiki').open).toBe(false)
  await page.choose('schema', false)
  await page.go(`${wiki}?release=rel-9`)
  expect(page.group('wiki').open).toBe(true)
  // A browser queues toggle even for programmatic :open updates.
  page.group('wiki').dispatchEvent(new Event('toggle'))
  await page.go(`${product}?release=rel-9`)
  expect([page.group('schema').open, page.group('wiki').open]).toEqual([false, false])

  await page.choose('wiki', true)
  await page.choose('wiki', false)
  await page.go(`${wiki}?release=rel-9`)
  expect(page.group('wiki').open).toBe(true)
  await page.go(`${product}?release=rel-9`)
  expect(page.group('wiki').open).toBe(false)
})

it('keeps manual choices per Space, release and product, and across component remounts', async () => {
  const page = await app(`${product}?release=rel-9`)
  await page.choose('schema', false)
  await page.choose('wiki', true)
  for (const address of [product.replace('/M1', '/M2') + '?release=rel-9',
    product.replace('/one/', '/two/') + '?release=rel-9', product + '?release=rel-next']) {
    await page.go(address)
    expect([page.group('schema').open, page.group('wiki').open]).toEqual([true, false])
    await page.go(`${wiki}?release=rel-9`)
    await page.go(`${product}?release=rel-9`)
    expect([page.group('schema').open, page.group('wiki').open]).toEqual([false, true])
  }
})

it('starts a separate app session with default expansion', async () => {
  const first = await app(`${product}?release=rel-9`)
  await first.choose('schema', false)
  await first.choose('wiki', true)
  const second = await app(`${product}?release=rel-9`)
  expect([second.group('schema').open, second.group('wiki').open]).toEqual([true, false])
})

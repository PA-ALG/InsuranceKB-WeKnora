// @vitest-environment happy-dom
// S3j acceptance (protected, written by Claude): moving between a product page and its free-wiki
// pages keeps the navigation as the reader left it: no reload flash for the release already shown,
// and schema_wiki / 自由知识wiki stay open or closed as the reader set them
// (Spec docs/design/slices/S3j-字段标题与缺失字段标识.md §2.4).
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter, RouterView, type RouteLocationNormalized } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseEntity from './EnterpriseEntity.vue'
import EnterpriseWikiPage from './EnterpriseWikiPage.vue'
import { readRelease } from './enterpriseApi'
import { wikiRelease } from './__tests__/wikiFixtures'

afterEach(() => { vi.resetAllMocks() })

const releaseId = (route: RouteLocationNormalized) =>
  typeof route.query.release === 'string' && route.query.release ? route.query.release : undefined

async function app(start: string) {
  vi.mocked(readRelease).mockImplementation(async () => wikiRelease())
  const blank = { template: '<div />' }
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: blank },
    { name: 'enterpriseSpace', path: '/enterprise/:spaceId', component: blank },
    { name: 'enterpriseConcept', path: '/enterprise/:spaceId/concepts/:conceptKey', component: blank },
    { name: 'enterpriseWikiPage', path: '/enterprise/:spaceId/wiki/:entityId/:pageType/:pageSlug', component: EnterpriseWikiPage,
      props: route => ({ ...route.params, releaseId: releaseId(route) }) },
    { name: 'enterpriseEntity', path: '/enterprise/:spaceId/entities/:entityId', component: EnterpriseEntity,
      props: route => ({ ...route.params, releaseId: releaseId(route) }) },
  ] })
  await router.push(start)
  const view = mount(defineComponent({ render: () => h(RouterView) }), {
    global: {
      plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { CitationPanel: true, Drawer: true },
    },
  })
  await flushPromises()
  return { view, router }
}

type App = Awaited<ReturnType<typeof app>>['view']
const schema = (view: App) => view.get('[data-nav-schema]').element as HTMLDetailsElement
const wiki = (view: App) => view.get('[data-nav-wiki]').element as HTMLDetailsElement
const link = (root: Element, title: string) => {
  const found = [...root.querySelectorAll('a')].find(a => a.textContent?.trim().startsWith(title))
  if (!found) throw new Error(`no link ${title}`)
  return found
}
async function toggle(details: HTMLDetailsElement, open: boolean) {
  details.open = open
  details.dispatchEvent(new Event('toggle'))
  await flushPromises()
}
async function click(anchor: HTMLAnchorElement) {
  anchor.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, button: 0 }))
  await flushPromises()
}

describe('navigation across a product and its free-wiki pages', () => {
  it('opens a field of the release already shown without reloading the page', async () => {
    const { view, router } = await app('/enterprise/demo/entities/M1')
    const before = schema(view)
    await click(link(before, '犹豫期'))
    expect(router.currentRoute.value.hash).toBe('#cooling_off_period')
    expect(view.find('[role="status"]').exists()).toBe(false)
    expect(schema(view)).toBe(before)
  })

  it('keeps schema_wiki closed and 自由知识wiki open while the reader moves between pages', async () => {
    const { view, router } = await app('/enterprise/demo/entities/M1?release=rel-9')
    await toggle(schema(view), false)
    await toggle(wiki(view), true)

    await click(link(wiki(view), '宽限期'))
    expect(router.currentRoute.value.name).toBe('enterpriseWikiPage')
    expect([schema(view).open, wiki(view).open]).toEqual([false, true])
    expect(link(wiki(view), '宽限期').getAttribute('aria-current')).toBe('page')

    await click(link(wiki(view), '甲医疗'))
    expect([schema(view).open, wiki(view).open]).toEqual([false, true])
    expect(link(wiki(view), '甲医疗').getAttribute('aria-current')).toBe('page')

    await click(link(view.get('[data-nav-entry]').element, '甲医疗'))
    expect(router.currentRoute.value.name).toBe('enterpriseEntity')
    expect([schema(view).open, wiki(view).open]).toEqual([false, true])
  })
})

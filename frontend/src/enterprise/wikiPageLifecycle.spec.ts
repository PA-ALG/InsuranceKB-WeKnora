// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub, type VueWrapper } from '@vue/test-utils'
import { afterAll, afterEach, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { Drawer } from 'tdesign-vue-next'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import EnterpriseWikiPage from './EnterpriseWikiPage.vue'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import CitationPanel from './CitationPanel.vue'
import { readRelease, type Release } from './enterpriseApi'
import { wikiRelease } from './__tests__/wikiFixtures'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(), readRelease: vi.fn() }))
// happy-dom puts virtual nodeName getters on subclasses; browsers dispatch them through Node.
// DOMPurify caches Node.prototype's getter. Bridge that dispatch only in this test environment.
const restoreNodeName = vi.hoisted(() => {
  const original = Object.getOwnPropertyDescriptor(Node.prototype, 'nodeName')!
  Object.defineProperty(Node.prototype, 'nodeName', { ...original, get() {
    for (let proto = Object.getPrototypeOf(this); proto && proto !== Node.prototype; proto = Object.getPrototypeOf(proto)) {
      const getter = Object.getOwnPropertyDescriptor(proto, 'nodeName')?.get
      if (getter) return getter.call(this)
    }
    return original.get!.call(this)
  } })
  return () => Object.defineProperty(Node.prototype, 'nodeName', original)
})
afterAll(restoreNodeName)
const views: ReturnType<typeof mount>[] = []
const deferred = <T>() => {
  let resolve!: (value: T) => void, reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const i18n = () => createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
async function page(props: Record<string, string | undefined> = {}) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { name: 'enterpriseWikiPage', path: '/spaces/:spaceId/wiki/:entityId/:pageType/:pageSlug', component: {} },
    { name: 'enterpriseEntity', path: '/spaces/:spaceId/entities/:entityId', component: {} },
    { name: 'enterpriseConcept', path: '/spaces/:spaceId/concepts/:conceptKey', component: {} },
    { name: 'enterpriseSpace', path: '/spaces/:spaceId', component: {} },
  ] })
  await router.push('/spaces/demo')
  const view = mount(EnterpriseWikiPage, { attachTo: document.body,
    props: { spaceId: 'demo', entityId: 'M1', pageType: 'concept', pageSlug: 'deng-dai-qi', releaseId: 'rel-9', ...props },
    global: { plugins: [router, i18n()], stubs: { CitationPanel: true } },
  })
  views.push(view); await flushPromises()
  return { view, router }
}
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

it('resolves Active once and pins native keyboard-activatable links and sources to the returned version', async () => {
  vi.mocked(readRelease).mockResolvedValue(wikiRelease())
  const { view, router } = await page({ releaseId: undefined })
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo']])
  const link = view.get('a[data-wiki-link]')
  expect(link.attributes('href')).toContain('?release=rel-9')
  expect(view.findAll('a').filter(item => item.attributes('href')?.includes('/entities/M1'))
    .every(item => item.attributes('href')?.includes('release=rel-9'))).toBe(true)
  await link.trigger('click', { button: 0, detail: 0 }); await flushPromises()
  expect(router.currentRoute.value.query).toEqual({ release: 'rel-9' })
  const source = view.get('[data-wiki-source]')
  ;(source.element as HTMLButtonElement).focus()
  await source.trigger('click'); await flushPromises()
  expect(view.getComponent(CitationPanel).props()).toMatchObject({ releaseId: 'rel-9', member: 'wiki/M1/concept/deng-dai-qi', evidence: 0 })
  view.getComponent(Drawer).vm.$emit('close'); await flushPromises()
  expect(document.activeElement).toBe(source.element)
})

it.each(['resolve', 'reject'] as const)('ignores a late %s after both Space and version change', async outcome => {
  const old = deferred<Release>(), next = { ...wikiRelease(), id: 'next-version' }
  vi.mocked(readRelease).mockReturnValueOnce(old.promise).mockResolvedValueOnce(next)
  const { view } = await page()
  expect(view.find('[role="status"]').exists()).toBe(true)
  await view.setProps({ spaceId: 'next-space', releaseId: 'next-version' }); await flushPromises()
  const fresh = view.html()
  if (outcome === 'resolve') old.resolve({ ...wikiRelease(), members: [] })
  else old.reject(new Error('late failure'))
  await flushPromises()
  expect(view.html()).toBe(fresh)
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9'], ['next-space', 'next-version']])
})

it('rejects a mismatched pinned response and retries that exact requested version', async () => {
  vi.mocked(readRelease).mockResolvedValueOnce({ ...wikiRelease(), id: 'wrong' }).mockResolvedValueOnce(wikiRelease())
  const { view } = await page()
  expect(view.find('[data-wiki-page]').exists()).toBe(false)
  await view.get('[role="alert"] button').trigger('click'); await flushPromises()
  expect(view.get('[data-wiki-page]').text()).toContain('等待期')
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9'], ['demo', 'rel-9']])
})

it('clears an open source when changing pages within the loaded version without re-reading Active', async () => {
  vi.mocked(readRelease).mockResolvedValue(wikiRelease())
  const { view } = await page({ releaseId: undefined })
  await view.get('[data-wiki-source]').trigger('click'); await flushPromises()
  await view.setProps({ pageSlug: 'kuan-xian-qi' }); await flushPromises()
  expect(view.get('[data-wiki-page] h1').text()).toBe('宽限期')
  expect(view.findComponent(CitationPanel).exists()).toBe(false)
  expect(readRelease).toHaveBeenCalledTimes(1)
  await view.setProps({ entityId: 'C1' }); await flushPromises()
  expect(view.text()).toContain('该版本中没有这个页面')
})

it('sanitizes Markdown, escapes Wiki labels and leaves code samples and unsupported links as text', async () => {
  const data = wikiRelease()
  data.members.find(item => item.logical_slug === 'wiki/M1/concept/deng-dai-qi')!.payload.content = [
    '## 安全标题\n\n**加粗**',
    '[[wiki/M1/concept/kuan-xian-qi|<img src=x onerror=alert(1)>]]',
    '[[https://evil.invalid|外部文字]] [[wiki/M1/other/page|未知种类]]',
    '`[[wiki/M1/concept/kuan-xian-qi|代码文字]]`',
    '```text\n[[wiki/M1/concept/kuan-xian-qi|代码块]]\n```',
    '[危险](javascript:alert%281%29)',
    '<a data-wiki-link="wiki/M1/concept/kuan-xian-qi" href="https://evil.invalid">伪造</a>',
    '<script src="https://evil.invalid/x.js"></script><iframe src="https://evil.invalid"></iframe>',
    '<img src=x onerror=alert(1)><svg onload=alert(1)></svg>',
  ].join('\n\n')
  vi.mocked(readRelease).mockResolvedValue(data)
  const { view } = await page()
  expect(view.get('[data-wiki-page] h2').text()).toBe('安全标题')
  expect(view.get('[data-wiki-page] strong').text()).toBe('加粗')
  const links = view.findAll('a[data-wiki-link]')
  expect(links).toHaveLength(1)
  expect(links[0]!.text()).toBe('<img src=x onerror=alert(1)>')
  expect(view.text()).toContain('外部文字')
  expect(view.text()).toContain('未知种类')
  expect(view.findAll('code').map(item => item.text()).join(' ')).toContain('[[wiki/M1/concept/kuan-xian-qi|代码文字]]')
  expect(view.find('script, iframe, svg, [onerror], [onload], a[href^="javascript:"]').exists()).toBe(false)
})

it('keeps modified clicks on the pinned native href', async () => {
  vi.mocked(readRelease).mockResolvedValue(wikiRelease())
  const { view, router } = await page()
  const push = vi.spyOn(router, 'push')
  await view.get('a[data-wiki-link]').trigger('click', { ctrlKey: true, button: 0 })
  expect(push).not.toHaveBeenCalled()
})

it('places the collapsed Wiki group after fields and resets it on a version change', async () => {
  const view = mount(EnterpriseNavigation, { props: { release: wikiRelease(), spaceId: 'demo', entityId: 'M1' },
    global: { plugins: [i18n()], stubs: { RouterLink: RouterLinkStub } } })
  views.push(view)
  const group = view.get('[data-nav-wiki]')
  expect(group.element).toBe(group.element.parentElement!.lastElementChild)
  expect(group.get('summary').text()).toContain('3')
  ;(group.element as HTMLDetailsElement).open = true
  await view.setProps({ release: { ...wikiRelease(), id: 'rel-10' } }); await flushPromises()
  expect(view.get('[data-nav-wiki]').attributes('open')).toBeUndefined()
  expect(view.get('[data-nav-wiki]').findAllComponents(RouterLinkStub)
    .every((link: VueWrapper<InstanceType<typeof RouterLinkStub>>) => {
      const target = link.props('to')
      return typeof target !== 'string' && target.query.release === 'rel-10'
    })).toBe(true)
})

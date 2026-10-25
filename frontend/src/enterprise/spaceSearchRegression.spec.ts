// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/i18n/locales/zh-CN'
import EnterpriseSpace from './EnterpriseSpace.vue'
import { readRelease, type Release } from './enterpriseApi'
import { claim, release } from './__tests__/s3eFixtures'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(), readRelease: vi.fn() }))
const views: ReturnType<typeof mount>[] = []
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })
async function page() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { name: 'enterpriseSpace', path: '/spaces/:spaceId', component: {} },
    { name: 'enterpriseEntity', path: '/spaces/:spaceId/entities/:entityId', component: {} },
    { name: 'enterpriseConcept', path: '/spaces/:spaceId/concepts/:conceptKey', component: {} },
    { name: 'enterpriseGraph', path: '/spaces/:spaceId/graph', component: {} },
    { name: 'enterpriseSpotChecks', path: '/spaces/:spaceId/spot-checks', component: {} },
    { name: 'enterpriseConfirmations', path: '/spaces/:spaceId/confirmations', component: {} },
  ] })
  await router.push('/spaces/demo')
  const view = mount(EnterpriseSpace, { attachTo: document.body, props: { spaceId: 'demo' }, global: {
    plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
  } })
  views.push(view); await flushPromises(); return { view, router }
}

it('renders source text safely, preserves generated labeling and exposes native pinned keyboard links without fetching', async () => {
  const data = structuredClone(release()), value = '<img src=x>癌<script>alert(2)</script>'
  const unsafe = claim('M1', 'untrusted_field', 'present', value)
  unsafe.payload.origin = 'MODEL_GENERATED'; data.members.push(unsafe)
  vi.mocked(readRelease).mockResolvedValue(data)
  const { view, router } = await page()
  await view.get('[data-space-search] input').setValue('癌'); await flushPromises()
  const hit = view.get('[data-search-hit]'), link = hit.get('a')
  expect(hit.text()).toContain(value)
  expect(hit.find('img, script').exists()).toBe(false)
  expect(hit.get('mark').text()).toBe('癌')
  expect(hit.get('.ek-origin--generated').text()).toBeTruthy()
  expect((link.element as HTMLAnchorElement).tabIndex).toBe(0)
  ;(link.element as HTMLAnchorElement).focus(); expect(document.activeElement).toBe(link.element)
  expect(router.currentRoute.value.name).toBe('enterpriseSpace')
  await link.trigger('click'); await flushPromises()
  expect(router.currentRoute.value).toMatchObject({ name: 'enterpriseEntity', query: { release: 'rel-9' }, hash: '#untrusted_field' })
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo']])
})

it('only shows the overall empty message when names, concepts and fields are all empty', async () => {
  vi.mocked(readRelease).mockResolvedValue(release())
  const { view } = await page()
  for (const query of ['甲医疗', '犹豫期', '90日']) {
    await view.get('[data-space-search] input').setValue(query)
    expect(view.text()).not.toContain('没有找到包含')
  }
  await view.get('[data-space-search] input').setValue('不存在')
  expect(view.text()).toContain('没有找到包含“不存在”的内容')
  await view.get('[data-space-search] input').setValue('  ')
  expect(view.find('[data-search-fields]').exists()).toBe(false)
  expect(vi.mocked(readRelease).mock.calls).toHaveLength(1)
})

it('clears old results on a Space or pinned-version change and ignores stale Release reads', async () => {
  let resolve!: (value: Release) => void
  const old = new Promise<Release>(done => { resolve = done })
  const latest = structuredClone(release()); latest.id = 'new-release'
  vi.mocked(readRelease).mockResolvedValueOnce(release()).mockReturnValueOnce(old).mockResolvedValueOnce(latest)
  const { view } = await page()
  await view.get('[data-space-search] input').setValue('90日')
  expect(view.findAll('[data-search-hit]')).toHaveLength(1)
  await view.setProps({ releaseId: 'slow' })
  expect(view.find('[data-search-hit]').exists()).toBe(false)
  await view.setProps({ spaceId: 'next', releaseId: 'new-release' }); await flushPromises()
  resolve({ ...release(), id: 'slow' }); await flushPromises()
  expect((view.get('[data-space-search] input').element as HTMLInputElement).value).toBe('')
  await view.get('[data-space-search] input').setValue('90日')
  expect(view.get('[data-search-hit] a').attributes('href')).toBe('/spaces/next/entities/M1?release=new-release#waiting_period')
  expect(vi.mocked(readRelease).mock.calls).toEqual([['demo'], ['demo', 'slow'], ['next', 'new-release']])
})

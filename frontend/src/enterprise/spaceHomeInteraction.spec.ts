// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/i18n/locales/zh-CN'
import EnterpriseSpace from './EnterpriseSpace.vue'
import EnterpriseNavigation from './EnterpriseNavigation.vue'
import { readRelease } from './enterpriseApi'
import { homeRelease } from './__tests__/spaceHomeFixtures'

vi.mock('./enterpriseApi', async original => ({
  ...(await original<typeof import('./enterpriseApi')>()), readRelease: vi.fn(),
}))
afterEach(() => vi.resetAllMocks())

async function setup(navigation = false) {
  const data = homeRelease()
  vi.mocked(readRelease).mockResolvedValue(data)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { name: 'enterpriseSpace', path: '/spaces/:spaceId', component: { template: '<div />' } },
    { name: 'enterpriseEntity', path: '/spaces/:spaceId/entities/:entityId', component: { template: '<div />' } },
    { name: 'enterpriseConcept', path: '/spaces/:spaceId/concepts/:conceptKey', component: { template: '<div />' } },
    { name: 'enterpriseGraph', path: '/spaces/:spaceId/graph', component: { template: '<div />' } },
    { name: 'enterpriseSpotChecks', path: '/spaces/:spaceId/spot-checks', component: { template: '<div />' } },
    { name: 'enterpriseConfirmations', path: '/spaces/:spaceId/confirmations', component: { template: '<div />' } },
  ] })
  await router.push('/spaces/demo')
  await router.isReady()
  const view = mount(navigation ? EnterpriseNavigation : EnterpriseSpace, {
    props: navigation ? { release: data, spaceId: 'demo', entityId: 'A' } : { spaceId: 'demo', releaseId: data.id },
    global: { plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] },
  })
  await flushPromises()
  return { view, router }
}

describe('home directory interactions', () => {
  it('keeps full counts while searching locally, limits shortcuts and opens the concept tab', async () => {
    const { view } = await setup()
    expect(view.findAll('[data-concept-shortcut]')).toHaveLength(6)
    expect(view.findAll('[data-common-concept]')).toHaveLength(10)
    const counts = view.get('[data-space-counts]').text()
    expect(view.get('[data-space-version]').attributes('title')).toContain('demo')
    await view.get('[data-space-search] input').setValue(' 产品 b ')
    expect(view.findAll('[data-overview-row]').map(row => row.attributes('data-overview-row'))).toEqual(['B'])
    expect(view.findAll('[data-overview-group]')).toHaveLength(1)
    expect(view.get('[data-space-counts]').text()).toBe(counts)
    await view.get('[data-space-search] input').setValue('字段')
    expect(view.findAll('[data-common-concept]')).toHaveLength(12)
    await view.get('[data-all-concepts]').trigger('click')
    expect(view.findAll('[role="tab"]').at(-1)!.attributes('aria-selected')).toBe('true')
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'home-release']])
    view.unmount()
  })

  it.each(['click', 'keydown'])('opens an entire product row on its pinned release using %s', async event => {
    const { view, router } = await setup()
    await view.get('[data-overview-row="C"]').trigger(event, event === 'keydown' ? { key: 'Enter' } : {})
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('enterpriseEntity')
    expect(router.currentRoute.value.params.entityId).toBe('C')
    expect(router.currentRoute.value.query.release).toBe('home-release')
    view.unmount()
  })

  it('links a concept shortcut to the same release', async () => {
    const { view, router } = await setup()
    await view.get('[data-concept-shortcut]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('enterpriseConcept')
    expect(router.currentRoute.value.params.conceptKey).toBe('field_2')
    expect(router.currentRoute.value.query.release).toBe('home-release')
    view.unmount()
  })
})

describe('compact navigation', () => {
  it('filters names, hides empty groups and reopens the current entry group', async () => {
    const { view } = await setup(true)
    const beta = view.get('[data-nav-group="beta"] button')
    await beta.trigger('click')
    expect(beta.attributes('aria-expanded')).toBe('false')
    await view.setProps({ entityId: 'C' })
    expect(beta.attributes('aria-expanded')).toBe('true')
    expect(view.get('[data-nav-entry] [title]').attributes('title')).toBe('产品 A')
    expect(view.findAll('.ek-nav-fields')).toHaveLength(1)
    await view.get('[data-nav-filter]').setValue('产品 B')
    expect(view.findAll('[data-nav-entry]')).toHaveLength(1)
    expect(view.findAll('[data-nav-group]')).toHaveLength(1)
    await view.findAll('[role="tab"]').at(-1)!.trigger('click')
    expect((view.get('[data-nav-filter]').element as HTMLInputElement).value).toBe('')
    await view.get('[data-nav-filter]').setValue('字段 11')
    expect(view.findAll('[data-nav-concept]')).toHaveLength(1)
    view.unmount()
  })
})

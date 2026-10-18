// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import zhCN from '@/i18n/locales/zh-CN'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(), readRelease: vi.fn() }))
import { readRelease } from './enterpriseApi'
import EnterpriseGraph from './EnterpriseGraph.vue'
import { release } from './__tests__/s3eFixtures'

function data() {
  const result = structuredClone(release())
  result.members = result.members.filter(member => member.payload.entity_id !== 'X1' && member.payload.subject_ref !== 'X1')
  return result
}
const views: ReturnType<typeof mount>[] = []
async function page() {
  vi.mocked(readRelease).mockResolvedValue(data())
  const view = mount(EnterpriseGraph, { props: { spaceId: 'demo', releaseId: 'rel-9' }, attachTo: document.body,
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub } } })
  views.push(view)
  await flushPromises()
  return view
}
const shared = '[data-graph-node="concept:cooling_off_period"]'
const partial = '[data-graph-node="concept:premium_grace_period"]'
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('graph common-concept controls', () => {
  it('starts narrowed, restores all concepts with the switch and clears hidden selection when switched back', async () => {
    const view = await page()
    expect(view.find(shared).exists()).toBe(false)
    expect(view.find(partial).exists()).toBe(true)
    const toggle = view.get('[data-graph-all-concepts] input')
    expect((toggle.element as HTMLInputElement).checked).toBe(false)
    expect(view.get('[data-graph-counts]').text()).toContain('已隐藏 1 个')
    await toggle.setValue(true)
    expect(view.find(shared).exists()).toBe(true)
    expect(view.findAll('[data-graph-edge]')).toHaveLength(5)
    expect(view.get('[data-graph-counts]').text()).toContain('显示全部概念：开')
    expect(view.get('[data-graph-counts]').text()).toContain('已隐藏 0 个')
    await view.get(shared).trigger('click')
    await toggle.setValue(false)
    expect(view.find(shared).exists()).toBe(false)
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
  })

  it('recomputes common concepts for a single-product group and for no visible products', async () => {
    const view = await page()
    await view.get('[data-graph-group="pack_medical"] input').setValue(false)
    expect(view.findAll('[data-graph-node^="entity:"]')).toHaveLength(1)
    expect(view.findAll('[data-graph-node^="concept:"]')).toHaveLength(0)
    expect(view.get('[data-graph-counts]').text()).toContain('已隐藏 2 个')
    await view.get('[data-graph-all-concepts] input').setValue(true)
    expect(view.findAll('[data-graph-edge]')).toHaveLength(2)
    await view.get('[data-graph-group="pack_critical"] input').setValue(false)
    expect(view.findAll('[data-graph-node]')).toHaveLength(0)
    expect(view.get('[data-graph-counts]').text()).toContain('已隐藏 0 个')
  })

  it('searches a hidden concept, reveals its edges, pins the link, and returns focus on close', async () => {
    const view = await page()
    await view.get('[data-graph-search] input').setValue('犹豫期')
    await view.get('[data-graph-search] input').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(view.find(shared).exists()).toBe(true)
    expect(view.findAll('[data-graph-edge]')).toHaveLength(5)
    expect(view.get('[data-graph-counts]').text()).toContain('已显示 1 个定位概念')
    expect(view.findAllComponents(RouterLinkStub).map(link => link.props('to'))).toContainEqual({
      name: 'enterpriseConcept', params: { spaceId: 'demo', conceptKey: 'cooling_off_period' }, query: { release: 'rel-9' },
    })
    await view.get('[data-graph-close]').trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(view.get(shared).element)
    await view.get('[data-graph-group="pack_medical"] input').setValue(false)
    expect(view.find(shared).exists()).toBe(false)
  })

  it('uses the same reveal path for external location and resets it on a new release', async () => {
    const view = await page()
    expect(await view.vm.locateNode('concept:cooling_off_period')).toBe(true)
    expect(view.find(shared).exists()).toBe(true)
    expect(view.get('[data-graph-detail]').text()).toContain('犹豫期')
    expect(await view.vm.locateNode('concept:missing')).toBe(false)
    vi.mocked(readRelease).mockResolvedValueOnce({ ...data(), id: 'next-release' })
    await view.setProps({ releaseId: 'next-release' })
    await flushPromises()
    expect(view.find(shared).exists()).toBe(false)
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    expect((view.get('[data-graph-all-concepts] input').element as HTMLInputElement).checked).toBe(false)
  })
})

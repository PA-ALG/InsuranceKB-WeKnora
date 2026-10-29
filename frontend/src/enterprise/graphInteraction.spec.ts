// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { afterEach, describe, expect, it, vi } from 'vitest'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(), readRelease: vi.fn() }))
import { readRelease, EnterpriseError } from './enterpriseApi'
import EnterpriseGraph from './EnterpriseGraph.vue'
import { release } from './__tests__/s3eFixtures'

const views: ReturnType<typeof mount>[] = []
function page(props = { spaceId: 'demo', releaseId: 'rel-9' }) {
  const view = mount(EnterpriseGraph, { props, attachTo: document.body,
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub } } })
  views.push(view)
  return view
}
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('graph interactions and release isolation', () => {
  it('returns focus to the selected SVG node when closing the detail', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    const node = view.get('[data-graph-node="entity:M1"]')
    await node.trigger('keydown', { key: 'Enter' })
    const close = view.get('[data-graph-close]')
    expect(document.activeElement).toBe(close.element)
    await close.trigger('click')
    await flushPromises()
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    expect(document.activeElement).toBe(node.element)
  })

  it('ignores an older response after navigation and clears old detail and links immediately', async () => {
    let finish!: (value: ReturnType<typeof release>) => void
    vi.mocked(readRelease).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ ...release(), id: 'next-release' })
    const view = page()
    await view.setProps({ releaseId: 'next-release' })
    await flushPromises()
    finish(release())
    await flushPromises()
    await view.get('[data-graph-node="entity:M1"]').trigger('click')
    expect(view.findAllComponents(RouterLinkStub).every(link => {
      const target = link.props('to')
      return typeof target !== 'string' && target.query.release === 'next-release'
    })).toBe(true)
    vi.mocked(readRelease).mockReturnValueOnce(new Promise(() => {}))
    await view.setProps({ releaseId: 'third-release' })
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    expect(view.findAllComponents(RouterLinkStub)).toHaveLength(0)
  })

  it('retries a missing pinned release without falling back to Active', async () => {
    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503))
      .mockResolvedValueOnce(release())
    const view = page()
    await flushPromises()
    await view.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9'], ['demo', 'rel-9']])
  })

  it('removes hidden detail and leaves only concepts attached to visible products', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    await view.get('[data-graph-node="entity:M1"]').trigger('click')
    for (const input of view.findAll('[data-graph-group] input')) await input.setValue(false)
    expect(view.findAll('[data-graph-node]')).toHaveLength(0)
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    expect(view.text()).toContain('请选择至少一个险种分组')
  })

  it('supports zoom, fit and neighbor emphasis', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    const transform = () => view.get('[data-graph-transform]').attributes('transform')
    const before = transform()
    await view.get('[data-graph-zoom-in]').trigger('click')
    expect(transform()).not.toBe(before)
    await view.get('[data-graph-fit]').trigger('click')
    await view.get('[data-graph-all-concepts] input').setValue(true) // full graph: products and concepts together
    await view.get('[data-graph-node="entity:M1"]').trigger('mouseenter')
    expect(view.get('[data-graph-node="entity:X1"]').classes()).toContain('ek-graph-node--muted')
    expect(view.get('[data-graph-node="concept:cooling_off_period"]').classes()).not.toContain('ek-graph-node--muted')
  })

  it('moves a dragged node without opening details, and pans the background separately', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    const node = view.get('[data-graph-node="entity:M1"]'), svg = view.get('svg')
    const before = node.attributes('transform')
    await node.trigger('pointerdown', { button: 0, pointerId: 1, clientX: 100, clientY: 100 })
    await svg.trigger('pointermove', { pointerId: 1, clientX: 140, clientY: 130 })
    await svg.trigger('pointerup', { pointerId: 1 })
    expect(node.attributes('transform')).not.toBe(before)
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    const pan = view.get('[data-graph-transform]').attributes('transform')
    await svg.trigger('pointerdown', { button: 0, pointerId: 2, clientX: 20, clientY: 20 })
    await svg.trigger('pointermove', { pointerId: 2, clientX: 80, clientY: 40 })
    await svg.trigger('pointerup', { pointerId: 2 })
    expect(view.get('[data-graph-transform]').attributes('transform')).not.toBe(pan)
    await node.trigger('pointerdown', { button: 0, pointerId: 3, clientX: 100, clientY: 100 })
    await svg.trigger('pointerup', { pointerId: 3 })
    expect(view.get('[data-graph-detail]').text()).toContain('甲医疗')
  })

  it('reduces labels at low zoom while keeping a selected node readable', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    await view.get('[data-graph-all-concepts] input').setValue(true) // full graph: products and concepts together
    await view.get('[data-graph-node="concept:cooling_off_period"]').trigger('click')
    for (let i = 0; i < 6; i++) await view.get('[data-graph-zoom-out]').trigger('click')
    expect(view.get('[data-graph-node="entity:M2"] text').attributes('opacity')).toBe('0')
    const label = view.get('[data-graph-node="concept:cooling_off_period"] text')
    expect(label.attributes('opacity')).toBe('1')
    expect(parseFloat((label.element as SVGElement).style.fontSize)).toBeGreaterThan(13)
  })
})

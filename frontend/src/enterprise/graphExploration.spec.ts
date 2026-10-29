// @vitest-environment happy-dom
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
vi.mock('./enterpriseApi', async original => ({ ...await original<typeof import('./enterpriseApi')>(), readRelease: vi.fn() }))
import { readRelease } from './enterpriseApi'
import { release } from './__tests__/s3eFixtures'
import { relationGraph } from './graphView'
import { graphDisplay } from './graphDisplay'
import EnterpriseGraph from './EnterpriseGraph.vue'
import RelationGraphCanvas from './RelationGraphCanvas.vue'

const views: ReturnType<typeof mount>[] = []
async function page() {
  vi.mocked(readRelease).mockResolvedValue(release())
  const view = mount(EnterpriseGraph, { attachTo: document.body, props: { spaceId: 'demo', releaseId: 'rel-9' },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: { RouterLink: RouterLinkStub } } })
  views.push(view); await flushPromises(); return view
}
const ids = (view: ReturnType<typeof mount>) => view.findAll('[data-graph-node]').map(node => node.attributes('data-graph-node')!)
afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('exploration display projection', () => {
  const full = relationGraph(release()), groups = [...new Set(full.nodes.filter(node => node.kind === 'product').map(node => node.group))]
  it('builds only published product groups and products in overview, without mutating the full graph', () => {
    const before = JSON.stringify(full), view = graphDisplay(full, groups)
    expect(view.mode).toBe('overview')
    expect(view.visible.nodes.filter(node => node.kind === 'concept')).toHaveLength(0)
    expect(view.visible.nodes.filter(node => node.kind === 'group')).toHaveLength(3)
    expect(view.visible.edges).toHaveLength(4)
    expect(view.visible.edges.every(edge => edge.source.startsWith('entity:') && edge.target.startsWith('group:'))).toBe(true)
    expect(JSON.stringify(full)).toBe(before)
  })
  it('shows exactly one center and its neighbors, including universally connected concepts', () => {
    const product = graphDisplay(full, groups, false, 'entity:M1')
    expect(product.mode).toBe('neighbors')
    expect(product.visible.nodes.map(node => node.id)).toEqual(['entity:M1', 'concept:cooling_off_period', 'concept:premium_grace_period'])
    expect(product.visible.edges.every(edge => edge.source === 'entity:M1')).toBe(true)
    const concept = graphDisplay(full, groups, false, 'concept:cooling_off_period')
    expect(concept.visible.nodes.map(node => node.id)).toEqual(['entity:M1', 'entity:M2', 'entity:C1', 'concept:cooling_off_period'])
    expect(concept.visible.edges).toHaveLength(3)
  })
  it('composes group filtering, all mode, empty groups and missing centers', () => {
    expect(graphDisplay(full, groups, true).visible).toEqual(full)
    expect(graphDisplay(full, ['pack_critical'], false, 'concept:cooling_off_period').visible.edges).toHaveLength(1)
    expect(graphDisplay(full, ['pack_critical'], false, 'entity:M1').mode).toBe('overview')
    expect(graphDisplay(full, [], false, 'concept:cooling_off_period').visible).toEqual({ nodes: [], edges: [] })
    expect(graphDisplay(full, groups, false, 'entity:X1').visible.nodes.map(node => node.id)).toEqual(['entity:X1'])
  })
})

describe('exploration page', () => {
  it('starts in overview, switches center by clicking neighbors, and returns explicitly', async () => {
    const view = await page()
    expect(ids(view).some(id => id.startsWith('concept:'))).toBe(false)
    await view.get('[data-graph-node="entity:M1"]').trigger('keydown', { key: 'Enter' })
    expect(ids(view).filter(id => id.startsWith('entity:'))).toEqual(['entity:M1'])
    expect(view.findAll('[data-graph-edge]')).toHaveLength(2)
    await view.get('[data-graph-node="concept:cooling_off_period"]').trigger('click')
    expect(ids(view).filter(id => id.startsWith('entity:'))).toEqual(['entity:M1', 'entity:M2', 'entity:C1'])
    expect(view.get('[data-graph-detail]').text()).toContain('模型补充')
    await view.get('[data-graph-node="entity:M2"]').trigger('click')
    expect(view.findAll('[data-graph-edge]')).toHaveLength(1)
    await view.get('[data-graph-overview]').trigger('click')
    expect(ids(view).some(id => id.startsWith('concept:'))).toBe(false)
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    expect(document.activeElement).toBe(view.get('[data-graph-node="entity:M2"]').element)
  })
  it('searches and externally locates concepts absent from overview, with pinned links and return focus', async () => {
    const view = await page()
    await view.get('[data-graph-search] input').setValue('犹豫期')
    await view.get('[data-graph-search] input').trigger('keydown', { key: 'Enter' })
    expect(ids(view)).toContain('concept:cooling_off_period')
    expect(view.findAllComponents(RouterLinkStub).map(link => link.props('to'))).toContainEqual({
      name: 'enterpriseConcept', params: { spaceId: 'demo', conceptKey: 'cooling_off_period' }, query: { release: 'rel-9' } })
    await view.get('[data-graph-close]').trigger('click'); await flushPromises()
    expect(document.activeElement).toBe(view.get('[data-graph-node="concept:cooling_off_period"]').element)
    await view.get('[data-graph-overview]').trigger('click')
    expect(await view.vm.locateNode('entity:C1')).toBe(true)
    expect(view.findAll('[data-graph-edge]')).toHaveLength(2)
  })
  it('restores the full graph with the switch and resets to overview when disabled', async () => {
    const view = await page()
    await view.get('[data-graph-all-concepts] input').setValue(true)
    expect(ids(view).some(id => id.startsWith('group:'))).toBe(false)
    expect(view.findAll('[data-graph-edge]')).toHaveLength(5)
    await view.get('[data-graph-node="entity:M1"]').trigger('click')
    expect(view.findAll('[data-graph-edge]')).toHaveLength(5)
    await view.get('[data-graph-all-concepts] input').setValue(false)
    expect(ids(view).some(id => id.startsWith('concept:'))).toBe(false)
  })
  it('keeps an eligible concept center when filtering and returns to overview if its product center disappears', async () => {
    const view = await page()
    await view.vm.locateNode('concept:cooling_off_period')
    await view.get('[data-graph-group="pack_medical"] input').setValue(false)
    expect(ids(view)).toEqual(['entity:C1', 'concept:cooling_off_period'])
    await view.vm.locateNode('entity:C1')
    await view.get('[data-graph-group="pack_critical"] input').setValue(false)
    expect(ids(view)).toEqual(['group:__other__', 'entity:X1'])
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
  })
  it('omits zero statistics in overview, both neighbor directions, full mode, an isolated product and empty filtering', async () => {
    const view = await page(), counts = () => view.get('[data-graph-counts]').text()
    expect(counts()).toContain('3 个险种 · 4 款产品 · 4 条关系')
    expect(counts()).not.toContain('概念')
    await view.vm.locateNode('entity:M1')
    expect(counts()).toContain('1 款产品 · 2 个概念 · 2 条关系')
    expect(counts()).not.toContain('险种')
    await view.vm.locateNode('concept:cooling_off_period')
    expect(counts()).toContain('3 款产品 · 1 个概念 · 3 条关系')
    expect(counts()).not.toContain('险种')
    await view.get('[data-graph-all-concepts] input').setValue(true)
    expect(counts()).toContain('4 款产品 · 2 个概念 · 5 条关系')
    expect(counts()).not.toContain('险种')
    await view.get('[data-graph-all-concepts] input').setValue(false)
    await view.vm.locateNode('entity:X1')
    expect(counts()).toContain('1 款产品')
    expect(counts()).not.toMatch(/险种|个概念|条关系/)
    for (const input of view.findAll('[data-graph-group] input')) await input.setValue(false)
    expect(view.get('[data-graph-counts]').findAll('span').at(-1)!.text()).toBe('')
    expect(counts()).not.toMatch(/0\s*(个|款|条)/)
  })
  it('discards pending old releases and resets the exploration state on navigation', async () => {
    const view = await page()
    await view.vm.locateNode('entity:M1')
    let finish!: (value: ReturnType<typeof release>) => void
    vi.mocked(readRelease).mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
      .mockResolvedValueOnce({ ...release(), id: 'newest' })
    await view.setProps({ releaseId: 'old-pending' })
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    await view.setProps({ releaseId: 'newest' }); await flushPromises()
    finish(release()); await flushPromises()
    expect(ids(view).some(id => id.startsWith('concept:'))).toBe(false)
    await view.vm.locateNode('entity:M1')
    expect(view.findAllComponents(RouterLinkStub).every(link => { const to = link.props('to'); return typeof to !== 'string' && to.query.release === 'newest' })).toBe(true)
  })
})


describe('exploration canvas', () => {
  it('wraps product labels by Unicode character, preserves full titles, and thins labels only after zooming out', async () => {
    const full = relationGraph(release())
    const product = full.nodes.find(node => node.id === 'entity:M1')!
    product.title = '😀甲乙丙丁戊己庚辛壬癸子丑'
    product.degree = 20
    const display = graphDisplay(full, ['pack_medical'], false, product.id)
    const view = mount(RelationGraphCanvas, { props: { graph: display.visible, mode: display.mode, centerId: product.id,
      selected: product.id, colors: new Map() }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] } })
    views.push(view)
    expect(view.findAll('[data-graph-node="entity:M1"] text tspan').map(line => line.text())).toEqual(['😀甲乙丙丁戊己庚辛壬癸子', '丑'])
    expect(view.get('[data-graph-node="entity:M1"] title').text()).toBe(product.title)
    expect(view.get('[data-graph-node="entity:M1"]').attributes('transform')).toBe('translate(0,0)')
    expect(view.findAll('[data-graph-node] text').every(node => node.attributes('opacity') === '1')).toBe(true)
    for (let i = 0; i < 8; i++) await view.get('[data-graph-zoom-out]').trigger('click')
    expect(view.get('[data-graph-node="concept:cooling_off_period"] text').attributes('opacity')).toBe('0')
    expect(view.get('[data-graph-node="entity:M1"] text').attributes('opacity')).toBe('1')
    await view.get('[data-graph-fit]').trigger('click')
    expect(view.findAll('[data-graph-node] text').every(node => node.attributes('opacity') === '1')).toBe(true)
  })
  it.each([
    ['😀' + '甲'.repeat(11), ['😀' + '甲'.repeat(11)]],
    ['甲'.repeat(12) + '乙', ['甲'.repeat(12), '乙']],
    ['甲'.repeat(12) + '乙'.repeat(12), ['甲'.repeat(12), '乙'.repeat(12)]],
    ['甲'.repeat(12) + '乙'.repeat(13), ['甲'.repeat(12), '乙'.repeat(11) + '…']],
  ])('limits product %s to two lines of at most twelve characters in overview and outside the neighbor ring', (title, expected) => {
    const full = relationGraph(release())
    const product = full.nodes.find(node => node.id === 'entity:M1')!
    product.title = title as string
    for (const centerId of ['', 'concept:cooling_off_period']) {
      const display = graphDisplay(full, ['pack_medical'], false, centerId)
      const view = mount(RelationGraphCanvas, { props: { graph: display.visible, mode: display.mode, centerId,
        colors: new Map() }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] } })
      views.push(view)
      const lines = view.findAll('[data-graph-node="entity:M1"] text tspan')
      expect(lines.map(line => line.text())).toEqual(expected)
      expect(lines.every(line => Array.from(line.text()).length <= 12)).toBe(true)
      expect(view.get('[data-graph-node="entity:M1"] title').text()).toBe(title)
      expect(new Set(lines.map(line => line.attributes('x'))).size).toBe(1)
      if (lines.length === 2) expect(Number(lines[1]!.attributes('dy'))).toBeGreaterThan(0)
    }
  })
  it('highlights product-to-group neighbors in overview without opening a detail for a group', async () => {
    const view = await page()
    await view.get('[data-graph-node="entity:M1"]').trigger('mouseenter')
    expect(view.get('[data-graph-node="group:pack_medical"]').classes()).not.toContain('ek-graph-node--muted')
    expect(view.get('[data-graph-node="entity:C1"]').classes()).toContain('ek-graph-node--muted')
    await view.get('[data-graph-node="group:pack_medical"]').trigger('click')
    expect(view.find('[data-graph-detail]').exists()).toBe(false)
    expect(ids(view)).toContain('entity:C1')
  })
})

// @vitest-environment happy-dom
// S3g acceptance (protected, written by Claude): the relation graph page reads one release and keeps
// every link on it (Spec docs/design/slices/S3g-知识图谱复用.md §2.2; R2 exploratory default view).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
}))

import EnterpriseGraph from './EnterpriseGraph.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import { EnterpriseError, readRelease } from './enterpriseApi'
import { release } from './__tests__/s3eFixtures'

function i18n() {
  return createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
}

function page(props: { spaceId: string; releaseId?: string } = { spaceId: 'demo', releaseId: 'rel-9' }) {
  return mount(EnterpriseGraph, { props, global: { plugins: [i18n()], stubs: { RouterLink: RouterLinkStub } } })
}

const linksOf = (view: ReturnType<typeof page>) => view.findAllComponents(RouterLinkStub).map(link => link.props('to'))

afterEach(() => { vi.resetAllMocks() })

describe('relation graph page', () => {
  it('draws the products of the release it was given, and a product\'s concepts once it is selected', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo', 'rel-9']])
    const ids = () => view.findAll('[data-graph-node]').map(node => node.attributes('data-graph-node'))
    expect(ids()).toContain('entity:M1')
    expect(ids().some(id => id?.startsWith('concept:'))).toBe(false) // the overview draws groups and products only
    expect(view.findAll('[data-graph-edge]').length).toBeGreaterThan(0)
    await view.get('[data-graph-node="entity:M1"]').trigger('click')
    expect(ids()).toContain('concept:cooling_off_period')
  })

  it('opens a product and a concept with links pinned to the same release', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page({ spaceId: 'demo' }) // no release named: the one read pins the links
    await flushPromises()
    expect(vi.mocked(readRelease).mock.calls).toEqual([['demo']])
    await view.get('[data-graph-node="entity:M1"]').trigger('click')
    const product = view.get('[data-graph-detail]')
    expect(product.text()).toContain('甲医疗')
    expect(linksOf(view)).toContainEqual({ name: 'enterpriseEntity', params: { spaceId: 'demo', entityId: 'M1' }, query: { release: 'rel-9' } })
    await view.get('[data-graph-node="concept:cooling_off_period"]').trigger('click')
    const concept = view.get('[data-graph-detail]')
    expect(concept.text()).toContain('犹豫期')
    expect(concept.text()).toContain('模型补充') // the definition came from a model-written concept member
    expect(linksOf(view)).toContainEqual({ name: 'enterpriseConcept', params: { spaceId: 'demo', conceptKey: 'cooling_off_period' }, query: { release: 'rel-9' } })
  })

  it('opens a node from the keyboard', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    await view.get('[data-graph-node="entity:C1"]').trigger('keydown', { key: 'Enter' })
    expect(view.get('[data-graph-detail]').text()).toContain('丙重疾')
  })

  it('finds a node by name and filters products by group', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = page()
    await flushPromises()
    await view.get('[data-graph-search] input').setValue('丙重疾')
    await view.get('[data-graph-search] input').trigger('keydown', { key: 'Enter' })
    expect(view.get('[data-graph-detail]').text()).toContain('丙重疾')

    await view.get('[data-graph-overview]').trigger('click') // group filtering is checked on the overview
    const before = view.findAll('[data-graph-node^="entity:"]').length
    await view.get('[data-graph-group="pack_medical"] input').setValue(false)
    const after = view.findAll('[data-graph-node^="entity:"]').map(node => node.attributes('data-graph-node'))
    expect(after.length).toBeLessThan(before)
    expect(after).not.toContain('entity:M1')
  })

  it('shows loading, unpublished, failure with retry, and an empty release', async () => {
    let resolve!: (value: ReturnType<typeof release>) => void
    vi.mocked(readRelease).mockReturnValueOnce(new Promise(ok => { resolve = ok }))
    const loading = page()
    expect(loading.find('[role="status"]').exists()).toBe(true)
    resolve(release())
    await flushPromises()

    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('RELEASE_NOT_FOUND', 404))
    const unpublished = page({ spaceId: 'demo' })
    await flushPromises()
    expect(unpublished.text()).toContain('该空间还没有发布版本')

    vi.mocked(readRelease).mockRejectedValueOnce(new EnterpriseError('SERVICE_UNAVAILABLE', 503)).mockResolvedValueOnce(release())
    const failing = page()
    await flushPromises()
    await failing.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(failing.findAll('[data-graph-node]').length).toBeGreaterThan(0)

    vi.mocked(readRelease).mockResolvedValueOnce({ id: 'rel-1', epoch: 1, members: [] })
    const empty = page()
    await flushPromises()
    expect(empty.text()).toContain('该版本中还没有条目')
  })

  it('is reachable from the Space page on the release it shows', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    const view = mount(EnterpriseSpace, { props: { spaceId: 'demo' }, global: { plugins: [i18n()], stubs: { RouterLink: RouterLinkStub } } })
    await flushPromises()
    expect(view.findAllComponents(RouterLinkStub).map(link => link.props('to')))
      .toContainEqual({ name: 'enterpriseGraph', params: { spaceId: 'demo' }, query: { release: 'rel-9' } })
  })
})

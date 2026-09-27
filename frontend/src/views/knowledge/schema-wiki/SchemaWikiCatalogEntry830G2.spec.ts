// @vitest-environment happy-dom

import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

const api = vi.hoisted(() => ({ load: vi.fn(), loadSchemaCatalog: vi.fn(), loadPreparation: vi.fn(), loadActive: vi.fn() }))
const route = reactive({ query: {} as Record<string, unknown> })
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('@/api/schema-wiki/conceptDirectory830G2', () => ({ loadConceptDirectory830G2: api.load }))
vi.mock('@/api/schema-wiki/schemaPackCatalog830G3', () => ({
  loadSchemaPackCatalog830G3: api.loadSchemaCatalog,
}))
vi.mock('@/api/schema-wiki/batchConcept830G3', () => ({
  loadBatchConceptPreparation830G3: api.loadPreparation,
  loadBatchConceptActive830G3: api.loadActive,
}))
vi.mock('@/utils/request', () => ({ get: vi.fn() }))
vi.mock('./SchemaPackCatalog830G3.vue', () => ({ default: {
  name: 'SchemaPackCatalog830G3', props: ['catalog'], template: '<section data-testid="g3-catalog">G3 Catalog</section>',
} }))
vi.mock('./SchemaWikiBrowser.vue', () => ({ default: {
  name: 'SchemaWikiBrowser', props: ['knowledgeBaseId'], template: '<div data-testid="legacy">legacy</div>',
} }))

import SchemaWikiCatalogEntry from './SchemaWikiCatalogEntry830G2.vue'
import { get } from '@/utils/request'
enableAutoUnmount(afterEach)

const H = 'a'.repeat(64)
const common = { scope: { version: 'schema-wiki-scope.v1', space_id: 'space', raw_kb_id: 'raw',
  wiki_kb_id: 'wiki-serving', scope_sha256: H }, releaseID: 'release-a', activationEpoch: 4 }

describe('SchemaWikiCatalogEntry830G2', () => {
  beforeEach(() => {
    api.load.mockReset()
    api.loadSchemaCatalog.mockReset()
    api.loadPreparation.mockReset()
    api.loadActive.mockReset()
    api.loadActive.mockResolvedValue(null)
    route.query = {}
    api.loadSchemaCatalog.mockResolvedValue({ catalog_id: 'schema_catalog_insurance_product', entries: [] })
    ;(window as any).__RUNTIME_CONFIG__ = { SCHEMA_WIKI_MVP_ENTRY_KB_ID: 'wiki-entry',
      SCHEMA_WIKI_MVP_SERVING_KB_ID: 'wiki-serving' }
  })

  it.each([['DRAFT', '待审核'], ['READY', '已审核但未发布']] as const)(
    'opens immutable %s preparation without loading current or Active', async (status, label) => {
      route.query = { tab: 'schema', preparation_id: 'preparation-g3' }
      api.loadPreparation.mockResolvedValue({ ...common, mode: 'g3-preparation', preparationID: 'preparation-g3',
        status, statusLabel: label, catalog: { catalog_id: 'schema_catalog_insurance_product', entries: [] }, entities: [] })
      const wrapper = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
        ConceptDirectory830G2: { props: ['catalog'], template: '<div data-testid="directory">{{catalog.statusLabel}}</div>' },
      } } })
      await flushPromises()
      expect(api.loadPreparation).toHaveBeenCalledWith('wiki-serving', 'preparation-g3', expect.any(Object))
      expect(api.load).not.toHaveBeenCalled()
      expect(api.loadActive).not.toHaveBeenCalled()
      expect(api.loadSchemaCatalog).not.toHaveBeenCalled()
      expect(wrapper.get('[data-testid="directory"]').text()).toBe(label)
      expect(wrapper.find('[data-testid="g3-catalog"]').exists()).toBe(true)
    },
  )

  it('renders a complete Active G3 directory while preserving normal G2 fallback', async () => {
    api.load.mockRejectedValue(new Error('not g2'))
    api.loadActive.mockResolvedValue({ ...common, mode: 'g3-active', releaseID: 'release-g3', activationEpoch: 6,
      catalog: { catalog_id: 'schema_catalog_insurance_product', entries: [] }, entities: [] })
    const wrapper = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
      ConceptDirectory830G2: { props: ['catalog'], template: '<div data-testid="directory">{{catalog.mode}}</div>' },
    } } })
    await flushPromises()
    expect(wrapper.get('[data-testid="directory"]').text()).toBe('g3-active')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('shares identical directory reads within a load and allows slow verified responses without retry', async () => {
    vi.mocked(get).mockClear()
    vi.mocked(get).mockImplementation((_path: string, options?: any) => {
      if ((options?.timeout ?? 30000) < 66000) return Promise.reject(new Error('timeout'))
      return Promise.resolve({ verified: true }) as any
    })
    api.loadActive.mockImplementation(async (_kb, transport) => {
      const reads = await Promise.all([transport.get('/fixed-search'), transport.get('/fixed-search')])
      expect(reads).toEqual([{ verified: true }, { verified: true }])
      return { ...common, mode: 'g3-active', catalog: { entries: [] }, entities: [] }
    })
    const wrapper = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
      ConceptDirectory830G2: { template: '<div data-testid="directory">G3</div>' },
    } } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(get).toHaveBeenCalledTimes(1)
    expect(vi.mocked(get).mock.calls[0][1]).toEqual({ timeout: 180000 })
    const transport = api.loadActive.mock.calls[0][1]
    vi.mocked(get).mockClear(); vi.mocked(get).mockRejectedValue(new Error('source unavailable'))
    await expect(transport.get('/failed-read')).rejects.toThrow('source unavailable')
    await expect(transport.get('/failed-read')).rejects.toThrow('source unavailable')
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('rejects ambiguous preparation query before any directory request', async () => {
    route.query = { tab: 'schema', preparation_id: ['preparation-g3', 'other'] }
    const wrapper = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' } })
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('目录读取失败')
    expect(api.loadPreparation).not.toHaveBeenCalled()
    expect(api.load).not.toHaveBeenCalled()
    expect(api.loadActive).not.toHaveBeenCalled()
  })

  it('uses the serving KB and renders only a complete G2 result', async () => {
    api.load.mockResolvedValue({ ...common, mode: 'g2', candidateHash: H, members: [], concepts: [], entities: [] })
    const wrapper = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
      ConceptDirectory830G2: { props: ['catalog'], template: '<div data-testid="g2">G2</div>' },
    } } })
    await flushPromises()
    expect(api.load).toHaveBeenCalledWith('wiki-serving', expect.any(Object))
    expect(api.loadSchemaCatalog).toHaveBeenCalledWith('wiki-serving', expect.any(Object))
    expect(wrapper.get('[data-testid="g3-catalog"]').text()).toBe('G3 Catalog')
    expect(wrapper.get('[data-testid="g2"]').text()).toBe('G2')
    expect(wrapper.findComponent({ name: 'SchemaWikiBrowser' }).exists()).toBe(false)
  })

  it('routes frozen G1 overview and pure schema releases without treating errors as legacy', async () => {
    api.load.mockResolvedValueOnce({ ...common, mode: 'entity-g1', entityID: 'entity-old' })
    const g1 = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
      RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' },
    } } })
    await flushPromises()
    expect(JSON.parse(g1.get('a').attributes('data-to')!)).toEqual({ name: 'entityPageOverview830G1',
      params: { kbId: 'wiki-serving', entityId: 'entity-old' }, query: { release_id: 'release-a' } })

    api.load.mockResolvedValueOnce({ ...common, mode: 'schema-legacy' })
    const legacy = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
      SchemaWikiBrowser: { props: ['knowledgeBaseId'], template: '<div data-testid="legacy">legacy</div>' },
    } } })
    await flushPromises()
    expect(legacy.get('[data-testid="legacy"]').text()).toBe('legacy')

    api.load.mockRejectedValueOnce(new Error('PIN_DRIFT'))
    const failed = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' } })
    await flushPromises()
    expect(failed.get('[role="alert"]').text()).toContain('目录读取失败')
    expect(failed.findComponent({ name: 'SchemaWikiBrowser' }).exists()).toBe(false)
  })

  it('keeps the published G2 directory visible when the protected G3 catalog fails closed', async () => {
    api.load.mockResolvedValue({ ...common, mode: 'g2', candidateHash: H, members: [], concepts: [], entities: [] })
    api.loadSchemaCatalog.mockRejectedValue(new Error('CATALOG_TAMPERED'))
    const wrapper = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
      ConceptDirectory830G2: { props: ['catalog'], template: '<div data-testid="g2">G2</div>' },
    } } })
    await flushPromises()

    expect(wrapper.get('[data-testid="g3-catalog-error"]').text()).toContain('产品结构目录读取失败')
    expect(wrapper.get('[data-testid="g2"]').text()).toBe('G2')
  })
})

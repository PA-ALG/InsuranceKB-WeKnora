// @vitest-environment happy-dom

import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ load: vi.fn() }))
vi.mock('@/api/schema-wiki/conceptDirectory830G2', () => ({ loadConceptDirectory830G2: api.load }))
vi.mock('@/utils/request', () => ({ get: vi.fn() }))
vi.mock('./SchemaWikiBrowser.vue', () => ({ default: {
  name: 'SchemaWikiBrowser', props: ['knowledgeBaseId'], template: '<div data-testid="legacy">legacy</div>',
} }))

import SchemaWikiCatalogEntry from './SchemaWikiCatalogEntry830G2.vue'

const H = 'a'.repeat(64)
const common = { scope: { version: 'schema-wiki-scope.v1', space_id: 'space', raw_kb_id: 'raw',
  wiki_kb_id: 'wiki-serving', scope_sha256: H }, releaseID: 'release-a', activationEpoch: 4 }

describe('SchemaWikiCatalogEntry830G2', () => {
  beforeEach(() => {
    api.load.mockReset()
    ;(window as any).__RUNTIME_CONFIG__ = { SCHEMA_WIKI_MVP_ENTRY_KB_ID: 'wiki-entry',
      SCHEMA_WIKI_MVP_SERVING_KB_ID: 'wiki-serving' }
  })

  it('uses the serving KB and renders only a complete G2 result', async () => {
    api.load.mockResolvedValue({ ...common, mode: 'g2', candidateHash: H, members: [], concepts: [], entities: [] })
    const wrapper = mount(SchemaWikiCatalogEntry, { props: { knowledgeBaseId: 'wiki-entry' }, global: { stubs: {
      ConceptDirectory830G2: { props: ['catalog'], template: '<div data-testid="g2">G2</div>' },
    } } })
    await flushPromises()
    expect(api.load).toHaveBeenCalledWith('wiki-serving', expect.any(Object))
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
})

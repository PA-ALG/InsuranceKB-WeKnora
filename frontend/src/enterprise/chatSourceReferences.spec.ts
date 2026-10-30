// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import ChatReferencesDrawer from '@/components/ChatReferencesDrawer.vue'
import ChatCitationFloat from '@/components/ChatCitationFloat.vue'
import DocInfo from '@/views/chat/components/docInfo.vue'
import { provideChatReferencesDrawer } from '@/composables/useChatReferencesDrawer'
import { useChatCitationPopover } from '@/composables/useChatCitationPopover'
import { buildReferenceList, resolveReferenceHighlightKey } from '@/utils/referenceSources'
import { preprocessCitationTags, resolveCitationChunkId } from '@/utils/citationMarkdown'
import { getChunkByIdOnly } from '@/api/knowledge-base'
import { chatSourceReferences as references } from './__tests__/chatSourceFixtures'

vi.mock('@/api/knowledge-base', () => ({ getChunkByIdOnly: vi.fn() }))
vi.mock('@/api/embed', () => ({ getEmbedChunkById: vi.fn() }))

const rawLabel = '原文检索（未经编译审核）'
const releaseLabel = '已发布知识（审核过）'
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; vi.useRealTimers(); vi.clearAllMocks() })

async function mountView(component: any, props: Record<string, unknown> = {}, drawer = false) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  const host = defineComponent({ setup() {
    if (drawer) provideChatReferencesDrawer().open({ references: references() })
    return () => h(component, props)
  } })
  const wrapper = mount(host, { global: {
    plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
    stubs: { Teleport: true, 't-icon': true, 't-tooltip': { template: '<span><slot /></span>' }, 't-popup': true },
  } })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

describe('chat reference provenance wiring', () => {
  it('keeps exact server chunk identities when the same title has several source tiers', () => {
    expect(resolveCitationChunkId('published', { doc: 'Policy' }, references())).toBe('published')
    expect(resolveCitationChunkId('raw-b', { doc: 'Policy' }, [
      { id: 'raw-a', chunk_ids: ['raw-a', 'raw-b'], knowledge_title: 'Policy' },
    ])).toBe('raw-b')
  })

  it('groups a document only within the same source tier and release', () => {
    const refs = references()
    const items = buildReferenceList(refs).filter(item => item.kind === 'document')
    expect(items).toHaveLength(4)
    expect(new Set(items.map(item => item.key)).size).toBe(4)
    expect(items[0].chunkIds).toEqual(['raw-a', 'raw-b'])
    expect(items[0].metadata).toEqual({ source_tier: 'raw_text', release_id: 'r1' })
    expect(items[0].content).not.toContain('reviewed')
    expect(resolveReferenceHighlightKey(refs, { chunkId: 'raw-old' })).toBe(items[1].key)
    expect(resolveReferenceHighlightKey(refs, { documentTitle: 'Policy' })).toBeNull()
  })

  it('shows separate source labels in the document list without labeling ordinary or web references', async () => {
    const view = await mountView(DocInfo, { session: { knowledge_references: references() }, contentOnly: true })
    const groups = view.findAll('.doc-group')
    expect(groups).toHaveLength(4)
    expect(groups[0].text()).toContain(rawLabel)
    expect(groups[1].text()).toContain(rawLabel)
    expect(groups[2].text()).toContain(releaseLabel)
    expect(groups[3].text()).not.toMatch(/未经编译审核|审核过/)
    expect(view.get('.doc-web').text()).not.toMatch(/未经编译审核|审核过/)
  })

  it('keeps source labels visible in drawer cards and preserves embedded navigation policy', async () => {
    const view = await mountView(ChatReferencesDrawer, { embeddedMode: true }, true)
    const cards = view.findAll('.reference-item--document')
    expect(cards).toHaveLength(4)
    expect(cards[0].text()).toContain(rawLabel)
    expect(cards[2].text()).toContain(releaseLabel)
    expect(cards[3].text()).not.toMatch(/未经编译审核|审核过/)
    expect(view.findAll('.reference-item__open')).toHaveLength(0)
    expect(view.get('.reference-item--web').text()).not.toMatch(/未经编译审核|审核过/)
  })

  it('derives hover labels from server references and ignores model attributes, including cached chunks', async () => {
    vi.useFakeTimers()
    vi.mocked(getChunkByIdOnly).mockResolvedValue({ data: { content: 'retrieved content' } } as any)
    const refs = ref(references())
    const content = ref('<kb doc="Policy" chunk_id="raw-a" source_tier="release" release_id="fake"/>')
    const host = defineComponent({ setup() {
      const root = ref<HTMLElement | null>(null)
      const { float } = useChatCitationPopover(root, { getKnowledgeReferences: () => refs.value, sessionId: () => 'provenance-test' })
      return () => h('div', [h('div', { ref: root, innerHTML: preprocessCitationTags(content.value, refs.value) }), h(ChatCitationFloat, { float: float.value })])
    } })
    const view = await mountView(host)
    const hover = async () => { await view.get('.citation-kb').trigger('mouseover'); await vi.advanceTimersByTimeAsync(80); await flushPromises() }
    await hover()
    expect(view.get('.chat-citation-float').text()).toContain(rawLabel)
    expect(view.get('.chat-citation-float').text()).not.toContain(releaseLabel)
    expect(view.get('.citation-kb').attributes('data-source-tier')).toBeUndefined()
    refs.value = refs.value.map(item => item.id === 'raw-a' ? { ...item, metadata: { source_tier: 'release', release_id: 'r2' } } : item)
    await hover()
    expect(view.get('.chat-citation-float').text()).toContain(releaseLabel)
    expect(getChunkByIdOnly).toHaveBeenCalledTimes(1)
    content.value = '<kb doc="Unknown" chunk_id="missing" source_tier="release"/>'
    await flushPromises(); await hover()
    expect(view.get('.chat-citation-float').text()).not.toMatch(/未经编译审核|审核过/)
    content.value = '<web url="https://example.com" title="Web" source_tier="release"/>'
    await flushPromises(); await view.get('.citation-web').trigger('mouseover'); await vi.advanceTimersByTimeAsync(40)
    expect(view.get('.chat-citation-float').text()).not.toMatch(/未经编译审核|审核过/)
  })
})

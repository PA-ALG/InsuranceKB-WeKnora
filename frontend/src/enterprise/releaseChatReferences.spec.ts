// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import ChatReferencesDrawer from '@/components/ChatReferencesDrawer.vue'
import ChatCitationFloat from '@/components/ChatCitationFloat.vue'
import { provideChatReferencesDrawer } from '@/composables/useChatReferencesDrawer'
import { useChatCitationPopover } from '@/composables/useChatCitationPopover'
import { preprocessCitationTags } from '@/utils/citationMarkdown'
import { getChunkByIdOnly } from '@/api/knowledge-base'
import { readCitation } from './enterpriseApi'

vi.mock('@/api/knowledge-base', () => ({ getChunkByIdOnly: vi.fn() }))
vi.mock('@/api/embed', () => ({ getEmbedChunkById: vi.fn() }))
vi.mock('./enterpriseApi', async importOriginal => ({ ...await importOriginal<object>(), readCitation: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); document.body.innerHTML = ''; vi.useRealTimers(); vi.clearAllMocks() })
const field = () => ({
  id: 'release:historic:item/field', knowledge_title: 'Product · Waiting period', content: '20 days',
  metadata: { source_tier: 'release', space_id: 'space-a', release_id: 'historic', logical_slug: 'item/field', evidence_index: '0' },
})
async function view(reference = field(), embeddedMode = false) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  const content = defineComponent({ setup() {
    const root = ref<HTMLElement | null>(null)
    const refs = [reference]
    const { float } = useChatCitationPopover(root, { getKnowledgeReferences: () => refs, sessionId: () => 'release-reference' })
    return () => h('div', [h('div', { ref: root, innerHTML: preprocessCitationTags(`<kb doc="Product" chunk_id="${reference.id}"/>`, refs) }),
      h(ChatCitationFloat, { float: float.value }), h(ChatReferencesDrawer, { embeddedMode })])
  } })
  const host = defineComponent({ setup() { provideChatReferencesDrawer(); return () => h(content) } })
  const wrapper = mount(host, { attachTo: document.body, global: {
    plugins: [router, createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
    stubs: { Teleport: true, 't-icon': true, SourcePageViewer: true },
  } })
  wrappers.push(wrapper); await flushPromises(); return wrapper
}

describe('published knowledge chat interaction', () => {
  it('previews persisted fields without chunk requests and opens the exact historical evidence', async () => {
    vi.useFakeTimers()
    vi.mocked(readCitation).mockResolvedValue({ quote: 'source quote', source: { document: 'Source.pdf' }, page: { number: 4 }, highlight: { rects: [], complete: true }, file: {} } as any)
    const wrapper = await view()
    await wrapper.get('.citation-kb').trigger('mouseover'); await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(wrapper.get('.chat-citation-float').text()).toContain('Product · Waiting period')
    expect(wrapper.get('.chat-citation-float').text()).toContain('20 days')
    expect(getChunkByIdOnly).not.toHaveBeenCalled()
    await wrapper.get('.citation-kb').trigger('click'); await flushPromises()
    expect(readCitation).toHaveBeenCalledWith('space-a', 'historic', 'item/field', 0)
    expect(wrapper.text()).toContain('source quote')
    expect(getChunkByIdOnly).not.toHaveBeenCalled()
  })
  it('does not fall back when a release reference has incomplete metadata', async () => {
    vi.useFakeTimers()
    const reference = field(); delete (reference.metadata as any).evidence_index
    const wrapper = await view(reference)
    await wrapper.get('.citation-kb').trigger('mouseover'); await vi.advanceTimersByTimeAsync(80); await flushPromises()
    expect(wrapper.get('.chat-citation-float__error').text()).toBeTruthy()
    await wrapper.get('.citation-kb').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(readCitation).not.toHaveBeenCalled(); expect(getChunkByIdOnly).not.toHaveBeenCalled()
  })
  it('keeps a failed exact citation retryable without changing release', async () => {
    vi.mocked(readCitation).mockRejectedValue(new Error('unavailable'))
    const wrapper = await view()
    await wrapper.get('.citation-kb').trigger('click'); await flushPromises()
    expect(wrapper.find('.ek-alert').exists()).toBe(true)
    await wrapper.get('.ek-alert button').trigger('click'); await flushPromises()
    expect(readCitation).toHaveBeenCalledTimes(2)
    expect(readCitation).toHaveBeenLastCalledWith('space-a', 'historic', 'item/field', 0)
    expect(getChunkByIdOnly).not.toHaveBeenCalled()
  })
  it('shows the existing authorization boundary for embedded references', async () => {
    const wrapper = await view(field(), true)
    await wrapper.get('.citation-kb').trigger('click'); await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(readCitation).not.toHaveBeenCalled(); expect(getChunkByIdOnly).not.toHaveBeenCalled()
  })
})

// @vitest-environment happy-dom
import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createPinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import AgentStreamDisplay from './AgentStreamDisplay.vue'
import ChatReferencesDrawer from '@/components/ChatReferencesDrawer.vue'
import { provideChatReferencesDrawer, type ChatReferencesDrawerContext } from '@/composables/useChatReferencesDrawer'
import { getChunkByIdOnly } from '@/api/knowledge-base'
import { clearCitationChunkCache } from '@/utils/citationChunkCache'

vi.mock('@/api/knowledge-base', async original => ({
  ...(await original<typeof import('@/api/knowledge-base')>()), getChunkByIdOnly: vi.fn(),
}))

vi.mock('@/utils/mermaidShared', () => ({
  appendMermaidSvgCache: vi.fn(), createMermaidCodeRenderer: vi.fn(() => () => ''),
  ensureMermaidInitialized: vi.fn(), enhanceMarkdownContainer: vi.fn(),
}))

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); clearCitationChunkCache(); vi.useRealTimers(); vi.clearAllMocks() })

async function mountAgent(toolName: string, historicalAnswer = false, faq = false) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  let drawer!: ChatReferencesDrawerContext
  const results = faq ? [{
    faq_id: '7aa0c635-c828-4809-a8fd-6e1fd94c7a51', result_index: 1, index: 0,
    knowledge_id: 'faq-policy', knowledge_title: 'FAQ Policy', faq_standard_question: 'How is a claim filed?',
    content: 'Submit the claim form.', metadata: { source_tier: 'raw_text', release_id: 'r1' },
  }] : [
    { chunk_id: 'raw-1', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'raw 1', metadata: { source_tier: 'raw_text', release_id: 'r1' } },
    { chunk_id: 'raw-2', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'raw 2', metadata: { source_tier: 'raw_text', release_id: 'r1' } },
    { chunk_id: 'published', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'published', metadata: { source_tier: 'release', release_id: 'r1' } },
    { chunk_id: 'old', knowledge_id: 'policy', knowledge_title: 'Policy', content: 'old', metadata: { source_tier: 'raw_text', release_id: 'r0' } },
  ]
  const host = defineComponent({ setup() {
    drawer = provideChatReferencesDrawer()
    return () => h('div', [h(AgentStreamDisplay, { session: { id: 'restored', is_completed: historicalAnswer, agentEventStream: [
      { type: 'tool_call', tool_name: toolName, tool_call_id: 'search', pending: false, success: true, tool_data: { results } },
      ...(historicalAnswer ? [{ type: 'answer', done: true, content: faq
        ? 'Answer <kb doc="How is a claim filed?" chunk_id="7aa0c635-c828-4809-a8fd-6e1fd94c7a51" source_tier="release"/>'
        : 'Answer <kb doc="Policy" chunk_id="raw-2" source_tier="release"/>' }] : []),
    ] } }), ...(faq ? [h(ChatReferencesDrawer)] : [])])
  } })
  const wrapper = mount(host, { global: {
    plugins: [router, createPinia(), createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
    stubs: {
      't-icon': true, 't-tooltip': { template: '<span><slot /></span>' },
      't-button': true, 't-popconfirm': true, 't-tag': true, 't-link': true, 't-drawer': true,
      Teleport: true,
      ChatRequestInfoButton: true, ToolResultRenderer: true, ChatArtifactsDrawer: true,
      SandboxCommandProgress: true, BrowserToolDetails: true, picturePreview: true,
    },
  } })
  wrappers.push(wrapper)
  await flushPromises()
  return { wrapper, drawer, results }
}

it.each(['search_knowledge', 'knowledge_search'])('restores %s references with metadata, chunk identities and separate releases', async toolName => {
  const { wrapper, drawer, results } = await mountAgent(toolName)
  await wrapper.get('.reference-trigger').trigger('click')
  expect(drawer.references.value).toHaveLength(3)
  expect(drawer.references.value.map(item => item.metadata)).toEqual([results[0].metadata, results[2].metadata, results[3].metadata])
  expect(drawer.references.value[0].chunk_ids).toEqual(['raw-1', 'raw-2'])
  expect(drawer.references.value[0].content).not.toContain('published')
})

it('uses historical tool metadata for citation hover and drawer when aggregate references are absent', async () => {
  vi.mocked(getChunkByIdOnly).mockResolvedValue({ data: { content: 'raw second chunk' } } as any)
  const { wrapper, drawer } = await mountAgent('search_knowledge', true)
  vi.useFakeTimers()
  await wrapper.get('.citation-kb').trigger('mouseover')
  await vi.advanceTimersByTimeAsync(80)
  await flushPromises()
  expect(wrapper.get('.chat-citation-float').text()).toContain('原文检索（未经编译审核）')
  expect(wrapper.get('.chat-citation-float').text()).not.toContain('已发布知识（审核过）')
  expect(getChunkByIdOnly).toHaveBeenCalledWith('raw-2')
  await wrapper.get('.citation-kb').trigger('click')
  expect(drawer.highlight.value?.chunkId).toBe('raw-2')
  expect(drawer.references.value).toHaveLength(3)
  expect(drawer.references.value[0].metadata?.source_tier).toBe('raw_text')
})

it.each(['search_knowledge', 'knowledge_search'])('restores real FAQ IDs from %s payloads for historical hover and citation clicks', async toolName => {
  vi.mocked(getChunkByIdOnly).mockResolvedValue({ data: { content: 'Submit the claim form.' } } as any)
  const { wrapper, drawer } = await mountAgent(toolName, true, true)
  vi.useFakeTimers()
  await wrapper.get('.citation-kb').trigger('mouseover')
  await vi.advanceTimersByTimeAsync(80)
  await flushPromises()
  expect(wrapper.get('.chat-citation-float').text()).toContain('原文检索（未经编译审核）')
  expect(wrapper.get('.chat-citation-float').text()).not.toContain('已发布知识（审核过）')
  expect(getChunkByIdOnly).toHaveBeenCalledWith('7aa0c635-c828-4809-a8fd-6e1fd94c7a51')
  await wrapper.get('.citation-kb').trigger('click')
  expect(drawer.highlight.value?.chunkId).toBe('7aa0c635-c828-4809-a8fd-6e1fd94c7a51')
  expect(drawer.references.value).toHaveLength(1)
  expect(drawer.references.value[0]).toMatchObject({
    id: '7aa0c635-c828-4809-a8fd-6e1fd94c7a51', chunk_ids: ['7aa0c635-c828-4809-a8fd-6e1fd94c7a51'],
    chunk_type: 'faq', metadata: { source_tier: 'raw_text', release_id: 'r1' },
  })
  expect(wrapper.get('.reference-item--document').text()).toContain('原文检索（未经编译审核）')
  expect(wrapper.get('.reference-item--document').text()).not.toContain('已发布知识（审核过）')
})

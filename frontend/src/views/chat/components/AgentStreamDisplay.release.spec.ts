// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createPinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import AgentStreamDisplay from './AgentStreamDisplay.vue'
import { provideChatReferencesDrawer, type ChatReferencesDrawerContext } from '@/composables/useChatReferencesDrawer'
import { getChunkByIdOnly } from '@/api/knowledge-base'
import { publishedKnowledgeTools } from '@/enterprise/releaseReferences'

vi.mock('@/api/knowledge-base', async original => ({ ...(await original<object>()), getChunkByIdOnly: vi.fn() }))
vi.mock('@/utils/mermaidShared', () => ({ appendMermaidSvgCache: vi.fn(), createMermaidCodeRenderer: vi.fn(() => () => ''), ensureMermaidInitialized: vi.fn(), enhanceMarkdownContainer: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); vi.useRealTimers(); vi.clearAllMocks() })

it.each(publishedKnowledgeTools)('restores %s metadata into the list, hover and keyboard citation drawer', async toolName => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  // The page tool cites model-written page members under their own tier (S6e).
  const page = toolName === 'knowledge_search_pages'
  const member = page ? 'wiki/product/concept/field' : 'product/field'
  const id = `release:historic:${member}`
  const metadata = { source_tier: page ? 'wiki_page' : 'release', space_id: 'space-a', release_id: 'historic', logical_slug: member, evidence_index: '0' }
  let drawer!: ChatReferencesDrawerContext
  const host = defineComponent({ setup() {
    drawer = provideChatReferencesDrawer()
    return () => h(AgentStreamDisplay, { session: { id: 'historical', is_completed: true, agentEventStream: [
      { type: 'tool_call', tool_name: toolName, tool_call_id: 'published', pending: false, success: true, tool_data: {
        display_type: 'search_results', results: [{ chunk_id: id, knowledge_title: 'Product · Field', content: '20 days', metadata }],
      } },
      { type: 'answer', done: true, content: `Answer <kb doc="Product · Field" chunk_id="${id}"/>` },
    ] } })
  } })
  const wrapper = mount(host, { global: { plugins: [router, createPinia(), createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: {
    't-icon': true, 't-tooltip': { template: '<span><slot /></span>' }, 't-button': true, 't-popconfirm': true, 't-tag': true, 't-link': true, 't-drawer': true,
    Teleport: true, ChatRequestInfoButton: true, ToolResultRenderer: true, ChatArtifactsDrawer: true, SandboxCommandProgress: true, BrowserToolDetails: true, picturePreview: true,
  } } })
  wrappers.push(wrapper); await flushPromises()
  await wrapper.get('.tree-root .action-header').trigger('click'); await flushPromises()
  const labelKeys: Record<string, keyof typeof zhCN.chat> = {
    knowledge_find_entity: 'knowledgeFindEntity', knowledge_get_fields: 'knowledgeGetFields',
    knowledge_search_fields: 'knowledgeSearchFields', knowledge_get_concept: 'knowledgeGetConcept',
    knowledge_search_pages: 'knowledgeSearchPages',
  }
  expect(wrapper.get('.tree-children .tool-event .action-name').text()).toBe(zhCN.chat[labelKeys[toolName]!])
  await wrapper.get('.reference-trigger').trigger('click')
  expect(drawer.references.value).toEqual([{ id, knowledge_title: 'Product · Field', content: '20 days', metadata }])
  drawer.close()
  vi.useFakeTimers()
  await wrapper.get('.citation-kb').trigger('mouseover'); await vi.advanceTimersByTimeAsync(80); await flushPromises()
  expect(wrapper.get('.chat-citation-float').text()).toContain('20 days')
  await wrapper.get('.citation-kb').trigger('keydown', { key: 'Enter' })
  expect(drawer.highlight.value?.chunkId).toBe(id)
  expect(drawer.references.value[0]?.metadata).toEqual(metadata)
  expect(getChunkByIdOnly).not.toHaveBeenCalled()
})

it.each([
  ['knowledge_find_entity', { results: [], count: 0, total: 2, notes: ['产品编号：A', '产品编号：B'] }, '找到 2 个结果'],
  ['knowledge_get_fields', { results: [], count: 0, total: 1, notes: ['等待期：unknown（无可回验出处）'] }, '找到 1 个结果'],
  ['knowledge_get_concept', { results: [], count: 0, total: 0, notes: ['模型补充（概念说明）：术语说明'] }, '已返回说明'],
  ['knowledge_search_fields', { results: [], count: 0, total: 0, notes: [] }, zhCN.agentStream.search.noResults],
])('summarizes %s independently of citable source count', async (toolName, toolData, summary) => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  const wrapper = mount(AgentStreamDisplay, { props: { session: { id: 'notes', is_completed: true, agentEventStream: [
    { type: 'tool_call', tool_name: toolName, pending: false, success: true, tool_data: toolData },
  ] } }, global: { plugins: [router, createPinia(), createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })], stubs: {
    't-icon': true, 't-tooltip': { template: '<span><slot /></span>' }, 't-button': true, 't-tag': true, 't-popconfirm': true, 't-link': true, 't-drawer': true,
    picturePreview: true, ChatRequestInfoButton: true, ToolResultRenderer: true, ChatArtifactsDrawer: true, SandboxCommandProgress: true,
  } } })
  wrappers.push(wrapper); await flushPromises()
  await wrapper.get('.tree-root .action-header').trigger('click'); await flushPromises()
  expect(wrapper.get('.results-summary-text').text()).toBe(summary)
})

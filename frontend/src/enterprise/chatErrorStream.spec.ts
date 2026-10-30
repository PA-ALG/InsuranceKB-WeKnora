// @vitest-environment happy-dom
import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { reactive, ref } from 'vue'
import { createPinia } from 'pinia'
import { createI18n } from 'vue-i18n'
import { createMemoryHistory, createRouter } from 'vue-router'
import { MessagePlugin } from 'tdesign-vue-next'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import Chat from '@/views/chat/index.vue'
import { useChatStreamHandler, type ChatMessage } from '@/composables/useChatStreamHandler'

const stream = vi.hoisted(() => ({ chunk: undefined as undefined | ((data: ChatMessage) => void) }))
const transportError = ref<string | null>(null)
vi.mock('@/api/chat/streame', () => ({ useStream: () => ({
  error: transportError, isStreaming: ref(false), lastStreamRequest: ref(null),
  onChunk: (callback: typeof stream.chunk) => { stream.chunk = callback },
  startStream: vi.fn(), stopStream: vi.fn(),
}) }))
vi.mock('@/api/chat/index', () => ({
  getSession: vi.fn(async () => ({ data: {} })),
  getMessageList: vi.fn(async () => ({ data: [] })),
  forkSession: vi.fn(), rewindSession: vi.fn(),
}))
vi.mock('@/api/chat/steer', () => ({ listSteerSession: vi.fn(async () => ({ items: [] })),
  promoteSteerSession: vi.fn(), removeSteerSession: vi.fn(), steerSession: vi.fn() }))
vi.mock('@/api/agent/index', async original => ({ ...(await original<object>()),
  getSuggestedQuestions: vi.fn(async () => ({ data: [] })) }))
vi.mock('@/api/message-suggestion', () => ({ ensureMessageSuggestions: vi.fn(),
  getMessageSuggestions: vi.fn(async () => ({ data: [] })), recordMessageSuggestionEvent: vi.fn() }))
vi.mock('@/utils/mermaidShared', () => ({ createMermaidCodeRenderer: vi.fn(() => () => ''),
  ensureMermaidInitialized: vi.fn(), enhanceMarkdownContainer: vi.fn(), appendMermaidSvgCache: vi.fn() }))

const wrappers: ReturnType<typeof shallowMount>[] = []
beforeEach(() => {
  transportError.value = null
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  vi.spyOn(MessagePlugin, 'error').mockResolvedValue({} as never)
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.restoreAllMocks()
})
const i18n = () => createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })
const raw = 'RELEASE_MANAGED_KB: server diagnostic'
const friendly = '这个知识库由发布版本管理，不能直接检索。请在企业知识中选择对应 Space 的原始材料库或 Wiki 库提问，或改用智能推理模式。'

it.each([undefined, {}])('writes guidance to the real handler message and callback (payload %s)', data => {
  const messagesList = reactive<ChatMessage[]>([])
  const onError = vi.fn(), loading = ref(true), isReplying = ref(true)
  let handler!: ReturnType<typeof useChatStreamHandler>
  const wrapper = shallowMount({ setup() {
    handler = useChatStreamHandler({ messagesList, loading, isReplying,
      currentAssistantMessageId: ref('assistant'), fullContent: ref(''),
      isAgentStreamSession: () => false, scrollToBottom: vi.fn(), onError })
    return () => null
  } }, { global: { plugins: [i18n()] } })
  wrappers.push(wrapper)
  handler.processStreamChunk({ id: 'request', response_type: 'agent_query', assistant_message_id: 'assistant' })
  handler.processStreamChunk({ id: 'request', response_type: 'error', content: raw, data })
  expect(messagesList[0]).toMatchObject({ content: friendly, is_completed: true })
  expect(onError).toHaveBeenCalledWith(friendly)
  expect(console.error).toHaveBeenCalledWith('[Chat Error]', raw)
  expect([loading.value, isReplying.value]).toEqual([false, false])
})

it.each([raw, 'network timeout', 'RELEASE_MANAGED_KBX: other'])('uses the chat page SSE and transport error paths: %s', async error => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
  await router.push('/')
  const wrapper = shallowMount(Chat, { props: { session_id: 'test-session', embeddedMode: true },
    global: { plugins: [createPinia(), i18n(), router] } })
  wrappers.push(wrapper)
  await flushPromises()
  stream.chunk!({ id: 'request', response_type: 'agent_query', assistant_message_id: 'assistant' })
  stream.chunk!({ id: 'request', response_type: 'error', content: error })
  await flushPromises()
  const expected = error === raw ? friendly : error
  expect(MessagePlugin.error).toHaveBeenLastCalledWith(expected)
  // Observe the actual page's message passed to its renderer, not just the helper.
  expect(wrapper.findComponent({ name: 'botmsg' }).props('session').content).toBe(expected)
  transportError.value = error
  await flushPromises()
  expect(MessagePlugin.error).toHaveBeenLastCalledWith(expected)
  expect(console.error).toHaveBeenCalledWith('[Chat Error]', error)
})

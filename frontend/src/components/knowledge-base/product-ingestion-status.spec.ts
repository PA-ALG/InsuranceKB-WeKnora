// @vitest-environment happy-dom
import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ listProductIngestions: vi.fn(), getProductIngestion: vi.fn(), retryProductFields: vi.fn() }))
vi.mock('@/api/product-ingestion', () => api)
const modules = import.meta.glob('./product-ingestion-status.vue')
const mounted: ReturnType<typeof mount>[] = []
async function render() {
  expect(modules['./product-ingestion-status.vue'], 'persistent product status component must exist').toBeTypeOf('function')
  const component: any = await modules['./product-ingestion-status.vue']!()
  const wrapper = mount(component.default, { props: { knowledgeBaseId: 'kb', refreshToken: 0 } })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}
const run = (extra = {}) => ({ run_id: 'r1', wiki_knowledge_base_id: 'kb', state: 'partial_success', stage: 'publish', stages: [{ name: 'extraction', state: 'succeeded', started_at: '2026-09-13T00:00:00Z', finished_at: '2026-09-13T00:00:05Z', success_count: 2, missing_count: 1, failure_count: 1 }], counts: { success_count: 2, missing_count: 1, failure_count: 1 }, model_call_count: 3, started_at: '2026-09-13T00:00:00Z', finished_at: '2026-09-13T00:00:10Z', fields: [{ field_key: 'premium', outcome: 'extraction_failed', reason: 'EVIDENCE_INVALID', value: 'UNVERIFIED_SECRET' }, { field_key: 'age', outcome: 'not_provided', reason: '材料未提供' }], ...extra })

describe('persistent product processing status', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-09-13T00:01:00Z')); api.listProductIngestions.mockResolvedValue([run()]) })
  afterEach(() => { mounted.splice(0).forEach(w => w.unmount()); vi.useRealTimers() })
  it('restores server stages, counts and partial terminal without exposing values', async () => {
    const w = await render()
    expect(api.listProductIngestions).toHaveBeenCalledWith('kb')
    expect(w.text()).toContain('部分完成')
    expect(w.text()).toContain('5 秒')
    expect(w.text()).toContain('10 秒')
    expect(w.text()).toContain('EVIDENCE_INVALID')
    expect(w.text()).not.toContain('UNVERIFIED_SECRET')
    expect(w.findAll('input[type="checkbox"]')).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(api.getProductIngestion).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('shows missing statistics and terminal timestamps as unknown, not zero or live time', async () => {
    api.listProductIngestions.mockResolvedValue([run({ counts: undefined, model_call_count: undefined, finished_at: undefined, stages: [] })])
    const w = await render()
    expect(w.get('[data-testid="counts"]').text()).toContain('成功 —')
    expect(w.get('[data-testid="run-duration"]').text()).toBe('耗时 —')
    expect(vi.getTimerCount()).toBe(0)
  })
  it('polls active runs until terminal and stops timers', async () => {
    api.listProductIngestions.mockResolvedValue([run({ state: 'running', finished_at: undefined })])
    api.getProductIngestion.mockResolvedValue(run({ state: 'succeeded' }))
    const w = await render()
    expect(w.get('[data-testid="run-duration"]').text()).toContain('1 分')
    await vi.advanceTimersByTimeAsync(2100)
    await flushPromises()
    expect(api.getProductIngestion).toHaveBeenCalledTimes(1)
    expect(w.text()).toContain('已完成')
    expect(vi.getTimerCount()).toBe(0)
  })
  it.each([['accepting_uploads', '接收材料'], ['awaiting_sources', '等待材料解析']])('shows server state %s in Chinese', async (state, label) => {
    api.listProductIngestions.mockResolvedValue([run({ state, finished_at: undefined, stage: undefined })])
    expect((await render()).text()).toContain(label)
  })
  it.each([['failed', '处理失败'], ['needs_confirmation', '需要确认']])('stops for terminal %s', async (state, label) => {
    api.listProductIngestions.mockResolvedValue([run({ state })])
    expect((await render()).text()).toContain(label)
    expect(vi.getTimerCount()).toBe(0)
  })
  it('retries only checked failures and shows the returned new run', async () => {
    api.retryProductFields.mockResolvedValue(run({ run_id: 'r2', state: 'created', fields: [], finished_at: undefined }))
    const w = await render()
    const retry = w.get('[data-testid="retry-fields"]')
    expect(retry.attributes('disabled')).toBeDefined()
    await w.get('input[type="checkbox"]').setValue(true)
    await retry.trigger('click')
    await flushPromises()
    expect(api.retryProductFields).toHaveBeenCalledWith('kb', 'r1', ['premium'])
    expect(w.findAll('[data-testid="product-run"]')).toHaveLength(2)
  })
  it.each(['javascript:alert(1)', '//evil.example/x', 'https://evil.example/x', '/platform/knowledge-bases/kb/../../settings'])('rejects unsafe publication URL %s', async url => {
    api.listProductIngestions.mockResolvedValue([run({ published_url: url })])
    expect((await render()).find('a').exists()).toBe(false)
  })
  it('links the published platform product', async () => {
    const url = '/platform/knowledge-bases/kb/schema-wiki/entities/e/overview'
    api.listProductIngestions.mockResolvedValue([run({ published_url: url })])
    expect((await render()).get('a').attributes('href')).toBe(url)
  })
  it('links the configured serving Wiki when its ID differs from the uploaded Raw KB', async () => {
    const url = '/platform/knowledge-bases/wiki-serving/schema-wiki/entities/e/overview'
    api.listProductIngestions.mockResolvedValue([run({ wiki_knowledge_base_id: 'wiki-serving', published_url: url })])
    expect((await render()).get('a').attributes('href')).toBe(url)
  })
  it.each([undefined, 'other-wiki'])('does not infer a published target when serving identity is %s', async wikiId => {
    api.listProductIngestions.mockResolvedValue([run({ wiki_knowledge_base_id: wikiId, published_url: '/platform/knowledge-bases/kb/schema-wiki' })])
    expect((await render()).find('a').exists()).toBe(false)
  })
  it('labels the actual extract stage', async () => {
    api.listProductIngestions.mockResolvedValue([run({ stage: 'extract', stages: [] })])
    expect((await render()).text()).toContain('抽取字段')
  })
  it('shows persisted source phase times and incomplete counts without invented zeroes', async () => {
    api.listProductIngestions.mockResolvedValue([run({ model_call_count_complete: false, source_processing: { materials: [
      { knowledge_id: 'new', file_name: '保险条款.pdf', reused: false, counts: { attempts: 2 }, phases: [
        { phase: 'docreader', recorded: true, occurrences: [{ occurrence: 0, status: 'done', duration_ms: 12500 }] },
        { phase: 'embedding', recorded: false, occurrences: [] },
      ] },
      { knowledge_id: 'old', file_name: '费率表.pdf', reused: true, counts: null, phases: [] },
    ] } })])
    const text = (await render()).text()
    expect(text).toContain('部分阶段统计尚未齐全')
    expect(text).toContain('保险条款.pdf')
    expect(text).toContain('12.5 秒')
    expect(text).toContain('未记录')
    expect(text).toContain('复用已有解析 · 模型调用尝试 —')
  })
  it('ignores stale responses after knowledge base navigation', async () => {
    let resolve!: (value: any) => void
    api.listProductIngestions.mockImplementationOnce(() => new Promise(r => { resolve = r })).mockResolvedValueOnce([run({ run_id: 'new-kb-run' })])
    const w = await render()
    await w.setProps({ knowledgeBaseId: 'other' })
    await flushPromises()
    resolve([run()]); await flushPromises()
    expect(w.text()).toContain('new-kb-run')
    expect(w.text()).not.toContain('r1')
  })
})

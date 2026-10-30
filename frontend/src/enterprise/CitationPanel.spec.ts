// @vitest-environment happy-dom
// S3d-3a acceptance (protected, written by Claude): one evidence of one member of an explicit
// release, shown with its quote and the cited page; a failure is a typed message, never another
// page (Spec docs/design/slices/S3d-3a-企业知识页面.md §3.3).
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readCitation: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import SourcePageViewer from './SourcePageViewer.vue'
import { EnterpriseError, readCitation, type Citation } from './enterpriseApi'

const FILE = '/api/v1/enterprise/spaces/demo/view/releases/rel-1/sources/k-1/attempts/2/file'

function citation(quote = '等待期为90日。', page = 6): Citation {
  return {
    release_id: 'rel-1', member: 'P1/f_wait', evidence_index: 1, origin: 'SOURCE_SUPPORTED',
    source: { knowledge_id: 'k-1', parse_attempt: 2, document: '保险条款.pdf', file_sha256: 'a'.repeat(64) },
    page: { number: page, width_points: '595.32', height_points: '841.92' },
    start: 10, end: 17, quote,
    highlight: { coordinate_space: 'normalized_0_1e6_top_left', complete: false, rects: [[100000, 200000, 400000, 250000]] },
    file: FILE,
  }
}

function panel(props: Record<string, unknown> = {}) {
  return mount(CitationPanel, {
    props: { spaceId: 'demo', releaseId: 'rel-1', member: 'P1/f_wait', evidence: 1, ...props },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { SourcePageViewer: true },
    },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(ok => { resolve = ok })
  return { promise, resolve }
}

afterEach(() => { vi.resetAllMocks() })

describe('citation panel', () => {
  it('reads the named evidence and shows its document, page, quote and highlighted page', async () => {
    vi.mocked(readCitation).mockResolvedValue(citation())
    const view = panel()
    expect(view.find('[role="status"]').exists()).toBe(true)
    await flushPromises()
    expect(vi.mocked(readCitation).mock.calls).toEqual([['demo', 'rel-1', 'P1/f_wait', 1]])
    expect(view.text()).toContain('保险条款.pdf')
    expect(view.text()).toContain('第 6 页')
    expect(view.text()).toContain('等待期为90日。')
    expect(view.get('[data-origin]').text()).toBe('原文依据')
    expect(view.getComponent(SourcePageViewer).props()).toEqual({
      file: FILE,
      page: 6,
      rects: [[100000, 200000, 400000, 250000]],
      complete: false,
      labels: {
        loading: '正在打开原文…',
        failed: '原文页无法显示',
        retry: '重试',
        incomplete: '高亮可能不完整',
        region: '保险条款.pdf 第 6 页',
      },
    })
  })

  it.each([
    ['EVIDENCE_MISMATCH', '原文已变化，无法回跳'],
    ['RELEASE_NOT_FOUND', '找不到被引用的原文'],
    ['MEMBER_NOT_FOUND', '找不到被引用的原文'],
    ['EVIDENCE_NOT_FOUND', '找不到被引用的原文'],
    ['SOURCE_NOT_FOUND', '找不到被引用的原文'],
    ['EVIDENCE_UNSUPPORTED', '这类出处暂不支持打开'],
    ['SOURCE_INTEGRITY', '出处无法打开'],
  ])('explains %s without showing any page', async (code, message) => {
    vi.mocked(readCitation).mockRejectedValue(new EnterpriseError(code))
    const view = panel()
    await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain(message)
    expect(view.findComponent(SourcePageViewer).exists()).toBe(false)
  })

  it('retries the same evidence', async () => {
    vi.mocked(readCitation).mockRejectedValueOnce(new EnterpriseError('REQUEST_FAILED')).mockResolvedValueOnce(citation())
    const view = panel()
    await flushPromises()
    await view.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(vi.mocked(readCitation).mock.calls).toEqual([
      ['demo', 'rel-1', 'P1/f_wait', 1],
      ['demo', 'rel-1', 'P1/f_wait', 1],
    ])
    expect(view.findComponent(SourcePageViewer).exists()).toBe(true)
  })

  it('shows only the latest evidence when another is opened while loading', async () => {
    const first = deferred<Citation>()
    const second = deferred<Citation>()
    vi.mocked(readCitation).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const view = panel({ evidence: 0 })
    await flushPromises()
    await view.setProps({ evidence: 1 })
    second.resolve(citation('第二段引文', 7))
    await flushPromises()
    first.resolve(citation('第一段引文', 6))
    await flushPromises()
    expect(vi.mocked(readCitation).mock.calls.map(call => call[3])).toEqual([0, 1])
    expect(view.text()).toContain('第二段引文')
    expect(view.text()).not.toContain('第一段引文')
    expect(view.getComponent(SourcePageViewer).props('page')).toBe(7)
  })
})

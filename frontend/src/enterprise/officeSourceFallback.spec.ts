// @vitest-environment happy-dom
// S11h acceptance (protected, written by Claude): when upstream's preview fails, stays silent for
// 30 seconds, cannot find the quote or can only mark the whole slide, the citation still shows the
// cited slide, block or row as text with the quote marked, and offers the original file (Spec
// docs/design/slices/S11h-Office渲染失败时的文本视图.md §2.2).
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('@/utils/request', () => ({ get: vi.fn() }))
// The preview gets rebuilt bytes; the text view and the download must get the downloaded ones.
vi.mock('./officePackage', async importOriginal => ({
  ...(await importOriginal<typeof import('./officePackage')>()),
  sanitizeOfficePackage: vi.fn(async () => new Uint8Array([9, 9]).buffer),
}))
vi.mock('@/components/document-preview.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'DocumentPreview',
      props: { sourceBlob: Object, fileType: String, fileName: String, active: Boolean, sourceMode: Boolean, locate: Object },
      emits: ['located'],
      setup: () => () => h('div', { 'data-upstream-preview': '' }),
    }),
  }
})
vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readCitation: vi.fn(),
}))

import { get } from '@/utils/request'
import CitationPanel from './CitationPanel.vue'
import OfficeSourceViewer from './OfficeSourceViewer.vue'
import OfficeTextView from './OfficeTextView.vue'
import { readCitation, type Citation } from './enterpriseApi'
import { officeTarget } from './officeCitation'
import { OfficePackageRejected, sanitizeOfficePackage } from './officePackage'
import enUS from './i18n/messages/en-US'
import jaJP from './i18n/messages/ja-JP'
import koKR from './i18n/messages/ko-KR'
import ruRU from './i18n/messages/ru-RU'
import zhCNMessages from './i18n/messages/zh-CN'
import { deck, manual, textBox, workbook, wp } from './__tests__/officeTextFixtures'

const FILE = '/api/v1/enterprise/spaces/demo/view/releases/rel-1/sources/k-1/attempts/2/file'
const BYTES = [80, 75, 3, 4]
const QUOTE = '犹豫期为十五日'
const TARGET = officeTarget({ kind: 'PPTX_SHAPE', slide: 2 }, QUOTE)!
const viewerLabels = {
  loading: '正在打开原文…', failed: '原文页无法显示', retry: '重试', coarse: '已标出引文所在的位置，未能逐字高亮',
  notLocated: '未能在原文中定位这段引文，请对照上方引文', unsafe: '原文件含有无法安全显示的内容，未打开，请对照上方引文',
  region: '演示.pptx 第 2 张幻灯片',
}
const textLabels = {
  title: 'TITLE', failed: 'REASON-FAILED', stalled: 'REASON-STALLED', notLocated: 'REASON-NOT-LOCATED',
  loading: 'LOADING', empty: 'EMPTY', unavailable: 'UNAVAILABLE', quoteMissing: 'QUOTE-MISSING', download: 'DOWNLOAD', notes: 'NOTES',
}

enableAutoUnmount(afterEach)
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.resetAllMocks()
})

/** The viewer with a fallback slot that reports what it was handed. */
function viewer(arrange = () => {}, target = TARGET) {
  vi.mocked(get).mockResolvedValue(new Uint8Array(BYTES).buffer as any)
  arrange()
  return mount(OfficeSourceViewer, {
    props: { file: FILE, document: `演示.${target.format}`, target, labels: viewerLabels },
    slots: {
      fallback: (slot: { reason: string; original: ArrayBuffer }) =>
        h('div', { 'data-fallback': slot.reason, 'data-bytes': [...new Uint8Array(slot.original)].join(',') }),
    },
  })
}

const fallback = (view: ReturnType<typeof viewer>) => view.find('[data-fallback]')
const preview = (view: ReturnType<typeof viewer>) => view.findComponent({ name: 'DocumentPreview' })

describe('office source viewer falls back to the text view', () => {
  it('when the preview shows its error, with the downloaded bytes', async () => {
    const view = viewer()
    await flushPromises()
    expect(fallback(view).exists()).toBe(false)
    const error = document.createElement('div')
    error.className = 'preview-error'
    view.get('[data-upstream-preview]').element.appendChild(error)
    await vi.waitFor(() => expect(fallback(view).exists()).toBe(true))
    expect(fallback(view).attributes('data-fallback')).toBe('failed')
    expect(fallback(view).attributes('data-bytes')).toBe(BYTES.join(','))
    expect(preview(view).exists()).toBe(true)
  })

  it('when the preview says nothing for 30 seconds, and withdraws it if the preview locates later', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const view = viewer()
    await flushPromises()
    vi.advanceTimersByTime(29_999)
    await flushPromises()
    expect(fallback(view).exists()).toBe(false)
    vi.advanceTimersByTime(1)
    await flushPromises()
    expect(fallback(view).attributes('data-fallback')).toBe('stalled')
    preview(view).vm.$emit('located', { found: true, precise: true })
    await flushPromises()
    expect(fallback(view).exists()).toBe(false)
  })

  it('when the preview cannot find the quote', async () => {
    const view = viewer()
    await flushPromises()
    preview(view).vm.$emit('located', { found: false, precise: false })
    await flushPromises()
    expect(fallback(view).attributes('data-fallback')).toBe('notLocated')
    expect(view.get('[role="note"]').text()).toBe(viewerLabels.notLocated)
  })

  it('when the preview can only mark the whole slide: the quote is not in its rendered text', async () => {
    const view = viewer()
    await flushPromises()
    preview(view).vm.$emit('located', { found: true, precise: false, granularity: 'block' })
    await flushPromises()
    expect(fallback(view).attributes('data-fallback')).toBe('notLocated')
    expect(view.get('[role="note"]').text()).toBe(viewerLabels.coarse)
  })

  it.each([
    ['the quote is marked word for word', TARGET, { found: true, precise: true }],
    ['a sheet row is marked whole', officeTarget({ kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:XFD3' }, QUOTE)!,
      { found: true, precise: false, granularity: 'block' }],
  ])('never when %s', async (_name, target, result) => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const view = viewer(undefined, target)
    await flushPromises()
    preview(view).vm.$emit('located', result)
    vi.advanceTimersByTime(60_000)
    await flushPromises()
    expect(fallback(view).exists()).toBe(false)
  })

  it('and starts over for another citation of the same file', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const view = viewer()
    await flushPromises()
    preview(view).vm.$emit('located', { found: false, precise: false })
    await flushPromises()
    expect(fallback(view).exists()).toBe(true)
    await view.setProps({ target: officeTarget({ kind: 'PPTX_SHAPE', slide: 3 }, '另一段引文')! })
    await flushPromises()
    expect(fallback(view).exists()).toBe(false)
    vi.advanceTimersByTime(30_000)
    await flushPromises()
    expect(fallback(view).attributes('data-fallback')).toBe('stalled')
  })

  it('and stops waiting when closed', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const view = viewer()
    await flushPromises()
    const pending = vi.getTimerCount()
    view.unmount()
    expect(vi.getTimerCount()).toBe(pending - 1)
  })

  it.each([
    ['the download failed', () => vi.mocked(get).mockRejectedValue(new Error('network'))],
    ['the package was refused', () => vi.mocked(sanitizeOfficePackage).mockRejectedValue(new OfficePackageRejected('structure'))],
  ])('but not when %s', async (_name, arrange) => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const view = viewer(arrange)
    await flushPromises()
    vi.advanceTimersByTime(60_000)
    await flushPromises()
    expect(preview(view).exists()).toBe(false)
    expect(fallback(view).exists()).toBe(false)
  })
})

function textView(original: ArrayBuffer, target = TARGET, reason = 'failed', document = '演示.pptx') {
  return mount(OfficeTextView, { props: { original, document, target, reason, labels: textLabels } as any })
}

const DECK = () => deck([
  { shapes: textBox(2, ['第一张']) },
  { shapes: textBox(2, ['适合人群', QUOTE, '&lt;b&gt;加粗&lt;/b&gt;']), notes: ['讲解备注'] },
])

describe('office text view', () => {
  it.each([['failed', 'REASON-FAILED'], ['stalled', 'REASON-STALLED'], ['notLocated', 'REASON-NOT-LOCATED']])(
    'shows the cited slide with the quote marked and says why (%s)',
    async (reason, said) => {
      const view = textView(await DECK(), TARGET, reason)
      expect(view.get('[role="status"]').text()).toBe('LOADING')
      await vi.waitFor(() => expect(view.find('mark').exists()).toBe(true))
      const section = view.get('[data-office-text-view]')
      expect(section.text()).toContain(said)
      expect(view.findAll('mark').map(mark => mark.text())).toEqual([QUOTE])
      expect(section.text()).toContain('适合人群')
      expect(section.text()).toContain('NOTES')
      expect(section.text()).toContain('讲解备注')
      expect(section.text()).not.toContain('第一张')
      expect(section.text()).not.toContain('QUOTE-MISSING')
      expect(view.find('[role="status"]').exists()).toBe(false)
    },
  )

  it('shows file text as text', async () => {
    const view = textView(await DECK())
    await vi.waitFor(() => expect(view.find('mark').exists()).toBe(true))
    expect(view.get('[data-office-text-view]').text()).toContain('<b>加粗</b>')
    expect(view.find('[data-office-text-view] b').exists()).toBe(false)
  })

  it('says when the quote is not there word for word and still shows the place', async () => {
    const view = textView(await DECK(), officeTarget({ kind: 'PPTX_SHAPE', slide: 2 }, '犹豫期为二十日')!)
    await vi.waitFor(() => expect(view.text()).toContain('QUOTE-MISSING'))
    expect(view.find('mark').exists()).toBe(false)
    expect(view.text()).toContain('适合人群')
  })

  it('marks the cited block among its neighbours and the cited row under its header', async () => {
    const doc = textView(await manual([wp('前一段'), wp('等待期为九十日'), wp('后一段')].join('')),
      officeTarget({ kind: 'DOCX_BLOCK', block_index: 1 }, '九十日')!, 'notLocated', '手册.docx')
    await vi.waitFor(() => expect(doc.find('mark').exists()).toBe(true))
    expect(doc.findAll('[data-cited]').map(line => line.text())).toEqual(['等待期为九十日'])
    expect(doc.text()).toContain('前一段')
    const sheet = textView(await workbook({ Rates: { 1: ['年龄', '年保费'], 3: ['31-40', 180] } }),
      officeTarget({ kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:XFD3' }, '180')!, 'failed', '费率.xlsx')
    await vi.waitFor(() => expect(sheet.find('mark').exists()).toBe(true))
    expect(sheet.findAll('th').map(cell => cell.text())).toEqual(['年龄', '年保费'])
    expect(sheet.findAll('[data-cited] td').map(cell => cell.text())).toEqual(['31-40', '180'])
  })

  it('says when the cited place has no text', async () => {
    const view = textView(await DECK(), officeTarget({ kind: 'PPTX_SHAPE', slide: 5 }, QUOTE)!)
    await vi.waitFor(() => expect(view.text()).toContain('EMPTY'))
    expect(view.find('mark').exists()).toBe(false)
  })

  it('says when no text can be read, and still offers the file', async () => {
    const view = textView(new Uint8Array([1, 2, 3]).buffer)
    await vi.waitFor(() => expect(view.text()).toContain('UNAVAILABLE'))
    expect(view.find('[role="alert"]').exists()).toBe(false)
    expect(view.get('a[download]').text()).toBe('DOWNLOAD')
  })

  it('downloads the original bytes without asking the server again', async () => {
    const created: Blob[] = []
    vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => {
      created.push(blob as Blob)
      return 'blob:office-original'
    })
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const original = new Uint8Array(BYTES).buffer
    const view = textView(original)
    await flushPromises()
    const link = view.get('a[download]')
    expect(link.attributes('href')).toBe('blob:office-original')
    expect(link.attributes('download')).toBe('演示.pptx')
    expect(created).toHaveLength(1)
    expect(created[0].type).toBe('application/octet-stream')
    expect([...new Uint8Array(await created[0].arrayBuffer())]).toEqual(BYTES)
    expect(get).not.toHaveBeenCalled()
    view.unmount()
    expect(revoke).toHaveBeenCalledWith('blob:office-original')
  })
})

describe('citation panel', () => {
  it('puts the text view in the viewer\'s fallback, in the reader\'s language', async () => {
    const original = await DECK()
    vi.mocked(readCitation).mockResolvedValue({
      release_id: 'rel-1', member: 'P1/f_sales', evidence_index: 0, origin: 'SOURCE_SUPPORTED',
      source: { knowledge_id: 'k-1', parse_attempt: 2, document: '演示.pptx', file_sha256: 'b'.repeat(64) },
      page: { number: 2 }, start: 0, end: QUOTE.length, quote: QUOTE,
      locator: { kind: 'PPTX_SHAPE', slide: 2 }, block: { block_id: 'p2/b1', start: 0, end: QUOTE.length }, file: FILE,
    } as Citation)
    const Viewer = defineComponent({
      name: 'OfficeSourceViewer',
      props: ['file', 'document', 'target', 'labels'],
      setup: (_, { slots }) => () => h('div', slots.fallback?.({ reason: 'failed', original })),
    })
    const view = mount(CitationPanel, {
      props: { spaceId: 'demo', releaseId: 'rel-1', member: 'P1/f_sales', evidence: 0 },
      global: {
        plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
        stubs: { OfficeSourceViewer: Viewer },
      },
    })
    await flushPromises()
    const text = view.getComponent(OfficeTextView)
    expect(text.props()).toMatchObject({ original, document: '演示.pptx', target: TARGET, reason: 'failed' })
    expect(text.props('labels')).toEqual(zhCNMessages.enterpriseKnowledge.viewer.text)
    await vi.waitFor(() => expect(view.find('mark').exists()).toBe(true))
    expect(view.get('[data-office-text-view]').text()).toContain(zhCNMessages.enterpriseKnowledge.viewer.text.failed)
  })

  it.each([['zh-CN', zhCNMessages], ['en-US', enUS], ['ja-JP', jaJP], ['ko-KR', koKR], ['ru-RU', ruRU]])(
    'has every text view string in %s', (_locale, messages) => {
      const strings = (messages as typeof zhCNMessages).enterpriseKnowledge.viewer.text
      expect(Object.keys(strings).sort()).toEqual(Object.keys(textLabels).sort())
      for (const value of Object.values(strings)) expect(String(value).trim()).not.toBe('')
    },
  )
})

// @vitest-environment happy-dom
// S11e acceptance (protected, written by Claude): the citation panel opens an Office citation in
// the Office viewer at its slide, block or row; a citation it cannot open shows the document,
// page and quote only; PDF citations are unchanged (Spec docs/design/slices/S11e-Office引用查看器.md §3.3).
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readCitation: vi.fn(),
}))

import CitationPanel from './CitationPanel.vue'
import OfficeSourceViewer from './OfficeSourceViewer.vue'
import SourcePageViewer from './SourcePageViewer.vue'
import { readCitation, type Citation } from './enterpriseApi'
import { officeTarget } from './officeCitation'

const FILE = '/api/v1/enterprise/spaces/demo/view/releases/rel-1/sources/k-9/attempts/1/file'

// The S11d response for Office evidence: no `highlight`, the captured block's locator instead
// (internal/enterprise/citation.go blockCitation; pinned by internal/enterprise/office_citation_test.go).
function officeCitation(document: string, page: number, locator: Record<string, unknown>, quote = '保障全面'): Citation {
  return {
    release_id: 'rel-1', member: 'P1/f_sales', evidence_index: 0, origin: 'SOURCE_SUPPORTED',
    source: { knowledge_id: 'k-9', parse_attempt: 1, document, file_sha256: 'b'.repeat(64) },
    page: { number: page },
    start: 6, end: 10, quote,
    locator,
    block: { block_id: 'p1/b2', start: 6, end: 10 },
    file: FILE,
  } as Citation
}

function pdfCitation(): Citation {
  return {
    release_id: 'rel-1', member: 'P1/f_wait', evidence_index: 1, origin: 'SOURCE_SUPPORTED',
    source: { knowledge_id: 'k-1', parse_attempt: 2, document: '保险条款.pdf', file_sha256: 'a'.repeat(64) },
    page: { number: 6, width_points: '595.32', height_points: '841.92' },
    start: 10, end: 17, quote: '等待期为90日。',
    highlight: { coordinate_space: 'normalized_0_1e6_top_left', complete: true, rects: [[100000, 200000, 400000, 250000]] },
    file: FILE,
  }
}

function panel() {
  return mount(CitationPanel, {
    props: { spaceId: 'demo', releaseId: 'rel-1', member: 'P1/f_sales', evidence: 0 },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { SourcePageViewer: true, OfficeSourceViewer: true },
    },
  })
}

function viewerLabels(region: string) {
  return {
    loading: '正在打开原文…',
    failed: '原文页无法显示',
    retry: '重试',
    coarse: '已标出引文所在的位置，未能逐字高亮',
    notLocated: '未能在原文中定位这段引文，请对照上方引文',
    unsafe: '原文件含有无法安全显示的内容，未打开，请对照上方引文',
    region,
  }
}

afterEach(() => { vi.resetAllMocks() })

describe('citation panel with Office evidence', () => {
  it.each([
    ['演示.pptx', 2, { kind: 'PPTX_SHAPE', slide: 2 }, '第 2 张幻灯片'],
    ['手册.docx', 1, { kind: 'DOCX_BLOCK', block_index: 2 }, '正文第 3 段'],
    ['费率.xlsx', 2, { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:XFD3' }, '工作表「Rates」第 3 行'],
  ])('opens %s at the cited place', async (document, page, locator, position) => {
    vi.mocked(readCitation).mockResolvedValue(officeCitation(document, page, locator))
    const view = panel()
    await flushPromises()
    expect(view.find('[role="alert"]').exists()).toBe(false)
    const source = view.get('.ek-citation__source').text()
    expect(source).toContain(document)
    expect(source).toContain(position)
    expect(source).not.toContain(`第 ${page} 页`)
    expect(view.get('[data-origin]').text()).toBe('原文依据')
    expect(view.get('.ek-citation__quote').text()).toBe('保障全面')
    expect(view.findComponent(SourcePageViewer).exists()).toBe(false)
    expect(view.getComponent(OfficeSourceViewer).props()).toEqual({
      file: FILE,
      document,
      target: officeTarget(locator, '保障全面'),
      labels: viewerLabels(`${document} ${position}`),
    })
  })

  it.each([
    ['no locator', undefined],
    ['an unknown locator', { kind: 'PPTX_TABLE_CELL', slide: 2 }],
    ['a malformed row', { kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:B3' }],
  ])('shows the document, page and quote only for %s', async (_name, locator) => {
    const read = officeCitation('材料.pptx', 4, locator as Record<string, unknown>)
    if (locator === undefined) delete (read as Partial<Citation>).locator
    vi.mocked(readCitation).mockResolvedValue(read)
    const view = panel()
    await flushPromises()
    expect(view.find('[role="alert"]').exists()).toBe(false)
    const source = view.get('.ek-citation__source').text()
    expect(source).toContain('材料.pptx')
    expect(source).toContain('第 4 页')
    expect(view.get('.ek-citation__quote').text()).toBe('保障全面')
    expect(view.get('[role="note"]').text()).toBe('这类出处暂不支持打开原文，请对照上方引文')
    expect(view.findComponent(SourcePageViewer).exists()).toBe(false)
    expect(view.findComponent(OfficeSourceViewer).exists()).toBe(false)
  })

  it('keeps opening PDF citations in the PDF page viewer', async () => {
    vi.mocked(readCitation).mockResolvedValue(pdfCitation())
    const view = panel()
    await flushPromises()
    expect(view.findComponent(OfficeSourceViewer).exists()).toBe(false)
    expect(view.find('[role="note"]').exists()).toBe(false)
    expect(view.getComponent(SourcePageViewer).props('page')).toBe(6)
    expect(view.get('.ek-citation__source').text()).toContain('第 6 页')
  })
})

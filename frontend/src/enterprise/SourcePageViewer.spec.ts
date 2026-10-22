// @vitest-environment happy-dom
// S3d-3b acceptance (protected, written by Claude): the cited page of a PDF with every highlight
// on it, and nothing else (Spec docs/design/slices/S3d-3b-原文页查看器.md §3.2). A missing page or
// a failed download is an error with a retry, never another page.
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn() }))
vi.mock('./pdfJsPort', () => ({ createPdfJsPort: vi.fn() }))

import { createPdfJsPort } from './pdfJsPort'
import { get } from '@/utils/request'
import SourcePageViewer from './SourcePageViewer.vue'

const FILE = '/api/v1/enterprise/spaces/demo/view/releases/rel-1/sources/k-1/attempts/2/file'
const BYTES = [37, 80, 68, 70]
const labels = {
  loading: '正在打开原文',
  failed: '原文无法打开',
  retry: '重试',
  incomplete: '高亮可能不完整',
  region: '保险条款.pdf 第 6 页',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

function fakePdf(pageCount = 8) {
  const close = vi.fn()
  const renderPage = vi.fn(async (pageNumber: number) => {
    const canvas = document.createElement('canvas')
    canvas.dataset.page = String(pageNumber)
    return { pageNumber, width: 600, height: 800, canvas }
  })
  const open = vi.fn(async (_bytes: Uint8Array) => ({ pageCount, renderPage, close }))
  vi.mocked(createPdfJsPort).mockReturnValue({ open } as any)
  return { open, renderPage, close }
}

function bytes() {
  return new Uint8Array(BYTES).buffer
}

function viewer(props: Record<string, unknown> = {}) {
  return mount(SourcePageViewer, {
    props: { file: FILE, page: 6, rects: [[100000, 200000, 400000, 250000]], complete: true, labels, ...props } as any,
  })
}

function box(element: Element) {
  const style = (element as HTMLElement).style
  return [style.left, style.top, style.width, style.height]
}

function signalOf(call: number): AbortSignal {
  return (vi.mocked(get).mock.calls[call][1] as any).signal
}

afterEach(() => { vi.resetAllMocks() })

describe('source page viewer', () => {
  it('fetches the cited bytes once and shows exactly the cited page with one box per rectangle', async () => {
    const pdf = fakePdf()
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer({ rects: [[100000, 200000, 400000, 250000], [100000, 260000, 300000, 300000]] })
    expect(view.get('[role="status"]').text()).toContain(labels.loading)
    await flushPromises()

    expect(get).toHaveBeenCalledTimes(1)
    const [url, config] = vi.mocked(get).mock.calls[0]
    expect(url).toBe(FILE)
    expect(config).toMatchObject({ responseType: 'arraybuffer' })
    expect(Array.from(pdf.open.mock.calls[0][0])).toEqual(BYTES)
    expect(pdf.renderPage.mock.calls).toEqual([[6]])

    const page = view.get('[data-source-page]')
    expect(page.attributes('role')).toBe('img')
    expect(page.attributes('aria-label')).toBe(labels.region)
    expect(page.get('canvas').attributes('data-page')).toBe('6')
    const boxes = page.findAll('[data-highlight]')
    expect(boxes.map(item => box(item.element))).toEqual([
      ['10%', '20%', '30%', '5%'],
      ['10%', '26%', '20%', '4%'],
    ])
    expect(boxes.every(item => item.attributes('aria-hidden') === 'true')).toBe(true)
    expect(view.find('[data-highlight-incomplete]').exists()).toBe(false)
    expect(view.find('[role="status"]').exists()).toBe(false)
  })

  it('says so when the highlight may not cover the whole quote', async () => {
    fakePdf()
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer({ complete: false })
    await flushPromises()
    const note = view.get('[data-highlight-incomplete]')
    expect(note.attributes('role')).toBe('note')
    expect(note.text()).toContain(labels.incomplete)
  })

  it('never shows another page when the cited page does not exist', async () => {
    const pdf = fakePdf(3)
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer({ page: 6 })
    await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain(labels.failed)
    expect(pdf.renderPage).not.toHaveBeenCalled()
    expect(view.find('canvas').exists()).toBe(false)
    expect(view.find('[data-source-page]').exists()).toBe(false)
    expect(pdf.close).toHaveBeenCalledTimes(1)
  })

  it('offers a retry after a failed download that reloads the same page', async () => {
    const pdf = fakePdf()
    vi.mocked(get).mockRejectedValueOnce({ status: 409, code: 'SOURCE_INTEGRITY' }).mockResolvedValueOnce(bytes() as any)
    const view = viewer()
    await flushPromises()
    const alert = view.get('[role="alert"]')
    expect(alert.text()).toContain(labels.failed)
    expect(pdf.open).not.toHaveBeenCalled()

    expect(alert.get('button').text()).toBe(labels.retry)
    await alert.get('button').trigger('click')
    await flushPromises()
    expect(vi.mocked(get).mock.calls.map(call => call[0])).toEqual([FILE, FILE])
    expect(pdf.renderPage.mock.calls).toEqual([[6]])
    expect(view.find('[role="alert"]').exists()).toBe(false)
    expect(view.get('[data-source-page] canvas').attributes('data-page')).toBe('6')
  })

  it('shows only the latest page when the citation changes while loading', async () => {
    const pdf = fakePdf()
    const first = deferred<ArrayBuffer>()
    const second = deferred<ArrayBuffer>()
    vi.mocked(get).mockReturnValueOnce(first.promise as any).mockReturnValueOnce(second.promise as any)
    const view = viewer({ page: 6 })
    await flushPromises()
    await view.setProps({ page: 7, rects: [[0, 0, 500000, 500000]] })
    await flushPromises()
    expect(signalOf(0).aborted).toBe(true)
    expect(signalOf(1).aborted).toBe(false)

    second.resolve(bytes())
    await flushPromises()
    first.resolve(bytes())
    await flushPromises()

    expect(pdf.renderPage).not.toHaveBeenCalledWith(6)
    expect(view.get('[data-source-page] canvas').attributes('data-page')).toBe('7')
    expect(view.findAll('[data-highlight]').map(item => box(item.element))).toEqual([['0%', '0%', '50%', '50%']])
    expect(pdf.close.mock.calls.length).toBe(pdf.open.mock.calls.length - 1)
  })

  it('closes the opened document and cancels a pending download when it goes away', async () => {
    const pdf = fakePdf()
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const shown = viewer()
    await flushPromises()
    shown.unmount()
    expect(pdf.close).toHaveBeenCalledTimes(1)

    const pending = deferred<ArrayBuffer>()
    vi.mocked(get).mockReturnValueOnce(pending.promise as any)
    const loading = viewer()
    await flushPromises()
    loading.unmount()
    expect(signalOf(1).aborted).toBe(true)
    pending.resolve(bytes())
    await flushPromises()
    expect(pdf.renderPage).toHaveBeenCalledTimes(1)
  })
})

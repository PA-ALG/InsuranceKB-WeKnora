// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import type { OpenedPdfDocument, RenderedPdfPage } from './pdfJsPort'

vi.mock('@/utils/request', () => ({ get: vi.fn() }))
vi.mock('./pdfJsPort', () => ({ createPdfJsPort: vi.fn() }))

import { get, type WithStatus } from '@/utils/request'
import { createPdfJsPort } from './pdfJsPort'
import SourcePageViewer from './SourcePageViewer.vue'

const labels = { loading: 'Loading', failed: 'Failed', retry: 'Retry', incomplete: 'Incomplete', region: 'Cited page' }
const views: VueWrapper[] = []

// request.get's status annotation is only guaranteed for JSON responses.
function bytes() { return new ArrayBuffer(4) as WithStatus<ArrayBuffer> }

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

function rendered(pageNumber: number): RenderedPdfPage {
  const canvas = document.createElement('canvas')
  canvas.dataset.page = String(pageNumber)
  return { pageNumber, width: 600, height: 800, canvas }
}

function documentPort() {
  return { pageCount: 8, close: vi.fn(), renderPage: vi.fn(async (page: number) => rendered(page)) }
}

function viewer(page = 2) {
  const view = mount(SourcePageViewer, {
    props: { file: '/citation/file', page, rects: [], complete: true, labels },
  })
  views.push(view)
  return view
}

afterEach(() => {
  views.splice(0).forEach(view => view.unmount())
  vi.resetAllMocks()
})

it('closes a document that finishes opening after the file changes', async () => {
  const late = deferred<OpenedPdfDocument>()
  const old = documentPort()
  const current = documentPort()
  const open = vi.fn().mockReturnValueOnce(late.promise).mockResolvedValueOnce(current)
  vi.mocked(createPdfJsPort).mockReturnValue({ open })
  vi.mocked(get).mockResolvedValue(bytes())
  const view = viewer()
  await flushPromises()
  await view.setProps({ file: '/new-citation/file', page: 4 })
  await flushPromises()
  late.resolve(old)
  await flushPromises()

  expect(old.renderPage).not.toHaveBeenCalled()
  expect(old.close).toHaveBeenCalledTimes(1)
  expect(current.close).not.toHaveBeenCalled()
  expect(view.get('canvas').attributes('data-page')).toBe('4')
  expect(get).toHaveBeenLastCalledWith('/new-citation/file', expect.objectContaining({ timeout: 180_000 }))
})

it('closes an in-flight render immediately and never inserts its late canvas', async () => {
  const pending = deferred<RenderedPdfPage>()
  const old = documentPort()
  old.renderPage.mockReturnValueOnce(pending.promise)
  const current = documentPort()
  vi.mocked(createPdfJsPort).mockReturnValue({ open: vi.fn().mockResolvedValueOnce(old).mockResolvedValueOnce(current) })
  vi.mocked(get).mockResolvedValue(bytes())
  const view = viewer()
  await flushPromises()
  await view.setProps({ page: 5 })
  expect(old.close).toHaveBeenCalledTimes(1)
  await flushPromises()
  pending.resolve(rendered(2))
  await flushPromises()
  expect(view.findAll('canvas')).toHaveLength(1)
  expect(view.get('canvas').attributes('data-page')).toBe('5')
  expect(old.close).toHaveBeenCalledTimes(1)
})

it('discards a late opening document after unmount', async () => {
  const late = deferred<OpenedPdfDocument>()
  const pdf = documentPort()
  vi.mocked(createPdfJsPort).mockReturnValue({ open: vi.fn().mockReturnValue(late.promise) })
  vi.mocked(get).mockResolvedValue(bytes())
  const view = viewer()
  await flushPromises()
  view.unmount()
  views.pop()
  late.resolve(pdf)
  await flushPromises()
  expect(pdf.renderPage).not.toHaveBeenCalled()
  expect(pdf.close).toHaveBeenCalledTimes(1)
})

it('reports a render failure, closes the document, and retries the same citation', async () => {
  const failed = documentPort()
  failed.renderPage.mockRejectedValueOnce(new Error('render failed'))
  const retried = documentPort()
  vi.mocked(createPdfJsPort).mockReturnValue({ open: vi.fn().mockResolvedValueOnce(failed).mockResolvedValueOnce(retried) })
  vi.mocked(get).mockResolvedValue(bytes())
  const view = viewer()
  await flushPromises()
  expect(view.get('[role="alert"]').text()).toContain(labels.failed)
  expect(view.find('canvas').exists()).toBe(false)
  expect(failed.close).toHaveBeenCalledTimes(1)
  await view.get('button').trigger('click')
  await flushPromises()
  expect(retried.renderPage).toHaveBeenCalledWith(2)
  expect(view.get('canvas').attributes('data-page')).toBe('2')
  expect(failed.close).toHaveBeenCalledTimes(1)
})

it.each([0, -1, 1.5, NaN, Infinity])('rejects an invalid cited page %s without rendering', async page => {
  const pdf = documentPort()
  vi.mocked(createPdfJsPort).mockReturnValue({ open: vi.fn().mockResolvedValue(pdf) })
  vi.mocked(get).mockResolvedValue(bytes())
  const view = viewer(page)
  await flushPromises()
  expect(pdf.renderPage).not.toHaveBeenCalled()
  expect(pdf.close).toHaveBeenCalledTimes(1)
  expect(view.get('[role="alert"]').text()).toContain(labels.failed)
  expect(view.find('[data-source-page]').exists()).toBe(false)
})

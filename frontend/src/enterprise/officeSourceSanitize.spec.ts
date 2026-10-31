// @vitest-environment happy-dom
// S11e (Spec §3.2/§3.2a, review R1): the preview only ever receives the rebuilt package; a package
// the rebuild refuses opens nothing and says so, without a retry that would fail the same way.
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn() }))
vi.mock('./officePackage', async importOriginal => ({
  ...(await importOriginal<typeof import('./officePackage')>()),
  sanitizeOfficePackage: vi.fn(),
}))
vi.mock('@/components/document-preview.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'DocumentPreview',
      props: { sourceBlob: Object, fileType: String, fileName: String, active: Boolean, sourceMode: Boolean, locate: Object },
      setup: () => () => h('div'),
    }),
  }
})

import { get } from '@/utils/request'
import OfficeSourceViewer from './OfficeSourceViewer.vue'
import { officeTarget } from './officeCitation'
import { OfficePackageRejected, sanitizeOfficePackage } from './officePackage'

const labels = {
  loading: '正在打开原文…', failed: '原文页无法显示', retry: '重试', coarse: 'c', notLocated: 'n',
  unsafe: '原文件含有无法安全显示的内容，未打开，请对照上方引文', region: 'r',
}
const RAW = new Uint8Array([1, 2, 3]).buffer
const CLEAN = new Uint8Array([4, 5, 6, 7]).buffer

function viewer() {
  return mount(OfficeSourceViewer, {
    props: { file: '/f', document: '手册.docx', target: officeTarget({ kind: 'DOCX_BLOCK', block_index: 0 }, 'q')!, labels },
  })
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

const DECK = { file: '/g', document: '演示.pptx', target: officeTarget({ kind: 'PPTX_SHAPE', slide: 1 }, 'q')! }

async function shownBytes(view: ReturnType<typeof viewer>) {
  const blob = view.findComponent({ name: 'DocumentPreview' }).props('sourceBlob') as Blob
  return [...new Uint8Array(await blob.arrayBuffer())]
}

afterEach(() => { vi.resetAllMocks() })

describe('the Office viewer and the package rebuild', () => {
  it('renders the rebuilt bytes, never the downloaded ones', async () => {
    vi.mocked(get).mockResolvedValue(RAW as any)
    vi.mocked(sanitizeOfficePackage).mockResolvedValue(CLEAN)
    const view = viewer()
    await flushPromises()
    expect(vi.mocked(sanitizeOfficePackage).mock.calls).toEqual([[RAW, 'docx']])
    const blob = view.findComponent({ name: 'DocumentPreview' }).props('sourceBlob') as Blob
    expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([4, 5, 6, 7])
  })

  it.each(['package', 'size', 'structure'] as const)('opens nothing for a package refused as %s', async problem => {
    vi.mocked(get).mockResolvedValue(RAW as any)
    vi.mocked(sanitizeOfficePackage).mockRejectedValue(new OfficePackageRejected(problem))
    const view = viewer()
    await flushPromises()
    expect(view.findComponent({ name: 'DocumentPreview' }).exists()).toBe(false)
    expect(view.get('[role="note"]').text()).toBe(labels.unsafe)
    expect(view.find('[role="alert"]').exists()).toBe(false)
    expect(view.find('button').exists()).toBe(false)
  })

  it('ignores a rebuild that finishes after another citation opened', async () => {
    const first = deferred<ArrayBuffer>()
    const second = deferred<ArrayBuffer>()
    vi.mocked(get).mockResolvedValue(RAW as any)
    vi.mocked(sanitizeOfficePackage).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const view = viewer()
    await flushPromises()
    await view.setProps(DECK)
    await flushPromises()
    expect(vi.mocked(sanitizeOfficePackage).mock.calls.map(call => call[1])).toEqual(['docx', 'pptx'])
    second.resolve(CLEAN)
    await flushPromises()
    first.resolve(new Uint8Array([9]).buffer)
    await flushPromises()
    const preview = view.findComponent({ name: 'DocumentPreview' })
    expect(preview.props('fileType')).toBe('pptx')
    expect(await shownBytes(view)).toEqual([4, 5, 6, 7])
  })

  it('ignores a late refusal of the earlier file', async () => {
    const first = deferred<ArrayBuffer>()
    vi.mocked(get).mockResolvedValue(RAW as any)
    vi.mocked(sanitizeOfficePackage).mockReturnValueOnce(first.promise).mockResolvedValueOnce(CLEAN)
    const view = viewer()
    await flushPromises()
    await view.setProps(DECK)
    await flushPromises()
    first.reject(new OfficePackageRejected('structure'))
    await flushPromises()
    expect(view.find('[role="note"]').exists()).toBe(false)
    expect(view.findComponent({ name: 'DocumentPreview' }).props('fileType')).toBe('pptx')
  })

  it('renders nothing when closed while the rebuild is running', async () => {
    const pending = deferred<ArrayBuffer>()
    vi.mocked(get).mockResolvedValue(RAW as any)
    vi.mocked(sanitizeOfficePackage).mockReturnValueOnce(pending.promise)
    const view = viewer()
    await flushPromises()
    expect(view.get('[role="status"]').text()).toBe(labels.loading)
    const signal = (vi.mocked(get).mock.calls[0][1] as any).signal as AbortSignal
    view.unmount()
    expect(signal.aborted).toBe(true)
    pending.resolve(CLEAN)
    await flushPromises()
    expect(view.exists()).toBe(false)
  })

  it('treats any other failure of the rebuild as a failed opening that can be retried', async () => {
    vi.mocked(get).mockResolvedValue(RAW as any)
    vi.mocked(sanitizeOfficePackage).mockRejectedValueOnce(new Error('worker crashed')).mockResolvedValueOnce(CLEAN)
    const view = viewer()
    await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain(labels.failed)
    await view.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(view.findComponent({ name: 'DocumentPreview' }).exists()).toBe(true)
  })
})

// @vitest-environment happy-dom
// S11e acceptance (protected, written by Claude): an Office citation opens its original file in
// upstream's preview, which reveals and highlights the cited block; what the preview could not
// locate is said, never replaced by another place (Spec docs/design/slices/S11e-Office引用查看器.md §3.2).
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn() }))
// The package rebuild (Spec §3.2a, review R1) has its own tests; here it hands the bytes through.
vi.mock('./officePackage', async importOriginal => ({
  ...(await importOriginal<typeof import('./officePackage')>()),
  sanitizeOfficePackage: vi.fn(async (bytes: ArrayBuffer) => bytes),
}))
vi.mock('@/components/document-preview.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    default: defineComponent({
      name: 'DocumentPreview',
      props: {
        sourceBlob: Object, fileType: String, fileName: String, active: Boolean,
        sourceMode: Boolean, locate: Object, knowledgeId: String,
      },
      emits: ['located'],
      setup: () => () => h('div', { 'data-upstream-preview': '' }),
    }),
  }
})

import { get } from '@/utils/request'
import OfficeSourceViewer from './OfficeSourceViewer.vue'
import { officeTarget, type OfficeTarget } from './officeCitation'

const FILE = '/api/v1/enterprise/spaces/demo/view/releases/rel-1/sources/k-1/attempts/2/file'
const QUOTE = '保险期间为一年'
const BYTES = [80, 75, 3, 4]
const labels = {
  loading: '正在打开原文…',
  failed: '原文页无法显示',
  retry: '重试',
  coarse: '已标出引文所在的位置，未能逐字高亮',
  notLocated: '未能在原文中定位这段引文，请对照上方引文',
  unsafe: '原文件含有无法安全显示的内容，未打开，请对照上方引文',
  region: '演示.pptx 第 2 张幻灯片',
}
const MEDIA = {
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}
const TARGETS: Record<keyof typeof MEDIA, OfficeTarget> = {
  pptx: officeTarget({ kind: 'PPTX_SHAPE', slide: 2 }, QUOTE)!,
  docx: officeTarget({ kind: 'DOCX_BLOCK', block_index: 2 }, QUOTE)!,
  xlsx: officeTarget({ kind: 'XLSX_CELL_RANGE', sheet: 'Rates', cell_range: 'A3:XFD3' }, QUOTE)!,
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

function bytes() {
  return new Uint8Array(BYTES).buffer
}

function viewer(props: Record<string, unknown> = {}) {
  return mount(OfficeSourceViewer, {
    props: { file: FILE, document: '演示.pptx', target: TARGETS.pptx, labels, ...props } as any,
  })
}

function preview(view: ReturnType<typeof viewer>) {
  return view.findComponent({ name: 'DocumentPreview' })
}

function signalOf(call: number): AbortSignal {
  return (vi.mocked(get).mock.calls[call][1] as any).signal
}

afterEach(() => { vi.resetAllMocks() })

describe('office source viewer', () => {
  it('downloads the cited file once, through the authorized release file route', async () => {
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer()
    expect(view.get('[role="status"]').text()).toBe(labels.loading)
    await flushPromises()
    expect(vi.mocked(get).mock.calls).toHaveLength(1)
    expect(vi.mocked(get).mock.calls[0][0]).toBe(FILE)
    expect(vi.mocked(get).mock.calls[0][1]).toMatchObject({ responseType: 'arraybuffer', timeout: 180_000 })
    expect(signalOf(0)).toBeInstanceOf(AbortSignal)
  })

  it.each(Object.keys(MEDIA) as (keyof typeof MEDIA)[])(
    'hands the %s bytes to the upstream preview with its locate request',
    async format => {
      vi.mocked(get).mockResolvedValue(bytes() as any)
      const view = viewer({ target: TARGETS[format], document: `演示.${format}` })
      await flushPromises()
      const props = preview(view).props() as Record<string, any>
      expect(props.fileType).toBe(format)
      expect(props.fileName).toBe(`演示.${format}`)
      expect(props.active).toBe(true)
      expect(props.sourceMode).toBe(true)
      // The upstream knowledge preview route does not check release access; only bytes are passed.
      expect(props.knowledgeId).toBeUndefined()
      expect(props.sourceBlob).toBeInstanceOf(Blob)
      expect(props.sourceBlob.type).toBe(MEDIA[format])
      expect([...new Uint8Array(await props.sourceBlob.arrayBuffer())]).toEqual(BYTES)
      expect(props.locate).toMatchObject({ locators: [TARGETS[format].locator], quotes: [QUOTE] })
      expect(Number.isFinite(props.locate.token)).toBe(true)
      expect(view.get('[role="region"]').attributes('aria-label')).toBe(labels.region)
    },
  )

  it('says nothing more when the quote was highlighted word for word', async () => {
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer()
    await flushPromises()
    preview(view).vm.$emit('located', { found: true, precise: true })
    await flushPromises()
    expect(view.find('[role="note"]').exists()).toBe(false)
  })

  it('says when only the surrounding slide, block or row could be marked', async () => {
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer({ target: TARGETS.xlsx, document: '演示.xlsx' })
    await flushPromises()
    preview(view).vm.$emit('located', { found: true, precise: false, granularity: 'block' })
    await flushPromises()
    expect(view.get('[role="note"]').text()).toBe(labels.coarse)
  })

  it.each([
    ['not found', { found: false, precise: false }],
    ['ambiguous', { found: false, precise: false, reason: 'ambiguous' }],
  ])('keeps the file open and says the quote was %s', async (_name, result) => {
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer()
    await flushPromises()
    preview(view).vm.$emit('located', result)
    await flushPromises()
    expect(view.get('[role="note"]').text()).toBe(labels.notLocated)
    expect(preview(view).exists()).toBe(true)
  })

  it('explains a failed download and retries the same file', async () => {
    vi.mocked(get).mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(bytes() as any)
    const view = viewer()
    await flushPromises()
    expect(view.get('[role="alert"]').text()).toContain(labels.failed)
    expect(preview(view).exists()).toBe(false)
    await view.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(vi.mocked(get).mock.calls.map(call => call[0])).toEqual([FILE, FILE])
    expect(preview(view).exists()).toBe(true)
  })

  it('aborts the download when closed', async () => {
    vi.mocked(get).mockReturnValue(deferred<ArrayBuffer>().promise as any)
    const view = viewer()
    await flushPromises()
    view.unmount()
    expect(signalOf(0).aborted).toBe(true)
  })

  it('shows only the latest file when another citation opens while downloading', async () => {
    const first = deferred<ArrayBuffer>()
    const second = deferred<ArrayBuffer>()
    vi.mocked(get).mockReturnValueOnce(first.promise as any).mockReturnValueOnce(second.promise as any)
    const view = viewer()
    await flushPromises()
    await view.setProps({ file: `${FILE}?other`, target: TARGETS.docx, document: '演示.docx' })
    expect(signalOf(0).aborted).toBe(true)
    second.resolve(bytes())
    await flushPromises()
    first.resolve(new Uint8Array([1, 2, 3]).buffer)
    await flushPromises()
    const props = preview(view).props() as Record<string, any>
    expect(props.fileType).toBe('docx')
    expect([...new Uint8Array(await props.sourceBlob.arrayBuffer())]).toEqual(BYTES)
  })

  it('asks the preview to locate again when another citation of the same file opens', async () => {
    vi.mocked(get).mockResolvedValue(bytes() as any)
    const view = viewer()
    await flushPromises()
    const before = (preview(view).props() as Record<string, any>).locate.token
    const next = officeTarget({ kind: 'PPTX_SHAPE', slide: 3 }, '另一段引文')!
    await view.setProps({ target: next })
    await flushPromises()
    const locate = (preview(view).props() as Record<string, any>).locate
    expect(locate.locators).toEqual([next.locator])
    expect(locate.token).not.toBe(before)
  })
})

describe('office rendering is adopted, not rebuilt', () => {
  // Enterprise code reaches the Office renderers only through upstream's DocumentPreview (Spec §2);
  // the zip library is used only to rebuild packages before rendering (Spec §3.2a).
  const sources = import.meta.glob(['./*.ts', './*.vue', '!./*.spec.ts'], { query: '?raw', import: 'default', eager: true })
  const importing = (library: string) => Object.entries(sources)
    .filter(([, text]) => new RegExp(`from\\s+['"]${library}['"]|import\\(\\s*['"]${library}['"]`).test(String(text)))
    .map(([path]) => path)

  it('imports no Office rendering library directly', () => {
    expect(['docx-preview', 'xlsx', '@vue-office/pptx'].flatMap(importing)).toEqual([])
  })

  it('uses the zip library only to rebuild packages', () => {
    expect(importing('jszip')).toEqual(['./officePackage.ts'])
  })

  it('renders through the upstream preview component', () => {
    expect(String(sources['./OfficeSourceViewer.vue'])).toContain("'@/components/document-preview.vue'")
  })
})

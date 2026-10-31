// @vitest-environment happy-dom
// S11e (Spec §3.2): links inside a rendered Office file are untrusted; only web and mail links
// may be followed from the preview.
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/request', () => ({ get: vi.fn() }))
vi.mock('./officePackage', async importOriginal => ({
  ...(await importOriginal<typeof import('./officePackage')>()),
  sanitizeOfficePackage: vi.fn(async (bytes: ArrayBuffer) => bytes),
}))
vi.mock('@/components/document-preview.vue', async () => {
  const { defineComponent, h } = await import('vue')
  const hrefs = ['javascript:void(0)', 'data:text/html,x', 'vbscript:x', 'https://example.com/a', 'mailto:a@example.com', '#anchor', '']
  return {
    default: defineComponent({
      name: 'DocumentPreview',
      setup: () => () => h('div', hrefs.map((href, i) => h('a', { href, 'data-link': i }, [h('span', `link ${i}`)]))),
    }),
  }
})

import { get } from '@/utils/request'
import OfficeSourceViewer from './OfficeSourceViewer.vue'
import { officeTarget } from './officeCitation'

const labels = { loading: 'l', failed: 'f', retry: 'r', coarse: 'c', notLocated: 'n', unsafe: 'u', region: 'region' }

afterEach(() => { vi.resetAllMocks() })

async function clicked(index: number, type: 'click' | 'auxclick' = 'click'): Promise<boolean> {
  vi.mocked(get).mockResolvedValue(new Uint8Array([80, 75]).buffer as any)
  const view = mount(OfficeSourceViewer, {
    props: { file: '/f', document: 'a.docx', target: officeTarget({ kind: 'DOCX_BLOCK', block_index: 0 }, 'q')!, labels },
    attachTo: document.body,
  })
  await flushPromises()
  const event = new MouseEvent(type, { bubbles: true, cancelable: true })
  view.get(`[data-link="${index}"] span`).element.dispatchEvent(event)
  view.unmount()
  return event.defaultPrevented
}

describe('links in a rendered Office file', () => {
  it.each([[0, 'javascript:'], [1, 'data:'], [2, 'vbscript:'], [6, 'a dropped target']])('blocks link %i (%s)', async index => {
    expect(await clicked(index)).toBe(true)
    expect(await clicked(index, 'auxclick')).toBe(true)
  })

  it.each([[3, 'https:'], [4, 'mailto:'], [5, 'an in-page anchor']])('follows link %i (%s)', async index => {
    expect(await clicked(index)).toBe(false)
  })
})

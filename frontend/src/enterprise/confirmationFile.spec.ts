// @vitest-environment happy-dom
// S5b-3d-2 acceptance (protected, written by Claude): a confirmation card whose item names a
// source opens that original file in a new tab; failures are explained on the card (Spec
// docs/design/slices/S5b-3d-2-待确认材料打开原文件.md §3).
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from '@/enterprise/i18n/locales/en-US'
import jaJP from '@/enterprise/i18n/locales/ja-JP'
import koKR from '@/enterprise/i18n/locales/ko-KR'
import ruRU from '@/enterprise/i18n/locales/ru-RU'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readConfirmationFile: vi.fn(),
}))

import ConfirmationCard from './ConfirmationCard.vue'
import { EnterpriseError, readConfirmationFile, type ConfirmationItem } from './enterpriseApi'
import { confirmationItem } from './__tests__/confirmationFixtures'

const sourceRef = `source:v1:k-raw-1:2:${'ab'.repeat(32)}`
const views: ReturnType<typeof mount>[] = []

function card(item: ConfirmationItem, open = true) {
  const view = mount(ConfirmationCard, {
    attachTo: document.body,
    props: open ? { item, draft: { base: '', option: '', note: '', busy: false, error: '' as const } } : { item },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] },
  })
  views.push(view)
  return view
}

function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

let tab: { location: { href: string }; close: ReturnType<typeof vi.fn> }
beforeEach(() => {
  tab = { location: { href: '' }, close: vi.fn() }
  vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window)
  URL.createObjectURL = vi.fn(() => 'blob:material')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  views.forEach(view => view.unmount()); views.length = 0
  vi.useRealTimers(); vi.restoreAllMocks(); vi.resetAllMocks()
})

const sourced = (extra: Partial<ConfirmationItem> = {}) =>
  confirmationItem('item-1', { space_id: 'demo', source_ref: sourceRef, ...extra })

describe('open the original file', () => {
  it('appears only for an item that names a source, open or closed', () => {
    expect(card(confirmationItem('plain')).find('[data-confirm-file]').exists()).toBe(false)
    expect(card(sourced()).get('[data-confirm-file]').text()).toBe('打开原文件')
    const closed = sourced({ closure: { reason: 'obsolete', closed_by: 'svc', closed_at: '2026-10-27T08:00:00Z' } })
    expect(card(closed, false).get('[data-confirm-file]').text()).toBe('打开原文件')
  })

  it('opens the tab at click time, then hands it the file', async () => {
    vi.useFakeTimers()
    const file = new Blob(['%PDF-1.7'], { type: 'application/pdf' })
    const pending = deferred<Blob>()
    vi.mocked(readConfirmationFile).mockReturnValue(pending.promise)
    const view = card(sourced())
    await view.get('[data-confirm-file]').trigger('click')
    expect(window.open).toHaveBeenCalledWith('', '_blank')
    expect(vi.mocked(readConfirmationFile).mock.calls[0].slice(0, 2)).toEqual(['demo', 'item-1'])
    expect(view.get('[data-confirm-file]').attributes('disabled')).toBeDefined()
    expect(view.get('[role="status"]').text()).toBe('正在打开…')

    pending.resolve(file)
    await flushPromises()
    expect(URL.createObjectURL).toHaveBeenCalledWith(file)
    expect(tab.location.href).toBe('blob:material')
    expect(tab.close).not.toHaveBeenCalled()
    expect(view.get('[data-confirm-file]').attributes('disabled')).toBeUndefined()
    expect(view.find('[data-confirm-file-error]').exists()).toBe(false)
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(60_000)
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:material')
  })

  it.each([
    ['SOURCE_NOT_FOUND', 404, '原文件已不存在'],
    ['SOURCE_INTEGRITY', 409, '原文件与提问时的版本不一致'],
    ['SOURCE_UNAVAILABLE', 503, '打开失败，请重试'],
  ])('closes the tab and explains %s', async (code, status, message) => {
    vi.mocked(readConfirmationFile).mockRejectedValue(new EnterpriseError(code, status))
    const view = card(sourced())
    await view.get('[data-confirm-file]').trigger('click')
    await flushPromises()
    expect(tab.close).toHaveBeenCalled()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    const error = view.get('[data-confirm-file-error]')
    expect(error.attributes('role')).toBe('alert')
    expect(error.text()).toBe(message)
    expect(view.get('[data-confirm-file]').attributes('disabled')).toBeUndefined()
  })

  it('asks to allow pop-ups instead of reading when the browser blocks the tab', async () => {
    vi.mocked(window.open).mockReturnValue(null)
    const view = card(sourced())
    await view.get('[data-confirm-file]').trigger('click')
    await flushPromises()
    expect(readConfirmationFile).not.toHaveBeenCalled()
    expect(view.get('[data-confirm-file-error]').text()).toBe('浏览器拦截了新窗口，请允许弹出窗口后重试')
  })

  it('words every new text in all five locales', () => {
    const keys = ['openFile', 'openingFile', 'fileMissing', 'fileChanged', 'fileFailed', 'fileBlocked']
    for (const locale of [zhCN, enUS, jaJP, koKR, ruRU]) {
      const confirm = (locale as { enterpriseKnowledge: { confirm: Record<string, unknown> } }).enterpriseKnowledge.confirm
      for (const key of keys) expect(typeof confirm[key] === 'string' && (confirm[key] as string).trim(), key).toBeTruthy()
    }
    const zh = (zhCN as unknown as { enterpriseKnowledge: { confirm: Record<string, string> } }).enterpriseKnowledge.confirm
    expect([zh.openFile, zh.openingFile, zh.fileMissing, zh.fileChanged, zh.fileFailed, zh.fileBlocked]).toEqual([
      '打开原文件', '正在打开…', '原文件已不存在', '原文件与提问时的版本不一致', '打开失败，请重试',
      '浏览器拦截了新窗口，请允许弹出窗口后重试',
    ])
  })
})

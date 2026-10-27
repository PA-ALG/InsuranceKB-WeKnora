// @vitest-environment happy-dom
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/i18n/locales/zh-CN'

vi.mock('./enterpriseApi', async original => ({
  ...(await original<typeof import('./enterpriseApi')>()), readConfirmationFile: vi.fn(),
}))
import ConfirmationCard from './ConfirmationCard.vue'
import { EnterpriseError, readConfirmationFile, type ConfirmationItem } from './enterpriseApi'
import { confirmationItem } from './__tests__/confirmationFixtures'

const views: ReturnType<typeof mount>[] = []
const sourceRef = `source:v1:original:1:${'12'.repeat(32)}`
const sourced = (id = 'item', extra: Partial<ConfirmationItem> = {}) => confirmationItem(id, { source_ref: sourceRef, ...extra })
const file = () => new Blob(['%PDF-1.7'], { type: 'application/pdf' })
const popup = () => ({ location: { href: '' }, close: vi.fn(), closed: false })
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
function card(item = sourced()) {
  const view = mount(ConfirmationCard, {
    props: { item, draft: { base: '', option: 'replace', note: 'Keep this draft', busy: false, error: '' as const } },
    global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })] },
  })
  views.push(view)
  return view
}
const openFile = (view: ReturnType<typeof mount>) => view.get('[data-confirm-file]').trigger('click')
const signalAt = (index: number) => vi.mocked(readConfirmationFile).mock.calls[index][2]!
let tab: ReturnType<typeof popup>
beforeEach(() => {
  vi.useFakeTimers()
  tab = popup()
  vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window)
  URL.createObjectURL = vi.fn(() => 'blob:original')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => {
  views.forEach(view => view.unmount()); views.length = 0
  vi.useRealTimers(); vi.restoreAllMocks(); vi.resetAllMocks()
})

describe('confirmation file resource ownership', () => {
  it('opens synchronously before fetching and ignores repeated clicks while loading', async () => {
    const pending = deferred<Blob>()
    vi.mocked(readConfirmationFile).mockReturnValue(pending.promise)
    const view = card()
    const button = view.get('[data-confirm-file]')
    button.element.dispatchEvent(new MouseEvent('click'))
    expect(window.open).toHaveBeenCalledTimes(1)
    expect(readConfirmationFile).toHaveBeenCalledTimes(1)
    expect(vi.mocked(window.open).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(readConfirmationFile).mock.invocationCallOrder[0])
    button.element.dispatchEvent(new MouseEvent('click'))
    expect(readConfirmationFile).toHaveBeenCalledTimes(1)
    expect(signalAt(0)).toBeInstanceOf(AbortSignal)
    expect(signalAt(0).aborted).toBe(false)
    pending.resolve(file())
    await flushPromises()
  })

  it.each(['resolve', 'reject'] as const)('aborts on unmount and ignores a late %s', async completion => {
    const pending = deferred<Blob>()
    vi.mocked(readConfirmationFile).mockReturnValue(pending.promise)
    const view = card()
    await openFile(view)
    const signal = signalAt(0)
    view.unmount()
    expect(signal.aborted).toBe(true)
    expect(tab.close).toHaveBeenCalledTimes(1)
    if (completion === 'resolve') pending.resolve(file())
    else pending.reject(new EnterpriseError('SOURCE_NOT_FOUND', 404))
    await flushPromises()
    expect(tab.location.href).toBe('')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(tab.close).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each(['resolve', 'reject'] as const)('cancels replaced items without letting a late %s affect the next open', async completion => {
    const old = deferred<Blob>(), current = deferred<Blob>(), currentTab = popup()
    vi.mocked(readConfirmationFile).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    vi.mocked(window.open).mockReturnValueOnce(tab as unknown as Window).mockReturnValueOnce(currentTab as unknown as Window)
    const view = card()
    await openFile(view)
    await view.setProps({ item: sourced('next-item', { space_id: 'next-space' }) })
    expect(signalAt(0).aborted).toBe(true)
    expect(tab.close).toHaveBeenCalledTimes(1)
    expect(view.find('[role="status"]').exists()).toBe(false)
    await openFile(view)
    if (completion === 'resolve') old.resolve(file())
    else old.reject(new EnterpriseError('SOURCE_INTEGRITY', 409))
    await flushPromises()
    expect(view.get('[data-confirm-file]').attributes('disabled')).toBeDefined()
    expect(view.find('[data-confirm-file-error]').exists()).toBe(false)
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    current.resolve(file())
    await flushPromises()
    expect(currentTab.location.href).toBe('blob:original')
    expect(currentTab.close).not.toHaveBeenCalled()
    expect(tab.location.href).toBe('')
    expect(vi.mocked(readConfirmationFile).mock.calls[1].slice(0, 2)).toEqual(['next-space', 'next-item'])
  })

  it('cancels when the source disappears from the same item', async () => {
    const pending = deferred<Blob>()
    vi.mocked(readConfirmationFile).mockReturnValue(pending.promise)
    const view = card()
    await openFile(view)
    await view.setProps({ item: sourced('item', { source_ref: undefined }) })
    expect(signalAt(0).aborted).toBe(true)
    expect(tab.close).toHaveBeenCalledTimes(1)
    expect(view.find('[data-confirm-file]').exists()).toBe(false)
    pending.resolve(file())
    await flushPromises()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('keeps reading when an answer refreshes the same item and source', async () => {
    const pending = deferred<Blob>()
    vi.mocked(readConfirmationFile).mockReturnValue(pending.promise)
    const view = card()
    await openFile(view)
    await view.setProps({ item: sourced('item', { title: 'Updated title' }) })
    expect(signalAt(0).aborted).toBe(false)
    expect(tab.close).not.toHaveBeenCalled()
    expect(view.get('[data-confirm-file]').attributes('disabled')).toBeDefined()
    pending.resolve(file())
    await flushPromises()
    expect(tab.location.href).toBe('blob:original')
  })

  it('clears a failed attempt before retrying with a fresh tab and signal', async () => {
    const retry = deferred<Blob>(), retryTab = popup()
    vi.mocked(readConfirmationFile).mockRejectedValueOnce(new EnterpriseError('SOURCE_INTEGRITY', 409)).mockReturnValueOnce(retry.promise)
    vi.mocked(window.open).mockReturnValueOnce(tab as unknown as Window).mockReturnValueOnce(retryTab as unknown as Window)
    const view = card()
    await openFile(view)
    await flushPromises()
    expect(view.get('[data-confirm-file-error]').text()).toBe('原文件与提问时的版本不一致')
    expect(tab.close).toHaveBeenCalledTimes(1)
    await openFile(view)
    expect(view.find('[data-confirm-file-error]').exists()).toBe(false)
    expect(signalAt(1)).not.toBe(signalAt(0))
    retry.resolve(file())
    await flushPromises()
    expect(retryTab.location.href).toBe('blob:original')
    expect(retryTab.close).not.toHaveBeenCalled()
  })

  it('revokes each successful URL once after sixty seconds or on unmount', async () => {
    vi.mocked(readConfirmationFile).mockResolvedValue(file())
    vi.mocked(URL.createObjectURL).mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:second')
    const view = card()
    await openFile(view)
    await flushPromises()
    vi.advanceTimersByTime(30_000)
    await openFile(view)
    await flushPromises()
    vi.advanceTimersByTime(29_999)
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(vi.mocked(URL.revokeObjectURL).mock.calls).toEqual([['blob:first']])
    view.unmount()
    expect(vi.mocked(URL.revokeObjectURL).mock.calls).toEqual([['blob:first'], ['blob:second']])
    expect(tab.close).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
    vi.advanceTimersByTime(60_000)
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2)
  })

  it('keeps cancellation and resource cleanup independent between cards', async () => {
    const first = deferred<Blob>(), second = deferred<Blob>(), secondTab = popup()
    vi.mocked(readConfirmationFile).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    vi.mocked(window.open).mockReturnValueOnce(tab as unknown as Window).mockReturnValueOnce(secondTab as unknown as Window)
    const firstView = card(sourced('first')), secondView = card(sourced('second'))
    await openFile(firstView)
    await openFile(secondView)
    firstView.unmount()
    expect(signalAt(0).aborted).toBe(true)
    expect(signalAt(1).aborted).toBe(false)
    second.resolve(file()); first.resolve(file())
    await flushPromises()
    expect(secondTab.location.href).toBe('blob:original')
    expect(secondTab.close).not.toHaveBeenCalled()
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(60_000)
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1)
  })

  it('releases a URL immediately if navigation fails even when closing also fails', async () => {
    vi.mocked(readConfirmationFile).mockResolvedValue(file())
    Object.defineProperty(tab.location, 'href', { set: () => { throw new Error('navigation failed') } })
    tab.close.mockImplementation(() => { throw new Error('close failed') })
    const view = card()
    await openFile(view)
    await flushPromises()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:original')
    expect(tab.close).toHaveBeenCalledTimes(1)
    expect(view.get('[data-confirm-file-error]').text()).toBe('打开失败，请重试')
    expect(view.get('[data-confirm-file]').attributes('disabled')).toBeUndefined()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('does not allocate a URL when the user closed the pending tab', async () => {
    const pending = deferred<Blob>()
    vi.mocked(readConfirmationFile).mockReturnValue(pending.promise)
    const view = card()
    await openFile(view)
    tab.closed = true
    pending.resolve(file())
    await flushPromises()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(view.get('[data-confirm-file]').attributes('disabled')).toBeUndefined()
    expect(view.get('[data-confirm-file-error]').text()).toBe('打开失败，请重试')
  })

  it('preserves draft controls and submission while the file is loading', async () => {
    const pending = deferred<Blob>()
    vi.mocked(readConfirmationFile).mockReturnValue(pending.promise)
    const view = card()
    await openFile(view)
    expect((view.get('textarea').element as HTMLTextAreaElement).value).toBe('Keep this draft')
    expect(view.get('textarea').attributes('disabled')).toBeUndefined()
    expect(view.get('[data-confirm-submit]').attributes('disabled')).toBeUndefined()
    await view.get('[data-confirm-option="supplement"]').setValue(true)
    await view.get('textarea').setValue('Still editable')
    await view.get('[data-confirm-submit]').trigger('click')
    expect(view.emitted('option')).toEqual([['supplement']])
    expect(view.emitted('note')).toEqual([['Still editable']])
    expect(view.emitted('submit')).toEqual([[]])
    pending.resolve(file())
    await flushPromises()
  })
})

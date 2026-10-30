// @vitest-environment happy-dom
// S5b-3e acceptance (protected, written by Claude): an item with an answer leaves 待处理 at once and
// waits under 已处理 until the system closes it; the workbench counts only unanswered items (Spec
// docs/design/slices/S5b-3e-待确认答复后移出待处理.md §1–§2; user 2026-10-27: "这个点了处理，处理的这一栏应该就不出现了").
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '@/enterprise/i18n/locales/zh-CN'
import enUS from '@/enterprise/i18n/locales/en-US'
import jaJP from '@/enterprise/i18n/locales/ja-JP'
import koKR from '@/enterprise/i18n/locales/ko-KR'
import ruRU from '@/enterprise/i18n/locales/ru-RU'

vi.mock('./enterpriseApi', async importOriginal => ({
  ...(await importOriginal<typeof import('./enterpriseApi')>()),
  readRelease: vi.fn(),
  listReviews: vi.fn(),
  listConfirmations: vi.fn(),
  listSamples: vi.fn(),
  answerConfirmation: vi.fn(),
}))

import EnterpriseConfirmations from './EnterpriseConfirmations.vue'
import EnterpriseSpace from './EnterpriseSpace.vue'
import {
  answerConfirmation, listConfirmations, listReviews, listSamples, readRelease, type ConfirmationItem,
} from './enterpriseApi'
import { confirmationAnswer, confirmationItem } from './__tests__/confirmationFixtures'
import { release } from './__tests__/s3eFixtures'

const views: ReturnType<typeof mount>[] = []
function mounted(component: typeof EnterpriseConfirmations | typeof EnterpriseSpace) {
  const view = mount(component, {
    attachTo: document.body,
    props: { spaceId: 'demo' },
    global: {
      plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN } })],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
  views.push(view)
  return view
}

type View = ReturnType<typeof mount>
const ids = (view: View) => view.findAll('[data-confirm-item]').map(item => item.attributes('data-confirm-item'))
const disabled = (element: { attributes: (name: string) => string | undefined }) =>
  element.attributes('disabled') !== undefined
const closure = { closed_by: 'service:submitter', closed_at: '2026-10-25T10:00:00Z' }

function lists(open: ConfirmationItem[], closed: ConfirmationItem[] = []) {
  vi.mocked(listConfirmations).mockImplementation((_space, status) => Promise.resolve(status === 'open' ? open : closed))
}

afterEach(() => { views.forEach(view => view.unmount()); views.length = 0; vi.resetAllMocks() })

describe('confirmation tabs by answer', () => {
  it('keeps answered items out of 待处理', async () => {
    lists([
      confirmationItem('c1'),
      confirmationItem('c2', { answer: confirmationAnswer('c2', { option_key: 'replace' }) }),
      confirmationItem('c3', { title: '第三份材料' }),
    ])
    const view = mounted(EnterpriseConfirmations)
    await flushPromises()
    expect(vi.mocked(listConfirmations).mock.calls).toEqual([['demo', 'open']])
    expect(ids(view)).toEqual(['c1', 'c3'])
    expect(view.text()).toContain('2 项')
    expect(view.text()).not.toContain('等待系统处理')
  })

  it('lists answered items under 已处理 before the closed ones, still changeable', async () => {
    lists([
      confirmationItem('c1'),
      confirmationItem('c2', { answer: confirmationAnswer('c2', { option_key: 'replace' }) }),
    ], [
      confirmationItem('c9', { answer: confirmationAnswer('c9', { id: 'a9', option_key: 'ignore' }),
        closure: { reason: 'applied', answer_id: 'a9', ...closure } }),
    ])
    const view = mounted(EnterpriseConfirmations)
    await flushPromises()
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    await flushPromises()
    expect(vi.mocked(listConfirmations).mock.calls.map(call => call[1]).sort()).toEqual(['closed', 'open', 'open'])
    expect(ids(view)).toEqual(['c2', 'c9'])
    expect(view.text()).toContain('2 项')
    const waiting = view.get('[data-confirm-item="c2"]')
    expect(waiting.get('[data-confirm-state]').text()).toContain('已选择：替换原有文件，等待系统处理')
    expect(waiting.get('[data-confirm-submit]').text()).toBe('修改选择')
    expect(view.get('[data-confirm-item="c9"] [data-confirm-state]').text()).toContain('已按「忽略这份文件」处理')
    expect(view.find('[data-confirm-item="c9"] [data-confirm-option]').exists()).toBe(false)
  })

  it('moves an item to 已处理 as soon as it is answered, without reading the list again', async () => {
    lists([confirmationItem('c1'), confirmationItem('c2', { title: '另一份材料' })])
    vi.mocked(answerConfirmation).mockResolvedValueOnce(confirmationAnswer('c1', { id: 'a1', option_key: 'supplement' }))
    const view = mounted(EnterpriseConfirmations)
    await flushPromises()
    const card = view.get('[data-confirm-item="c1"]')
    await card.get('[data-confirm-option="supplement"]').setValue(true)
    await card.get('[data-confirm-submit]').trigger('click')
    await flushPromises()
    expect(vi.mocked(answerConfirmation).mock.calls).toEqual([['demo', 'c1', 'supplement', '']])
    expect(ids(view)).toEqual(['c2'])
    expect(view.text()).toContain('1 项')
    const moved = view.get('[data-confirm-moved]')
    expect(moved.attributes('role')).toBe('status')
    expect(moved.text()).toContain('作为补充材料')
    expect(moved.text()).toContain('已处理')
    expect(document.activeElement).toBe(moved.element)
    expect(vi.mocked(listConfirmations)).toHaveBeenCalledTimes(1)

    vi.mocked(answerConfirmation).mockResolvedValueOnce(confirmationAnswer('c2', { id: 'a2', option_key: 'ignore' }))
    const last = view.get('[data-confirm-item="c2"]')
    await last.get('[data-confirm-option="ignore"]').setValue(true)
    await last.get('[data-confirm-submit]').trigger('click')
    await flushPromises()
    expect(ids(view)).toEqual([])
    expect(view.text()).toContain('没有待确认的材料')
    expect(view.get('[data-confirm-moved]').text()).toContain('忽略这份文件')
    expect(document.activeElement).toBe(view.get('[data-confirm-moved]').element)
  })

  it('keeps a changed choice under 已处理', async () => {
    lists([confirmationItem('c2', { answer: confirmationAnswer('c2', { id: 'a1', option_key: 'replace', note: '' }) })])
    vi.mocked(answerConfirmation).mockResolvedValueOnce(confirmationAnswer('c2', { id: 'a2', option_key: 'ignore', note: '' }))
    const view = mounted(EnterpriseConfirmations)
    await flushPromises()
    expect(ids(view)).toEqual([])
    await view.get('[data-confirm-tab="closed"]').trigger('click')
    await flushPromises()
    const card = view.get('[data-confirm-item="c2"]')
    const submit = card.get('[data-confirm-submit]')
    expect(disabled(submit)).toBe(true)
    await card.get('[data-confirm-option="ignore"]').setValue(true)
    expect(disabled(submit)).toBe(false)
    await submit.trigger('click')
    await flushPromises()
    expect(vi.mocked(answerConfirmation).mock.calls).toEqual([['demo', 'c2', 'ignore', '']])
    expect(ids(view)).toEqual(['c2'])
    const state = view.get('[data-confirm-item="c2"] [data-confirm-state]')
    expect(state.text()).toContain('已选择：忽略这份文件，等待系统处理')
    expect(document.activeElement).toBe(state.element)
    expect(view.find('[data-confirm-moved]').exists()).toBe(false)
  })

  it('counts only unanswered items on the workbench', async () => {
    vi.mocked(readRelease).mockResolvedValue(release())
    vi.mocked(listReviews).mockResolvedValue([])
    vi.mocked(listSamples).mockResolvedValue([])
    lists([
      confirmationItem('c1'), confirmationItem('c2'),
      confirmationItem('c3', { answer: confirmationAnswer('c3') }),
    ])
    const view = mounted(EnterpriseSpace)
    await flushPromises()
    const entry = view.get('[data-space-workbench] [data-workbench-entry="confirmations"]')
    expect(entry.get('[data-workbench-count]').text()).toBe('2')

    for (const view of views) view.unmount()
    views.length = 0
    lists([confirmationItem('c3', { answer: confirmationAnswer('c3') })])
    const answered = mounted(EnterpriseSpace)
    await flushPromises()
    expect(answered.get('[data-space-workbench] [data-workbench-entry="confirmations"] [data-workbench-count]').text())
      .toBe('无待办')
  })

  it('words the moved notice in all five locales', () => {
    for (const messages of [zhCN, enUS, jaJP, koKR, ruRU]) {
      const confirm = (messages as { enterpriseKnowledge: { confirm: Record<string, string> } })
        .enterpriseKnowledge.confirm
      expect(confirm.moved).toMatch(/\{option\}/)
    }
  })
})
